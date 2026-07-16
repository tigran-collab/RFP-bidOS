"""Asynchronous-capable document processing pipeline.

State machine: Uploaded -> Queued -> Processing -> Extracted -> Indexed ->
Needs Review (candidate claims await approval) | Failed | Archived.

The app has no distributed task queue; ``process_document`` is a synchronous,
deterministic function used by the CLI, the tests, and a background thread
(``enqueue_processing``) so uploads return promptly. This is the documented
tradeoff versus Celery/RQ.

Steps: extract text (preserving page/section/sheet boundaries) -> chunk ->
scan for prompt injection -> extract candidate metadata + candidate claims
(routed to review as Pending Review; never auto-approved) -> detect conflicts.
An existing analysis is only replaced after the new one is built successfully.
"""

from __future__ import annotations

import json
import re
import threading

from sqlmodel import Session, delete, select

from app.db import engine
from app.kb_models import Claim, KbClaimSource, KbConflict, KbDocument, KbDocumentChunk
from app.kb_vocab import (
    CLAIM_STATUS_PENDING,
    DOC_STATUS_EXTRACTED,
    DOC_STATUS_FAILED,
    DOC_STATUS_INDEXED,
    DOC_STATUS_NEEDS_REVIEW,
    DOC_STATUS_PROCESSING,
    DOC_STATUS_QUEUED,
)
from app.models import utcnow_naive
from app.services.kb.extraction import (
    ExtractedSegment,
    extract_document,
    scan_for_injection,
)

CHUNK_CHARS = 1200
CHUNK_OVERLAP = 150
MAX_CANDIDATE_CLAIMS = 40

# --- candidate-claim heuristics (deterministic; no AI required) --------------
# Each detector maps a text pattern to a claim category. Candidates are created
# as Pending Review so a human converts them into trusted knowledge.
_LICENSE_RE = re.compile(
    r"\b(?:PPO|PSC|license|licen[sc]e|permit|registration)\s*(?:no\.?|number|#|:)?\s*"
    r"([A-Z]{0,3}[-\s]?\d{3,10})",
    re.I,
)
_EXPIRATION_RE = re.compile(
    r"\b(?:expir\w*|valid\s+through|valid\s+until|renewal)\b.{0,40}?"
    r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|[A-Z][a-z]+\s+\d{1,2},?\s+\d{4})",
    re.I,
)
_MONEY_RE = re.compile(r"\$\s?\d{1,3}(?:,\d{3})+(?:\.\d{2})?|\$\s?\d+(?:\.\d{2})?")
_YEARS_RE = re.compile(r"\b(\d{1,3})\+?\s+years?\b", re.I)
_EMPLOYEES_RE = re.compile(r"\b([\d,]{2,})\s+(?:employees|officers|guards|personnel|staff)\b", re.I)
_FOUNDED_RE = re.compile(r"\b(?:founded|established|incorporated|since)\s+(?:in\s+)?(\d{4})", re.I)
_CERT_RE = re.compile(r"\b(ISO\s?\d{3,5}|SOC\s?2|OSHA|certified|certification|accredited)\b", re.I)
_INSURANCE_RE = re.compile(
    r"\b(general liability|workers.?\s?comp\w*|umbrella|professional liability|bond\w*)\b",
    re.I,
)


def enqueue_processing(document_id: int) -> None:
    """Mark Queued and kick off processing on a background thread.

    Used by the upload endpoint so the request returns immediately. The worker
    opens its own Session (the request's session is closed by then).
    """
    with Session(engine) as session:
        document = session.get(KbDocument, document_id)
        if document is None:
            return
        document.processing_status = DOC_STATUS_QUEUED
        document.updated_at = utcnow_naive()
        session.add(document)
        session.commit()

    def _worker() -> None:
        with Session(engine) as worker_session:
            try:
                process_document(worker_session, document_id)
            except Exception:  # noqa: BLE001 - background thread must not crash
                _mark_failed(worker_session, document_id, "Background processing error")

    threading.Thread(target=_worker, daemon=True).start()


