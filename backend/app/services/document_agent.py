"""Local AI document agent: works through an opportunity's parsed documents.

Unlike the requirement extractor and AI evaluator — which read one bounded
snippet across all files — this agent reads EVERY parsed document end-to-end
in overlapping chunks, extracts structured facts per chunk with the local
Ollama model, folds them into a per-document analysis, then synthesizes an
opportunity-level brief across documents. Every fact carries a citation back
to its file and chunk so a human can verify it.

Strictly local AI (Ollama), no proposal drafting, no network beyond the local
model. Output is a review aid; nothing is auto-submitted or auto-decided.

Persistence rules (hard-learned in this repo): an existing completed analysis
is never deleted until its replacement has been built successfully, and a
failed refresh leaves the previous rows untouched.
"""

import json
from pathlib import Path

from sqlmodel import select

from app.models import Document, DocumentAnalysis, Opportunity, utcnow_naive
from app.services.ollama_client import (
    LOCAL_AI_UNAVAILABLE,
    OLLAMA_GENERATE_FAILED,
    OLLAMA_TIMEOUT,
    LocalAIGenerateError,
    LocalAITimeoutError,
    LocalAIUnavailableError,
    generate_json,
)

# ~1,500-2,000 tokens per chunk leaves room for the prompt inside the model's
# 8k context. Overlap keeps facts that straddle a boundary readable in full.
CHUNK_CHARS = 6000
CHUNK_OVERLAP = 300
# Safety cap per file (240k chars ≈ a very large RFP). Hitting it sets
# truncated=True on the analysis so the gap is visible, never silent.
MAX_CHUNKS_PER_DOCUMENT = 40

FACT_CATEGORIES = (
    "deadline",
    "submission",
    "scope",
    "staffing",
    "wages_benefits",
    "insurance_bonding",
    "licensing",
    "evaluation_criteria",
    "contract_term_value",
    "other",
)

BRIEF_KIND = "brief"
DOCUMENT_KIND = "document"


def analyze_opportunity_documents(
    opportunity_id: int, session, refresh: bool = False
) -> dict:
    """Run the document agent for one opportunity.

    Analyzes each parsed document that has no completed analysis yet
    (``refresh=True`` re-analyzes everything), then rebuilds the
    opportunity-level brief. Returns a summary dict; ``error`` is set only
    when nothing could be done at all.
    """
    opportunity = session.get(Opportunity, opportunity_id)
    if opportunity is None:
        return {"error": "Opportunity not found"}

    documents = [
        document
        for document in session.exec(
            select(Document)
            .where(Document.opportunity_id == opportunity_id)
            .order_by(Document.id)
        ).all()
        if document.extracted_text_path
    ]
    if not documents:
        return {
            "error": (
                "No parsed documents to analyze. Download and parse the "
                "opportunity's documents first (pursuit prep)."
            )
        }

    analyzed = 0
    skipped = 0
    errors: list[str] = []

    for document in documents:
        existing = _analysis_for_document(session, opportunity_id, document.id)
        if existing is not None and existing.status == "completed" and not refresh:
            skipped += 1
            continue

        text = _load_document_text(document)
        if text is None:
            errors.append(f"{document.filename}: extracted text file is missing.")
            continue
        if not text.strip():
            errors.append(f"{document.filename}: extracted text is empty.")
            continue

        try:
            analysis = _analyze_document(opportunity, document, text)
        except LocalAIUnavailableError:
            errors.append(LOCAL_AI_UNAVAILABLE)
            return _run_summary(analyzed, skipped, errors, brief=None, aborted=True)
        except LocalAITimeoutError as exc:
            errors.append(str(exc) or OLLAMA_TIMEOUT)
            return _run_summary(analyzed, skipped, errors, brief=None, aborted=True)
        except LocalAIGenerateError as exc:
            errors.append(str(exc) or OLLAMA_GENERATE_FAILED)
            return _run_summary(analyzed, skipped, errors, brief=None, aborted=True)

        # Replace the old analysis only now that the new one exists.
        if existing is not None:
            session.delete(existing)
        session.add(analysis)
        session.commit()
        analyzed += 1
        if analysis.status == "partial":
            errors.append(
                f"{document.filename}: {analysis.error or 'some chunks failed.'}"
            )

    brief_payload = None
    document_analyses = _document_analyses(session, opportunity_id)
    if document_analyses:
        try:
            brief_payload = _synthesize_brief(
                opportunity, document_analyses, session
            )
        except LocalAIUnavailableError:
            errors.append(LOCAL_AI_UNAVAILABLE)
        except LocalAITimeoutError as exc:
            errors.append(str(exc) or OLLAMA_TIMEOUT)
        except LocalAIGenerateError as exc:
            errors.append(str(exc) or OLLAMA_GENERATE_FAILED)

    return _run_summary(analyzed, skipped, errors, brief=brief_payload)


