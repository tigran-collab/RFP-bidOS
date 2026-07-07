"""CPU-fallback for a crashed Ollama GPU runner.

Observed live: an Ollama/CUDA driver mismatch made every /api/generate call
500 ("PTX ... unsupported toolchain") while /api/tags kept reporting models as
available. _post_generate retries once with num_gpu=0 so all AI features keep
working on CPU. No network — requests.post is stubbed.
"""

import requests

from app.services import ollama_client


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = str(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


def test_gpu_crash_retries_on_cpu(monkeypatch):
    posts = []

    def fake_post(url, json=None, timeout=None):
        posts.append(json)
        if len(posts) == 1:
            return FakeResponse(500, {"error": "CUDA error: unsupported toolchain"})
        return FakeResponse(200, {"response": "OK"})

    monkeypatch.setattr(ollama_client.requests, "post", fake_post)

    response = ollama_client._post_generate(
        {"model": "qwen3:8b", "prompt": "hi", "options": {"temperature": 0.2}},
        timeout=30,
    )

    assert response.status_code == 200
    assert len(posts) == 2
    assert posts[0]["options"] == {"temperature": 0.2}
    assert posts[1]["options"] == {"temperature": 0.2, "num_gpu": 0}


def test_healthy_gpu_posts_once(monkeypatch):
    posts = []

    def fake_post(url, json=None, timeout=None):
        posts.append(json)
        return FakeResponse(200, {"response": "OK"})

    monkeypatch.setattr(ollama_client.requests, "post", fake_post)

    ollama_client._post_generate({"model": "qwen3:8b", "prompt": "hi"}, timeout=30)

    assert len(posts) == 1
    assert "num_gpu" not in (posts[0].get("options") or {})


def test_persistent_failure_still_raises(monkeypatch):
    def fake_post(url, json=None, timeout=None):
        return FakeResponse(500, {"error": "CUDA error"})

    monkeypatch.setattr(ollama_client.requests, "post", fake_post)

    try:
        ollama_client._post_generate({"model": "qwen3:8b", "prompt": "hi"}, timeout=30)
    except requests.HTTPError:
        pass
    else:
        raise AssertionError("expected HTTPError")


def test_client_errors_are_not_retried(monkeypatch):
    posts = []

    def fake_post(url, json=None, timeout=None):
        posts.append(json)
        return FakeResponse(404, {"error": "model not found"})

    monkeypatch.setattr(ollama_client.requests, "post", fake_post)

    try:
        ollama_client._post_generate({"model": "missing", "prompt": "hi"}, timeout=30)
    except requests.HTTPError:
        pass
    else:
        raise AssertionError("expected HTTPError")
    assert len(posts) == 1
