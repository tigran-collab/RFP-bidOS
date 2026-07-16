"""Model -> dict serializers shared by services, routers, and version snapshots."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app.kb_models import (
    Claim,
    CompanyEntity,
    GeneratedResponse,
    KbApproval,
    KbAuditLog,
    KbClaimSource,
    KbClaimVersion,
    KbComment,
    KbConflict,
    KbDocument,
    KbDocumentChunk,
    KbReviewRequest,
    KbUser,
    ResponseCitation,
    ReusableAnswer,
    ReusableQuestion,
)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _loads(raw: str | None) -> Any:
    if not raw:
        return []
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return []


def entity_to_dict(e: CompanyEntity) -> dict:
    return {
        "id": e.id,
        "name": e.name,
        "legal_name": e.legal_name,
        "dba": e.dba,
        "state_of_incorporation": e.state_of_incorporation,
        "description": e.description,
        "active": e.active,
        "created_at": _iso(e.created_at),
    }


def user_to_dict(u: KbUser) -> dict:
    return {
        "id": u.id,
        "name": u.name,
        "email": u.email,
        "role": u.role,
        "active": u.active,
        "created_at": _iso(u.created_at),
    }


def document_to_dict(d: KbDocument, *, include_flags: bool = True) -> dict:
    data = {
        "id": d.id,
        "title": d.title,
        "filename": d.filename,
        "file_type": d.file_type,
        "mime_type": d.mime_type,
        "sha256": d.sha256,
        "size_bytes": d.size_bytes,
        "doc_type": d.doc_type,
        "category": d.category,
        "company_entity_id": d.company_entity_id,
        "applicable_state": d.applicable_state,
        "applicable_industry": d.applicable_industry,
        "service_type": d.service_type,
        "tags": _loads(d.tags_json),
        "effective_date": _iso(d.effective_date),
        "expiration_date": _iso(d.expiration_date),
        "uploaded_by": d.uploaded_by,
        "uploaded_at": _iso(d.uploaded_at),
        "last_reviewed_at": _iso(d.last_reviewed_at),
        "archived": d.archived,
        "notes": d.notes,
        "processing_status": d.processing_status,
        "processing_error": d.processing_error,
        "processed_at": _iso(d.processed_at),
        "page_count": d.page_count,
        "chunk_count": d.chunk_count,
        "sheet_names": _loads(d.sheet_names_json),
        "created_at": _iso(d.created_at),
        "updated_at": _iso(d.updated_at),
    }
    if include_flags:
        data["injection_flags"] = _loads(d.injection_flags_json)
    return data


def chunk_to_dict(c: KbDocumentChunk) -> dict:
    return {
        "id": c.id,
        "document_id": c.document_id,
        "chunk_index": c.chunk_index,
        "page_number": c.page_number,
        "section": c.section,
        "sheet_name": c.sheet_name,
        "cell_range": c.cell_range,
        "text": c.text,
        "char_count": c.char_count,
    }


def claim_to_dict(c: Claim) -> dict:
    return {
        "id": c.id,
        "title": c.title,
        "canonical_text": c.canonical_text,
        "short_text": c.short_text,
        "long_text": c.long_text,
        "category": c.category,
        "company_entity_id": c.company_entity_id,
        "geographic_scope": c.geographic_scope,
        "applicable_states": _loads(c.applicable_states_json),
        "service_scope": _loads(c.service_scope_json),
        "industry_scope": _loads(c.industry_scope_json),
        "source_document_id": c.source_document_id,
        "source_page": c.source_page,
        "source_section": c.source_section,
        "supporting_excerpt": c.supporting_excerpt,
        "status": c.status,
        "approved_by": c.approved_by,
        "approved_at": _iso(c.approved_at),
        "effective_date": _iso(c.effective_date),
        "expiration_date": _iso(c.expiration_date),
        "last_reviewed_at": _iso(c.last_reviewed_at),
        "owner": c.owner,
        "confidence": c.confidence,
        "restrictions": c.restrictions,
        "internal_notes": c.internal_notes,
        "prohibited_use_notes": c.prohibited_use_notes,
        "superseded_by_id": c.superseded_by_id,
        "version": c.version,
        "created_by": c.created_by,
        "created_at": _iso(c.created_at),
        "updated_at": _iso(c.updated_at),
    }


def claim_source_to_dict(s: KbClaimSource) -> dict:
    return {
        "id": s.id,
        "claim_id": s.claim_id,
        "document_id": s.document_id,
        "chunk_id": s.chunk_id,
        "page_number": s.page_number,
        "section": s.section,
        "excerpt": s.excerpt,
        "created_at": _iso(s.created_at),
    }


def claim_version_to_dict(v: KbClaimVersion) -> dict:
    return {
        "id": v.id,
        "claim_id": v.claim_id,
        "version": v.version,
        "snapshot": _loads(v.snapshot_json),
        "change_note": v.change_note,
        "changed_by": v.changed_by,
        "created_at": _iso(v.created_at),
    }


def question_to_dict(q: ReusableQuestion) -> dict:
    return {
        "id": q.id,
        "title": q.title,
        "variants": _loads(q.variants_json),
        "category": q.category,
        "created_by": q.created_by,
        "created_at": _iso(q.created_at),
    }


def answer_to_dict(a: ReusableAnswer) -> dict:
    return {
        "id": a.id,
        "question_id": a.question_id,
        "question_title": a.question_title,
        "variants": _loads(a.variants_json),
        "category": a.category,
        "short_answer": a.short_answer,
        "standard_answer": a.standard_answer,
        "long_answer": a.long_answer,
        "company_entity_id": a.company_entity_id,
        "applicable_services": _loads(a.applicable_services_json),
        "applicable_states": _loads(a.applicable_states_json),
        "applicable_industries": _loads(a.applicable_industries_json),
        "supporting_claim_ids": _loads(a.supporting_claim_ids_json),
        "supporting_document_ids": _loads(a.supporting_document_ids_json),
        "status": a.status,
        "owner": a.owner,
        "approved_by": a.approved_by,
        "approved_at": _iso(a.approved_at),
        "effective_date": _iso(a.effective_date),
        "expiration_date": _iso(a.expiration_date),
        "last_reviewed_at": _iso(a.last_reviewed_at),
        "usage_count": a.usage_count,
        "last_used_at": _iso(a.last_used_at),
        "internal_guidance": a.internal_guidance,
        "restrictions": a.restrictions,
        "version": a.version,
        "created_by": a.created_by,
        "created_at": _iso(a.created_at),
        "updated_at": _iso(a.updated_at),
    }


def response_to_dict(r: GeneratedResponse, *, include_prompt: bool = False) -> dict:
    data = {
        "id": r.id,
        "request_question": r.request_question,
        "normalized_question": r.normalized_question,
        "category": r.category,
        "agency_name": r.agency_name,
        "solicitation_number": r.solicitation_number,
        "company_entity_id": r.company_entity_id,
        "state": r.state,
        "industry": r.industry,
        "service_type": r.service_type,
        "word_count_target": r.word_count_target,
        "tone": r.tone,
        "detail_level": r.detail_level,
        "formatting_instructions": r.formatting_instructions,
        "response_text": r.response_text,
        "confidence_score": r.confidence_score,
        "model_name": r.model_name,
        "warnings": _loads(r.warnings_json),
        "opportunity_id": r.opportunity_id,
        "rfp_section": r.rfp_section,
        "question_number": r.question_number,
        "assigned_owner": r.assigned_owner,
        "review_status": r.review_status,
        "due_date": _iso(r.due_date),
        "created_by": r.created_by,
        "created_at": _iso(r.created_at),
        "updated_at": _iso(r.updated_at),
    }
    if include_prompt:
        data["prompt_text"] = r.prompt_text
        data["retrieved_context"] = _loads(r.retrieved_context_json)
    return data


def citation_to_dict(c: ResponseCitation) -> dict:
    return {
        "id": c.id,
        "response_id": c.response_id,
        "marker": c.marker,
        "claim_id": c.claim_id,
        "answer_id": c.answer_id,
        "document_id": c.document_id,
        "page_number": c.page_number,
        "section": c.section,
        "excerpt": c.excerpt,
        "approval_status": c.approval_status,
        "effective_date": _iso(c.effective_date),
        "expiration_date": _iso(c.expiration_date),
    }


def conflict_to_dict(c: KbConflict) -> dict:
    return {
        "id": c.id,
        "conflict_type": c.conflict_type,
        "company_entity_id": c.company_entity_id,
        "claim_a_id": c.claim_a_id,
        "claim_b_id": c.claim_b_id,
        "field": c.field,
        "value_a": c.value_a,
        "value_b": c.value_b,
        "detail": c.detail,
        "status": c.status,
        "resolution": c.resolution,
        "authoritative_claim_id": c.authoritative_claim_id,
        "explanation": c.explanation,
        "resolved_by": c.resolved_by,
        "resolved_at": _iso(c.resolved_at),
        "created_at": _iso(c.created_at),
    }


def review_request_to_dict(r: KbReviewRequest) -> dict:
    return {
        "id": r.id,
        "target_type": r.target_type,
        "target_id": r.target_id,
        "status": r.status,
        "note": r.note,
        "requested_by": r.requested_by,
        "assigned_to": r.assigned_to,
        "resolution": r.resolution,
        "resolved_by": r.resolved_by,
        "resolved_at": _iso(r.resolved_at),
        "created_at": _iso(r.created_at),
    }


def comment_to_dict(c: KbComment) -> dict:
    return {
        "id": c.id,
        "target_type": c.target_type,
        "target_id": c.target_id,
        "author_id": c.author_id,
        "body": c.body,
        "created_at": _iso(c.created_at),
    }


def approval_to_dict(a: KbApproval) -> dict:
    return {
        "id": a.id,
        "target_type": a.target_type,
        "target_id": a.target_id,
        "action": a.action,
        "actor_id": a.actor_id,
        "note": a.note,
        "created_at": _iso(a.created_at),
    }


def audit_to_dict(a: KbAuditLog) -> dict:
    return {
        "id": a.id,
        "actor_id": a.actor_id,
        "action": a.action,
        "target_type": a.target_type,
        "target_id": a.target_id,
        "detail": _loads(a.detail_json) if a.detail_json else None,
        "created_at": _iso(a.created_at),
    }
