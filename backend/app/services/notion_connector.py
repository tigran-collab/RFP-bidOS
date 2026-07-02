"""Notion connector — sync opportunities to a user's Notion database.

Talks to the Notion REST API v1 with the `requests` library. The integration
token is a secret and lives ONLY in the OS keychain (via credential_store); the
target database id is a non-secret and lives in the AppSetting store. The token
is never written to the DB, logged, or returned from any read.

The HTTP callable is injected (default requests.request) so tests never touch
the network, and the module never calls the network at import time.

Dedup: for each opportunity we query the database for an existing page (matched
by "Solicitation Number" when that property exists, else by title). If found we
PATCH it, otherwise we POST a new page. Only properties that actually exist in
the database schema are set, mapped case-insensitively by name.
"""

from __future__ import annotations

from typing import Any, Callable

from sqlmodel import Session, select

import requests

from app.models import Opportunity
from app.services import credential_store
from app.services.settings_store import get_setting, set_setting

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

# Keychain reference + username for the integration token.
KEYRING_REF = "rfp-bidos:notion"
KEYRING_USERNAME = "notion"

# AppSetting key for the (non-secret) target database id.
DATABASE_ID_KEY = "notion_database_id"

# Default HTTP callable. Injected in tests. Signature mirrors requests.request.
HttpCallable = Callable[..., "requests.Response"]


def _get_token() -> str | None:
    return credential_store.get_password(KEYRING_REF, KEYRING_USERNAME)


def _get_database_id(session: Session) -> str | None:
    return get_setting(session, DATABASE_ID_KEY)


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def is_configured(session: Session) -> bool:
    """True when a token is present in the keychain AND a database id is set."""
    return bool(_get_token()) and bool(_get_database_id(session))


def notion_status(session: Session, http: HttpCallable = requests.request) -> dict:
    """Return a status dict; never includes the token.

    When configured, does a lightweight GET /databases/{id} to validate the
    token + access, reporting connection_ok true/false. When not configured,
    connection_ok is None and no network call is made.
    """
    database_id = _get_database_id(session)
    token = _get_token()
    has_token = bool(token)

    status: dict[str, Any] = {
        "configured": has_token and bool(database_id),
        "database_id": database_id,
        "connection_ok": None,
        "keyring_available": credential_store.is_available(),
        "message": "",
    }

    if not has_token and not database_id:
        status["message"] = "Notion is not configured. Add an integration token and database id."
        return status
    if not has_token:
        status["message"] = "Notion database id is set, but no integration token is stored."
        return status
    if not database_id:
        status["message"] = "An integration token is stored, but no database id is set."
        return status

    # Both present — validate against the API.
    try:
        response = http(
            "GET",
            f"{NOTION_API_BASE}/databases/{database_id}",
            headers=_headers(token),
            timeout=30,
        )
    except Exception as exc:  # network failure, etc.
        status["connection_ok"] = False
        status["message"] = f"Could not reach Notion: {exc}"
        return status

    if response.status_code == 200:
        status["connection_ok"] = True
        status["message"] = "Connected to the Notion database."
    else:
        status["connection_ok"] = False
        status["message"] = _error_message(response, "validate the Notion database")
    return status


def configure(
    session: Session,
    token: str,
    database_id: str,
    http: HttpCallable = requests.request,
) -> dict:
    """Store the token in the keychain and the database id in settings.

    Returns a status dict (never the token). Requires an available keychain so
    the secret is never persisted to the DB as a fallback.
    """
    token = (token or "").strip()
    database_id = (database_id or "").strip()
    if not token:
        return {
            "configured": False,
            "database_id": _get_database_id(session),
            "connection_ok": None,
            "keyring_available": credential_store.is_available(),
            "message": "An integration token is required.",
        }
    if not database_id:
        return {
            "configured": False,
            "database_id": None,
            "connection_ok": None,
            "keyring_available": credential_store.is_available(),
            "message": "A database id is required.",
        }
    if not credential_store.is_available():
        return {
            "configured": False,
            "database_id": _get_database_id(session),
            "connection_ok": None,
            "keyring_available": False,
            "message": (
                "OS keychain (keyring) is not available. Install it with "
                "`pip install keyring` so the token can be stored securely."
            ),
        }

    store_result = credential_store.set_password(KEYRING_REF, KEYRING_USERNAME, token)
    del token
    if not store_result["ok"]:
        return {
            "configured": False,
            "database_id": _get_database_id(session),
            "connection_ok": None,
            "keyring_available": credential_store.is_available(),
            "message": store_result["message"],
        }

    set_setting(session, DATABASE_ID_KEY, database_id)
    return notion_status(session, http=http)


