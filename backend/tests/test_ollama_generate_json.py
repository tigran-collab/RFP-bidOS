"""Tests for ollama_client.generate_json: context sizing and error taxonomy.

No network — requests.post is stubbed.
"""

import requests

from app.services import ollama_client
from app.services.ollama_client import (
    LocalAIGenerateError,
    LocalAIModelMissingError,
    LocalAITimeoutError,
    LocalAIUnavailableError,
)


class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = "{}"

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


def test_generate_json_sets_num_ctx_and_num_predict(monkeypatch):
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["payload"] = json
        return _FakeResponse(200, {"response": "{}"})

    monkeypatch.setattr(ollama_client.requests, "post", fake_post)

    ollama_client.generate_json("prompt", model="qwen3:8b")

    options = captured["payload"]["options"]
    assert options["num_ctx"] >= 8192
    assert options["num_predict"] == 1024
    assert options["temperature"] == 0.2


def test_generate_json_timeout_maps_to_timeout_error(monkeypatch):
    def fake_post(url, json=None, timeout=None):
        raise requests.Timeout("slow")

    monkeypatch.setattr(ollama_client.requests, "post", fake_post)

    try:
        ollama_client.generate_json("prompt")
    except LocalAITimeoutError:
        pass
    else:
        raise AssertionError("expected LocalAITimeoutError")


def test_generate_json_404_maps_to_model_missing(monkeypatch):
    def fake_post(url, json=None, timeout=None):
        return _FakeResponse(404, {"error": "model not found"})

    monkeypatch.setattr(ollama_client.requests, "post", fake_post)

    try:
        ollama_client.generate_json("prompt", model="missing")
    except LocalAIModelMissingError:
        pass
    else:
        raise AssertionError("expected LocalAIModelMissingError")


def test_generate_json_persistent_5xx_maps_to_generate_error(monkeypatch):
    # Every call 5xx: after the CPU retry it still fails -> generate error,
    # not "start Ollama".
    def fake_post(url, json=None, timeout=None):
        return _FakeResponse(500, {"error": "boom"})

    monkeypatch.setattr(ollama_client.requests, "post", fake_post)

    try:
        ollama_client.generate_json("prompt")
    except LocalAIGenerateError:
        pass
    else:
        raise AssertionError("expected LocalAIGenerateError")


def test_generate_json_connection_error_maps_to_unavailable(monkeypatch):
    def fake_post(url, json=None, timeout=None):
        raise requests.ConnectionError("refused")

    monkeypatch.setattr(ollama_client.requests, "post", fake_post)

    try:
        ollama_client.generate_json("prompt")
    except LocalAIUnavailableError:
        pass
    else:
        raise AssertionError("expected LocalAIUnavailableError")
