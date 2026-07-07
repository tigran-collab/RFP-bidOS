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
import os
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse


def _browser_channels() -> list[str | None]:
    """Preferred browser launch channels, first that launches wins.

    Prefers the user's REAL system browser (Edge/Chrome) over Playwright's
    bundled Chromium, which on Windows is frequently blocked or removed by
    antivirus ("spawn UNKNOWN" / "Executable doesn't exist"). ``None`` means the
    bundled Chromium. Override with RFP_BIDOS_BROWSER_CHANNEL (e.g. "chrome",
    "msedge", or "chromium").
    """
    override = os.environ.get("RFP_BIDOS_BROWSER_CHANNEL", "").strip().lower()
    if override:
        return [None] if override == "chromium" else [override]
    if sys.platform == "win32":
        return ["msedge", "chrome", None]
    return ["chrome", "chromium", None]


def _launch_persistent_context(pw, profile_dir: str, headless: bool, **extra):
    """Launch a persistent context, trying system browsers before bundled Chromium.

    The same channel order is used everywhere so the persisted login session is
    reused by the same browser for later headless scrapes.
    """
    errors = []
    for channel in _browser_channels():
        kwargs = {"headless": headless, **extra}
        if channel:
            kwargs["channel"] = channel
        try:
            return pw.chromium.launch_persistent_context(profile_dir, **kwargs)
        except Exception as exc:  # noqa: BLE001 - try the next channel
            label = channel or "chromium"
            errors.append(f"{label}: {str(exc).splitlines()[0] if str(exc) else type(exc).__name__}")
    raise RuntimeError("No launchable browser. Tried -> " + "; ".join(errors))


_DOWNLOADABLE_CONTENT_TYPES = {
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "text/csv": ".csv",
    "application/csv": ".csv",
    "application/zip": ".zip",
    "application/x-zip-compressed": ".zip",
    "text/plain": ".txt",
}

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


class BrowserClosedError(RuntimeError):
    """Raised when the visible browser window/context is closed mid-operation.

    Typically the human closed the window; the caller should stop cleanly
    instead of erroring on every remaining item.
    """


def _browser_gone(exc: Exception) -> bool:
    message = str(exc).lower()
    return "has been closed" in message or "context disposed" in message


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


def _session_state_path(profile_dir: str) -> Path:
    return Path(profile_dir) / "session_state.json"


def _save_session_state(context, profile_dir: str) -> None:
    """Persist the authenticated session (incl. session cookies) after login.

    Playwright's persistent profile does not restore session cookies (no expiry)
    on relaunch, which SSO logins rely on. Capturing storage_state while the
    context is open lets a later fetch restore the exact session — the standard
    "stay logged in" mechanism, using the user's own session, not evasion.
    """
    try:
        state = context.storage_state()
        _session_state_path(profile_dir).write_text(json.dumps(state), encoding="utf-8")
    except Exception:
        pass


def _restore_session_state(context, profile_dir: str) -> None:
    """Re-inject cookies saved by a prior login so the fetch is authenticated."""
    try:
        path = _session_state_path(profile_dir)
        if not path.exists():
            return
        cookies = json.loads(path.read_text(encoding="utf-8")).get("cookies") or []
        if cookies:
            context.add_cookies(cookies)
    except Exception:
        pass


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
            context = _launch_persistent_context(pw, profile_dir, headless=False)
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
            # Capture the authenticated session (incl. session cookies) while the
            # context is still open, then close (which persists the profile).
            _save_session_state(context, profile_dir)
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
    headless: bool = True,
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
        context = _launch_persistent_context(pw, profile_dir, headless=headless)
        _restore_session_state(context, profile_dir)
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
    headless: bool = True,
    search_keyword: str | None = None,
    search_input_selector: str | None = None,
    search_submit_selector: str | None = None,
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
        context = _launch_persistent_context(pw, profile_dir, headless=headless)
        _restore_session_state(context, profile_dir)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            response = page.goto(page_url, timeout=timeout_ms)
            status = response.status if response is not None else None
            final_url = page.url

            # Optional: run a keyword search before reading results. Some portals
            # (e.g. BidNet) POST the search, so a plain GET shows only a default
            # slice; typing a keyword and submitting is normal use of the page.
            if search_keyword and search_input_selector:
                try:
                    page.fill(search_input_selector, search_keyword, timeout=timeout_ms)
                    if search_submit_selector:
                        page.click(search_submit_selector, timeout=timeout_ms)
                    else:
                        page.keyboard.press("Enter")
                    try:
                        page.wait_for_load_state("networkidle", timeout=timeout_ms)
                    except Exception:
                        pass
                except Exception:
                    # Search UI not present/changed — fall through to whatever
                    # the page shows; parse degrades to [] if nothing matches.
                    pass

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