def _mark_failed(session: Session, document_id: int, message: str) -> None:
    document = session.get(KbDocument, document_id)
    if document is None:
        return
    document.processing_status = DOC_STATUS_FAILED
    document.processing_error = message
    document.updated_at = utcnow_naive()
    session.add(document)
    session.commit()


def process_document(
    session: Session, document_id: int, *, extract_claims: bool = True
) -> dict:
    """Run the full pipeline for one document. Returns a summary dict."""
    document = session.get(KbDocument, document_id)
    if document is None:
        return {"error": f"Document {document_id} not found"}

    document.processing_status = DOC_STATUS_PROCESSING
    document.processing_error = None
    document.updated_at = utcnow_naive()
    session.add(document)
    session.commit()

    extraction = extract_document(document.path, document.file_type)
    if extraction.error and not extraction.has_text:
        _mark_failed(session, document_id, extraction.error)
        return {"error": extraction.error, "document_id": document_id}

    document.processing_status = DOC_STATUS_EXTRACTED
    document.page_count = extraction.page_count
    document.sheet_names_json = (
        json.dumps(extraction.sheet_names) if extraction.sheet_names else None
    )
    document.injection_flags_json = (
        json.dumps(scan_for_injection(extraction.segments)) or None
    )
    session.add(document)
    session.commit()

    # Build the new chunk set, then replace the old one atomically.
    new_chunks = _chunk_segments(document_id, extraction.segments)
    session.exec(
        delete(KbDocumentChunk).where(KbDocumentChunk.document_id == document_id)
    )
    for chunk in new_chunks:
        session.add(chunk)
    document.chunk_count = len(new_chunks)
    document.processing_status = DOC_STATUS_INDEXED
    document.processed_at = utcnow_naive()
    session.add(document)
    session.commit()
    for chunk in new_chunks:
        session.refresh(chunk)

    candidates_created = 0
    if extract_claims:
        candidates_created = _create_candidate_claims(session, document, new_chunks)

    # Candidate claims await human review; documents with candidates land in
    # "Needs Review", otherwise they are fully "Indexed".
    document.processing_status = (
        DOC_STATUS_NEEDS_REVIEW if candidates_created else DOC_STATUS_INDEXED
    )
    document.updated_at = utcnow_naive()
    session.add(document)
    session.commit()

    # Detect conflicts across the entity's claims after new candidates land.
    conflicts_found = 0
    try:
        from app.services.kb.conflicts import detect_conflicts

        conflicts_found = detect_conflicts(
            session, company_entity_id=document.company_entity_id
        )
    except Exception:  # noqa: BLE001 - conflict detection is best-effort
        conflicts_found = 0

    return {
        "document_id": document_id,
        "status": document.processing_status,
        "chunks": len(new_chunks),
        "page_count": extraction.page_count,
        "sheet_names": extraction.sheet_names,
        "candidate_claims": candidates_created,
        "conflicts_found": conflicts_found,
        "injection_flags": json.loads(document.injection_flags_json or "[]"),
        "truncated": extraction.truncated,
    }


def _chunk_segments(
    document_id: int, segments: list[ExtractedSegment]
) -> list[KbDocumentChunk]:
    chunks: list[KbDocumentChunk] = []
    index = 0
    now = utcnow_naive()
    for segment in segments:
        text = segment.text or ""
        for piece in _split_text(text):
            if not piece.strip():
                continue
            chunks.append(
                KbDocumentChunk(
                    document_id=document_id,
                    chunk_index=index,
                    page_number=segment.page_number,
                    section=segment.section,
                    sheet_name=segment.sheet_name,
                    cell_range=segment.cell_range,
                    text=piece,
                    char_count=len(piece),
                    created_at=now,
                )
            )
            index += 1
    return chunks


def _split_text(text: str) -> list[str]:
    if len(text) <= CHUNK_CHARS:
        return [text] if text.strip() else []
    pieces = []
    step = CHUNK_CHARS - CHUNK_OVERLAP
    for start in range(0, len(text), step):
        piece = text[start : start + CHUNK_CHARS]
        if piece.strip():
            pieces.append(piece)
        if start + CHUNK_CHARS >= len(text):
            break
    return pieces


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [p.strip() for p in parts if len(p.strip()) > 15]


