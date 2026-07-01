"""Tests for the OS-keychain credential store wrapper.

These run fully offline by injecting a fake in-memory keyring backend, so they
verify set/get/delete round-trips and graceful degradation without touching the
real OS keychain. They also assert the password never leaks into any status or
serialization path.
"""

import sys
import types
from types import SimpleNamespace

import pytest

from app.services import credential_store
from app.services import source_credentials


class _FakeKeyringModule:
    """Minimal stand-in for the `keyring` module, backed by a dict."""

    class _FakeBackend:
        # Non-"fail" module name so is_available() treats it as usable.
        __module__ = "fake.backend"

    class errors:  # noqa: N801  (mirror keyring.errors shape)
        class PasswordDeleteError(Exception):
            pass

    def __init__(self):
        self._store: dict[tuple[str, str], str] = {}
        self._backend = self._FakeBackend()

    def get_keyring(self):
        return self._backend

    def set_password(self, ref, username, password):
        self._store[(ref, username)] = password

    def get_password(self, ref, username):
        return self._store.get((ref, username))

    def delete_password(self, ref, username):
        if (ref, username) not in self._store:
            raise self.errors.PasswordDeleteError("not found")
        del self._store[(ref, username)]


@pytest.fixture
def fake_keyring(monkeypatch):
    fake = _FakeKeyringModule()
    monkeypatch.setattr(credential_store, "_load_keyring", lambda: fake)
    return fake


def test_set_get_delete_round_trip(fake_keyring):
    assert credential_store.is_available() is True

    set_result = credential_store.set_password("ref:1", "alice", "s3cret")
    assert set_result["ok"] is True

    assert credential_store.get_password("ref:1", "alice") == "s3cret"
    assert credential_store.has_password("ref:1", "alice") is True

    delete_result = credential_store.delete_password("ref:1", "alice")
    assert delete_result["ok"] is True
    assert credential_store.get_password("ref:1", "alice") is None
    assert credential_store.has_password("ref:1", "alice") is False


def test_delete_missing_is_idempotent(fake_keyring):
    result = credential_store.delete_password("ref:1", "nobody")
    assert result["ok"] is True


def test_graceful_when_keyring_unavailable(monkeypatch):
    monkeypatch.setattr(credential_store, "_load_keyring", lambda: None)

    assert credential_store.is_available() is False
    assert credential_store.get_password("ref", "user") is None
    assert credential_store.has_password("ref", "user") is False

    set_result = credential_store.set_password("ref", "user", "pw")
    assert set_result["ok"] is False
    assert "keyring is not available" in set_result["message"]

    delete_result = credential_store.delete_password("ref", "user")
    assert delete_result["ok"] is False


def test_set_requires_ref_and_username(fake_keyring):
    assert credential_store.set_password("", "user", "pw")["ok"] is False
    assert credential_store.set_password("ref", "", "pw")["ok"] is False


def test_password_never_leaks_into_auth_status(fake_keyring):
    credential_store.set_password("ref:9", "alice", "topsecret")
    source = SimpleNamespace(
        id=9,
        name="Keyring Source",
        base_url="https://example.gov",
        requires_credentials=True,
        credential_type="Keyring",
        credential_username="alice",
        credential_secret_ref="ref:9",
        credential_notes=None,
        auth_last_checked_at=None,
    )

    status = source_credentials.get_source_auth_status(source)

    # Ready, and the secret value appears nowhere in the serialized status.
    assert status["auth_status"] == source_credentials.AUTH_STATUS_CONFIGURED
    assert status["keyring_password_present"] is True
    serialized = repr(status)
    assert "topsecret" not in serialized


def test_keyring_status_reports_missing_password(fake_keyring):
    source = SimpleNamespace(
        id=10,
        name="Keyring Source",
        base_url="https://example.gov",
        requires_credentials=True,
        credential_type="Keyring",
        credential_username="bob",
        credential_secret_ref="ref:10",
        credential_notes=None,
        auth_last_checked_at=None,
    )
    status = source_credentials.get_source_auth_status(source)
    assert status["auth_status"] == source_credentials.AUTH_STATUS_NOT_CONFIGURED
    assert "password not stored in OS keychain" in status["missing_fields"]


def test_keyring_status_when_keyring_unavailable(monkeypatch):
    monkeypatch.setattr(credential_store, "_load_keyring", lambda: None)
    source = SimpleNamespace(
        id=11,
        name="Keyring Source",
        base_url="https://example.gov",
        requires_credentials=True,
        credential_type="Keyring",
        credential_username="carol",
        credential_secret_ref="ref:11",
        credential_notes=None,
        auth_last_checked_at=None,
    )
    status = source_credentials.get_source_auth_status(source)
    assert status["auth_status"] == source_credentials.AUTH_STATUS_NOT_CONFIGURED
    assert status["keyring_available"] is False


def test_is_available_false_for_fail_backend(monkeypatch):
    class _FailModule:
        class _Fail:
            __module__ = "keyring.backends.fail"

        def get_keyring(self):
            return self._Fail()

    monkeypatch.setattr(credential_store, "_load_keyring", lambda: _FailModule())
    assert credential_store.is_available() is False
