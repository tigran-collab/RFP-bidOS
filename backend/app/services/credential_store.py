"""OS keychain credential store (thin wrapper over `keyring`).

Passwords for authenticated sources are stored ONLY in the operating system
keychain (macOS Keychain, Windows Credential Manager, Secret Service on Linux)
via the `keyring` library. They are never written to the SQLite database, never
committed to git, and never logged or echoed.

`keyring` is imported lazily so the app and the full test suite import and run
even when `keyring` is not installed. Every function reports a clear
"keyring not available" status instead of crashing when the backend is missing.

A credential is addressed by a (service, username) pair:
  - ``service`` (a.k.a. ``ref``) is stored in SourceConfig.credential_secret_ref
    (e.g. ``"rfp-bidos:planetbids:12"``).
  - ``username`` is stored in SourceConfig.credential_username.

Only the (service, username) references live in the DB; the secret itself
lives only in the keychain.
"""

from __future__ import annotations

_KEYRING_UNAVAILABLE_MSG = (
    "keyring is not available. Install it with `pip install keyring` to store "
    "credentials in the OS keychain."
)


def _load_keyring():
    """Lazily import `keyring`; return the module or None if unavailable."""
    try:
        import keyring  # noqa: PLC0415  (intentional lazy/optional import)

        return keyring
    except Exception:
        return None


def is_available() -> bool:
    """True when `keyring` is importable and has a usable backend."""
    keyring = _load_keyring()
    if keyring is None:
        return False
    try:
        backend = keyring.get_keyring()
    except Exception:
        return False
    if backend is None:
        return False
    # The "fail" backend is what keyring installs when no real OS keychain is
    # present; treat it as unavailable so callers can degrade cleanly.
    backend_name = type(backend).__module__ or ""
    return "fail" not in backend_name.lower()


def set_password(ref: str, username: str, password: str) -> dict:
    """Store ``password`` for (ref, username) in the OS keychain.

    Returns {ok: bool, message: str}. Never logs or echoes the password.
    """
    if not ref or not username:
        return {"ok": False, "message": "ref and username are required"}
    keyring = _load_keyring()
    if keyring is None:
        return {"ok": False, "message": _KEYRING_UNAVAILABLE_MSG}
    try:
        keyring.set_password(ref, username, password)
    except Exception as exc:  # keyring.errors.PasswordSetError and friends
        return {"ok": False, "message": f"Failed to store credential: {exc}"}
    return {"ok": True, "message": "Credential stored in OS keychain."}


def get_password(ref: str, username: str) -> str | None:
    """Return the stored password for (ref, username), or None if absent.

    Returns None (never raises) when keyring is unavailable so callers can
    treat "no keyring" and "no stored password" identically.
    """
    if not ref or not username:
        return None
    keyring = _load_keyring()
    if keyring is None:
        return None
    try:
        return keyring.get_password(ref, username)
    except Exception:
        return None


def delete_password(ref: str, username: str) -> dict:
    """Delete the stored password for (ref, username).

    Returns {ok: bool, message: str}. Treats an already-absent credential as a
    non-error so deletion is idempotent.
    """
    if not ref or not username:
        return {"ok": False, "message": "ref and username are required"}
    keyring = _load_keyring()
    if keyring is None:
        return {"ok": False, "message": _KEYRING_UNAVAILABLE_MSG}
    try:
        keyring.delete_password(ref, username)
    except Exception as exc:
        # Deleting a missing credential raises PasswordDeleteError; treat that
        # as success (idempotent) but surface unexpected backend failures.
        name = type(exc).__name__
        if "PasswordDelete" in name or "NoKeyring" in name:
            return {"ok": True, "message": "No stored credential to delete."}
        return {"ok": False, "message": f"Failed to delete credential: {exc}"}
    return {"ok": True, "message": "Credential deleted from OS keychain."}


def has_password(ref: str, username: str) -> bool:
    """True when a non-empty password is stored for (ref, username)."""
    return bool(get_password(ref, username))
