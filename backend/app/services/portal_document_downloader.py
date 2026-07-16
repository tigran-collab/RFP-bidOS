"""Headed assisted-login document downloader for portal-hosted bid docs."""

from __future__ import annotations

import json
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote

from sqlmodel import Session, select

from app.config import BROWSER_PROFILE_ROOT, DOWNLOAD_ROOT
from app.models import Document, Opportunity, SourceConfig
from app.services import credential_store
from app.services.downloader import (
    MAX_DOWNLOAD_BYTES,
    resolve_downloaded_document_path,
    sha256_file,
)
from app.services.scrapers import browser_session
from app.services.scrapers.browser_session import (
    PlaywrightNotInstalledError,
    SessionExpiredError,
)
from app.services.scrapers.portal_templates import DEFAULT_LOGIN_SUCCESS_SUBSTRINGS

SUPPORTED_PORTAL_SOURCE_TYPES = {"planetbids", "authenticated_browser"}


def portal_document_download_available(opportunity: Opportunity, session: Session) -> dict:
    """Return whether an opportunity has a supported assisted-login portal."""
    source = _source_for_opportunity(opportunity, session)
    if source is None:
        return {"available": False, "reason": "No matching portal source found."}
    source_type = (source.source_type or "").lower()
    if source_type not in SUPPORTED_PORTAL_SOURCE_TYPES:
        return {
            "available": False,
            "reason": f"Source '{source.name}' is not an assisted-login portal source.",
        }
    # Mirror the guard in download_portal_documents_headed: without a page URL
    # the download would error immediately, so report it as unavailable (the
    # pursuit workflow shows "skipped" instead of a spurious step failure).
    if not (opportunity.source_url or opportunity.portal_url):
        return {
            "available": False,
            "reason": "Opportunity has no source_url or portal_url.",
        }
    return {"available": True, "source_id": source.id, "source_name": source.name}


def download_portal_documents_headed(opportunity_id: int, session: Session) -> dict:
    """Download bid documents through a visible authenticated browser session."""
    summary = _empty_summary()
    opportunity = session.get(Opportunity, opportunity_id)
    if opportunity is None:
        summary["errors"].append("Opportunity not found")
        return summary

    source = _source_for_opportunity(opportunity, session)
    if source is None:
        summary["errors"].append(
            "No matching portal source found for this opportunity."
        )
        return summary

    source_type = (source.source_type or "").lower()
    if source_type not in SUPPORTED_PORTAL_SOURCE_TYPES:
        summary["errors"].append(
            f"Source '{source.name}' is not an assisted-login portal source."
        )
        return summary

    page_url = opportunity.source_url or opportunity.portal_url
    if not page_url:
        summary["errors"].append("Opportunity has no source_url or portal_url.")
        return summary

    profile_dir = str(BROWSER_PROFILE_ROOT / str(source.id))
    config = _load_source_config(source)
    download_config = _download_config(config)
    # A unique staging dir per run: two concurrent downloads of the SAME
    # opportunity previously shared one ".portal_downloads" dir that each wiped
    # on entry, deleting the other run's in-flight files. mkdtemp guarantees a
    # distinct dir, so concurrent runs never clobber each other.
    opportunity_dir = DOWNLOAD_ROOT / f"opportunity_{opportunity_id}"
    opportunity_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(
        tempfile.mkdtemp(prefix=".portal_downloads_", dir=str(opportunity_dir))
    )

    def _run_download() -> dict:
        return browser_session.download_document_links_headed(
            page_url,
            profile_dir,
            str(temp_dir),
            wait_selector=download_config.get("wait_selector"),
            pre_click_selectors=download_config.get("pre_click_selectors"),
            download_click_selectors=download_config.get("download_click_selectors"),
            timeout_seconds=int(download_config.get("timeout_seconds") or 120),
            max_downloads=int(download_config.get("max_downloads") or 25),
            min_confidence=float(download_config.get("min_confidence") or 0.3),
            settle_ms=int(download_config.get("settle_ms") or 1500),
            allow_external=bool(download_config.get("allow_external", False)),
        )

    try:
        browser_result = _run_download()
    except PlaywrightNotInstalledError as exc:
        summary["errors"].append(str(exc))
        return summary
    except SessionExpiredError:
        # Effortless path: run assisted login (visible window, credentials
        # pre-filled from the OS keychain, human completes any MFA/CAPTCHA),
        # then retry the download once in the fresh session.
        if not _auto_login(source, config, profile_dir, summary):
            return summary
        summary["login_performed"] = True
        try:
            browser_result = _run_download()
        except SessionExpiredError as exc:
            summary["errors"].append(
                f"Portal session still unavailable after login: {exc}"
            )
            return summary
        except Exception as exc:  # noqa: BLE001 - surface a clear operator error
            summary["errors"].append(f"Headed portal download failed: {exc}")
            return summary
    except Exception as exc:  # noqa: BLE001 - surface a clear operator error
        summary["errors"].append(f"Headed portal download failed: {exc}")
        return summary

    summary["candidates_found"] = browser_result.get("candidates_found", 0)
    summary["downloads_attempted"] = browser_result.get("downloads_attempted", 0)
    summary["errors"].extend(browser_result.get("errors") or [])

    for item in browser_result.get("downloaded_files") or []:
        _register_downloaded_file(session, opportunity, item, summary)

    session.commit()
    shutil.rmtree(temp_dir, ignore_errors=True)
    return summary


