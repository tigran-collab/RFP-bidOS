"""In-app portal management endpoints.

These endpoints let a human manage authenticated portals entirely from the
local web UI (add a portal, store credentials, run an assisted login, enable,
scrape) without touching the terminal.

Security invariants (mirrored from the CLI):
  * The password travels from the browser to the LOCAL backend only. It is
    stored ONLY in the OS keychain via ``credential_store`` — never in the
    database, never returned by any GET, never logged.
  * Assisted login remains a HUMAN completing a real login in a VISIBLE
    browser. This code never solves CAPTCHAs and never forges tokens.
  * Playwright stays lazy/optional. When it is unavailable, portal-login fails
    cleanly with an explanatory state instead of crashing.

The assisted login runs in a BACKGROUND THREAD so the HTTP request returns
immediately; the browser window can stay open for minutes while the human logs
in. Per-source progress is tracked in an in-memory, lock-guarded dict.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlmodel import Session

from app.db import engine
from app.models import SourceConfig
from app.schemas import SourceConfigRead
from app.services import credential_store
from app.services.scrapers.portal_templates import list_templates
from app.services.source_credentials import (
    CREDENTIAL_TYPE_KEYRING,
    get_source_auth_status,
)

router = APIRouter(prefix="/sources", tags=["portals"])


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# In-memory assisted-login state (per source), guarded by a lock. This is
# process-local progress only; nothing sensitive is stored here.
#   states: "idle" | "launching" | "awaiting_user" | "success" | "expired"
#           | "failed"
# ---------------------------------------------------------------------------
LOGIN_STATE: dict[int, dict] = {}
_LOGIN_LOCK = threading.Lock()


def _set_login_state(source_id: int, state: str, message: str) -> dict:
    entry = {
        "state": state,
        "message": message,
        "updated_at": _utc_now().isoformat(),
    }
    with _LOGIN_LOCK:
        LOGIN_STATE[source_id] = entry
    return dict(entry)


def _get_login_state(source_id: int) -> dict:
    with _LOGIN_LOCK:
        entry = LOGIN_STATE.get(source_id)
        if entry is None:
            return {
                "state": "idle",
                "message": "No login attempt yet.",
                "updated_at": None,
            }
        return dict(entry)


class AddPortalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template: str | None = None
    name: str
    source_type: str | None = None
    login_url: str | None = None
    list_url: str | None = None


class SourceCredentialsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str
    password: str


def _keyring_ref_for_source(source: SourceConfig) -> str:
    """Return the source's keyring service ref, deriving a stable one if unset."""
    if source.credential_secret_ref:
        return source.credential_secret_ref
    return f"rfp-bidos:{source.id}"


# ---------------------------------------------------------------------------
# 1. Templates. Registered on the /sources prefix but under a non-numeric path
#    so it never collides with /sources/{source_id}.
# ---------------------------------------------------------------------------
@router.get("/portal-templates")
def get_portal_templates() -> list[dict]:
    return list_templates()


