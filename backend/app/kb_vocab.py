"""Controlled vocabularies, roles, and the permission matrix for the Company
Knowledge Base module.

These are canonical constants used for validation (schemas), filter dropdowns
(frontend), and seeding. Following the existing app's string-based design
(``Opportunity.service_type``/``state`` are plain strings), the extensible
vocabularies below are seeded controlled lists rather than foreign-key tables —
a deliberate consistency choice, documented in the README architecture notes.

Nothing here contains company facts. Unverified company claims are never
hardcoded; only structural categories and scaffolding live in this module.
"""

from __future__ import annotations

# --- Roles -------------------------------------------------------------------

ROLE_ADMIN = "administrator"
ROLE_KNOWLEDGE_MANAGER = "knowledge_manager"
ROLE_PROPOSAL_WRITER = "proposal_writer"
ROLE_REVIEWER = "reviewer"
ROLE_READ_ONLY = "read_only"

ROLES: tuple[str, ...] = (
    ROLE_ADMIN,
    ROLE_KNOWLEDGE_MANAGER,
    ROLE_PROPOSAL_WRITER,
    ROLE_REVIEWER,
    ROLE_READ_ONLY,
)

ROLE_LABELS = {
    ROLE_ADMIN: "Administrator",
    ROLE_KNOWLEDGE_MANAGER: "Knowledge Manager",
    ROLE_PROPOSAL_WRITER: "Proposal Writer",
    ROLE_REVIEWER: "Reviewer",
    ROLE_READ_ONLY: "Read-only User",
}

# --- Permissions -------------------------------------------------------------
# Every mutating action gates on one of these. Reading non-restricted content is
# implicit for any active user; PERM_VIEW_RESTRICTED gates restricted content.

PERM_UPLOAD_DOCUMENTS = "upload_documents"
PERM_EDIT_METADATA = "edit_metadata"
PERM_CREATE_CLAIMS = "create_claims"
PERM_APPROVE_CLAIMS = "approve_claims"
PERM_REJECT_CLAIMS = "reject_claims"
PERM_DRAFT_RESPONSES = "draft_responses"
PERM_VIEW_RESTRICTED = "view_restricted"
PERM_MANAGE_USERS = "manage_users"
PERM_EXPORT_CONTENT = "export_content"
PERM_ARCHIVE_DOCUMENTS = "archive_documents"
PERM_RESOLVE_CONFLICTS = "resolve_conflicts"

PERMISSIONS: tuple[str, ...] = (
    PERM_UPLOAD_DOCUMENTS,
    PERM_EDIT_METADATA,
    PERM_CREATE_CLAIMS,
    PERM_APPROVE_CLAIMS,
    PERM_REJECT_CLAIMS,
    PERM_DRAFT_RESPONSES,
    PERM_VIEW_RESTRICTED,
    PERM_MANAGE_USERS,
    PERM_EXPORT_CONTENT,
    PERM_ARCHIVE_DOCUMENTS,
    PERM_RESOLVE_CONFLICTS,
)

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    ROLE_ADMIN: frozenset(PERMISSIONS),
    ROLE_KNOWLEDGE_MANAGER: frozenset(
        {
            PERM_UPLOAD_DOCUMENTS,
            PERM_EDIT_METADATA,
            PERM_CREATE_CLAIMS,
            PERM_APPROVE_CLAIMS,
            PERM_REJECT_CLAIMS,
            PERM_DRAFT_RESPONSES,
            PERM_VIEW_RESTRICTED,
            PERM_EXPORT_CONTENT,
            PERM_ARCHIVE_DOCUMENTS,
            PERM_RESOLVE_CONFLICTS,
        }
    ),
    ROLE_PROPOSAL_WRITER: frozenset(
        {
            PERM_UPLOAD_DOCUMENTS,
            PERM_EDIT_METADATA,
            PERM_CREATE_CLAIMS,
            PERM_DRAFT_RESPONSES,
            PERM_EXPORT_CONTENT,
        }
    ),
    ROLE_REVIEWER: frozenset(
        {
            PERM_EDIT_METADATA,
            PERM_APPROVE_CLAIMS,
            PERM_REJECT_CLAIMS,
            PERM_VIEW_RESTRICTED,
            PERM_EXPORT_CONTENT,
            PERM_RESOLVE_CONFLICTS,
        }
    ),
    ROLE_READ_ONLY: frozenset(),
}


