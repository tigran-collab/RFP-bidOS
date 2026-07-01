"""Assisted-login browser session helper (Playwright, lazy/optional).

This module supports ASSISTED authenticated access to portals whose bids are
only reachable behind a real login. The design is deliberately narrow and
safe:

  * Login is performed by a HUMAN in a VISIBLE (non-headless) browser window.
    The human types the username/password (optionally pre-filled) and clears
    any CAPTCHA / MFA. This code never solves CAPTCHAs, never forges anti-bot
    tokens, and never bypasses access controls. A real person completing a real
    login is the entire mechanism.
  * The authenticated session is persisted to an on-disk browser profile
    (a Playwright persistent context). Later data fetches REUSE that profile
    headlessly instead of logging in again, which respects the portal and keeps
    request volume low.
  * When the persisted session has expired, the fetch path detects the login
    redirect / 401 / access-denied and raises SessionExpiredError so the caller
    can prompt the human to run assisted login again — it never tries to
    re-authenticate on its own.

Playwright is imported LAZILY inside each function so this module (and the full
test suite) import and run even when Playwright or its Chromium browser are not
installed. Installing the browser is a one-time manual step, documented in the
README:

    pip install -r requirements.txt
    playwright install chromium

Never call `playwright install` from application code.
"""

from __future__ import annotations

import json
from pathlib import Path

# Best-effort selectors for pre-filling the login form. These are only
# conveniences for the human; if none match, the human simply types the
# credentials manually. We never submit the form programmatically.
_USERNAME_SELECTORS = (
    "input[type='email']",
    "input[name='username']",
    "input[name='email']",
    "input[name='user']",
    "input[id*='user' i]",
    "input[id*='email' i]",
)
_PASSWORD_SELECTORS = (
    "input[type='password']",
    "input[name='password']",
    "input[id*='pass' i]",
)

# Substrings that indicate the persisted session is no longer authenticated.
_SESSION_EXPIRED_MARKERS = (
    "direct_access",
    "not authorized",
    "unauthorized",
    "please log in",
    "please sign in",
    "session expired",
    "login required",
)


class SessionExpiredError(RuntimeError):
    """Raised when a persisted browser session is no longer authenticated.

    The caller should prompt the human to re-run assisted login rather than
    attempting any automated re-authentication.
    """


class PlaywrightNotInstalledError(RuntimeError):
    """Raised when a browser operation is attempted without Playwright."""


def playwright_available() -> bool:
    """True when the Playwright Python package is importable.

    Note this does not guarantee the Chromium browser binary is installed
    (that is the separate `playwright install chromium` step); a launch failure
    for a missing browser surfaces as a clear error at call time.
    """
    try:
        import playwright  # noqa: F401, PLC0415  (lazy/optional import probe)

        return True
    except Exception:
        return False


def _require_playwright():
    """Import and return sync_playwright, or raise PlaywrightNotInstalledError."""
    try:
        from playwright.sync_api import sync_playwright  # noqa: PLC0415

        return sync_playwright
    except Exception as exc:  # ImportError or partial install
        raise PlaywrightNotInstalledError(
            "Playwright is not installed. Run `pip install -r requirements.txt` "
            "then `playwright install chromium` (one-time) to enable "
            "browser-based authenticated sources."
        ) from exc


def _ensure_profile_dir(profile_dir: str) -> str:
    path = Path(profile_dir)
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def assisted_login(
    portal_url: str,
    profile_dir: str,
    prefill_username: str | None = None,
    prefill_password: str | None = None,
    success_url_substring: str | None = None,
    timeout_seconds: int = 180,
) -> dict:
    """Open a VISIBLE browser for a human to log in, then persist the session.

    Launches a visible persistent-context Chromium at ``profile_dir``, navigates
    to ``portal_url``, best-effort pre-fills the username/password fields (never
    submitting), then WAITS for the human to complete login (and any CAPTCHA /
    MFA). Completion is detected when the page URL contains
    ``success_url_substring`` (if provided); otherwise it waits until the human
    closes the window or the timeout elapses. Closing the context persists
    cookies/localStorage to ``profile_dir`` for later headless reuse.

    Returns {ok: bool, message: str}. The password is never logged.
    """
    sync_playwright = _require_playwright()
    profile_dir = _ensure_profile_dir(profile_dir)
    timeout_ms = max(1, int(timeout_seconds)) * 1000

    with sync_playwright() as pw:
        try:
            context = pw.chromium.launch_persistent_context(
                profile_dir,
                headless=False,
            )
        except Exception as exc:  # noqa: BLE001 - surface a clear operator message
            first_line = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
            return {
                "ok": False,
                "message": (
                    "Could not open a visible browser window for login. The backend "
                    "must run in your own desktop session to show a browser — start "
                    "the app with start_rfp_bidos.bat or the desktop launcher (not as "
                    "a background/service process), then try Log in again. "
                    f"(details: {first_line})"
                ),
            }
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(portal_url, timeout=60_000)
            _prefill_login_fields(page, prefill_username, prefill_password)

            if success_url_substring:
                try:
                    page.wait_for_url(
                        lambda url: success_url_substring in url,
                        timeout=timeout_ms,
                    )
                    message = "Login detected; session persisted."
                    ok = True
                except Exception:
                    message = (
                        "Timed out waiting for login to complete. If you did log "
                        "in, the session may still have been persisted; try a "
                        "fetch and re-run login if it reports the session expired."
                    )
                    ok = False
            else:
                # No success marker: let the human close the window when done.
                # Wait for the page/context to close, bounded by the timeout.
                ok, message = _wait_until_closed(page, timeout_ms)
        finally:
            # Closing persists the storage state to profile_dir.
            try:
                context.close()
            except Exception:
                pass

    return {"ok": ok, "message": message}


