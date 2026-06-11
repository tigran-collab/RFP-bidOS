import os
from datetime import UTC, datetime

from app.models import SourceConfig

AUTH_STATUS_NOT_REQUIRED = "Not Required"
AUTH_STATUS_NOT_CONFIGURED = "Not Configured"
AUTH_STATUS_CONFIGURED = "Configured"
AUTH_STATUS_NEEDS_REVIEW = "Needs Review"
AUTH_STATUS_UNSUPPORTED = "Unsupported This Phase"

CREDENTIAL_TYPE_MANUAL = "Manual"
CREDENTIAL_TYPE_ENVIRONMENT = "Environment"
CREDENTIAL_TYPE_FUTURE_SECRET_STORE = "Future Secret Store"


def get_source_auth_status(source_config: SourceConfig) -> dict:
    if not source_config.requires_credentials:
        return _status(source_config, AUTH_STATUS_NOT_REQUIRED, [])

    credential_type = _normalized_credential_type(source_config.credential_type)
    if credential_type == CREDENTIAL_TYPE_ENVIRONMENT:
        return check_environment_credentials(source_config)

    if credential_type == CREDENTIAL_TYPE_FUTURE_SECRET_STORE:
        missing = []
        if not source_config.credential_secret_ref:
            missing.append("credential_secret_ref missing")
        status = AUTH_STATUS_CONFIGURED if not missing else AUTH_STATUS_NOT_CONFIGURED
        return _status(source_config, status, missing)

    if credential_type == CREDENTIAL_TYPE_MANUAL:
        missing = []
        if not source_config.credential_username:
            missing.append("credential_username missing")
        if not source_config.credential_notes:
            missing.append("credential_notes missing")
        status = AUTH_STATUS_NEEDS_REVIEW if missing else AUTH_STATUS_CONFIGURED
        return _status(source_config, status, missing)

    return _status(
        source_config,
        AUTH_STATUS_NOT_CONFIGURED,
        ["credential_type missing"],
    )


def check_environment_credentials(source_config: SourceConfig) -> dict:
    username_var, password_var = _environment_variable_names(source_config)
    missing = []
    username_present = bool(os.getenv(username_var))
    password_present = bool(os.getenv(password_var))

    if not username_present:
        missing.append(f"{username_var} missing")
    if not password_present:
        missing.append(f"{password_var} missing")

    status = AUTH_STATUS_CONFIGURED if username_present and password_present else AUTH_STATUS_NOT_CONFIGURED
    return {
        **_status(source_config, status, missing),
        "environment_username_var": username_var,
        "environment_password_var": password_var,
        "environment_username_present": username_present,
        "environment_password_present": password_present,
    }


def update_source_auth_status(source_id: int, session) -> dict:
    source = session.get(SourceConfig, source_id)
    if source is None:
        return {"error": "Source not found"}

    result = get_source_auth_status(source)
    source.auth_status = result["auth_status"]
    source.auth_last_checked_at = _utc_now()
    session.add(source)
    session.commit()
    session.refresh(source)
    result["auth_last_checked_at"] = source.auth_last_checked_at.isoformat()
    return result


def _status(source_config: SourceConfig, auth_status: str, missing_fields: list[str]) -> dict:
    return {
        "source_id": source_config.id,
        "source_name": source_config.name,
        "requires_credentials": source_config.requires_credentials,
        "credential_type": source_config.credential_type,
        "credential_username": source_config.credential_username,
        "credential_secret_ref": source_config.credential_secret_ref,
        "credential_notes": source_config.credential_notes,
        "auth_status": auth_status,
        "auth_last_checked_at": (
            source_config.auth_last_checked_at.isoformat()
            if source_config.auth_last_checked_at
            else None
        ),
        "missing_fields": missing_fields,
        "message": _message(auth_status, missing_fields),
    }


def _message(auth_status: str, missing_fields: list[str]) -> str:
    if auth_status == AUTH_STATUS_CONFIGURED:
        return "Credential references are configured for future authenticated access."
    if auth_status == AUTH_STATUS_NOT_REQUIRED:
        return "This source does not require credentials."
    if missing_fields:
        return f"Missing safe credential fields: {', '.join(missing_fields)}"
    return "Credential configuration needs review."


def _environment_variable_names(source_config: SourceConfig) -> tuple[str, str]:
    name = f"{source_config.name} {source_config.base_url or ''}".lower()
    if "bidnet" in name:
        return "BIDNET_USERNAME", "BIDNET_PASSWORD"

    prefix_source = source_config.name or "SOURCE"
    prefix = "".join(char if char.isalnum() else "_" for char in prefix_source.upper())
    while "__" in prefix:
        prefix = prefix.replace("__", "_")
    prefix = prefix.strip("_") or "SOURCE"
    return f"{prefix}_USERNAME", f"{prefix}_PASSWORD"


def _normalized_credential_type(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().replace("_", " ").replace("-", " ").lower()
    if normalized == "manual":
        return CREDENTIAL_TYPE_MANUAL
    if normalized == "environment":
        return CREDENTIAL_TYPE_ENVIRONMENT
    if normalized in {"future secret store", "future secretstore"}:
        return CREDENTIAL_TYPE_FUTURE_SECRET_STORE
    return value


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
