"""Idempotent seed for the Company Knowledge Base.

Creates the default role users, a default company entity scaffold, the common
reusable-question catalog, and tag seeds. It deliberately creates NO company
claims or answers — extracted/asserted company facts must be created and
approved by a human, never hardcoded.
"""

from __future__ import annotations

import json

from sqlmodel import Session, select

from app.kb_models import CompanyEntity, KbTag, KbUser, ReusableQuestion
from app.kb_vocab import (
    ROLE_ADMIN,
    ROLE_KNOWLEDGE_MANAGER,
    ROLE_PROPOSAL_WRITER,
    ROLE_READ_ONLY,
    ROLE_REVIEWER,
)
from app.models import utcnow_naive

# Default users, one per role (local-first; no login). The administrator is the
# default acting user when no X-KB-User-Id header is supplied.
_DEFAULT_USERS = [
    {"name": "Aventus Admin", "email": "admin@aventussecurity.com", "role": ROLE_ADMIN},
    {"name": "Knowledge Manager", "email": "km@aventussecurity.com", "role": ROLE_KNOWLEDGE_MANAGER},
    {"name": "Proposal Writer", "email": "writer@aventussecurity.com", "role": ROLE_PROPOSAL_WRITER},
    {"name": "Reviewer", "email": "reviewer@aventussecurity.com", "role": ROLE_REVIEWER},
    {"name": "Read-only User", "email": "viewer@aventussecurity.com", "role": ROLE_READ_ONLY},
]

# Common RFP questions (structure only; answers are authored + approved later).
_REUSABLE_QUESTIONS = [
    ("Describe your company.", "Company Description", ["Provide a company overview", "Tell us about your firm"]),
    ("Explain your recruitment process.", "Recruitment Process", ["How do you recruit officers?", "Describe hiring practices"]),
    ("Describe your employee screening process.", "Employee Screening", ["What background checks do you perform?"]),
    ("Explain your training program.", "Training Program", ["Describe guard training", "What certifications do officers hold?"]),
    ("Describe your supervision model.", "Supervision Model", ["How are officers supervised?"]),
    ("Explain your quality-control process.", "Quality Control", ["Describe your QA/QC program"]),
    ("Describe your transition plan.", "Transition Plan", ["How do you handle contract startup?", "Describe your phase-in plan"]),
    ("Explain your incident-reporting process.", "Incident Reporting", ["How are incidents reported and escalated?"]),
    ("Describe your technology platform.", "Technology Platform", ["What reporting technology do you use?"]),
    ("Explain your emergency-response procedures.", "Emergency Response", ["How do you respond to emergencies?"]),
    ("Describe your experience with similar contracts.", "Similar Contract Experience", ["Provide relevant past performance"]),
    ("Explain your employee-retention strategy.", "Employee Retention", ["How do you reduce turnover?"]),
    ("Describe your customer-service approach.", "Customer Service", ["How do you manage the client relationship?"]),
]

_DEFAULT_TAGS = [
    ("armed", "claim"),
    ("unarmed", "claim"),
    ("california", "claim"),
    ("healthcare", "claim"),
    ("municipal", "claim"),
    ("insurance-certificate", "document"),
    ("license", "document"),
    ("capabilities-statement", "document"),
    ("past-performance", "document"),
]


def seed_kb(session: Session, *, default_entity_name: str = "Aventus Security") -> dict:
    now = utcnow_naive()
    users_created = 0
    for spec in _DEFAULT_USERS:
        existing = session.exec(
            select(KbUser).where(KbUser.email == spec["email"])
        ).first()
        if existing is None:
            session.add(
                KbUser(
                    name=spec["name"],
                    email=spec["email"],
                    role=spec["role"],
                    active=True,
                    created_at=now,
                )
            )
            users_created += 1

    entities_created = 0
    existing_entity = session.exec(
        select(CompanyEntity).where(CompanyEntity.name == default_entity_name)
    ).first()
    if existing_entity is None:
        session.add(
            CompanyEntity(
                name=default_entity_name,
                description="Default legal entity (edit in Admin Settings).",
                active=True,
                created_at=now,
                updated_at=now,
            )
        )
        entities_created += 1

    questions_created = 0
    for title, category, variants in _REUSABLE_QUESTIONS:
        existing_q = session.exec(
            select(ReusableQuestion).where(ReusableQuestion.title == title)
        ).first()
        if existing_q is None:
            session.add(
                ReusableQuestion(
                    title=title,
                    category=category,
                    variants_json=json.dumps(variants),
                    created_at=now,
                    updated_at=now,
                )
            )
            questions_created += 1

    tags_created = 0
    for name, kind in _DEFAULT_TAGS:
        existing_tag = session.exec(
            select(KbTag).where(KbTag.name == name, KbTag.kind == kind)
        ).first()
        if existing_tag is None:
            session.add(KbTag(name=name, kind=kind, created_at=now))
            tags_created += 1

    session.commit()
    return {
        "users_created": users_created,
        "entities_created": entities_created,
        "questions_created": questions_created,
        "tags_created": tags_created,
    }
