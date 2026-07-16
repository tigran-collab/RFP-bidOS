"""Pydantic request/response schemas for the Knowledge Base API.

Create/update schemas keep fields optional and ``extra="ignore"`` so the
service layer (which validates choices and handles partial payloads) stays the
single source of truth. Only supplied fields are forwarded via
``model_dump(exclude_unset=True)``.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore")


# --- admin -------------------------------------------------------------------


class UserCreate(_Base):
    name: str
    email: str | None = None
    role: str = "read_only"
    active: bool = True


class UserUpdate(_Base):
    name: str | None = None
    email: str | None = None
    role: str | None = None
    active: bool | None = None


class EntityCreate(_Base):
    name: str
    legal_name: str | None = None
    dba: str | None = None
    state_of_incorporation: str | None = None
    description: str | None = None
    active: bool = True


class EntityUpdate(_Base):
    name: str | None = None
    legal_name: str | None = None
    dba: str | None = None
    state_of_incorporation: str | None = None
    description: str | None = None
    active: bool | None = None


# --- documents ---------------------------------------------------------------


class DocumentMetadataUpdate(_Base):
    title: str | None = None
    doc_type: str | None = None
    category: str | None = None
    company_entity_id: int | None = None
    applicable_state: str | None = None
    applicable_industry: str | None = None
    service_type: str | None = None
    tags: list[str] | None = None
    effective_date: datetime | None = None
    expiration_date: datetime | None = None
    last_reviewed_at: datetime | None = None
    notes: str | None = None


class ArchiveRequest(_Base):
    archived: bool = True


# --- gallery -----------------------------------------------------------------


class GalleryAssetUpdate(_Base):
    title: str | None = None
    category: str | None = None
    company_entity_id: int | None = None
    description: str | None = None
    alt_text: str | None = None
    tags: list[str] | None = None
    effective_date: datetime | None = None
    expiration_date: datetime | None = None
    last_reviewed_at: datetime | None = None


# --- claims ------------------------------------------------------------------


class ClaimCreate(_Base):
    title: str
    canonical_text: str
    short_text: str | None = None
    long_text: str | None = None
    category: str | None = None
    company_entity_id: int | None = None
    geographic_scope: str | None = None
    applicable_states: list[str] | None = None
    service_scope: list[str] | None = None
    industry_scope: list[str] | None = None
    source_document_id: int | None = None
    source_page: int | None = None
    source_section: str | None = None
    supporting_excerpt: str | None = None
    status: str | None = None
    effective_date: datetime | None = None
    expiration_date: datetime | None = None
    owner: int | None = None
    confidence: str | None = None
    restrictions: str | None = None
    internal_notes: str | None = None
    prohibited_use_notes: str | None = None


class ClaimUpdate(_Base):
    title: str | None = None
    canonical_text: str | None = None
    short_text: str | None = None
    long_text: str | None = None
    category: str | None = None
    company_entity_id: int | None = None
    geographic_scope: str | None = None
    applicable_states: list[str] | None = None
    service_scope: list[str] | None = None
    industry_scope: list[str] | None = None
    source_document_id: int | None = None
    source_page: int | None = None
    source_section: str | None = None
    supporting_excerpt: str | None = None
    effective_date: datetime | None = None
    expiration_date: datetime | None = None
    last_reviewed_at: datetime | None = None
    owner: int | None = None
    confidence: str | None = None
    restrictions: str | None = None
    internal_notes: str | None = None
    prohibited_use_notes: str | None = None
    change_note: str | None = None


class StatusChangeRequest(_Base):
    note: str | None = None


class SupersedeRequest(_Base):
    superseded_by_id: int
    note: str | None = None


class ClaimSourceRequest(_Base):
    document_id: int | None = None
    chunk_id: int | None = None
    page_number: int | None = None
    section: str | None = None
    excerpt: str | None = None


# --- answers -----------------------------------------------------------------


class QuestionCreate(_Base):
    title: str
    variants: list[str] | None = None
    category: str | None = None


class AnswerCreate(_Base):
    question_id: int | None = None
    question_title: str
    variants: list[str] | None = None
    category: str | None = None
    short_answer: str | None = None
    standard_answer: str | None = None
    long_answer: str | None = None
    company_entity_id: int | None = None
    applicable_services: list[str] | None = None
    applicable_states: list[str] | None = None
    applicable_industries: list[str] | None = None
    supporting_claim_ids: list[int] | None = None
    supporting_document_ids: list[int] | None = None
    status: str | None = None
    owner: int | None = None
    effective_date: datetime | None = None
    expiration_date: datetime | None = None
    internal_guidance: str | None = None
    restrictions: str | None = None


class AnswerUpdate(_Base):
    question_id: int | None = None
    question_title: str | None = None
    variants: list[str] | None = None
    category: str | None = None
    short_answer: str | None = None
    standard_answer: str | None = None
    long_answer: str | None = None
    company_entity_id: int | None = None
    applicable_services: list[str] | None = None
    applicable_states: list[str] | None = None
    applicable_industries: list[str] | None = None
    supporting_claim_ids: list[int] | None = None
    supporting_document_ids: list[int] | None = None
    effective_date: datetime | None = None
    expiration_date: datetime | None = None
    last_reviewed_at: datetime | None = None
    internal_guidance: str | None = None
    restrictions: str | None = None
    change_note: str | None = None


# --- responses / drafting ----------------------------------------------------


class GenerateRequest(_Base):
    question: str
    agency_name: str | None = None
    solicitation_number: str | None = None
    company_entity_id: int | None = None
    state: str | None = None
    industry: str | None = None
    service_type: str | None = None
    word_count_target: int | None = None
    tone: str | None = None
    detail_level: str | None = None
    formatting_instructions: str | None = None
    opportunity_id: int | None = None
    rfp_section: str | None = None
    question_number: str | None = None
    assigned_owner: int | None = None
    provider: str | None = None  # "local" (default) | "claude"


class TransformRequest(_Base):
    operation: str
    instructions: str | None = None
    provider: str | None = None  # "local" (default) | "claude"


class ClaudeConfigUpdate(_Base):
    api_key: str | None = None
    model: str | None = None


class GoogleDriveConfigUpdate(_Base):
    access_token: str | None = None
    refresh_token: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    folder_id: str | None = None


class GoogleDriveImportRequest(_Base):
    file_ids: list[str]
    company_entity_id: int | None = None


class ResponseUpdate(_Base):
    response_text: str | None = None
    rfp_section: str | None = None
    question_number: str | None = None
    assigned_owner: int | None = None
    agency_name: str | None = None
    solicitation_number: str | None = None
    review_status: str | None = None
    due_date: datetime | None = None
    opportunity_id: int | None = None


class SaveToProjectRequest(_Base):
    opportunity_id: int
    rfp_section: str | None = None
    question_number: str | None = None
    assigned_owner: int | None = None
    due_date: datetime | None = None
    review_status: str | None = None


# --- conflicts ---------------------------------------------------------------


class ConflictResolveRequest(_Base):
    resolution: str
    authoritative_claim_id: int | None = None
    explanation: str | None = None


class DetectConflictsRequest(_Base):
    company_entity_id: int | None = None


# --- reviews / comments ------------------------------------------------------


class ReviewRequestCreate(_Base):
    target_type: str
    target_id: int
    note: str | None = None
    assigned_to: int | None = None


class ReviewResolveRequest(_Base):
    status: str
    resolution: str | None = None


class CommentCreate(_Base):
    target_type: str
    target_id: int
    body: str
