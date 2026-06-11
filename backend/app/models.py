from sqlmodel import SQLModel


class OpportunityBase(SQLModel):
    title: str
    source: str | None = None