def role_has_permission(role: str | None, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(role or "", frozenset())


# --- Statuses ----------------------------------------------------------------

CLAIM_STATUS_DRAFT = "Draft"
CLAIM_STATUS_PENDING = "Pending Review"
CLAIM_STATUS_APPROVED = "Approved"
CLAIM_STATUS_REJECTED = "Rejected"
CLAIM_STATUS_EXPIRED = "Expired"
CLAIM_STATUS_SUPERSEDED = "Superseded"
CLAIM_STATUS_RESTRICTED = "Restricted"
CLAIM_STATUS_ARCHIVED = "Archived"

CLAIM_STATUSES: tuple[str, ...] = (
    CLAIM_STATUS_DRAFT,
    CLAIM_STATUS_PENDING,
    CLAIM_STATUS_APPROVED,
    CLAIM_STATUS_REJECTED,
    CLAIM_STATUS_EXPIRED,
    CLAIM_STATUS_SUPERSEDED,
    CLAIM_STATUS_RESTRICTED,
    CLAIM_STATUS_ARCHIVED,
)

# Statuses whose claims may be used automatically in AI-generated responses.
# Restricted is deliberately excluded from automatic use (requires override).
CLAIM_USABLE_STATUSES: frozenset[str] = frozenset({CLAIM_STATUS_APPROVED})

ANSWER_STATUS_DRAFT = "Draft"
ANSWER_STATUS_PENDING = "Pending Review"
ANSWER_STATUS_APPROVED = "Approved"
ANSWER_STATUS_REJECTED = "Rejected"
ANSWER_STATUS_EXPIRED = "Expired"
ANSWER_STATUS_ARCHIVED = "Archived"

ANSWER_STATUSES: tuple[str, ...] = (
    ANSWER_STATUS_DRAFT,
    ANSWER_STATUS_PENDING,
    ANSWER_STATUS_APPROVED,
    ANSWER_STATUS_REJECTED,
    ANSWER_STATUS_EXPIRED,
    ANSWER_STATUS_ARCHIVED,
)
ANSWER_USABLE_STATUSES: frozenset[str] = frozenset({ANSWER_STATUS_APPROVED})

# Document processing state machine.
DOC_STATUS_UPLOADED = "Uploaded"
DOC_STATUS_QUEUED = "Queued"
DOC_STATUS_PROCESSING = "Processing"
DOC_STATUS_EXTRACTED = "Extracted"
DOC_STATUS_INDEXED = "Indexed"
DOC_STATUS_NEEDS_REVIEW = "Needs Review"
DOC_STATUS_FAILED = "Failed"
DOC_STATUS_ARCHIVED = "Archived"

DOC_STATUSES: tuple[str, ...] = (
    DOC_STATUS_UPLOADED,
    DOC_STATUS_QUEUED,
    DOC_STATUS_PROCESSING,
    DOC_STATUS_EXTRACTED,
    DOC_STATUS_INDEXED,
    DOC_STATUS_NEEDS_REVIEW,
    DOC_STATUS_FAILED,
    DOC_STATUS_ARCHIVED,
)

CONFIDENCE_LEVELS: tuple[str, ...] = ("High", "Medium", "Low")

REVIEW_REQUEST_STATUSES: tuple[str, ...] = (
    "Open",
    "Approved",
    "Rejected",
    "Changes Requested",
)

CONFLICT_STATUSES: tuple[str, ...] = ("Open", "Resolved", "Dismissed")
CONFLICT_RESOLUTIONS: tuple[str, ...] = (
    "Authoritative Selected",
    "Superseded",
    "Merged",
    "Restricted",
    "Rejected",
    "Explained",
)

# Response drafting controls.
RESPONSE_TONES: tuple[str, ...] = (
    "Formal",
    "Professional",
    "Conversational",
    "Persuasive",
)
RESPONSE_DETAIL_LEVELS: tuple[str, ...] = ("Concise", "Standard", "Detailed")
RESPONSE_REVIEW_STATUSES: tuple[str, ...] = (
    "Draft",
    "In Review",
    "Approved",
    "Rejected",
)

# Targets that can be reviewed / commented / approved / audited generically.
TARGET_TYPES: tuple[str, ...] = (
    "document",
    "claim",
    "answer",
    "response",
    "conflict",
    "entity",
    "user",
)

# --- Controlled vocabularies (seeded; power validation + filter dropdowns) ----

# Knowledge categories (Claims Registry). Combines the generic RFP categories
# with the security-services-contractor categories from the spec.
CLAIM_CATEGORIES: tuple[str, ...] = (
    "Company Overview",
    "Corporate History",
    "Licensing",
    "Insurance",
    "Staffing",
    "Recruiting",
    "Screening",
    "Training",
    "Supervision",
    "Quality Assurance",
    "Technology",
    "Incident Reporting",
    "Scheduling",
    "Transition Planning",
    "Emergency Response",
    "Past Performance",
    "References",
    "Financial Stability",
    "Policies",
    "Certifications",
    "Geographic Coverage",
    "Service Capabilities",
    "Diversity and Workforce",
    "Legal and Compliance",
    # Security-services capability categories (Aventus configuration).
    "Armed Security",
    "Unarmed Security",
    "Mobile Patrol",
    "Vehicle Patrol",
    "Fire Watch",
    "Courthouse Security",
    "Healthcare Security",
    "Campus Security",
    "Municipal Security",
    "Commercial-Property Security",
)

# Reusable answer categories (common RFP questions).
ANSWER_CATEGORIES: tuple[str, ...] = (
    "Company Description",
    "Recruitment Process",
    "Employee Screening",
    "Training Program",
    "Supervision Model",
    "Quality Control",
    "Transition Plan",
    "Incident Reporting",
    "Technology Platform",
    "Emergency Response",
    "Similar Contract Experience",
    "Employee Retention",
    "Customer Service",
    "Other",
)

# Document types for the vault.
DOCUMENT_TYPES: tuple[str, ...] = (
    "Policy",
    "License",
    "Insurance Certificate",
    "Resume",
    "Capabilities Statement",
    "Previous Proposal",
    "Training Material",
    "Reference",
    "Operating Procedure",
    "Certification",
    "Financial Statement",
    "Contract",
    "Spreadsheet",
    "Other",
)

# Service types (security-services contractor).
SERVICE_TYPES: tuple[str, ...] = (
    "Armed Security",
    "Unarmed Security",
    "Mobile Patrol",
    "Vehicle Patrol",
    "Fire Watch",
    "Courthouse Security",
    "Healthcare Security",
    "Campus Security",
    "Municipal Security",
    "Commercial-Property Security",
    "Event Security",
    "Access Control",
    "Alarm Response",
    "Other",
)

# Industries served.
INDUSTRIES: tuple[str, ...] = (
    "Government",
    "Municipal",
    "Healthcare",
    "Education",
    "Commercial Real Estate",
    "Retail",
    "Industrial",
    "Transportation",
    "Utilities",
    "Financial",
    "Other",
)

# US states + DC + territories, stored/validated as 2-letter codes.
US_STATES: tuple[str, ...] = (
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC", "PR", "GU", "VI", "AS", "MP",
)

GEOGRAPHIC_SCOPES: tuple[str, ...] = (
    "National",
    "Multi-State",
    "State-Specific",
    "Regional",
    "Local",
)

TAG_KINDS: tuple[str, ...] = ("document", "claim", "answer", "gallery")

# --- Media Gallery -----------------------------------------------------------

# Visual-asset categories for the gallery (logos, badges, photos, diagrams).
GALLERY_CATEGORIES: tuple[str, ...] = (
    "Logo",
    "Logo Mark / Icon",
    "Certification Badge",
    "Award / Recognition",
    "Team Photo",
    "Facility Photo",
    "Uniform / Equipment Photo",
    "Diagram / Chart",
    "Cover Art",
    "Signature",
    "Screenshot",
    "Other",
)

# Allowed image extensions and their canonical MIME types.
GALLERY_IMAGE_EXTS: tuple[str, ...] = (
    "png",
    "jpg",
    "jpeg",
    "gif",
    "webp",
    "svg",
    "bmp",
)
GALLERY_MIME_BY_EXT: dict[str, str] = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "svg": "image/svg+xml",
    "bmp": "image/bmp",
}
