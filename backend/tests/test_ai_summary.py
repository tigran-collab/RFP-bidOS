from app.models import Opportunity
from app.services import ai_summary
from app.services.ollama_client import LOCAL_AI_UNAVAILABLE, LocalAIUnavailableError


def _make_opportunity(session) -> Opportunity:
    opportunity = Opportunity(
        title="Unarmed Security Guard Services",
        agency="City of Example",
        location="CA",
        service_type="Security Guard",
        contract_type="Services",
    )
    session.add(opportunity)
    session.commit()
    session.refresh(opportunity)
    return opportunity


def test_summarize_opportunity_stores_and_returns(monkeypatch, session):
    opportunity = _make_opportunity(session)
    canned = "This is a short advisory summary of the opportunity."

    monkeypatch.setattr(ai_summary, "generate_text", lambda *a, **k: canned)

    result = ai_summary.summarize_opportunity(opportunity.id, session)

    assert result["ok"] is True
    assert result["summary"] == canned
    assert result["message"] == "ok"

    refreshed = session.get(Opportunity, opportunity.id)
    assert refreshed.ai_summary == canned
    assert refreshed.ai_summary_at is not None


def test_summarize_opportunity_ollama_unavailable(monkeypatch, session):
    opportunity = _make_opportunity(session)

    def _raise(*args, **kwargs):
        raise LocalAIUnavailableError(LOCAL_AI_UNAVAILABLE)

    monkeypatch.setattr(ai_summary, "generate_text", _raise)

    result = ai_summary.summarize_opportunity(opportunity.id, session)

    assert result["ok"] is False
    assert result["summary"] is None
    assert result["message"] == LOCAL_AI_UNAVAILABLE

    refreshed = session.get(Opportunity, opportunity.id)
    assert refreshed.ai_summary is None
    assert refreshed.ai_summary_at is None


def test_summarize_opportunity_generic_error_no_crash(monkeypatch, session):
    opportunity = _make_opportunity(session)

    def _raise(*args, **kwargs):
        raise RuntimeError("network exploded")

    monkeypatch.setattr(ai_summary, "generate_text", _raise)

    result = ai_summary.summarize_opportunity(opportunity.id, session)

    assert result["ok"] is False
    assert result["summary"] is None
    assert "network exploded" in result["message"]

    refreshed = session.get(Opportunity, opportunity.id)
    assert refreshed.ai_summary is None


def test_summarize_opportunity_missing(monkeypatch, session):
    monkeypatch.setattr(ai_summary, "generate_text", lambda *a, **k: "unused")

    result = ai_summary.summarize_opportunity(9999, session)

    assert result["ok"] is False
    assert result["summary"] is None
    assert result["message"] == "Opportunity not found"