def capture_page(
    page_url: str,
    profile_dir: str,
    headless: bool = True,
    settle_ms: int = 9000,
) -> dict:
    """Diagnostic: fetch a page via the persisted session and return what came back.

    Unlike fetch_authenticated_html, this does NOT raise on 403 / login redirect;
    it navigates, waits for the page to settle (network idle, best-effort), and
    returns {status, final_url, html, title}. Used to tell a WAF block apart from
    a real results page and to finalize selectors. A real browser reusing a real
    login — no header forgery, no automation hiding.
    """
    sync_playwright = _require_playwright()
    if not Path(profile_dir).exists():
        raise SessionExpiredError(
            f"No persisted browser profile at {profile_dir}. Run assisted login first."
        )
    with sync_playwright() as pw:
        context = _launch_persistent_context(pw, profile_dir, headless=headless)
        _restore_session_state(context, profile_dir)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            response = page.goto(page_url, timeout=60_000)
            status = response.status if response is not None else None
            # Let SPA content / any redirect settle before capturing.
            for state in ("domcontentloaded", "networkidle"):
                try:
                    page.wait_for_load_state(state, timeout=settle_ms)
                except Exception:
                    pass
            return {
                "status": status,
                "final_url": page.url,
                "title": (page.title() or "")[:120],
                "html": _read_html(page),
            }
        finally:
            try:
                context.close()
            except Exception:
                pass


def download_document_links_headed(
    page_url: str,
    profile_dir: str,
    output_dir: str,
    wait_selector: str | None = None,
    pre_click_selectors: list[str] | None = None,
    download_click_selectors: list[str] | None = None,
    timeout_seconds: int = 120,
    max_downloads: int = 25,
    min_confidence: float = 0.3,
    settle_ms: int = 1500,
    allow_external: bool = False,
) -> dict:
    """Open a visible authenticated browser and save bid-document downloads.

    This reuses the human-established portal session, opens the opportunity in
    a visible browser, optionally clicks configured tabs/expanders, then clicks
    document-like links or configured download controls. It never logs in,
    solves CAPTCHA, submits bids, or bypasses access controls.
    """
    from app.services.scrapers.extraction_utils import (
        extract_document_candidates,
        extract_document_view_links,
        is_document_url,
    )

    sync_playwright = _require_playwright()
    if not Path(profile_dir).exists():
        raise SessionExpiredError(
            f"No persisted browser profile at {profile_dir}. Run assisted login first."
        )
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    timeout_ms = max(1, int(timeout_seconds)) * 1000
    max_downloads = max(1, int(max_downloads))
    min_confidence = max(0.0, float(min_confidence))

    result = {
        "page_url": page_url,
        "final_url": None,
        "candidates_found": 0,
        "downloads_attempted": 0,
        "downloaded_files": [],
        "errors": [],
    }

    with sync_playwright() as pw:
        context = _launch_persistent_context(
            pw, profile_dir, headless=False, accept_downloads=True
        )
        _restore_session_state(context, profile_dir)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            response = page.goto(page_url, timeout=timeout_ms)
            status = response.status if response is not None else None
            _settle_page(page, settle_ms)

            for selector in _clean_selectors(pre_click_selectors):
                try:
                    locator = page.locator(selector).first
                    if locator.count() > 0:
                        locator.click(timeout=timeout_ms)
                        _settle_page(page, settle_ms)
                except Exception as exc:  # noqa: BLE001 - keep trying other selectors
                    result["errors"].append(f"Pre-click selector failed ({selector}): {exc}")

            if wait_selector and "TODO" not in str(wait_selector):
                try:
                    page.wait_for_selector(wait_selector, timeout=timeout_ms)
                except Exception:
                    pass

            html = _read_html(page)
            result["final_url"] = page.url
            _raise_if_session_expired(status, page.url, html, page_url)

            # Documents often live behind a tab ("Documents", ?innerTabId=...).
            # Visit the loaded page first, then up to 3 document-view links
            # discovered on it, harvesting downloads from each view.
            views = [page.url, *extract_document_view_links(html, page.url)[:3]]
            seen_candidate_urls: set[str] = set()

            try:
                for candidate in _configured_click_targets(page, download_click_selectors):
                    if result["downloads_attempted"] >= max_downloads:
                        break
                    result["downloads_attempted"] += 1
                    _download_by_selector(page, candidate, output_path, timeout_ms, result)

                for view_index, view_url in enumerate(views):
                    if result["downloads_attempted"] >= max_downloads:
                        break
                    if view_index > 0:
                        try:
                            page.goto(view_url, timeout=timeout_ms)
                            _settle_page(page, settle_ms)
                            html = _read_html(page)
                        except Exception as exc:  # noqa: BLE001 - skip this view
                            if _browser_gone(exc):
                                raise BrowserClosedError(str(exc)) from exc
                            result["errors"].append(f"{view_url}: could not open view: {exc}")
                            continue

                    candidates = [
                        candidate
                        for candidate in _filter_download_candidates(
                            extract_document_candidates(
                                html, page.url, allow_external=allow_external
                            ),
                            page.url,
                            min_confidence,
                        )
                        if candidate.get("url") not in seen_candidate_urls
                    ]
                    result["candidates_found"] += len(candidates)

                    for candidate in candidates:
                        if result["downloads_attempted"] >= max_downloads:
                            break
                        seen_candidate_urls.add(candidate.get("url"))
                        result["downloads_attempted"] += 1
                        before_count = len(result["downloaded_files"])
                        if is_document_url(candidate.get("url", "")):
                            _download_by_browser_request(
                                context, candidate, output_path, timeout_ms, result
                            )
                        if len(result["downloaded_files"]) == before_count:
                            _download_by_click(page, context, candidate, output_path, timeout_ms, result)
            except BrowserClosedError:
                result["errors"].append(
                    "Browser window was closed before all downloads completed; stopping."
                )
        finally:
            _save_session_state(context, profile_dir)
            try:
                context.close()
            except Exception:
                pass

    return result