# ---------------------------------------------------------------------------
# 2. Add a portal (disabled, requires credentials).
# ---------------------------------------------------------------------------
@router.post("/add-portal", response_model=SourceConfigRead, status_code=201)
def add_portal(payload: AddPortalRequest) -> SourceConfig:
    # Imported here to avoid a Typer import at module load and to keep the
    # importable service logic in one place (cli.add_portal_source).
    from app.cli import add_portal_source

    if not (payload.name or "").strip():
        raise HTTPException(status_code=422, detail="name is required")

    with Session(engine) as session:
        try:
            result = add_portal_source(
                session,
                name=payload.name.strip(),
                template=payload.template,
                source_type=payload.source_type,
                login_url=payload.login_url,
                list_url=payload.list_url,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        source = session.get(SourceConfig, result["source_id"])
        if source is None:  # pragma: no cover - defensive
            raise HTTPException(status_code=500, detail="Portal creation failed")
        return source


# ---------------------------------------------------------------------------
# 3. Store credentials in the OS keychain (password never returned/logged).
# ---------------------------------------------------------------------------
@router.put("/{source_id}/credentials")
def set_source_credentials(source_id: int, payload: SourceCredentialsRequest) -> dict:
    username = (payload.username or "").strip()
    if not username:
        raise HTTPException(status_code=422, detail="username is required")
    if not payload.password:
        raise HTTPException(status_code=422, detail="password is required")

    if not credential_store.is_available():
        raise HTTPException(
            status_code=503,
            detail=(
                "OS keychain (keyring) is not available. Install it with "
                "`pip install keyring` and ensure your OS keychain is accessible."
            ),
        )

    with Session(engine) as session:
        source = session.get(SourceConfig, source_id)
        if source is None:
            raise HTTPException(status_code=404, detail="Source not found")

        ref = _keyring_ref_for_source(source)
        store_result = credential_store.set_password(ref, username, payload.password)
        # Never keep the plaintext around longer than needed; never log it.
        if not store_result["ok"]:
            raise HTTPException(status_code=502, detail=store_result["message"])

        source.credential_username = username
        source.credential_secret_ref = ref
        source.credential_type = CREDENTIAL_TYPE_KEYRING
        source.requires_credentials = True
        status = get_source_auth_status(source)
        source.auth_status = status["auth_status"]
        source.auth_last_checked_at = _utc_now()
        session.add(source)
        session.commit()
        session.refresh(source)
        result = get_source_auth_status(source)

    # The auth-status dict reports only credential *references* and presence,
    # never the password itself.
    return result


# ---------------------------------------------------------------------------
# 4. Delete stored credentials.
# ---------------------------------------------------------------------------
@router.delete("/{source_id}/credentials")
def delete_source_credentials(source_id: int) -> dict:
    with Session(engine) as session:
        source = session.get(SourceConfig, source_id)
        if source is None:
            raise HTTPException(status_code=404, detail="Source not found")

        ref = source.credential_secret_ref
        username = source.credential_username
        if ref and username:
            credential_store.delete_password(ref, username)

        source.credential_username = None
        status = get_source_auth_status(source)
        source.auth_status = status["auth_status"]
        source.auth_last_checked_at = _utc_now()
        session.add(source)
        session.commit()
        session.refresh(source)
        result = get_source_auth_status(source)

    return result


# ---------------------------------------------------------------------------
# 5. Start assisted login in a background thread.
# ---------------------------------------------------------------------------
def _profile_dir_for_source_id(source_id: int) -> str:
    root = Path(__file__).resolve().parents[2] / "data" / "browser_profiles"
    return str(root / str(source_id))


def _portal_login_url(source: SourceConfig) -> str | None:
    if source.login_url:
        return source.login_url
    # Fall back to config_json.login_url / list_url, then base_url.
    import json as _json

    if source.config_json:
        try:
            config = _json.loads(source.config_json)
        except (TypeError, ValueError):
            config = {}
        if isinstance(config, dict):
            for key in ("login_url", "list_url"):
                value = config.get(key)
                if value and not str(value).startswith("TODO"):
                    return value
    return source.base_url


def _run_assisted_login(
    source_id: int,
    portal_url: str,
    profile_dir: str,
    username: str | None,
    password: str | None,
    success_substr: str | None,
) -> None:
    """Background worker: open the visible browser and persist the session.

    Catches ALL exceptions and records them as state "failed" so the server
    never crashes. The password is never logged.
    """
    from app.services.scrapers import browser_session

    _set_login_state(
        source_id,
        "awaiting_user",
        "Opening browser — complete the login in the window that opened.",
    )
    try:
        result = browser_session.assisted_login(
            portal_url,
            profile_dir,
            prefill_username=username,
            prefill_password=password,
            success_url_substring=success_substr,
            timeout_seconds=180,
        )
        if result.get("ok"):
            _set_login_state(source_id, "success", result.get("message", "Session persisted."))
        else:
            _set_login_state(
                source_id,
                "expired",
                result.get("message", "Login did not complete; try again."),
            )
    except Exception as exc:  # never crash the server
        _set_login_state(source_id, "failed", f"Assisted login failed: {exc}")
    finally:
        del password


@router.post("/{source_id}/portal-login")
def start_portal_login(source_id: int) -> dict:
    from app.services.scrapers import browser_session

    with Session(engine) as session:
        source = session.get(SourceConfig, source_id)
        if source is None:
            raise HTTPException(status_code=404, detail="Source not found")

        portal_url = _portal_login_url(source)
        if not portal_url:
            raise HTTPException(
                status_code=400,
                detail=f"Source '{source.name}' has no login_url or base_url to open.",
            )

        username = source.credential_username
        password = None
        if username and source.credential_secret_ref:
            password = credential_store.get_password(
                source.credential_secret_ref, username
            )
        profile_dir = _profile_dir_for_source_id(source_id)

        success_substr = None
        if source.config_json:
            import json as _json

            try:
                config = _json.loads(source.config_json)
            except (TypeError, ValueError):
                config = {}
            if isinstance(config, dict):
                success_substr = config.get("success_url_substring")

    if not browser_session.playwright_available():
        return _set_login_state(
            source_id,
            "failed",
            (
                "Playwright is not installed. Run `pip install -r requirements.txt` "
                "then `playwright install chromium` (one-time) to enable "
                "browser-based assisted login."
            ),
        )

    _set_login_state(source_id, "launching", "Launching the browser…")
    worker = threading.Thread(
        target=_run_assisted_login,
        args=(source_id, portal_url, profile_dir, username, password, success_substr),
        daemon=True,
    )
    worker.start()
    return _get_login_state(source_id)


# ---------------------------------------------------------------------------
# 6. Login status (progress + session-profile presence + keyring auth-status).
# ---------------------------------------------------------------------------
@router.get("/{source_id}/login-status")
def get_login_status(source_id: int) -> dict:
    with Session(engine) as session:
        source = session.get(SourceConfig, source_id)
        if source is None:
            raise HTTPException(status_code=404, detail="Source not found")
        auth_status = get_source_auth_status(source)

    profile_dir = _profile_dir_for_source_id(source_id)
    has_session_profile = Path(profile_dir).exists()

    return {
        **_get_login_state(source_id),
        "has_session_profile": has_session_profile,
        "auth_status": auth_status,
    }
