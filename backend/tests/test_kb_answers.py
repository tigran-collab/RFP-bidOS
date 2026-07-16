"""Reusable Answer Library: creation, approval, usage tracking, expiration."""

from datetime import timedelta

from app.kb_models import ReusableAnswer
from app.kb_vocab import (
    ANSWER_STATUS_APPROVED,
    ANSWER_STATUS_EXPIRED,
    ANSWER_STATUS_PENDING,
)
from app.models import utcnow_naive
from app.services.kb import answers
from tests.kb_factories import make_admin, make_writer


def test_create_answer_draft(session):
    admin = make_admin(session)
    ans = answers.create_answer(
        session, admin, {"question_title": "Describe your company.", "standard_answer": "We are Aventus."}
    )
    assert ans.status == "Draft"


def test_writer_cannot_self_approve_answer(session):
    writer = make_writer(session)
    ans = answers.create_answer(
        session, writer,
        {"question_title": "Q", "standard_answer": "A", "status": "Approved"},
    )
    assert ans.status == ANSWER_STATUS_PENDING


def test_approve_answer(session):
    admin = make_admin(session)
    ans = answers.create_answer(session, admin, {"question_title": "Q", "standard_answer": "A"})
    approved = answers.approve_answer(session, admin, ans.id)
    assert approved.status == ANSWER_STATUS_APPROVED
    assert approved.approved_by == admin.id


def test_record_usage_increments(session):
    admin = make_admin(session)
    ans = answers.create_answer(session, admin, {"question_title": "Q", "standard_answer": "A"})
    answers.record_answer_usage(session, ans.id)
    answers.record_answer_usage(session, ans.id)
    refreshed = session.get(ReusableAnswer, ans.id)
    assert refreshed.usage_count == 2
    assert refreshed.last_used_at is not None


def test_expire_due_answers(session):
    admin = make_admin(session)
    ans = answers.create_answer(
        session, admin,
        {"question_title": "Q", "standard_answer": "A",
         "expiration_date": (utcnow_naive() - timedelta(days=1)).isoformat()},
    )
    answers.approve_answer(session, admin, ans.id)
    assert answers.expire_due_answers(session) == 1
    assert session.get(ReusableAnswer, ans.id).status == ANSWER_STATUS_EXPIRED
