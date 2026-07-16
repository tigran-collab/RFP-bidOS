"""M4b: /ai-evaluate must use the same HTTP error codes as /extract-requirements.

Previously an invalid-JSON model response came back as HTTP 200 with an
{"error": ...} body; it now maps to 502, and an unavailable model maps to 503.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app import models  # noqa: F401  (register tables)
from app.main import app
from app.models import Opportunity
from app.services import ai_evaluator
from app.services.ollama_client import (
    LOCAL_AI_UNAVAILABLE,
    OLLAMA_GENERATE_FAILED,
    OLLAMA_TIMEOUT,
    LocalAIGenerateError,
    LocalAITimeoutError,
    LocalAIUnavailableError,
)


@pytest.fixture
def ai_client(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr("app.routers.opportunities.engine", engine, raising=True)
    client = TestClient(app)
    client._engine = engine
    return client


def _seed_opportunity(client):
    with Session(client._engine) as session:
        opportunity = Opportunity(title="Security Guard Services")
        session.add(opportunity)
        session.commit()
        session.refresh(opportunity)
        return opportunity.id


def test_ai_evaluate_invalid_json_returns_502(ai_client, monkeypatch):
    opportunity_id = _seed_opportunity(ai_client)
    monkeypatch.setattr(
        ai_evaluator,
        "generate_json",
        lambda prompt: {
            "raw_response": "garbage",
            "response_text": "definitely not json",
            "model": "test-model",
        },
    )

    response = ai_client.post(f"/opportunities/{opportunity_id}/ai-evaluate")

    assert response.status_code == 502
    assert response.json()["detail"] == "Local AI model returned invalid JSON."


def test_ai_evaluate_unavailable_returns_503(ai_client, monkeypatch):
    opportunity_id = _seed_opportunity(ai_client)

    def _raise(prompt):
        raise LocalAIUnavailableError(LOCAL_AI_UNAVAILABLE)

    monkeypatch.setattr(ai_evaluator, "generate_json", _raise)

    response = ai_client.post(f"/opportunities/{opportunity_id}/ai-evaluate")

    assert response.status_code == 503
    assert response.json()["detail"] == LOCAL_AI_UNAVAILABLE


def test_ai_evaluate_timeout_returns_504(ai_client, monkeypatch):
    opportunity_id = _seed_opportunity(ai_client)

    def _raise(prompt):
        raise LocalAITimeoutError(OLLAMA_TIMEOUT)

    monkeypatch.setattr(ai_evaluator, "generate_json", _raise)

    response = ai_client.post(f"/opportunities/{opportunity_id}/ai-evaluate")

    assert response.status_code == 504
    assert response.json()["detail"] == OLLAMA_TIMEOUT


def test_ai_evaluate_generate_error_returns_502(ai_client, monkeypatch):
    opportunity_id = _seed_opportunity(ai_client)

    def _raise(prompt):
        raise LocalAIGenerateError(f"{OLLAMA_GENERATE_FAILED} backend said no")

    monkeypatch.setattr(ai_evaluator, "generate_json", _raise)

    response = ai_client.post(f"/opportunities/{opportunity_id}/ai-evaluate")

    assert response.status_code == 502
    assert response.json()["detail"].startswith(OLLAMA_GENERATE_FAILED)
