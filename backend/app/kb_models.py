"""Company Knowledge Base data model.

Governed knowledge system (not a chatbot-over-a-folder): source documents,
approved claims, approved reusable answers, company entities, evidence records,
conflicts, review/approval workflow, version history, and generated responses
with citations.

Tables are namespaced (``Kb*`` / ``Claim`` / ``CompanyEntity``) so they never
collide with the opportunity-side ``Document`` / ``Requirement`` tables. Text is
related by id rather than duplicated wherever practical; longer lists (states,
industries, tags, supporting ids) follow the repo's established ``*_json``
string-column convention.

Timestamps use ``models.utcnow_naive`` for consistency with the rest of the app.
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel

from app.models import utcnow_naive


# --- Governance: entities, users --------------------------------------------


class CompanyEntity(SQLModel, table=True):
    """A legal entity. Claims/answers/documents belong to exactly one entity so
    facts from different legal entities are never silently combined."""

    __tablename__ = "kb_company_entity"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    legal_name: str | None = None
    dba: str | None = None
    state_of_incorporation: str | None = None
    description: str | None = None
    active: bool = True
    created_at: datetime = Field(default_factory=utcnow_naive)
    updated_at: datetime = Field(default_factory=utcnow_naive)


class KbUser(SQLModel, table=True):
    """A knowledge-base user with a role. The app has no login (local-first);
    the acting user is resolved from a request header and permissions are
    enforced server-side from this row's role. See kb_vocab.ROLE_PERMISSIONS."""

    __tablename__ = "kb_user"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    email: str | None = Field(default=None, index=True)
    role: str = "read_only"
    active: bool = True
    created_at: datetime = Field(default_factory=utcnow_naive)


# --- Source Document Vault ---------------------------------------------------


class KbDocument(SQLModel, table=True):
    """A source document in the vault. Retains the original file (``path``) and
    the extracted text (per-page/section in KbDocumentChunk rows)."""

    __tablename__ = "kb_document"

    id: int | None = Field(default=None, primary_key=True)
    title: str
    filename: str
    path: str  # stored original file (under data/kb_documents/)
    file_type: str | None = None  # normalized extension: pdf/docx/xlsx/csv/txt/...
    mime_type: str | None = None
    sha256: str | None = Field(default=None, index=True)
    size_bytes: int | None = None

    # Metadata / classification
    doc_type: str | None = None  # kb_vocab.DOCUMENT_TYPES
    category: str | None = None  # kb_vocab.CLAIM_CATEGORIES
    company_entity_id: int | None = Field(
        default=None, foreign_key="kb_company_entity.id", index=True
    )
    applicable_state: str | None = None
    applicable_industry: str | None = None
    service_type: str | None = None
    tags_json: str | None = None  # ["tag", ...]

    effective_date: datetime | None = None
    expiration_date: datetime | None = None
    uploaded_by: int | None = Field(default=None, foreign_key="kb_user.id")
    uploaded_at: datetime = Field(default_factory=utcnow_naive)
    last_reviewed_at: datetime | None = None
    archived: bool = False
    notes: str | None = None

    # Processing pipeline
    processing_status: str = "Uploaded"  # kb_vocab.DOC_STATUSES
    processing_error: str | None = None
    processed_at: datetime | None = None
    page_count: int | None = None
    chunk_count: int | None = None
    sheet_names_json: str | None = None  # spreadsheets: ["Sheet1", ...]
    # Prompt-injection markers detected in the extracted text (untrusted data).
    injection_flags_json: str | None = None  # [{page, snippet, pattern}]

    created_at: datetime = Field(default_factory=utcnow_naive)
    updated_at: datetime = Field(default_factory=utcnow_naive)


class KbDocumentChunk(SQLModel, table=True):
    """A retrievable unit of a document, preserving page boundaries (PDF) and
    sheet/cell ranges (spreadsheets) so responses can cite the real source."""

    __tablename__ = "kb_document_chunk"

    id: int | None = Field(default=None, primary_key=True)
    document_id: int = Field(foreign_key="kb_document.id", index=True)
    chunk_index: int = 0
    page_number: int | None = None
    section: str | None = None
    sheet_name: str | None = None
    cell_range: str | None = None
    text: str = ""
    char_count: int | None = None
    # Optional local embedding (Ollama) as a JSON float array; retrieval works
    # without it via the lexical TF-IDF path.
    embedding_json: str | None = None
    created_at: datetime = Field(default_factory=utcnow_naive)


