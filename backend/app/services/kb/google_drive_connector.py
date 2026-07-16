"""Google Drive connector — import files into the KB Source Document Vault.

Talks to the Google Drive API v3 with the ``requests`` library. OAuth secrets
(access token, and optionally a refresh token + client id/secret for auto-refresh)
are stored ONLY in the OS keychain (via credential_store) as a JSON blob; the
non-secret target folder id lives in the AppSetting store. Tokens are never
written to the DB, logged, or returned from any read.

The HTTP callable is injected (default ``requests.request``) so tests never
touch the network, and the module never calls the network at import time.

This app cannot perform the interactive Google OAuth consent flow itself — the
user obtains an OAuth access token (and optional refresh token + client
credentials) out of band and supplies them here; the connector stores them and
uses them to list and download files. Imported files run through the same vault
validation (extension + size + MIME) and processing pipeline as uploads.
"""

from __future__ import annotations

import json
from re import sub
from typing import Any, Callable

import requests
from sqlmodel import Session

from app.services import credential_store
from app.services.kb import documents as kb_documents
from app.services.kb import processing as kb_processing
from app.services.settings_store import get_setting, set_setting

DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

KEYRING_REF = "rfp-bidos:gdrive"
KEYRING_USERNAME = "gdrive"
FOLDER_ID_KEY = "gdrive_folder_id"

# Google-native types must be exported to a downloadable format.
GOOGLE_EXPORT: dict[str, tuple[str, str]] = {
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "docx",
    ),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "xlsx",
    ),
    "application/vnd.google-apps.presentation": ("application/pdf", "pdf"),
}

HttpCallable = Callable[..., "requests.Response"]


# --- credential storage ------------------------------------------------------


def _load_creds() -> dict:
    raw = credential_store.get_password(KEYRING_REF, KEYRING_USERNAME)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def _store_creds(creds: dict) -> dict:
    return credential_store.set_password(
        KEYRING_REF, KEYRING_USERNAME, json.dumps(creds)
    )


def _folder_id(session: Session) -> str | None:
    return get_setting(session, FOLDER_ID_KEY)


def is_configured() -> bool:
    return bool(_load_creds().get("access_token"))


def get_status(session: Session) -> dict:
    """Config status for the UI. NEVER includes any token or secret."""
    creds = _load_creds()
    return {
        "configured": bool(creds.get("access_token")),
        "folder_id": _folder_id(session),
        "has_refresh": bool(
            creds.get("refresh_token") and creds.get("client_id") and creds.get("client_secret")
        ),
        "keychain_available": credential_store.is_available(),
    }


def configure(session: Session, payload: dict) -> dict:
    """Store/merge OAuth secrets (keychain) + folder id (AppSetting).

    ``payload`` may contain access_token, refresh_token, client_id,
    client_secret, folder_id. An access token is required to become configured.
    Returns status (never any secret).
    """
    if not credential_store.is_available():
        raise DriveConfigError(
            "OS keychain is not available. Install keyring so the token can be "
            "stored securely."
        )
    creds = _load_creds()
    for field in ("access_token", "refresh_token", "client_id", "client_secret"):
        value = (payload.get(field) or "").strip()
        if value:
            creds[field] = value
    if not creds.get("access_token"):
        raise DriveConfigError("A Google OAuth access token is required.")
    result = _store_creds(creds)
    if not result.get("ok"):
        raise DriveConfigError(result.get("message") or "Could not store the token.")
    if "folder_id" in payload:
        set_setting(session, FOLDER_ID_KEY, (payload.get("folder_id") or "").strip() or None)
    return get_status(session)


def clear(session: Session) -> dict:
    credential_store.delete_password(KEYRING_REF, KEYRING_USERNAME)
    set_setting(session, FOLDER_ID_KEY, None)
    return get_status(session)


class DriveConfigError(RuntimeError):
    status_code = 400


class DriveError(RuntimeError):
    status_code = 502


# --- authenticated requests (with refresh-on-401) ----------------------------


def _refresh_access_token(http: HttpCallable) -> str | None:
    """Refresh the access token using the stored refresh token, if possible.

    Returns the new access token (also persisted) or None when refresh is not
    configured / fails.
    """
    creds = _load_creds()
    if not (creds.get("refresh_token") and creds.get("client_id") and creds.get("client_secret")):
        return None
    try:
        resp = http(
            "POST",
            GOOGLE_TOKEN_URL,
            data={
                "client_id": creds["client_id"],
                "client_secret": creds["client_secret"],
                "refresh_token": creds["refresh_token"],
                "grant_type": "refresh_token",
            },
            timeout=30,
        )
    except Exception:
        return None
    if resp.status_code != 200:
        return None
    token = (resp.json() or {}).get("access_token")
    if not token:
        return None
    creds["access_token"] = token
    _store_creds(creds)
    return token


def _authed(http: HttpCallable, method: str, url: str, **kwargs) -> "requests.Response":
    """Make an authed Drive request; on 401 refresh the token once and retry."""
    creds = _load_creds()
    token = creds.get("access_token")
    if not token:
        raise DriveConfigError("Google Drive is not configured.")
    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = http(method, url, headers=headers, timeout=30, **kwargs)
    except Exception as exc:
        raise DriveError(f"Could not reach Google Drive: {exc}") from exc
    if resp.status_code == 401:
        new_token = _refresh_access_token(http)
        if new_token:
            headers = {"Authorization": f"Bearer {new_token}"}
            try:
                resp = http(method, url, headers=headers, timeout=30, **kwargs)
            except Exception as exc:
                raise DriveError(f"Could not reach Google Drive: {exc}") from exc
    return resp


