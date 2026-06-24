"""Tests for the local-chat prompt/guardrail/status logic.

These cover the layers that have historically produced the false
"model unavailable" message and the timeout-fallback recursion bug.
"""

from datetime import datetime

import pytest

from app.services import local_chat
from app.services.local_chat import (
    ChatError,
    build_chat_prompt,
    get_chat_status,
    _fallback_context,
    _format_context,
)


def test_fallback_does_not_recurse_from_pursuit_mode():
    # Regression: in pursuit mode (the fallback target) we must NOT fall back
    # again, even when the message contains "opportunit".
    assert _fallback_context({"mode": "pursuit"}, "summarize opportunities") is None


def test_fallback_triggers_for_app_overview():
    fallback = _fallback_context({"mode": "app_overview"}, "anything")
    assert fallback is not None
    assert fallback["mode"] == "pursuit"
    assert fallback["limit"] == 10


def test_fallback_triggers_on_opportunity_keyword_in_auto():
    fallback = _fallback_context({"mode": "auto"}, "summarize opportunities")
    assert fallback is not None
    assert fallback["mode"] == "pursuit"


def test_fallback_none_for_unrelated_deadlines_message():
    assert _fallback_context({"mode": "deadlines"}, "what is due") is None


def test_build_chat_prompt_includes_user_message():
    prompt = build_chat_prompt("Say OK", {"mode": "auto", "opportunity_count": 0})
    assert "Say OK" in prompt
    assert "read-only" in prompt.lower()


def test_build_chat_prompt_raises_when_too_large():
    huge_message = "x" * 40000
    with pytest.raises(ChatError) as exc:
        build_chat_prompt(huge_message, {})
    assert exc.value.category == "prompt_too_large"


def test_format_context_serializes_datetime():
    # default=str must keep datetimes JSON-safe (no exception, no ORM leak).
    text = _format_context({"due": datetime(2026, 6, 24, 9, 0), "mode": "auto"})
    assert "2026-06-24" in text


def test_format_context_drops_requested_key():
    text = _format_context({"requested": "secret", "mode": "auto"})
    assert "secret" not in text


def _fake_models(monkeypatch, *, available, names):
    def fake_list():
        return {
            "available": available,
            "models": [{"name": n} for n in names],
        }

    monkeypatch.setattr(local_chat, "list_ollama_models", fake_list)


def test_get_chat_status_available(monkeypatch):
    _fake_models(monkeypatch, available=True, names=["qwen3:8b", "other:1b"])
    status = get_chat_status()
    assert status["available"] is True
    assert status["error_category"] is None


def test_get_chat_status_model_missing(monkeypatch):
    _fake_models(monkeypatch, available=True, names=["other:1b"])
    status = get_chat_status()
    assert status["available"] is False
    assert status["error_category"] == "model_missing"


def test_get_chat_status_ollama_unavailable(monkeypatch):
    _fake_models(monkeypatch, available=False, names=[])
    status = get_chat_status()
    assert status["available"] is False
    assert status["error_category"] == "ollama_unavailable"