# --- Claims Registry ---------------------------------------------------------


class Claim(SQLModel, table=True):
    """A structured, individually-governed company fact. Only Approved,
    non-expired claims are used automatically in AI responses."""

    __tablename__ = "kb_claim"

    id: int | None = Field(default=None, primary_key=True)
    title: str
    canonical_text: str
    short_text: str | None = None
    long_text: str | None = None
    category: str | None = Field(default=None, index=True)

    company_entity_id: int | None = Field(
        default=None, foreign_key="kb_company_entity.id", index=True
    )
    geographic_scope: str | None = None
    applicable_states_json: str | None = None  # ["CA", "TX"]
    service_scope_json: str | None = None  # ["Armed Security", ...]
    industry_scope_json: str | None = None  # ["Healthcare", ...]

    # Primary evidence (additional evidence lives in KbClaimSource rows).
    source_document_id: int | None = Field(
        default=None, foreign_key="kb_document.id", index=True
    )
    source_page: int | None = None
    source_section: str | None = None
    supporting_excerpt: str | None = None

    status: str = Field(default="Draft", index=True)  # kb_vocab.CLAIM_STATUSES
    approved_by: int | None = Field(default=None, foreign_key="kb_user.id")
    approved_at: datetime | None = None
    effective_date: datetime | None = None
    expiration_date: datetime | None = None
    last_reviewed_at: datetime | None = None
    owner: int | None = Field(default=None, foreign_key="kb_user.id")
    confidence: str | None = None  # High/Medium/Low
    restrictions: str | None = None
    internal_notes: str | None = None
    prohibited_use_notes: str | None = None
    superseded_by_id: int | None = Field(
        default=None, foreign_key="kb_claim.id", index=True
    )
    version: int = 1
    created_by: int | None = Field(default=None, foreign_key="kb_user.id")
    created_at: datetime = Field(default_factory=utcnow_naive)
    updated_at: datetime = Field(default_factory=utcnow_naive)


class KbClaimSource(SQLModel, table=True):
    """Additional evidence records tying a claim to a document page/section.

    Table is ``kb_claim_evidence`` (not ``kb_claim_source``) so its
    ``document_id`` index name does not collide with ``kb_claim.source_document_id``
    (both would otherwise auto-name ``ix_kb_claim_source_document_id``)."""

    __tablename__ = "kb_claim_evidence"

    id: int | None = Field(default=None, primary_key=True)
    claim_id: int = Field(foreign_key="kb_claim.id", index=True)
    document_id: int | None = Field(
        default=None, foreign_key="kb_document.id", index=True
    )
    chunk_id: int | None = Field(default=None, foreign_key="kb_document_chunk.id")
    page_number: int | None = None
    section: str | None = None
    excerpt: str | None = None
    created_at: datetime = Field(default_factory=utcnow_naive)


class KbClaimVersion(SQLModel, table=True):
    """Immutable snapshot of a claim at a point in time (audit/version history)."""

    __tablename__ = "kb_claim_version"

    id: int | None = Field(default=None, primary_key=True)
    claim_id: int = Field(foreign_key="kb_claim.id", index=True)
    version: int = 1
    snapshot_json: str = "{}"
    change_note: str | None = None
    changed_by: int | None = Field(default=None, foreign_key="kb_user.id")
    created_at: datetime = Field(default_factory=utcnow_naive)


# --- Reusable Answer Library -------------------------------------------------


class ReusableQuestion(SQLModel, table=True):
    """A common RFP question (with variants) that maps to reusable answers."""

    __tablename__ = "kb_reusable_question"

    id: int | None = Field(default=None, primary_key=True)
    title: str
    variants_json: str | None = None  # ["Describe your company", ...]
    category: str | None = None  # kb_vocab.ANSWER_CATEGORIES
    created_by: int | None = Field(default=None, foreign_key="kb_user.id")
    created_at: datetime = Field(default_factory=utcnow_naive)
    updated_at: datetime = Field(default_factory=utcnow_naive)


