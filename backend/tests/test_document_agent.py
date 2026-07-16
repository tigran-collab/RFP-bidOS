"""Tests for the local AI document agent (services/document_agent.py).

Ollama is mocked; documents are real temp text files. The agent must work
through EVERY parsed file chunk by chunk, keep citations, never lose an
existing analysis on a failed refresh, and abort loudly when local AI is down.
"""

import json

from sqlmodel import select

from app.models import Document, DocumentAnalysis, Opportunity
from app.services import document_agent
from app.services.document_agent import (
    CHUNK_CHARS,
    analyze_opportunity_documents,
    get_document_brief,
)
from app.services.ollama_client import LOCAL_AI_UNAVAILABLE, LocalAIUnavailableError


def _seed_opportunity(session, tmp_path, texts_by_filename):
    opportunity = Opportunity(title="Security Guard Services", agency="City of Mesa")
    session.add(opportunity)
    session.commit()
    session.refresh(opportunity)
    documents = []
    for filename, text in texts_by_filename.items():
        path = tmp_path / f"{filename}.txt"
        path.write_text(text, encoding="utf-8")
        document = Document(
            opportunity_id=opportunity.id,
            filename=filename,
            path=str(tmp_path / filename),
            parsed_status="Parsed",
            extracted_text_path=str(path),
        )
        session.add(document)
        session.commit()
        session.refresh(document)
        documents.append(document)
    return opportunity, documents


def _fake_generate_json(responses):
    """Return a generate_json stub that pops canned parsed-JSON values."""
    calls = []

    def fake(prompt, model=None, temperature=0.2):
        calls.append(prompt)
        value = responses[min(len(calls), len(responses)) - 1]
        if isinstance(value, Exception):
            raise value
        return {
            "model": "qwen3:8b",
            "response_text": json.dumps(value),
            "raw_response": json.dumps(value),
            "json": value,
            "ollama": {},
        }

    fake.calls = calls
    return fake


CHUNK_RESULT = {
    "summary": "Covers submission logistics.",
    "facts": [
        {"category": "deadline", "detail": "Proposals due 2026-08-15 2:00 PM"},
        {"category": "licensing", "detail": "BSIS PPO license required"},
    ],
    "red_flags": ["Mandatory pre-bid conference"],
    "open_questions": ["Is a site walk required?"],
}

BRIEF_RESULT = {
    "summary": "The City seeks armed guard services; proposals due August 15.",
    "top_risks": ["Mandatory pre-bid conference"],
    "open_questions": ["Is a site walk required?"],
}


def test_agent_works_through_every_document_and_builds_brief(session, tmp_path, monkeypatch):
    opportunity, documents = _seed_opportunity(
        session,
        tmp_path,
        {
            "rfp.pdf": "Guard services RFP. " * 50,
            # Long enough for multiple chunks — the agent must read past the
            # first chunk instead of sampling the head of the file.
            "attachment.pdf": "Insurance and bonding terms. " + ("x" * (CHUNK_CHARS * 2)),
        },
    )
    fake = _fake_generate_json([CHUNK_RESULT, CHUNK_RESULT, CHUNK_RESULT, CHUNK_RESULT, BRIEF_RESULT])
    monkeypatch.setattr(document_agent, "generate_json", fake)

    result = analyze_opportunity_documents(opportunity.id, session)

    assert result.get("error") is None
    assert result["documents_analyzed"] == 2
    assert result["documents_skipped"] == 0
    assert result["brief"]["summary"].startswith("The City seeks")

    payload = get_document_brief(opportunity.id, session)
    assert payload["brief"]["kind"] == "brief"
    assert len(payload["documents"]) == 2
    multi_chunk = next(
        d for d in payload["documents"] if d["document_id"] == documents[1].id
    )
    assert multi_chunk["chunk_count"] >= 2
    # Facts carry citations back to file + chunk.
    fact = payload["documents"][0]["facts"][0]
    assert fact["source_file"] == "rfp.pdf"
    assert fact["chunk"] == 1
    # 2 chunk calls for doc1? doc1 is short (1 chunk) + doc2 (>=2 chunks) + 1 brief call.
    assert len(fake.calls) >= 4


