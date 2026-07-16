"""Hybrid retrieval over the knowledge base.

The app runs on SQLite (no pgvector), so semantic vector search is unavailable.
The closest technically sound implementation — deterministic, offline, and
testable — is a hybrid lexical retriever: BM25 term scoring + exact-phrase
boosting + metadata filtering, over the candidate rows for a query. At the
current scale (hundreds–thousands of rows) this runs comfortably in-process.
An optional Ollama-embedding reranker can layer on when available, but the
default path needs no model and no network. This tradeoff is documented in the
README architecture notes.

Retrieval also enforces governance rules used by drafting:
- only Approved, non-expired claims/answers are returned for automatic use;
- state/service/industry-scoped items are excluded outside their scope;
- entity filtering never mixes a different legal entity's claims.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime

from sqlmodel import Session, select

from app.kb_models import Claim, KbDocument, KbDocumentChunk, ReusableAnswer
from app.kb_vocab import (
    ANSWER_USABLE_STATUSES,
    CLAIM_USABLE_STATUSES,
)
from app.models import utcnow_naive

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    """a an and are as at be by for from has have how in is it its of on or
    that the to was were what when where which who will with your you our we
    describe explain provide detail process plan approach program""".split()
)

BM25_K1 = 1.5
BM25_B = 0.75


def tokenize(text: str) -> list[str]:
    return [
        tok
        for tok in _TOKEN_RE.findall((text or "").lower())
        if len(tok) > 1 and tok not in _STOPWORDS
    ]


@dataclass
class RetrievalFilters:
    company_entity_id: int | None = None
    state: str | None = None
    industry: str | None = None
    service_type: str | None = None
    category: str | None = None
    include_restricted: bool = False


@dataclass
class RetrievedItem:
    kind: str  # "claim" | "answer" | "chunk"
    id: int
    score: float
    title: str
    text: str
    metadata: dict = field(default_factory=dict)


def _loads_list(raw: str | None) -> list:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        return []
    return value if isinstance(value, list) else []


def _is_expired(expiration: datetime | None, now: datetime) -> bool:
    return expiration is not None and expiration < now


def _scope_ok(scope_values: list, wanted: str | None) -> bool:
    """A scoped item applies when it has no scope list (applies everywhere) or
    the wanted value is in its list. Comparison is case-insensitive."""
    if not wanted:
        return True
    if not scope_values:
        return True
    wanted_l = str(wanted).strip().lower()
    return any(str(v).strip().lower() == wanted_l for v in scope_values)


def _entity_ok(entity_id: int | None, wanted: int | None) -> bool:
    """Never mix a different legal entity's content. When an entity is wanted,
    keep matching-entity and entity-agnostic (null) rows only."""
    if wanted is None:
        return True
    return entity_id is None or entity_id == wanted


def _bm25_scores(query_tokens: list[str], docs_tokens: list[list[str]]) -> list[float]:
    """Classic BM25 over the candidate corpus for this query."""
    n = len(docs_tokens)
    if n == 0 or not query_tokens:
        return [0.0] * n
    doc_lens = [len(d) for d in docs_tokens]
    avgdl = sum(doc_lens) / n if n else 0.0
    # document frequency per query term
    df: dict[str, int] = {}
    query_set = set(query_tokens)
    for tokens in docs_tokens:
        present = query_set.intersection(tokens)
        for term in present:
            df[term] = df.get(term, 0) + 1
    scores = [0.0] * n
    for i, tokens in enumerate(docs_tokens):
        if not tokens:
            continue
        tf: dict[str, int] = {}
        for tok in tokens:
            if tok in query_set:
                tf[tok] = tf.get(tok, 0) + 1
        score = 0.0
        for term, freq in tf.items():
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            denom = freq + BM25_K1 * (1 - BM25_B + BM25_B * (doc_lens[i] / avgdl if avgdl else 1))
            score += idf * (freq * (BM25_K1 + 1)) / (denom or 1)
        scores[i] = score
    return scores


def _phrase_bonus(query: str, text: str) -> float:
    """Boost exact phrase and bigram substring matches."""
    q = (query or "").strip().lower()
    t = (text or "").lower()
    if not q or not t:
        return 0.0
    bonus = 0.0
    if len(q) >= 4 and q in t:
        bonus += 2.0
    q_tokens = tokenize(query)
    for a, b in zip(q_tokens, q_tokens[1:]):
        if f"{a} {b}" in t:
            bonus += 0.4
    return bonus


def _normalize(scores: list[float]) -> list[float]:
    top = max(scores) if scores else 0.0
    if top <= 0:
        return [0.0] * len(scores)
    return [s / top for s in scores]


# --- candidate loaders -------------------------------------------------------


def _candidate_claims(
    session: Session,
    filters: RetrievalFilters,
    usable_only: bool,
    now: datetime,
) -> list[Claim]:
    claims = list(session.exec(select(Claim)).all())
    out: list[Claim] = []
    for claim in claims:
        status = claim.status or "Draft"
        if usable_only:
            if status not in CLAIM_USABLE_STATUSES:
                continue
            if _is_expired(claim.expiration_date, now):
                continue
        else:
            if status in {"Restricted"} and not filters.include_restricted:
                continue
        if not _entity_ok(claim.company_entity_id, filters.company_entity_id):
            continue
        if filters.category and (claim.category or "") != filters.category:
            continue
        if not _scope_ok(_loads_list(claim.applicable_states_json), filters.state):
            continue
        if not _scope_ok(_loads_list(claim.service_scope_json), filters.service_type):
            continue
        if not _scope_ok(_loads_list(claim.industry_scope_json), filters.industry):
            continue
        out.append(claim)
    return out


def _candidate_answers(
    session: Session,
    filters: RetrievalFilters,
    usable_only: bool,
    now: datetime,
) -> list[ReusableAnswer]:
    answers = list(session.exec(select(ReusableAnswer)).all())
    out: list[ReusableAnswer] = []
    for answer in answers:
        status = answer.status or "Draft"
        if usable_only:
            if status not in ANSWER_USABLE_STATUSES:
                continue
            if _is_expired(answer.expiration_date, now):
                continue
        if not _entity_ok(answer.company_entity_id, filters.company_entity_id):
            continue
        if filters.category and (answer.category or "") != filters.category:
            continue
        if not _scope_ok(_loads_list(answer.applicable_states_json), filters.state):
            continue
        if not _scope_ok(
            _loads_list(answer.applicable_services_json), filters.service_type
        ):
            continue
        if not _scope_ok(
            _loads_list(answer.applicable_industries_json), filters.industry
        ):
            continue
        out.append(answer)
    return out


def _claim_search_text(claim: Claim) -> str:
    return " ".join(
        p
        for p in [
            claim.title,
            claim.canonical_text,
            claim.short_text,
            claim.long_text,
            claim.category,
            claim.supporting_excerpt,
        ]
        if p
    )


def _answer_search_text(answer: ReusableAnswer) -> str:
    return " ".join(
        p
        for p in [
            answer.question_title,
            " ".join(_loads_list(answer.variants_json)),
            answer.short_answer,
            answer.standard_answer,
            answer.long_answer,
            answer.category,
        ]
        if p
    )


def _score_items(query: str, texts: list[str]) -> list[float]:
    query_tokens = tokenize(query)
    docs_tokens = [tokenize(t) for t in texts]
    bm25 = _bm25_scores(query_tokens, docs_tokens)
    combined = [bm25[i] + _phrase_bonus(query, texts[i]) for i in range(len(texts))]
    return _normalize(combined)


# --- public API --------------------------------------------------------------


def search_claims(
    session: Session,
    query: str,
    *,
    filters: RetrievalFilters | None = None,
    usable_only: bool = True,
    limit: int = 10,
    now: datetime | None = None,
) -> list[RetrievedItem]:
    filters = filters or RetrievalFilters()
    now = now or utcnow_naive()
    claims = _candidate_claims(session, filters, usable_only, now)
    texts = [_claim_search_text(c) for c in claims]
    scores = _score_items(query, texts)
    items = [
        RetrievedItem(
            kind="claim",
            id=c.id,
            score=scores[i],
            title=c.title,
            text=c.canonical_text,
            metadata={
                "category": c.category,
                "status": c.status,
                "company_entity_id": c.company_entity_id,
                "source_document_id": c.source_document_id,
                "source_page": c.source_page,
                "source_section": c.source_section,
                "supporting_excerpt": c.supporting_excerpt,
                "short_text": c.short_text,
                "long_text": c.long_text,
                "expiration_date": c.expiration_date.isoformat()
                if c.expiration_date
                else None,
                "restrictions": c.restrictions,
            },
        )
        for i, c in enumerate(claims)
    ]
    items = [it for it in items if it.score > 0 or not query.strip()]
    items.sort(key=lambda it: it.score, reverse=True)
    return items[:limit]


def search_answers(
    session: Session,
    query: str,
    *,
    filters: RetrievalFilters | None = None,
    usable_only: bool = True,
    limit: int = 10,
    now: datetime | None = None,
) -> list[RetrievedItem]:
    filters = filters or RetrievalFilters()
    now = now or utcnow_naive()
    answers = _candidate_answers(session, filters, usable_only, now)
    texts = [_answer_search_text(a) for a in answers]
    scores = _score_items(query, texts)
    items = [
        RetrievedItem(
            kind="answer",
            id=a.id,
            score=scores[i],
            title=a.question_title,
            text=a.standard_answer or a.short_answer or a.long_answer or "",
            metadata={
                "category": a.category,
                "status": a.status,
                "company_entity_id": a.company_entity_id,
                "short_answer": a.short_answer,
                "standard_answer": a.standard_answer,
                "long_answer": a.long_answer,
                "supporting_claim_ids": _loads_list(a.supporting_claim_ids_json),
                "supporting_document_ids": _loads_list(a.supporting_document_ids_json),
                "expiration_date": a.expiration_date.isoformat()
                if a.expiration_date
                else None,
            },
        )
        for i, a in enumerate(answers)
    ]
    items = [it for it in items if it.score > 0 or not query.strip()]
    items.sort(key=lambda it: it.score, reverse=True)
    return items[:limit]


def search_chunks(
    session: Session,
    query: str,
    *,
    filters: RetrievalFilters | None = None,
    limit: int = 10,
    document_ids: list[int] | None = None,
    include_archived: bool = False,
) -> list[RetrievedItem]:
    filters = filters or RetrievalFilters()
    documents = {d.id: d for d in session.exec(select(KbDocument)).all()}
    chunks = list(session.exec(select(KbDocumentChunk)).all())

    def keep(chunk: KbDocumentChunk) -> bool:
        doc = documents.get(chunk.document_id)
        if doc is None:
            return False
        if doc.archived and not include_archived:
            return False
        if document_ids is not None and chunk.document_id not in document_ids:
            return False
        if not _entity_ok(doc.company_entity_id, filters.company_entity_id):
            return False
        if filters.category and (doc.category or "") != filters.category:
            return False
        if filters.state and doc.applicable_state and doc.applicable_state != filters.state:
            return False
        if (
            filters.service_type
            and doc.service_type
            and doc.service_type != filters.service_type
        ):
            return False
        return True

    candidates = [c for c in chunks if keep(c)]
    texts = [c.text for c in candidates]
    scores = _score_items(query, texts)
    items = []
    for i, chunk in enumerate(candidates):
        doc = documents.get(chunk.document_id)
        items.append(
            RetrievedItem(
                kind="chunk",
                id=chunk.id,
                score=scores[i],
                title=(doc.title if doc else f"Document {chunk.document_id}"),
                text=chunk.text,
                metadata={
                    "document_id": chunk.document_id,
                    "document_title": doc.title if doc else None,
                    "page_number": chunk.page_number,
                    "section": chunk.section,
                    "sheet_name": chunk.sheet_name,
                    "cell_range": chunk.cell_range,
                    "expiration_date": doc.expiration_date.isoformat()
                    if doc and doc.expiration_date
                    else None,
                },
            )
        )
    items = [it for it in items if it.score > 0]
    items.sort(key=lambda it: it.score, reverse=True)
    return items[:limit]


def hybrid_search(
    session: Session,
    query: str,
    *,
    filters: RetrievalFilters | None = None,
    kinds: tuple[str, ...] = ("claim", "answer", "chunk"),
    limit_per_kind: int = 10,
    usable_only: bool = False,
) -> dict[str, list[RetrievedItem]]:
    """General search across knowledge entities (Search page)."""
    result: dict[str, list[RetrievedItem]] = {}
    if "claim" in kinds:
        result["claims"] = search_claims(
            session, query, filters=filters, usable_only=usable_only, limit=limit_per_kind
        )
    if "answer" in kinds:
        result["answers"] = search_answers(
            session, query, filters=filters, usable_only=usable_only, limit=limit_per_kind
        )
    if "chunk" in kinds:
        result["chunks"] = search_chunks(
            session, query, filters=filters, limit=limit_per_kind
        )
    return result


def retrieve_for_drafting(
    session: Session,
    query: str,
    *,
    filters: RetrievalFilters | None = None,
    max_claims: int = 8,
    max_answers: int = 3,
    max_chunks: int = 6,
    now: datetime | None = None,
) -> dict[str, list[RetrievedItem]]:
    """Retrieve approved, in-scope evidence for the drafting pipeline.

    Claims and answers are restricted to usable (Approved, non-expired) rows.
    Supporting chunks are drawn from the source documents of the retrieved
    claims plus the top query-matching chunks, so the draft has verbatim
    evidence to cite.
    """
    filters = filters or RetrievalFilters()
    now = now or utcnow_naive()
    claims = search_claims(
        session, query, filters=filters, usable_only=True, limit=max_claims, now=now
    )
    answers = search_answers(
        session, query, filters=filters, usable_only=True, limit=max_answers, now=now
    )
    source_doc_ids = [
        c.metadata.get("source_document_id")
        for c in claims
        if c.metadata.get("source_document_id")
    ]
    chunks = search_chunks(
        session,
        query,
        filters=filters,
        limit=max_chunks,
        document_ids=source_doc_ids or None,
    )
    if len(chunks) < max_chunks:
        extra = search_chunks(
            session, query, filters=filters, limit=max_chunks
        )
        seen = {c.id for c in chunks}
        for item in extra:
            if item.id not in seen:
                chunks.append(item)
                seen.add(item.id)
            if len(chunks) >= max_chunks:
                break
    return {"claims": claims, "answers": answers, "chunks": chunks[:max_chunks]}