class ReusableAnswer(SQLModel, table=True):
    """An approved reusable answer for a common question."""

    __tablename__ = "kb_reusable_answer"

    id: int | None = Field(default=None, primary_key=True)
    question_id: int | None = Field(
        default=None, foreign_key="kb_reusable_question.id", index=True
    )
    question_title: str
    variants_json: str | None = None
    category: str | None = Field(default=None, index=True)
    short_answer: str | None = None
    standard_answer: str | None = None
    long_answer: str | None = None

    company_entity_id: int | None = Field(
        default=None, foreign_key="kb_company_entity.id", index=True
    )
    applicable_services_json: str | None = None
    applicable_states_json: str | None = None
    applicable_industries_json: str | None = None
    supporting_claim_ids_json: str | None = None  # [claim_id, ...]
    supporting_document_ids_json: str | None = None  # [document_id, ...]

    status: str = Field(default="Draft", index=True)  # kb_vocab.ANSWER_STATUSES
    owner: int | None = Field(default=None, foreign_key="kb_user.id")
    approved_by: int | None = Field(default=None, foreign_key="kb_user.id")
    approved_at: datetime | None = None
    effective_date: datetime | None = None
    expiration_date: datetime | None = None
    last_reviewed_at: datetime | None = None
    usage_count: int = 0
    last_used_at: datetime | None = None
    internal_guidance: str | None = None
    restrictions: str | None = None
    version: int = 1
    created_by: int | None = Field(default=None, foreign_key="kb_user.id")
    created_at: datetime = Field(default_factory=utcnow_naive)
    updated_at: datetime = Field(default_factory=utcnow_naive)


class KbAnswerVersion(SQLModel, table=True):
    __tablename__ = "kb_answer_version"

    id: int | None = Field(default=None, primary_key=True)
    answer_id: int = Field(foreign_key="kb_reusable_answer.id", index=True)
    version: int = 1
    snapshot_json: str = "{}"
    change_note: str | None = None
    changed_by: int | None = Field(default=None, foreign_key="kb_user.id")
    created_at: datetime = Field(default_factory=utcnow_naive)


# --- Generated responses + citations -----------------------------------------


class GeneratedResponse(SQLModel, table=True):
    """A saved AI-drafted response with full audit metadata: prompt, retrieved
    context, output, model info. Optionally linked to an existing Opportunity."""

    __tablename__ = "kb_generated_response"

    id: int | None = Field(default=None, primary_key=True)
    request_question: str
    normalized_question: str | None = None
    category: str | None = None

    agency_name: str | None = None
    solicitation_number: str | None = None
    company_entity_id: int | None = Field(
        default=None, foreign_key="kb_company_entity.id", index=True
    )
    state: str | None = None
    industry: str | None = None
    service_type: str | None = None
    word_count_target: int | None = None
    tone: str | None = None
    detail_level: str | None = None
    formatting_instructions: str | None = None

    response_text: str | None = None
    confidence_score: float | None = None
    model_name: str | None = None
    prompt_text: str | None = None
    retrieved_context_json: str | None = None  # {claims:[], answers:[], chunks:[]}
    warnings_json: str | None = None  # [{type, message, severity}]

    # Project integration
    opportunity_id: int | None = Field(
        default=None, foreign_key="opportunity.id", index=True
    )
    rfp_section: str | None = None
    question_number: str | None = None
    assigned_owner: int | None = Field(default=None, foreign_key="kb_user.id")
    review_status: str = "Draft"  # kb_vocab.RESPONSE_REVIEW_STATUSES
    due_date: datetime | None = None

    created_by: int | None = Field(default=None, foreign_key="kb_user.id")
    created_at: datetime = Field(default_factory=utcnow_naive)
    updated_at: datetime = Field(default_factory=utcnow_naive)


class ResponseCitation(SQLModel, table=True):
    __tablename__ = "kb_response_citation"

    id: int | None = Field(default=None, primary_key=True)
    response_id: int = Field(foreign_key="kb_generated_response.id", index=True)
    marker: str | None = None  # e.g. "[1]"
    claim_id: int | None = Field(default=None, foreign_key="kb_claim.id")
    answer_id: int | None = Field(
        default=None, foreign_key="kb_reusable_answer.id"
    )
    document_id: int | None = Field(default=None, foreign_key="kb_document.id")
    page_number: int | None = None
    section: str | None = None
    excerpt: str | None = None
    approval_status: str | None = None
    effective_date: datetime | None = None
    expiration_date: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow_naive)


# --- Review / approval / audit / conflicts -----------------------------------


class KbReviewRequest(SQLModel, table=True):
    __tablename__ = "kb_review_request"

    id: int | None = Field(default=None, primary_key=True)
    target_type: str = Field(index=True)  # kb_vocab.TARGET_TYPES
    target_id: int = Field(index=True)
    status: str = "Open"  # kb_vocab.REVIEW_REQUEST_STATUSES
    note: str | None = None
    requested_by: int | None = Field(default=None, foreign_key="kb_user.id")
    assigned_to: int | None = Field(default=None, foreign_key="kb_user.id")
    resolution: str | None = None
    resolved_by: int | None = Field(default=None, foreign_key="kb_user.id")
    resolved_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow_naive)


