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


class Requirement(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    opportunity_id: int = Field(foreign_key="opportunity.id", index=True)
    document_id: int | None = Field(default=None, foreign_key="document.id", index=True)
    requirement_text: str
    source_file: str | None = None
    source_page: int | None = None
    source_section: str | None = None
    mandatory: bool = False
    response_location: str | None = None
    evidence_needed: str | None = None
    owner: str | None = None
    status: str = "open"
    risk: str | None = None


class SourceConfig(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    source_type: str
    base_url: str | None = None
    login_url: str | None = None
    enabled: bool = True
    notes: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ScrapeRun(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    source_name: str
    started_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: datetime | None = None
    status: str = "pending"
    records_found: int = 0
    error_message: str | None = None
