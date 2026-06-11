from datetime import datetime

from sqlmodel import Field, SQLModel


class OpportunityBase(SQLModel):
    title: str
    source: str | None = None


class Opportunity(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    agency: str | None = None
    solicitation_number: str | None = Field(default=None, index=True)
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
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Document(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    opportunity_id: int = Field(foreign_key="opportunity.id", index=True)
    filename: str
    path: str
    file_type: str | None = None
    sha256: str | None = None
    source_url: str | None = None
    downloaded_at: datetime | None = None
    parsed_status: str = "pending"
    extracted_text_path: str | None = None
    page_count: int | None = None
    parsed_at: datetime | None = None


class Requirement(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    opportunity_id: int = Field(foreign_key="opportunity.id", index=True)
    document_id: int | None = Field(default=None, foreign_key="document.id", index=True)
    requirement_type: str | None = None
    title: str | None = None
    requirement_text: str
    source_file: str | None = None
    source_page: int | None = None
    source_section: str | None = None
    mandatory: bool = True
    due_date: datetime | None = None
    assigned_response_section: str | None = None
    notes: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    extractor_type: str | None = None
    response_location: str | None = None
    evidence_needed: str | None = None
    owner: str | None = None
    status: str = "Needs Review"
    risk: str | None = None


class SourceConfig(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
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
    auth_last_checked_at: datetime | None = None
    last_scrape_at: datetime | None = None
    last_scrape_status: str | None = None
    last_scrape_summary: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ScrapeRun(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    source_name: str
    source_id: int | None = Field(default=None, index=True)
    started_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: datetime | None = None
    status: str = "pending"
    records_found: int = 0
    created_count: int = 0
    updated_count: int = 0
    skipped_duplicates: int = 0
    error_message: str | None = None


class OpportunityEvaluation(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    opportunity_id: int = Field(foreign_key="opportunity.id", index=True)
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
    created_at: datetime = Field(default_factory=datetime.utcnow)