def _login_url_for_source(source: SourceConfig, config: dict) -> str | None:
    if source.login_url:
        return source.login_url
    for key in ("login_url", "list_url"):
        value = config.get(key)
        if value and not str(value).startswith("TODO"):
            return value
    return source.base_url


def _auto_login(
    source: SourceConfig, config: dict, profile_dir: str, summary: dict
) -> bool:
    """Assisted login with keychain-prefilled credentials; True on success.

    The human still completes the login (and any MFA/CAPTCHA) in the visible
    window — this only removes the trip to the Portals tab. With a
    success_url_substring the window closes itself once logged in.
    """
    login_url = _login_url_for_source(source, config)
    if not login_url:
        summary["errors"].append(
            "Portal session expired and the source has no login URL. "
            "Set one on the Portals tab, then retry."
        )
        return False

    username = source.credential_username
    password = None
    if username and source.credential_secret_ref:
        password = credential_store.get_password(
            source.credential_secret_ref, username
        )

    success_substring = config.get("success_url_substring") or (
        DEFAULT_LOGIN_SUCCESS_SUBSTRINGS.get((source.portal_type or "").lower())
    )
    try:
        result = browser_session.assisted_login(
            login_url,
            profile_dir,
            prefill_username=username,
            prefill_password=password,
            success_url_substring=success_substring,
            timeout_seconds=int(config.get("login_timeout_seconds") or 240),
        )
    except Exception as exc:  # noqa: BLE001 - surface a clear operator error
        summary["errors"].append(f"Assisted login failed: {exc}")
        return False
    finally:
        del password

    if not result.get("ok"):
        summary["errors"].append(
            result.get("message") or "Login did not complete; try again."
        )
        return False
    return True


def _source_for_opportunity(
    opportunity: Opportunity, session: Session
) -> SourceConfig | None:
    if opportunity.source:
        source = session.exec(
            select(SourceConfig).where(SourceConfig.name == opportunity.source)
        ).first()
        if source is not None:
            return source
    page_url = (opportunity.portal_url or opportunity.source_url or "").lower()
    if not page_url:
        return None
    sources = list(session.exec(select(SourceConfig)).all())
    for source in sources:
        for value in (source.base_url, source.login_url):
            if value and value.lower().split("?")[0].rstrip("/") in page_url:
                return source
    return None