def _prefill_login_fields(page, username: str | None, password: str | None) -> None:
    """Best-effort fill of login fields. Never submits; failures are ignored."""
    if username:
        _fill_first(page, _USERNAME_SELECTORS, username)
    if password:
        _fill_first(page, _PASSWORD_SELECTORS, password)


def _fill_first(page, selectors, value: str) -> bool:
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.count() > 0:
                locator.fill(value, timeout=2_000)
                return True
        except Exception:
            continue
    return False


def _wait_until_closed(page, timeout_ms: int) -> tuple[bool, str]:
    try:
        page.wait_for_event("close", timeout=timeout_ms)
        return True, "Login window closed; session persisted."
    except Exception:
        return (
            True,
            "Login window left open until timeout; session persisted as-is. "
            "Re-run login if a later fetch reports the session expired.",
        )


def fetch_authenticated_json(
    api_url: str,
    profile_dir: str,
    timeout_seconds: int = 45,
):
    """Fetch JSON from ``api_url`` using the persisted (already-authenticated)
    profile, HEADLESSLY.

    Launches a headless persistent-context Chromium at the SAME ``profile_dir``
    used by assisted_login, navigates to ``api_url``, and returns the parsed
    JSON (a dict or list). This is a real browser context reusing a real login;
    no headers are forged.

    Raises:
      PlaywrightNotInstalledError: Playwright is not installed.
      SessionExpiredError: the persisted session is no longer authenticated
        (login redirect / 401 / 403 / access-denied marker).
      ValueError: the response body is not JSON.
    """
    sync_playwright = _require_playwright()
    if not Path(profile_dir).exists():
        raise SessionExpiredError(
            f"No persisted browser profile at {profile_dir}. Run assisted login first."
        )
    timeout_ms = max(1, int(timeout_seconds)) * 1000

    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(profile_dir, headless=True)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            response = page.goto(api_url, timeout=timeout_ms, wait_until="commit")
            status = response.status if response is not None else None
            final_url = page.url
            body = _read_body(page, response)

            _raise_if_session_expired(status, final_url, body, api_url)

            return _parse_json_body(body, api_url)
        finally:
            try:
                context.close()
            except Exception:
                pass


def fetch_authenticated_html(
    page_url: str,
    profile_dir: str,
    wait_selector: str | None = None,
    timeout_seconds: int = 45,
) -> str:
    """Fetch the rendered HTML of ``page_url`` using the persisted profile, HEADLESSLY.

    Launches a headless persistent-context Chromium at the SAME ``profile_dir``
    used by assisted_login, navigates to ``page_url``, optionally waits for
    ``wait_selector`` to appear (so SPA-rendered rows have loaded), and returns
    the page's rendered ``outerHTML``. This is a real browser context reusing a
    real login; no headers are forged.

    Raises:
      PlaywrightNotInstalledError: Playwright is not installed.
      SessionExpiredError: the persisted session is no longer authenticated
        (login redirect / 401 / 403 / access-denied marker).
    """
    sync_playwright = _require_playwright()
    if not Path(profile_dir).exists():
        raise SessionExpiredError(
            f"No persisted browser profile at {profile_dir}. Run assisted login first."
        )
    timeout_ms = max(1, int(timeout_seconds)) * 1000

    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(profile_dir, headless=True)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            response = page.goto(page_url, timeout=timeout_ms)
            status = response.status if response is not None else None
            final_url = page.url

            if wait_selector:
                try:
                    page.wait_for_selector(wait_selector, timeout=timeout_ms)
                except Exception:
                    # A missing selector is not fatal on its own — the session
                    # check below still runs, and an empty parse degrades to [].
                    pass

            html = _read_html(page)
            _raise_if_session_expired(status, final_url, html, page_url)
            return html
        finally:
            try:
                context.close()
            except Exception:
                pass


def _read_html(page) -> str:
    try:
        return page.content()
    except Exception:
        try:
            return page.evaluate(
                "() => document.documentElement ? document.documentElement.outerHTML : ''"
            )
        except Exception:
            return ""


def _read_body(page, response) -> str:
    """Return the response body text, preferring the raw HTTP body."""
    if response is not None:
        try:
            return response.text()
        except Exception:
            pass
    try:
        # Fallback: the JSON is often rendered into the page as text.
        return page.evaluate("() => document.body ? document.body.innerText : ''")
    except Exception:
        return ""


def _raise_if_session_expired(
    status: int | None, final_url: str, body: str, api_url: str
) -> None:
    if status in (401, 403):
        raise SessionExpiredError(
            f"Authenticated fetch returned HTTP {status} for {api_url}. "
            "The persisted session has expired; re-run assisted login."
        )
    # A redirect away from the API host to a login page is the common signal.
    lowered_url = (final_url or "").lower()
    if "login" in lowered_url or "signin" in lowered_url or "sign-in" in lowered_url:
        raise SessionExpiredError(
            f"Authenticated fetch was redirected to a login page ({final_url}). "
            "The persisted session has expired; re-run assisted login."
        )
    lowered_body = (body or "")[:2000].lower()
    if any(marker in lowered_body for marker in _SESSION_EXPIRED_MARKERS):
        raise SessionExpiredError(
            "Authenticated fetch returned an access-denied / login response. "
            "The persisted session has expired; re-run assisted login."
        )


def _parse_json_body(body: str, api_url: str):
    try:
        return json.loads(body)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Authenticated fetch for {api_url} did not return JSON."
        ) from exc