def clear(session: Session) -> dict:
    """Delete the token from the keychain and clear the database id."""
    credential_store.delete_password(KEYRING_REF, KEYRING_USERNAME)
    set_setting(session, DATABASE_ID_KEY, None)
    return {
        "configured": False,
        "database_id": None,
        "connection_ok": None,
        "keyring_available": credential_store.is_available(),
        "message": "Notion configuration removed.",
    }


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------
# Opportunity attribute -> (Notion property name, preferred value kind).
# Value kind is a hint; the actual Notion property type from the DB schema wins
# and unsupported types are skipped.
_MAPPINGS: list[tuple[str, str]] = [
    ("agency", "Agency"),
    ("due_date", "Due Date"),
    ("review_status", "Status"),
    ("relevance_decision", "Relevance"),
    ("bid_score", "Score"),
    ("solicitation_number", "Solicitation Number"),
    ("source_url", "Source URL"),
]

# Notion property types this connector knows how to build a value for.
_SUPPORTED_TYPES = {"title", "rich_text", "date", "select", "number", "url"}


def _error_message(response: "requests.Response", action: str) -> str:
    detail = ""
    try:
        payload = response.json()
        detail = payload.get("message") or payload.get("code") or ""
    except Exception:
        detail = (response.text or "")[:200]
    suffix = f": {detail}" if detail else ""
    return f"Notion API returned {response.status_code} trying to {action}{suffix}"


def _schema_property_index(schema: dict) -> dict[str, dict]:
    """Map lowercased property name -> property definition (with 'name'/'type')."""
    props = schema.get("properties") or {}
    index: dict[str, dict] = {}
    for name, definition in props.items():
        if isinstance(definition, dict):
            entry = dict(definition)
            entry.setdefault("name", name)
            index[name.strip().lower()] = entry
    return index


def _title_property_name(schema: dict) -> str | None:
    for name, definition in (schema.get("properties") or {}).items():
        if isinstance(definition, dict) and definition.get("type") == "title":
            return name
    return None


def _priority_value(opp: Opportunity) -> str | None:
    return opp.priority_tier or opp.priority


def _to_text(value: Any) -> str:
    return "" if value is None else str(value)


def _build_property_value(prop_type: str, value: Any) -> dict | None:
    """Build a Notion property value for a supported type, or None to skip."""
    if value is None:
        return None
    if prop_type == "title":
        text = _to_text(value)
        return {"title": [{"text": {"content": text[:2000]}}]}
    if prop_type == "rich_text":
        text = _to_text(value)
        return {"rich_text": [{"text": {"content": text[:2000]}}]}
    if prop_type == "date":
        iso = value.isoformat() if hasattr(value, "isoformat") else _to_text(value)
        if not iso:
            return None
        return {"date": {"start": iso}}
    if prop_type == "select":
        text = _to_text(value).strip()
        if not text:
            return None
        return {"select": {"name": text[:100]}}
    if prop_type == "number":
        try:
            return {"number": float(value)}
        except (TypeError, ValueError):
            return None
    if prop_type == "url":
        text = _to_text(value).strip()
        if not text:
            return None
        return {"url": text}
    return None


def _build_properties(opp: Opportunity, schema_index: dict[str, dict], title_name: str | None) -> dict:
    """Map an opportunity to Notion properties present in the DB schema."""
    properties: dict[str, dict] = {}

    # Title always maps to whatever the DB's title property is called.
    if title_name:
        title_value = _build_property_value("title", opp.title)
        if title_value is not None:
            properties[title_name] = title_value

    # Values keyed by the attribute name used in _MAPPINGS.
    values: dict[str, Any] = {
        "agency": opp.agency,
        "due_date": opp.due_date,
        "review_status": opp.review_status,
        "relevance_decision": opp.relevance_decision,
        "bid_score": opp.bid_score,
        "solicitation_number": opp.solicitation_number,
        "source_url": opp.source_url,
    }

    for attr, prop_name in _MAPPINGS:
        definition = schema_index.get(prop_name.strip().lower())
        if definition is None:
            continue
        prop_type = definition.get("type")
        actual_name = definition.get("name", prop_name)
        if prop_type not in _SUPPORTED_TYPES or prop_type == "title":
            continue
        built = _build_property_value(prop_type, values.get(attr))
        if built is not None:
            properties[actual_name] = built

    # Priority maps from priority_tier or priority, if a "Priority" prop exists.
    priority_def = schema_index.get("priority")
    if priority_def is not None:
        prop_type = priority_def.get("type")
        if prop_type in _SUPPORTED_TYPES and prop_type != "title":
            built = _build_property_value(prop_type, _priority_value(opp))
            if built is not None:
                properties[priority_def.get("name", "Priority")] = built

    return properties