def _url_path_base(url: str) -> str:
    """URL without query/fragment, for self-link comparison."""
    parsed = urlparse(url or "")
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/").lower()


def _filter_download_candidates(
    candidates: list[dict], page_url: str, min_confidence: float
) -> list[dict]:
    """Drop self-links, duplicates, and low-confidence candidates.

    Links back to the opportunity page itself (e.g. ?innerTabId=... tab
    anchors) are navigation, not documents — clicking them navigates the
    visible browser away and derails the remaining downloads.
    """
    page_base = _url_path_base(page_url)
    seen_urls: set[str] = set()
    filtered = []
    for candidate in candidates:
        if float(candidate.get("confidence_score") or 0) < min_confidence:
            continue
        url = candidate.get("url") or ""
        if not url or url in seen_urls:
            continue
        if _url_path_base(url) == page_base:
            continue
        seen_urls.add(url)
        filtered.append(candidate)
    return filtered


def _clean_selectors(selectors: list[str] | None) -> list[str]:
    return [
        selector
        for selector in (selectors or [])
        if selector and "TODO" not in str(selector)
    ]


def _settle_page(page, settle_ms: int) -> None:
    for state in ("domcontentloaded", "networkidle"):
        try:
            page.wait_for_load_state(state, timeout=settle_ms)
        except Exception:
            pass


def _configured_click_targets(page, selectors: list[str] | None) -> list[dict]:
    targets = []
    for selector in _clean_selectors(selectors):
        try:
            count = min(page.locator(selector).count(), 25)
        except Exception:
            continue
        for index in range(count):
            targets.append(
                {
                    "selector": selector,
                    "selector_index": index,
                    "label": selector,
                    "url": "",
                    "confidence_score": 1.0,
                    "reason": "configured portal download selector",
                }
            )
    return targets


def _download_by_browser_request(
    context,
    candidate: dict,
    output_dir: Path,
    timeout_ms: int,
    result: dict,
) -> None:
    url = candidate.get("url")
    if not url:
        return
    try:
        response = context.request.get(url, timeout=timeout_ms)
        status = response.status
        body = response.body()
        headers = {key.lower(): value for key, value in response.headers.items()}
        content_type = (headers.get("content-type") or "").split(";", 1)[0].lower()
        text_sample = body[:2000].decode("utf-8", errors="ignore")
        _raise_if_session_expired(status, response.url, text_sample, url)
        if status >= 400:
            result["errors"].append(f"{url}: HTTP {status}")
            return
        extension = _extension_for_download(url, content_type)
        if not extension:
            return
        filename = _filename_for_response(url, headers, candidate, extension)
        path = _available_output_path(output_dir / filename)
        path.write_bytes(body)
        result["downloaded_files"].append(
            {
                "url": url,
                "label": candidate.get("label") or filename,
                "path": str(path),
                "filename": path.name,
                "content_type": content_type or None,
                "method": "browser_request",
            }
        )
    except SessionExpiredError:
        raise
    except Exception as exc:  # noqa: BLE001 - try the click path next
        if _browser_gone(exc):
            raise BrowserClosedError(str(exc)) from exc
        result["errors"].append(f"{url}: browser request failed: {exc}")


