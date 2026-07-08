"""Tests for the local-AI requirement extractor.

Offline: requests.post is monkeypatched so no network (or Ollama) is touched.
"""

import json
from datetime import datetime

import requests
from sqlmodel import select

from app.models import Document, Opportunity, Requirement
from app.services import requirement_extractor
from app.services.requirement_extractor import (
    _parse_datetime_or_none,
    extract_requirements_with_local_ai,
    refresh_requirements_with_local_ai,
)


class _FakeOllamaResponse:
    def __init__(self, payload):
        self._payload = payload
        self.text = json.dumps(payload)
        self.status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _seed_opportunity(session, tmp_path):
    opportunity = Opportunity(title="Security Guard Services")
    session.add(opportunity)
    session.commit()
    session.refresh(opportunity)

    text_path = tmp_path / "doc.txt"
    text_path.write_text(
        "Proposals due June 1, 2026. BSIS guard card required.", encoding="utf-8"
    )
    document = Document(
        opportunity_id=opportunity.id,
        filename="doc.pdf",
        path=str(tmp_path / "doc.pdf"),
        extracted_text_path=str(text_path),
    )
    session.add(document)

    existing = Requirement(
        opportunity_id=opportunity.id,
        requirement_text="Submit proposal through the portal.",
        extractor_type="local_ollama",
    )
    session.add(existing)
    session.commit()
    return opportunity


def _requirements_for(session, opportunity_id):
    return list(
        session.exec(
            select(Requirement).where(Requirement.opportunity_id == opportunity_id)
        ).all()
    )


def test_refresh_keeps_existing_requirements_when_ollama_is_down(
    session, tmp_path, monkeypatch
):
    opportunity = _seed_opportunity(session, tmp_path)

    def _raise(*args, **kwargs):
        raise requests.ConnectionError("Ollama is down")

    monkeypatch.setattr(requirement_extractor.requests, "post", _raise)

    result = refresh_requirements_with_local_ai(opportunity.id, session)

    assert "error" in result
    remaining = _requirements_for(session, opportunity.id)
    assert len(remaining) == 1
    assert remaining[0].requirement_text == "Submit proposal through the portal."


def test_refresh_keeps_existing_requirements_on_invalid_json(
    session, tmp_path, monkeypatch
):
    opportunity = _seed_opportunity(session, tmp_path)
    monkeypatch.setattr(
        requirement_extractor.requests,
        "post",
        lambda *args, **kwargs: _FakeOllamaResponse({"response": "not valid json"}),
    )

    result = refresh_requirements_with_local_ai(opportunity.id, session)

    assert result["error"] == requirement_extractor.INVALID_JSON
    assert len(_requirements_for(session, opportunity.id)) == 1


def test_refresh_replaces_existing_requirements_on_success(
    session, tmp_path, monkeypatch
):
    opportunity = _seed_opportunity(session, tmp_path)
    extraction = {
        "summary": "One requirement found.",
        "requirements": [
            {
                "requirement_type": "License",
                "title": "BSIS License",
                "requirement_text": "Contractor must hold a BSIS PPO license.",
                "mandatory": True,
                "status": "Needs Review",
            }
        ],
        "missing_information": [],
        "risk_flags": [],
    }
    monkeypatch.setattr(
        requirement_extractor.requests,
        "post",
        lambda *args, **kwargs: _FakeOllamaResponse(
            {"response": json.dumps(extraction)}
        ),
    )

    result = refresh_requirements_with_local_ai(opportunity.id, session)

    assert result["requirements_count"] == 1
    remaining = _requirements_for(session, opportunity.id)
    assert len(remaining) == 1
    assert remaining[0].requirement_text == "Contractor must hold a BSIS PPO license."


def test_extract_is_idempotent_across_two_runs(session, tmp_path, monkeypatch):
    opportunity = _seed_opportunity(session, tmp_path)
    extraction = {
        "summary": "One requirement found.",
        "requirements": [
            {
                "requirement_type": "License",
                "title": "BSIS License",
                "requirement_text": "Contractor must hold a BSIS PPO license.",
                "mandatory": True,
                "status": "Needs Review",
            }
        ],
        "missing_information": [],
        "risk_flags": [],
    }
    monkeypatch.setattr(
        requirement_extractor.requests,
        "post",
        lambda *args, **kwargs: _FakeOllamaResponse({"response": json.dumps(extraction)}),
    )

    first = extract_requirements_with_local_ai(opportunity.id, session)
    second = extract_requirements_with_local_ai(opportunity.id, session)

    assert first["requirements_count"] == 1
    assert second["requirements_count"] == 1
    remaining = _requirements_for(session, opportunity.id)
    assert len(remaining) == 1
    assert remaining[0].requirement_text == "Contractor must hold a BSIS PPO license."


def test_extract_keeps_existing_requirements_when_ollama_is_down(
    session, tmp_path, monkeypatch
):
    opportunity = _seed_opportunity(session, tmp_path)

    def _raise(*args, **kwargs):
        raise requests.ConnectionError("Ollama is down")

    monkeypatch.setattr(requirement_extractor.requests, "post", _raise)

    result = extract_requirements_with_local_ai(opportunity.id, session)

    assert "error" in result
    remaining = _requirements_for(session, opportunity.id)
    assert len(remaining) == 1
    assert remaining[0].requirement_text == "Submit proposal through the portal."


def test_parse_datetime_converts_non_utc_offset_to_utc():
    parsed = _parse_datetime_or_none("2026-03-01T10:00:00-07:00")
    assert parsed == datetime(2026, 3, 1, 17, 0)
    assert parsed.tzinfo is None


def test_parse_datetime_handles_z_suffix_and_naive_values():
    assert _parse_datetime_or_none("2026-03-01T10:00:00Z") == datetime(2026, 3, 1, 10, 0)
    assert _parse_datetime_or_none("2026-03-01T10:00:00") == datetime(2026, 3, 1, 10, 0)
    assert _parse_datetime_or_none("not a date") is None
    assert _parse_datetime_or_none(None) is None
