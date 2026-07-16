"""Hybrid search across the knowledge base.

Covers source documents, extracted document text (chunks), claims, reusable
answers, and generated responses. Modes:
- keyword / semantic: BM25 + TF-IDF lexical scoring (retrieval module);
- exact phrase: substring match;
plus metadata / entity / state / category / approval-status filtering.

True vector semantic search (pgvector) is unavailable on SQLite; the lexical
hybrid is the documented tradeoff.
"""

from __future__ import annotations

from sqlmodel import Session, select

from app.kb_models import GeneratedResponse, KbDocument
from app.services.kb.retrieval import (
    RetrievalFilters,
    hybrid_search,
    tokenize,
)
from app.services.kb.serializers import document_to_dict, response_to_dict


def _phrase_hits(query: str, text: str) -> bool:
    return bool(query) and query.strip().lower() in (text or "").lower()


def _keyword_hits(query: str, text: str) -> bool:
    q = set(tokenize(query))
    if not q:
        return True
    return bool(q.intersection(tokenize(text)))


def search_documents(
    session: Session,
    query: str,
    *,
    filters: RetrievalFilters | None = None,
    exact_phrase: bool = False,
    include_archived: bool = False,
    limit: int = 20,
) -> list[dict]:
    filters = filters or RetrievalFilters()
    documents = list(session.exec(select(KbDocument)).all())
    results = []
    for d in documents:
        if d.archived and not include_archived:
            continue
        if filters.company_entity_id is not None and d.company_entity_id != filters.company_entity_id:
            continue
        if filters.category and d.category != filters.category:
            continue
        if filters.state and d.applicable_state and d.applicable_state != filters.state:
            continue
        if filters.service_type and d.service_type and d.service_type != filters.service_type:
            continue
        haystack = " ".join(
            p for p in [d.title, d.filename, d.doc_type, d.category, d.notes] if p
        )
        if query.strip():
            if exact_phrase and not _phrase_hits(query, haystack):
                continue
            if not exact_phrase and not _keyword_hits(query, haystack):
                continue
        results.append(document_to_dict(d, include_flags=False))
    return results[:limit]


def search_responses(
    session: Session,
    query: str,
    *,
    exact_phrase: bool = False,
    limit: int = 20,
) -> list[dict]:
    responses = list(session.exec(select(GeneratedResponse)).all())
    results = []
    for r in responses:
        haystack = " ".join(
            p for p in [r.request_question, r.response_text, r.category] if p
        )
        if query.strip():
            if exact_phrase and not _phrase_hits(query, haystack):
                continue
            if not exact_phrase and not _keyword_hits(query, haystack):
                continue
        results.append(response_to_dict(r))
    return results[:limit]


def search_all(
    session: Session,
    query: str,
    *,
    filters: RetrievalFilters | None = None,
    kinds: tuple[str, ...] = ("document", "claim", "answer", "response", "chunk"),
    exact_phrase: bool = False,
    include_restricted: bool = False,
    limit_per_kind: int = 15,
) -> dict:
    filters = filters or RetrievalFilters()
    filters.include_restricted = include_restricted
    out: dict = {}

    lexical_kinds = tuple(k for k in ("claim", "answer", "chunk") if k in kinds)
    if lexical_kinds:
        hits = hybrid_search(
            session,
            query,
            filters=filters,
            kinds=lexical_kinds,
            limit_per_kind=limit_per_kind,
            usable_only=False,
        )
        for key, items in hits.items():
            # In exact-phrase mode, keep only items whose text/title actually
            # contains the phrase (BM25 alone is order-independent).
            if exact_phrase and query.strip():
                items = [
                    it for it in items if _phrase_hits(query, f"{it.title} {it.text}")
                ]
            out[key] = [
                {
                    "kind": it.kind,
                    "id": it.id,
                    "score": round(it.score, 4),
                    "title": it.title,
                    "text": it.text[:400],
                    "metadata": it.metadata,
                }
                for it in items
            ]

    if "document" in kinds:
        out["documents"] = search_documents(
            session, query, filters=filters, exact_phrase=exact_phrase, limit=limit_per_kind
        )
    if "response" in kinds:
        out["responses"] = search_responses(
            session, query, exact_phrase=exact_phrase, limit=limit_per_kind
        )
    return out