def get_document_brief(opportunity_id: int, session) -> dict | None:
    """Return the stored brief + per-document analyses, or None if absent."""
    brief = session.exec(
        select(DocumentAnalysis)
        .where(
            DocumentAnalysis.opportunity_id == opportunity_id,
            DocumentAnalysis.kind == BRIEF_KIND,
        )
        .order_by(DocumentAnalysis.id.desc())
    ).first()
    document_analyses = _document_analyses(session, opportunity_id)
    if brief is None and not document_analyses:
        return None
    return {
        "brief": _analysis_to_dict(brief) if brief else None,
        "documents": [_analysis_to_dict(row) for row in document_analyses],
    }


# --- per-document pass -------------------------------------------------------


def _analyze_document(
    opportunity: Opportunity, document: Document, text: str
) -> DocumentAnalysis:
    chunks = _chunk_text(text)
    truncated = len(chunks) > MAX_CHUNKS_PER_DOCUMENT
    if truncated:
        chunks = chunks[:MAX_CHUNKS_PER_DOCUMENT]

    facts: list[dict] = []
    red_flags: list[str] = []
    open_questions: list[str] = []
    chunk_summaries: list[str] = []
    failed_chunks: list[int] = []
    model_name: str | None = None

    for index, chunk in enumerate(chunks, start=1):
        prompt = _chunk_prompt(opportunity, document, chunk, index, len(chunks))
        # Small local models occasionally emit unusable JSON at low
        # temperature; one retry recovers most of those before we give up
        # and mark the chunk failed.
        parsed = None
        for _attempt in range(2):
            response = generate_json(prompt)
            model_name = response.get("model") or model_name
            candidate = response.get("json")
            if isinstance(candidate, dict):
                parsed = candidate
                break
        if parsed is None:
            failed_chunks.append(index)
            continue
        summary = str(parsed.get("summary") or "").strip()
        if summary:
            chunk_summaries.append(summary)
        for fact in parsed.get("facts") or []:
            if not isinstance(fact, dict):
                continue
            detail = str(fact.get("detail") or "").strip()
            if not detail:
                continue
            category = str(fact.get("category") or "other").strip().lower()
            if category not in FACT_CATEGORIES:
                category = "other"
            facts.append(
                {
                    "category": category,
                    "detail": detail,
                    "source_file": document.filename,
                    "chunk": index,
                }
            )
        red_flags.extend(_string_items(parsed.get("red_flags")))
        open_questions.extend(_string_items(parsed.get("open_questions")))

    status = "partial" if failed_chunks else "completed"
    error = None
    if failed_chunks:
        error = (
            f"model returned unusable JSON for chunk(s) "
            f"{', '.join(str(i) for i in failed_chunks)} of {len(chunks)}."
        )

    return DocumentAnalysis(
        opportunity_id=opportunity.id,
        document_id=document.id,
        kind=DOCUMENT_KIND,
        model_name=model_name,
        status=status,
        summary=" ".join(chunk_summaries)[:4000] or None,
        facts_json=json.dumps(_dedupe_facts(facts)),
        red_flags_json=json.dumps(_dedupe_strings(red_flags)),
        open_questions_json=json.dumps(_dedupe_strings(open_questions)),
        chunk_count=len(chunks),
        analyzed_chars=min(len(text), len(chunks) * CHUNK_CHARS),
        truncated=truncated,
        error=error,
        created_at=utcnow_naive(),
    )