def test_agent_skips_analyzed_documents_unless_refresh(session, tmp_path, monkeypatch):
    opportunity, documents = _seed_opportunity(
        session, tmp_path, {"rfp.pdf": "Guard services RFP text."}
    )
    fake = _fake_generate_json([CHUNK_RESULT, BRIEF_RESULT, CHUNK_RESULT, BRIEF_RESULT])
    monkeypatch.setattr(document_agent, "generate_json", fake)

    first = analyze_opportunity_documents(opportunity.id, session)
    assert first["documents_analyzed"] == 1
    first_row_id = session.exec(
        select(DocumentAnalysis).where(
            DocumentAnalysis.document_id == documents[0].id
        )
    ).first().id

    second = analyze_opportunity_documents(opportunity.id, session)
    assert second["documents_analyzed"] == 0
    assert second["documents_skipped"] == 1

    third = analyze_opportunity_documents(opportunity.id, session, refresh=True)
    assert third["documents_analyzed"] == 1
    rows = session.exec(
        select(DocumentAnalysis).where(
            DocumentAnalysis.document_id == documents[0].id
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].id != first_row_id


def test_unusable_chunk_json_marks_partial_but_continues(session, tmp_path, monkeypatch):
    opportunity, _documents = _seed_opportunity(
        session, tmp_path, {"rfp.pdf": "Guard services RFP text."}
    )

    def fake(prompt, model=None, temperature=0.2):
        if "bid-review brief" in prompt:
            value = BRIEF_RESULT
        else:
            return {
                "model": "qwen3:8b",
                "response_text": "not json",
                "raw_response": "not json",
                "json": None,
                "ollama": {},
            }
        return {
            "model": "qwen3:8b",
            "response_text": json.dumps(value),
            "raw_response": json.dumps(value),
            "json": value,
            "ollama": {},
        }

    monkeypatch.setattr(document_agent, "generate_json", fake)

    result = analyze_opportunity_documents(opportunity.id, session)

    assert result["documents_analyzed"] == 1
    assert any("unusable JSON" in e for e in result["errors"])
    payload = get_document_brief(opportunity.id, session)
    assert payload["documents"][0]["status"] == "partial"


def test_local_ai_down_aborts_without_touching_existing_rows(session, tmp_path, monkeypatch):
    opportunity, documents = _seed_opportunity(
        session, tmp_path, {"rfp.pdf": "Guard services RFP text."}
    )
    fake = _fake_generate_json([CHUNK_RESULT, BRIEF_RESULT])
    monkeypatch.setattr(document_agent, "generate_json", fake)
    analyze_opportunity_documents(opportunity.id, session)

    monkeypatch.setattr(
        document_agent,
        "generate_json",
        _fake_generate_json([LocalAIUnavailableError(LOCAL_AI_UNAVAILABLE)]),
    )
    result = analyze_opportunity_documents(opportunity.id, session, refresh=True)

    assert result["error"] == LOCAL_AI_UNAVAILABLE
    # The earlier completed analysis is untouched.
    payload = get_document_brief(opportunity.id, session)
    assert payload["documents"][0]["status"] == "completed"
    assert payload["documents"][0]["document_id"] == documents[0].id


def test_no_parsed_documents_is_a_clear_error(session):
    opportunity = Opportunity(title="Security Guard Services")
    session.add(opportunity)
    session.commit()
    session.refresh(opportunity)

    result = analyze_opportunity_documents(opportunity.id, session)

    assert "No parsed documents" in result["error"]


def test_missing_text_file_is_reported_not_fatal(session, tmp_path, monkeypatch):
    opportunity, documents = _seed_opportunity(
        session, tmp_path, {"rfp.pdf": "Guard services RFP text."}
    )
    ghost = Document(
        opportunity_id=opportunity.id,
        filename="ghost.pdf",
        path=str(tmp_path / "ghost.pdf"),
        parsed_status="Parsed",
        extracted_text_path=str(tmp_path / "does-not-exist.txt"),
    )
    session.add(ghost)
    session.commit()

    fake = _fake_generate_json([CHUNK_RESULT, BRIEF_RESULT])
    monkeypatch.setattr(document_agent, "generate_json", fake)

    result = analyze_opportunity_documents(opportunity.id, session)

    assert result["documents_analyzed"] == 1
    assert any("ghost.pdf" in e for e in result["errors"])
    assert result["brief"] is not None