def _error_message(resp: "requests.Response", action: str) -> str:
    detail = ""
    try:
        payload = resp.json()
        detail = (payload.get("error") or {}).get("message") or ""
    except Exception:
        detail = (getattr(resp, "text", "") or "")[:200]
    if resp.status_code == 401:
        return (
            f"Google Drive rejected the access token while trying to {action} "
            "(401). The token may be expired — reconfigure it."
        )
    suffix = f": {detail}" if detail else ""
    return f"Google Drive API returned {resp.status_code} trying to {action}{suffix}"


# --- listing + import --------------------------------------------------------


def list_files(
    session: Session,
    folder_id: str | None = None,
    http: HttpCallable = requests.request,
) -> dict:
    """List non-trashed files in the configured (or given) folder."""
    if not is_configured():
        return {"files": [], "error": "Google Drive is not configured."}
    folder = folder_id or _folder_id(session)
    if folder:
        query = f"'{folder}' in parents and trashed = false"
    else:
        query = "trashed = false and mimeType != 'application/vnd.google-apps.folder'"
    resp = _authed(
        http,
        "GET",
        f"{DRIVE_API_BASE}/files",
        params={
            "q": query,
            "fields": "files(id,name,mimeType,size,modifiedTime)",
            "pageSize": 100,
            "orderBy": "modifiedTime desc",
        },
    )
    if resp.status_code != 200:
        return {"files": [], "error": _error_message(resp, "list files")}
    files = (resp.json() or {}).get("files") or []
    return {"files": files, "folder_id": folder}


def _download_bytes(file_id: str, mime_type: str, http: HttpCallable) -> tuple[bytes, str, str]:
    """Download (or export) a Drive file. Returns (content, extension, mime)."""
    if mime_type in GOOGLE_EXPORT:
        target_mime, ext = GOOGLE_EXPORT[mime_type]
        resp = _authed(
            http, "GET", f"{DRIVE_API_BASE}/files/{file_id}/export",
            params={"mimeType": target_mime},
        )
        if resp.status_code != 200:
            raise DriveError(_error_message(resp, "export the Google document"))
        return resp.content, ext, target_mime
    resp = _authed(
        http, "GET", f"{DRIVE_API_BASE}/files/{file_id}", params={"alt": "media"}
    )
    if resp.status_code != 200:
        raise DriveError(_error_message(resp, "download the file"))
    return resp.content, "", mime_type


def _safe_name(name: str, ext: str) -> str:
    cleaned = sub(r"[^A-Za-z0-9._-]+", "_", name or "").strip("._") or "drive_file"
    if ext and not cleaned.lower().endswith(f".{ext}"):
        cleaned = f"{cleaned}.{ext}"
    return cleaned


def import_files(
    session: Session,
    actor,
    file_ids: list[str],
    *,
    company_entity_id: int | None = None,
    http: HttpCallable = requests.request,
) -> dict:
    """Import selected Drive files into the vault and queue processing.

    Each file is downloaded (Google-native docs are exported to docx/xlsx/pdf)
    and passed through ``documents.create_document`` — which enforces the vault's
    extension/size/MIME validation and the uploader permission. Never crashes the
    batch; per-file errors are collected.
    """
    result: dict[str, Any] = {"imported": 0, "skipped": 0, "errors": [], "documents": []}
    if not is_configured():
        result["error"] = "Google Drive is not configured."
        return result

    for file_id in file_ids:
        try:
            meta = _authed(
                http, "GET", f"{DRIVE_API_BASE}/files/{file_id}",
                params={"fields": "id,name,mimeType"},
            )
            if meta.status_code != 200:
                result["errors"].append(f"{file_id}: {_error_message(meta, 'read file metadata')}")
                continue
            info = meta.json() or {}
            name = info.get("name") or file_id
            mime_type = info.get("mimeType") or ""

            if mime_type.startswith("application/vnd.google-apps.") and mime_type not in GOOGLE_EXPORT:
                result["skipped"] += 1
                result["errors"].append(f"{name}: unsupported Google Drive type '{mime_type}'.")
                continue

            content, ext, target_mime = _download_bytes(file_id, mime_type, http)
            filename = _safe_name(name, ext)
            doc = kb_documents.create_document(
                session, actor, filename=filename, content=content,
                metadata={
                    "company_entity_id": company_entity_id,
                    "mime_type": target_mime,
                    "notes": f"Imported from Google Drive (file id {file_id}).",
                },
            )
            result["imported"] += 1
            result["documents"].append({"id": doc.id, "filename": doc.filename})
            kb_processing.enqueue_processing(doc.id)
        except kb_documents.KbDocumentError as exc:
            result["skipped"] += 1
            result["errors"].append(f"{file_id}: {exc}")
        except DriveError as exc:
            result["errors"].append(f"{file_id}: {exc}")
        except Exception as exc:  # noqa: BLE001 — never crash the batch
            result["errors"].append(f"{file_id}: {exc}")

    return result
