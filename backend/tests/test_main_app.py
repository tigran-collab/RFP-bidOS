"""Tests for app wiring: startup init_db and localhost-CSRF middleware.

No real DB is touched: init_db is stubbed for the lifespan test, and the CSRF
tests use a plain TestClient (no `with`) so the lifespan never runs.
"""

from fastapi.testclient import TestClient

from app import db as app_db
from app.main import app


def test_init_db_called_on_startup(monkeypatch):
    calls = []
    monkeypatch.setattr(app_db, "init_db", lambda: calls.append(True))

    # Entering the context manager triggers the FastAPI lifespan handler.
    with TestClient(app):
        pass

    assert calls == [True]


def test_get_with_foreign_origin_passes():
    client = TestClient(app)
    response = client.get("/health", headers={"Origin": "http://evil.example"})
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_post_with_foreign_origin_is_rejected():
    client = TestClient(app)
    # Middleware runs before routing, so the foreign-Origin POST is blocked
    # even though /health defines no POST handler.
    response = client.post("/health", headers={"Origin": "http://evil.example"})
    assert response.status_code == 403
    assert response.json() == {"detail": "Cross-origin request rejected"}


def test_post_with_localhost_origin_passes_middleware():
    client = TestClient(app)
    response = client.post(
        "/health", headers={"Origin": "http://localhost:5173"}
    )
    # Not 403: it reached routing (405 method-not-allowed for the GET-only route).
    assert response.status_code != 403


def test_post_with_no_origin_passes_middleware():
    client = TestClient(app)
    response = client.post("/health")
    assert response.status_code != 403