def _chunk_prompt(
    opportunity: Opportunity,
    document: Document,
    chunk: str,
    index: int,
    total: int,
) -> str:
    categories = ", ".join(FACT_CATEGORIES)
    return f"""
You are a document analyst for a security-guard services contractor reviewing a government solicitation.
Opportunity: {opportunity.title!r} — agency: {opportunity.agency or "unknown"}.
You are reading chunk {index} of {total} of the file {document.filename!r}.

Extract ONLY facts stated in the text below. Never invent dates, amounts, or requirements.
Respond with ONE JSON object, no other text:
{{
  "summary": "1-2 sentences on what this part of the document covers",
  "facts": [{{"category": "<one of: {categories}>", "detail": "the fact, quoted or tightly paraphrased, with numbers/dates verbatim"}}],
  "red_flags": ["conditions that make this bid risky or costly for a guard contractor"],
  "open_questions": ["things a bidder must clarify with the agency"]
}}
Use empty lists when this chunk has nothing relevant.

TEXT:
{chunk}
""".strip()


# --- opportunity-level synthesis ----------------------------------------------


def _synthesize_brief(
    opportunity: Opportunity, document_analyses: list[DocumentAnalysis], session
) -> dict:
    merged_facts: list[dict] = []
    merged_flags: list[str] = []
    merged_questions: list[str] = []
    doc_lines: list[str] = []
    for row in document_analyses:
        merged_facts.extend(_loads_list(row.facts_json))
        merged_flags.extend(_string_items(_loads_list(row.red_flags_json)))
        merged_questions.extend(_string_items(_loads_list(row.open_questions_json)))
        doc_lines.append(f"- {_document_label(session, row)}: {row.summary or 'no summary'}")

    fact_lines = "\n".join(
        f"- [{fact['category']}] {fact['detail']} ({fact['source_file']} chunk {fact['chunk']})"
        for fact in merged_facts[:120]
    )
    prompt = f"""
You are preparing a bid-review brief for a security-guard services contractor.
Opportunity: {opportunity.title!r} — agency: {opportunity.agency or "unknown"}.

Per-document summaries:
{chr(10).join(doc_lines)}

Extracted facts (with sources):
{fact_lines or "- none"}

Write ONE JSON object, no other text:
{{
  "summary": "5-8 sentence brief: what is being procured, where, key dates, and what it takes to respond",
  "top_risks": ["the most consequential risks/red flags, most severe first"],
  "open_questions": ["what to clarify with the agency before bidding"]
}}
Base everything strictly on the material above.
""".strip()

    response = generate_json(prompt)
    parsed = response.get("json") if isinstance(response.get("json"), dict) else {}
    summary = str(parsed.get("summary") or "").strip() or None
    flags = _dedupe_strings(
        [*_string_items(parsed.get("top_risks")), *_dedupe_strings(merged_flags)]
    )
    questions = _dedupe_strings(
        [*_string_items(parsed.get("open_questions")), *_dedupe_strings(merged_questions)]
    )

    brief = DocumentAnalysis(
        opportunity_id=opportunity.id,
        document_id=None,
        kind=BRIEF_KIND,
        model_name=response.get("model"),
        status="completed" if summary else "partial",
        summary=summary,
        facts_json=json.dumps(_dedupe_facts(merged_facts)),
        red_flags_json=json.dumps(flags),
        open_questions_json=json.dumps(questions),
        chunk_count=sum(row.chunk_count or 0 for row in document_analyses),
        analyzed_chars=sum(row.analyzed_chars or 0 for row in document_analyses),
        truncated=any(row.truncated for row in document_analyses),
        error=None if summary else "model returned unusable JSON for the brief.",
        created_at=utcnow_naive(),
    )

    # Replace the previous brief only after the new one was built.
    previous = session.exec(
        select(DocumentAnalysis).where(
            DocumentAnalysis.opportunity_id == opportunity.id,
            DocumentAnalysis.kind == BRIEF_KIND,
        )
    ).all()
    for row in previous:
        session.delete(row)
    session.add(brief)
    session.commit()
    session.refresh(brief)
    return _analysis_to_dict(brief)