def _find_existing_page(
    http: HttpCallable,
    token: str,
    database_id: str,
    opp: Opportunity,
    schema_index: dict[str, dict],
    title_name: str | None,
) -> str | None:
    """Return the page id of an existing matching page, or None.

    Prefers matching by "Solicitation Number" (rich_text) when the property
    exists and the opportunity has one; otherwise matches by title text.
    """
    filter_body: dict | None = None
    sol_def = schema_index.get("solicitation number")
    if sol_def is not None and sol_def.get("type") == "rich_text" and opp.solicitation_number:
        filter_body = {
            "property": sol_def.get("name", "Solicitation Number"),
            "rich_text": {"equals": opp.solicitation_number},
        }
    elif title_name and opp.title:
        filter_body = {
            "property": title_name,
            "title": {"equals": opp.title},
        }

    if filter_body is None:
        return None

    response = http(
        "POST",
        f"{NOTION_API_BASE}/databases/{database_id}/query",
        headers=_headers(token),
        json={"filter": filter_body, "page_size": 1},
        timeout=30,
    )
    if response.status_code != 200:
        raise RuntimeError(_error_message(response, "query the Notion database"))
    results = (response.json() or {}).get("results") or []
    if results:
        return results[0].get("id")
    return None


def sync_opportunities(
    session: Session,
    opportunity_ids: list[int] | None = None,
    status: str | None = None,
    limit: int = 200,
    http: HttpCallable = requests.request,
) -> dict:
    """Sync selected opportunities to the Notion database, with dedup.

    Selection: by explicit ids, else by review_status, else all not Archived.
    Bounded by ``limit``. Never crashes the batch — per-opportunity errors are
    caught and collected. Returns created/updated/skipped/errors/synced_ids.
    """
    result: dict[str, Any] = {
        "created": 0,
        "updated": 0,
        "skipped": 0,
        "errors": [],
        "synced_ids": [],
    }

    if not is_configured(session):
        result["message"] = (
            "Notion is not configured. Add an integration token and database id first."
        )
        return result

    token = _get_token()
    database_id = _get_database_id(session)

    # Fetch the schema once so we only set properties that exist.
    try:
        schema_response = http(
            "GET",
            f"{NOTION_API_BASE}/databases/{database_id}",
            headers=_headers(token),
            timeout=30,
        )
    except Exception as exc:
        result["message"] = f"Could not reach Notion: {exc}"
        return result
    if schema_response.status_code != 200:
        result["message"] = _error_message(schema_response, "load the Notion database schema")
        return result
    schema = schema_response.json() or {}
    schema_index = _schema_property_index(schema)
    title_name = _title_property_name(schema)

    # Select opportunities.
    statement = select(Opportunity)
    if opportunity_ids:
        statement = statement.where(Opportunity.id.in_(opportunity_ids))
    elif status:
        statement = statement.where(Opportunity.review_status == status)
    else:
        statement = statement.where(Opportunity.review_status != "Archived")
    opportunities = list(session.exec(statement).all())
    if limit and limit > 0:
        opportunities = opportunities[:limit]

    for opp in opportunities:
        try:
            properties = _build_properties(opp, schema_index, title_name)
            if not properties:
                result["skipped"] += 1
                result["errors"].append(
                    f"[{opp.id}] {opp.title}: no matching Notion properties to set."
                )
                continue

            page_id = _find_existing_page(
                http, token, database_id, opp, schema_index, title_name
            )

            if page_id:
                response = http(
                    "PATCH",
                    f"{NOTION_API_BASE}/pages/{page_id}",
                    headers=_headers(token),
                    json={"properties": properties},
                    timeout=30,
                )
                if response.status_code == 200:
                    result["updated"] += 1
                    result["synced_ids"].append(opp.id)
                else:
                    result["errors"].append(
                        f"[{opp.id}] {opp.title}: "
                        + _error_message(response, "update the Notion page")
                    )
            else:
                response = http(
                    "POST",
                    f"{NOTION_API_BASE}/pages",
                    headers=_headers(token),
                    json={
                        "parent": {"database_id": database_id},
                        "properties": properties,
                    },
                    timeout=30,
                )
                if response.status_code == 200:
                    result["created"] += 1
                    result["synced_ids"].append(opp.id)
                else:
                    result["errors"].append(
                        f"[{opp.id}] {opp.title}: "
                        + _error_message(response, "create the Notion page")
                    )
        except Exception as exc:  # noqa: BLE001 — never crash the batch
            result["errors"].append(f"[{opp.id}] {opp.title}: {exc}")

    result["message"] = (
        f"{result['created']} created, {result['updated']} updated, "
        f"{result['skipped']} skipped, {len(result['errors'])} error(s)."
    )
    return result