def extract_candidate_claims(
    document: KbDocument, chunks: list[KbDocumentChunk]
) -> list[dict]:
    """Deterministically surface candidate claims from a document's chunks.

    Returns candidate dicts (category, title, text, page, excerpt). These become
    Pending-Review claims — never auto-approved.
    """
    candidates: list[dict] = []
    seen: set[str] = set()

    def add(category: str, title: str, sentence: str, chunk: KbDocumentChunk) -> None:
        key = f"{category}:{sentence.strip().lower()[:120]}"
        if key in seen:
            return
        seen.add(key)
        candidates.append(
            {
                "category": category,
                "title": title,
                "text": sentence.strip(),
                "page": chunk.page_number,
                "section": chunk.section,
                "chunk_id": chunk.id,
                "excerpt": sentence.strip()[:400],
            }
        )

    for chunk in chunks:
        for sentence in _split_sentences(chunk.text):
            if _LICENSE_RE.search(sentence):
                add("Licensing", "Candidate: license/permit reference", sentence, chunk)
            if _EXPIRATION_RE.search(sentence):
                add("Licensing", "Candidate: expiration date", sentence, chunk)
            if _INSURANCE_RE.search(sentence) or (
                _MONEY_RE.search(sentence) and re.search(r"insur|liabilit|bond", sentence, re.I)
            ):
                add("Insurance", "Candidate: insurance/bonding figure", sentence, chunk)
            if _YEARS_RE.search(sentence) or _FOUNDED_RE.search(sentence):
                add("Corporate History", "Candidate: years in business", sentence, chunk)
            if _EMPLOYEES_RE.search(sentence):
                add("Staffing", "Candidate: staffing/headcount", sentence, chunk)
            if _CERT_RE.search(sentence):
                add("Certifications", "Candidate: certification/accreditation", sentence, chunk)
            if len(candidates) >= MAX_CANDIDATE_CLAIMS:
                return candidates
    return candidates


def _create_candidate_claims(
    session: Session, document: KbDocument, chunks: list[KbDocumentChunk]
) -> int:
    # Idempotent: drop prior auto-generated candidates for this document before
    # regenerating (only removes ones still Pending Review, never approved ones).
    existing = session.exec(
        select(Claim).where(
            Claim.source_document_id == document.id,
            Claim.status == CLAIM_STATUS_PENDING,
            Claim.created_by == None,  # noqa: E711 - system-generated marker
        )
    ).all()
    existing_ids = {claim.id for claim in existing}
    # Purge any Open conflicts referencing these candidates before deleting them,
    # so re-processing does not leave dangling, unresolvable conflict rows or
    # accumulate duplicates (candidates get new ids each run).
    if existing_ids:
        for conflict in session.exec(select(KbConflict)).all():
            if conflict.claim_a_id in existing_ids or conflict.claim_b_id in existing_ids:
                session.delete(conflict)
    for claim in existing:
        # Remove associated evidence rows too.
        for src in session.exec(
            select(KbClaimSource).where(KbClaimSource.claim_id == claim.id)
        ).all():
            session.delete(src)
        session.delete(claim)
    session.commit()

    candidates = extract_candidate_claims(document, chunks)
    now = utcnow_naive()
    created = 0
    for cand in candidates:
        claim = Claim(
            title=cand["title"],
            canonical_text=cand["text"],
            category=cand["category"],
            company_entity_id=document.company_entity_id,
            source_document_id=document.id,
            source_page=cand.get("page"),
            source_section=cand.get("section"),
            supporting_excerpt=cand.get("excerpt"),
            status=CLAIM_STATUS_PENDING,
            confidence="Low",
            internal_notes="Auto-extracted candidate; verify before approval.",
            created_by=None,  # system-generated marker
            version=1,
            created_at=now,
            updated_at=now,
        )
        session.add(claim)
        session.commit()
        session.refresh(claim)
        session.add(
            KbClaimSource(
                claim_id=claim.id,
                document_id=document.id,
                chunk_id=cand.get("chunk_id"),
                page_number=cand.get("page"),
                section=cand.get("section"),
                excerpt=cand.get("excerpt"),
                created_at=now,
            )
        )
        session.commit()
        created += 1
    return created
