from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


class HealthResponse(BaseModel):
    status: str


class OpportunityCreate(BaseModel):
    title: str
    agency: str | None = None
    solicitation_number: str | None = None
    source: str | None = None
    source_url: str | None = None
    portal_url: str | None = None
    location: str | None = None
    due_date: datetime | None = None
    pre_bid_date: datetime | None = None
    pre_bid_mandatory: bool = False
    q_and_a_deadline: datetime | None = None
    service_type: str | None = None
    contract_type: str | None = None
    estimated_value: float | None = None
    bid_decision: str | None = None
    bid_score: float | None = None
    bid_reason: str | None = None
    ai_recommendation: str | None = None
    ai_score: float | None = None
    ai_reason: str | None = None
    ai_risk_level: str | None = None
    ai_evaluated_at: datetime | None = None
    status: str = "new"


class OpportunityUpdate(BaseModel):
    title: str | None = None
    agency: str | None = None
    solicitation_number: str | None = None
    source: str | None = None
    source_url: str | None = None
    portal_url: str | None = None
    location: str | None = None
    due_date: datetime | None = None
    pre_bid_date: datetime | None = None
    pre_bid_mandatory: bool | None = None
    q_and_a_deadline: datetime | None = None
    service_type: str | None = None
    contract_type: str | None = None
    estimated_value: float | None = None
    bid_decision: str | None = None
    bid_score: float | None = None
    bid_reason: str | None = None
    ai_recommendation: str | None = None
    ai_score: float | None = None
    ai_reason: str | None = None
    ai_risk_level: str | None = None
    ai_evaluated_at: datetime | None = None
    status: str | None = None


class OpportunityRead(OpportunityCreate):
    id: int
    created_at: datetime
    updated_at: datetime


class DocumentRead(BaseModel):
    id: int
    opportunity_id: int
    filename: str
    path: str
    file_type: str | None = None
    sha256: str | None = None
    source_url: str | None = None
    downloaded_at: datetime | None = None
    parsed_status: str
    extracted_text_path: str | None = None
    page_count: int | None = None
    parsed_at: datetime | None = None


class RequirementRead(BaseModel):
    id: int
    opportunity_id: int
    document_id: int | None = None
    requirement_type: str | None = None
    title: str | None = None
    requirement_text: str
    source_file: str | None = None
    source_page: int | None = None
    source_section: str | None = None
    mandatory: bool
    due_date: datetime | None = None
    assigned_response_section: str | None = None
    notes: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    extractor_type: str | None = None
    response_location: str | None = None
    evidence_needed: str | None = None
    owner: str | None = None
    status: str
    risk: str | None = None


class SourceConfigCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    source_type: str
    base_url: str | None = None
    login_url: str | None = None
    enabled: bool = True
    notes: str | None = None
    requires_credentials: bool = False
    credential_type: str | None = None
    credential_username: str | None = None
    credential_secret_ref: str | None = None
    credential_notes: str | None = None
    auth_status: str | None = "Not Configured"

    @field_validator("credential_type")
    @classmethod
    def validate_credential_type(cls, value: str | None) -> str | None:
        return _validate_choice(
            value,
            {None, "Manual", "Environment", "Future Secret Store"},
            "credential_type",
        )

    @field_validator("auth_status")
    @classmethod
    def validate_auth_status(cls, value: str | None) -> str | None:
        return _validate_choice(
            value,
            {
                None,
                "Not Required",
                "Not Configured",
                "Configured",
                "Needs Review",
                "Unsupported This Phase",
            },
            "auth_status",
        )


class SourceConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    source_type: str | None = None
    base_url: str | None = None
    login_url: str | None = None
    enabled: bool | None = None
    notes: str | None = None
    requires_credentials: bool | None = None
    credential_type: str | None = None
    credential_username: str | None = None
    credential_secret_ref: str | None = None
    credential_notes: str | None = None
    auth_status: str | None = None

    @field_validator("credential_type")
    @classmethod
    def validate_credential_type(cls, value: str | None) -> str | None:
        return _validate_choice(
            value,
            {None, "Manual", "Environment", "Future Secret Store"},
            "credential_type",
        )

    @field_validator("auth_status")
    @classmethod
    def validate_auth_status(cls, value: str | None) -> str | None:
        return _validate_choice(
            value,
            {
                None,
                "Not Required",
                "Not Configured",
                "Configured",
                "Needs Review",
                "Unsupported This Phase",
            },
            "auth_status",
        )


class SourceConfigRead(SourceConfigCreate):
    id: int
    auth_last_checked_at: datetime | None = None
    last_scrape_at: datetime | None = None
    last_scrape_status: str | None = None
    last_scrape_summary: str | None = None
    created_at: datetime


class OpportunityEvaluationRead(BaseModel):
    id: int
    opportunity_id: int
    evaluator_type: str
    model_name: str | None = None
    recommendation: str | None = None
    score: float | None = None
    risk_level: str | None = None
    pursuit_effort: str | None = None
    reason: str | None = None
    positive_factors_json: str | None = None
    negative_factors_json: str | None = None
    missing_information_json: str | None = None
    questions_to_verify_json: str | None = None
    recommended_next_action: str | None = None
    raw_response: str | None = None
    created_at: datetime


def _validate_choice(value: str | None, allowed: set[str | None], field_name: str) -> str | None:
    if value in allowed:
        return value
    allowed_values = ", ".join(sorted(item for item in allowed if item is not None))
    raise ValueError(f"{field_name} must be one of: {allowed_values}")
