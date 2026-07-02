"""Tiny key/value settings store backed by the AppSetting table.

Holds small, non-secret configuration values (e.g. the Notion database id).
Secrets such as API tokens are NEVER stored here; those live only in the OS
keychain via credential_store.
"""

from __future__ import annotations

from sqlmodel import Session

from app.models import AppSetting


def get_setting(session: Session, key: str) -> str | None:
    """Return the stored value for ``key``, or None if unset."""
    setting = session.get(AppSetting, key)
    return setting.value if setting is not None else None


def set_setting(session: Session, key: str, value: str | None) -> None:
    """Upsert ``value`` for ``key`` and commit."""
    setting = session.get(AppSetting, key)
    if setting is None:
        setting = AppSetting(key=key, value=value)
    else:
        setting.value = value
    session.add(setting)
    session.commit()