def _download_by_click(
    page,
    context,
    candidate: dict,
    output_dir: Path,
    timeout_ms: int,
    result: dict,
) -> None:
    url = candidate.get("url")
    if not url:
        return
    token = f"rfp-bidos-download-{abs(hash(url))}"
    page_url_before = page.url
    try:
        found = page.evaluate(
            """({url, token}) => {
                const anchors = Array.from(document.querySelectorAll('a[href]'));
                for (const anchor of anchors) {
                    const resolved = new URL(anchor.getAttribute('href'), document.baseURI).href.split('#')[0];
                    if (resolved === url) {
                        anchor.setAttribute('data-rfp-bidos-download-target', token);
                        return true;
                    }
                }
                return false;
            }""",
            {"url": url, "token": token},
        )
        if not found:
            result["errors"].append(f"{url}: link not found on page")
            return
        locator = page.locator(f'[data-rfp-bidos-download-target="{token}"]').first
        _save_click_download(page, locator, candidate, output_dir, timeout_ms, result)
    except Exception as exc:  # noqa: BLE001
        if _browser_gone(exc):
            raise BrowserClosedError(str(exc)) from exc
        # A click that navigated instead of downloading leaves the page on the
        # wrong URL for every later candidate — restore it before moving on.
        try:
            if page.url != page_url_before:
                page.go_back(timeout=10_000)
        except Exception:  # noqa: BLE001 - restore is best-effort
            pass
        # Fallback: a click sometimes opens a document URL inline rather than a
        # download. Try the browser request path one last time.
        before_count = len(result["downloaded_files"])
        _download_by_browser_request(context, candidate, output_dir, timeout_ms, result)
        if len(result["downloaded_files"]) == before_count:
            result["errors"].append(f"{url}: click failed: {exc}")


def _download_by_selector(
    page,
    candidate: dict,
    output_dir: Path,
    timeout_ms: int,
    result: dict,
) -> None:
    selector = candidate.get("selector")
    index = int(candidate.get("selector_index") or 0)
    try:
        locator = page.locator(selector).nth(index)
        _save_click_download(page, locator, candidate, output_dir, timeout_ms, result)
    except Exception as exc:  # noqa: BLE001
        if _browser_gone(exc):
            raise BrowserClosedError(str(exc)) from exc
        result["errors"].append(f"{selector}: configured click failed: {exc}")


def _save_click_download(page, locator, candidate: dict, output_dir: Path, timeout_ms: int, result: dict) -> None:
    # Element clicks get a short leash: an invisible/hidden link should fail in
    # seconds, not consume the whole page timeout retrying (observed on BidNet
    # nav anchors). The download itself may still take up to timeout_ms.
    with page.expect_download(timeout=min(timeout_ms, 30_000)) as download_info:
        locator.click(timeout=min(timeout_ms, 10_000))
    download = download_info.value
    filename = download.suggested_filename or _filename_from_url(candidate.get("url")) or "document"
    path = _available_output_path(output_dir / filename)
    download.save_as(str(path))
    result["downloaded_files"].append(
        {
            "url": candidate.get("url") or getattr(download, "url", None),
            "label": candidate.get("label") or filename,
            "path": str(path),
            "filename": path.name,
            "content_type": None,
            "method": "click_download",
        }
    )


def _extension_for_download(url: str, content_type: str | None) -> str | None:
    suffix = Path(unquote(urlparse(url).path)).suffix.lower()
    if suffix in {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".zip", ".txt"}:
        return suffix
    return _DOWNLOADABLE_CONTENT_TYPES.get(content_type or "")


def _filename_for_response(url: str, headers: dict, candidate: dict, extension: str) -> str:
    disposition = headers.get("content-disposition") or ""
    filename = _filename_from_content_disposition(disposition)
    if not filename:
        filename = _filename_from_url(url)
    if not filename:
        label = str(candidate.get("label") or "document")
        filename = "".join(char if char.isalnum() else "_" for char in label).strip("_")
    filename = filename or "document"
    if not Path(filename).suffix and extension:
        filename = f"{filename}{extension}"
    return filename


def _filename_from_content_disposition(value: str) -> str | None:
    if "filename=" not in value.lower():
        return None
    raw = value.split("filename=", 1)[1].strip().strip('"')
    return Path(raw).name or None


def _filename_from_url(url: str | None) -> str | None:
    if not url:
        return None
    name = Path(unquote(urlparse(url).path)).name
    return name or None


def _available_output_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem or "document"
    suffix = path.suffix
    for index in range(1, 1000):
        candidate = path.with_name(f"{stem}_{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not create a non-conflicting filename for {path.name}")


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
