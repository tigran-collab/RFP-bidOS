"""Shared factories for KB service tests (uses the in-memory `session` fixture)."""

from app.kb_models import CompanyEntity, KbUser
from app.kb_vocab import (
    ROLE_ADMIN,
    ROLE_PROPOSAL_WRITER,
    ROLE_READ_ONLY,
    ROLE_REVIEWER,
)


def make_user(session, role=ROLE_ADMIN, name=None):
    user = KbUser(name=name or role, email=f"{role}@example.com", role=role, active=True)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def make_admin(session):
    return make_user(session, ROLE_ADMIN, "Admin")


def make_writer(session):
    return make_user(session, ROLE_PROPOSAL_WRITER, "Writer")


def make_reviewer(session):
    return make_user(session, ROLE_REVIEWER, "Reviewer")


def make_reader(session):
    return make_user(session, ROLE_READ_ONLY, "Reader")


def make_entity(session, name="Aventus Security"):
    entity = CompanyEntity(name=name, active=True)
    session.add(entity)
    session.commit()
    session.refresh(entity)
    return entity