# --- helpers -------------------------------------------------------------------


def _chunk_text(text: str) -> list[str]:
    if len(text) <= CHUNK_CHARS:
        return [text]
    chunks = []
    step = CHUNK_CHARS - CHUNK_OVERLAP
    for start in range(0, len(text), step):
        chunk = text[start : start + CHUNK_CHARS]
        if chunk.strip():
            chunks.append(chunk)
        if start + CHUNK_CHARS >= len(text):
            break
    return chunks


def _load_document_text(document: Document) -> str | None:
    path = Path(document.extracted_text_path)
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _analysis_for_document(
    session, opportunity_id: int, document_id: int
) -> DocumentAnalysis | None:
    return session.exec(
        select(DocumentAnalysis)
        .where(
            DocumentAnalysis.opportunity_id == opportunity_id,
            DocumentAnalysis.document_id == document_id,
            DocumentAnalysis.kind == DOCUMENT_KIND,
        )
        .order_by(DocumentAnalysis.id.desc())
    ).first()


def _document_analyses(session, opportunity_id: int) -> list[DocumentAnalysis]:
    return list(
        session.exec(
            select(DocumentAnalysis)
            .where(
                DocumentAnalysis.opportunity_id == opportunity_id,
                DocumentAnalysis.kind == DOCUMENT_KIND,
            )
            .order_by(DocumentAnalysis.document_id)
        ).all()
    )


def _document_label(session, analysis: DocumentAnalysis) -> str:
    if analysis.document_id is None:
        return "all documents"
    document = session.get(Document, analysis.document_id)
    return document.filename if document else f"document {analysis.document_id}"


def _string_items(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _dedupe_strings(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        key = value.lower()
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _dedupe_facts(facts: list[dict]) -> list[dict]:
    seen = set()
    result = []
    for fact in facts:
        key = (fact.get("category"), str(fact.get("detail", "")).lower())
        if key not in seen:
            seen.add(key)
            result.append(fact)
    return result


def _loads_list(raw: str | None) -> list:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except ValueError:
        return []
    return value if isinstance(value, list) else []


def _analysis_to_dict(row: DocumentAnalysis) -> dict:
    return {
        "id": row.id,
        "opportunity_id": row.opportunity_id,
        "document_id": row.document_id,
        "kind": row.kind,
        "model_name": row.model_name,
        "status": row.status,
        "summary": row.summary,
        "facts": _loads_list(row.facts_json),
        "red_flags": _loads_list(row.red_flags_json),
        "open_questions": _loads_list(row.open_questions_json),
        "chunk_count": row.chunk_count,
        "analyzed_chars": row.analyzed_chars,
        "truncated": row.truncated,
        "error": row.error,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _run_summary(
    analyzed: int,
    skipped: int,
    errors: list[str],
    brief: dict | None,
    aborted: bool = False,
) -> dict:
    result = {
        "documents_analyzed": analyzed,
        "documents_skipped": skipped,
        "errors": errors,
        "brief": brief,
    }
    if aborted and not analyzed:
        # Nothing was accomplished; surface the first error at the top level so
        # callers (router/CLI) can map it like the other local-AI endpoints.
        result["error"] = errors[0] if errors else "Document analysis failed."
    return result