class KbComment(SQLModel, table=True):
    __tablename__ = "kb_comment"

    id: int | None = Field(default=None, primary_key=True)
    target_type: str = Field(index=True)
    target_id: int = Field(index=True)
    author_id: int | None = Field(default=None, foreign_key="kb_user.id")
    body: str = ""
    created_at: datetime = Field(default_factory=utcnow_naive)


class KbApproval(SQLModel, table=True):
    """An approval-history record (who approved/rejected/restricted what, when)."""

    __tablename__ = "kb_approval"

    id: int | None = Field(default=None, primary_key=True)
    target_type: str = Field(index=True)
    target_id: int = Field(index=True)
    action: str = ""  # approved / rejected / restricted / superseded / ...
    actor_id: int | None = Field(default=None, foreign_key="kb_user.id")
    note: str | None = None
    created_at: datetime = Field(default_factory=utcnow_naive)


class KbConflict(SQLModel, table=True):
    """A detected potential contradiction between two claims."""

    __tablename__ = "kb_conflict"

    id: int | None = Field(default=None, primary_key=True)
    conflict_type: str = ""  # employee_count / address / license_number / ...
    company_entity_id: int | None = Field(
        default=None, foreign_key="kb_company_entity.id", index=True
    )
    claim_a_id: int | None = Field(default=None, foreign_key="kb_claim.id")
    claim_b_id: int | None = Field(default=None, foreign_key="kb_claim.id")
    field: str | None = None
    value_a: str | None = None
    value_b: str | None = None
    detail: str | None = None
    status: str = Field(default="Open", index=True)  # kb_vocab.CONFLICT_STATUSES
    resolution: str | None = None
    authoritative_claim_id: int | None = Field(
        default=None, foreign_key="kb_claim.id"
    )
    explanation: str | None = None
    resolved_by: int | None = Field(default=None, foreign_key="kb_user.id")
    resolved_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow_naive)


class KbAuditLog(SQLModel, table=True):
    __tablename__ = "kb_audit_log"

    id: int | None = Field(default=None, primary_key=True)
    actor_id: int | None = Field(default=None, foreign_key="kb_user.id", index=True)
    action: str = Field(index=True)
    target_type: str | None = Field(default=None, index=True)
    target_id: int | None = Field(default=None, index=True)
    detail_json: str | None = None
    created_at: datetime = Field(default_factory=utcnow_naive)


class KbTag(SQLModel, table=True):
    """Free-form tag catalog (documents/claims/answers reference tags by name in
    their ``tags_json`` arrays; this table powers tag discovery/filtering)."""

    __tablename__ = "kb_tag"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    kind: str | None = None  # kb_vocab.TAG_KINDS
    created_at: datetime = Field(default_factory=utcnow_naive)


# --- Media Gallery -----------------------------------------------------------


class GalleryAsset(SQLModel, table=True):
    """A reusable visual asset (logo, badge, photo, diagram) for proposals.

    Unlike KbDocument, gallery assets are displayed/reused as images rather than
    text-extracted into claims. The original file is retained under
    ``data/kb_gallery/`` and served safely by id."""

    __tablename__ = "kb_gallery_asset"

    id: int | None = Field(default=None, primary_key=True)
    title: str
    filename: str
    path: str  # stored original file (under data/kb_gallery/)
    file_type: str | None = None  # png/jpg/svg/...
    mime_type: str | None = None
    sha256: str | None = Field(default=None, index=True)
    size_bytes: int | None = None
    width: int | None = None
    height: int | None = None

    category: str | None = None  # kb_vocab.GALLERY_CATEGORIES
    company_entity_id: int | None = Field(
        default=None, foreign_key="kb_company_entity.id", index=True
    )
    tags_json: str | None = None  # ["tag", ...]
    description: str | None = None
    alt_text: str | None = None

    effective_date: datetime | None = None
    expiration_date: datetime | None = None
    uploaded_by: int | None = Field(default=None, foreign_key="kb_user.id")
    uploaded_at: datetime = Field(default_factory=utcnow_naive)
    last_reviewed_at: datetime | None = None
    archived: bool = False

    created_at: datetime = Field(default_factory=utcnow_naive)
    updated_at: datetime = Field(default_factory=utcnow_naive)