def _load_source_config(source: SourceConfig) -> dict:
    raw = source.config_json
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _download_config(config: dict) -> dict:
    nested = config.get("document_download")
    if isinstance(nested, dict):
        merged = dict(nested)
    else:
        merged = {}
    for key in (
        "wait_selector",
        "pre_click_selectors",
        "download_click_selectors",
        "timeout_seconds",
        "max_downloads",
        "min_confidence",
        "settle_ms",
        "allow_external",
    ):
        if key not in merged and key in config:
            merged[key] = config[key]
    if "wait_selector" not in merged and config.get("wait_selector"):
        merged["wait_selector"] = config["wait_selector"]
    return merged


def _register_downloaded_file(
    session: Session,
    opportunity: Opportunity,
    item: dict,
    summary: dict,
) -> None:
    temp_path = Path(item.get("path") or "")
    if not temp_path.is_file():
        summary["errors"].append(f"Downloaded file missing: {temp_path}")
        return
    size = temp_path.stat().st_size
    if size > MAX_DOWNLOAD_BYTES:
        summary["errors"].append(
            f"{temp_path.name}: skipped because it exceeds the "
            f"{MAX_DOWNLOAD_BYTES // (1024 * 1024)} MB download limit"
        )
        temp_path.unlink(missing_ok=True)
        return

    file_hash = sha256_file(str(temp_path))
    existing_by_hash = session.exec(
        select(Document).where(
            Document.opportunity_id == opportunity.id,
            Document.sha256 == file_hash,
        )
    ).first()
    if existing_by_hash is not None:
        summary["skipped_count"] += 1
        summary["files"].append(_file_summary(existing_by_hash))
        temp_path.unlink(missing_ok=True)
        return

    source_url = item.get("url") or f"{opportunity.source_url or opportunity.portal_url}#{item.get('filename')}"
    document = session.exec(
        select(Document).where(
            Document.opportunity_id == opportunity.id,
            Document.source_url == source_url,
        )
    ).first()
    if document is not None and resolve_downloaded_document_path(document) is not None:
        summary["skipped_count"] += 1
        summary["files"].append(_file_summary(document))
        temp_path.unlink(missing_ok=True)
        return

    filename = _safe_filename(item.get("filename") or temp_path.name)
    dest_dir = DOWNLOAD_ROOT / f"opportunity_{opportunity.id}"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = _available_path(dest_dir / filename)
    shutil.move(str(temp_path), str(dest_path))

    if document is None:
        document = Document(
            opportunity_id=opportunity.id,
            filename=dest_path.name,
            path=str(dest_path),
            source_url=source_url,
        )
    document.filename = dest_path.name
    document.path = str(dest_path)
    document.file_type = dest_path.suffix.lower().lstrip(".") or None
    document.sha256 = file_hash
    document.source_url = source_url
    document.downloaded_at = _utc_now()
    document.parsed_status = "Not Parsed"
    session.add(document)
    session.flush()
    session.refresh(document)

    summary["downloaded_count"] += 1
    summary["files"].append(_file_summary(document))


def _safe_filename(filename: str) -> str:
    name = Path(unquote(filename)).name
    cleaned = "".join(char if char.isalnum() or char in "._-" else "_" for char in name)
    cleaned = cleaned.strip("._")
    return cleaned or "document"


def _available_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem or "document"
    suffix = path.suffix
    for index in range(1, 1000):
        candidate = path.with_name(f"{stem}_{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not create a non-conflicting filename for {path.name}")


def _file_summary(document: Document) -> dict:
    return {
        "document_id": document.id,
        "filename": document.filename,
        "path": document.path,
        "source_url": document.source_url,
    }


def _empty_summary() -> dict:
    return {
        "downloaded_count": 0,
        "skipped_count": 0,
        "candidates_found": 0,
        "downloads_attempted": 0,
        "login_performed": False,
        "files": [],
        "errors": [],
    }


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
