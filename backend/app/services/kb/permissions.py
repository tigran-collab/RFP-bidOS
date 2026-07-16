"""Role-based access control for the Knowledge Base.

The app is local-first with no login, so the acting user is resolved from the
``X-KB-User-Id`` request header (or an explicit id in service/CLI calls) and
permissions are enforced server-side from that user's role. When no user is
supplied, the seeded administrator is used so a single-user local install works
out of the box. This is the documented tradeoff versus a full auth system.
"""

from __future__ import annotations

from sqlmodel import Session, select

from app.kb_models import KbUser
from app.kb_vocab import (
    PERM_VIEW_RESTRICTED,
    ROLE_ADMIN,
    ROLE_READ_ONLY,
    role_has_permission,
)


class KbAuthError(RuntimeError):
    """Acting user could not be resolved (missing/unknown/inactive user)."""

    status_code = 401


class KbPermissionError(RuntimeError):
    """Acting user's role lacks the required permission."""

    status_code = 403

    def __init__(self, permission: str, role: str | None):
        self.permission = permission
        self.role = role
        super().__init__(
            f"Role '{role or 'unknown'}' is not permitted to: {permission}"
        )


def resolve_acting_user(
    session: Session, user_id: int | None, *, required: bool = True
) -> KbUser | None:
    """Return the acting KbUser.

    ``user_id`` typically comes from the ``X-KB-User-Id`` header. When it is
    None, fall back to the first active administrator (single-user default).
    Raises ``KbAuthError`` when ``required`` and no valid user can be resolved.
    """
    if user_id is not None:
        user = session.get(KbUser, user_id)
        if user is None:
            raise KbAuthError(f"Knowledge-base user {user_id} not found")
        if not user.active:
            raise KbAuthError(f"Knowledge-base user {user_id} is inactive")
        return user

    admin = session.exec(
        select(KbUser).where(KbUser.role == ROLE_ADMIN, KbUser.active == True)  # noqa: E712
    ).first()
    if admin is not None:
        return admin

    any_user = session.exec(
        select(KbUser).where(KbUser.active == True)  # noqa: E712
    ).first()
    if any_user is not None:
        return any_user

    if required:
        raise KbAuthError(
            "No knowledge-base users exist. Run `kb-seed` to create the default users."
        )
    return None


def has_permission(user: KbUser | None, permission: str) -> bool:
    if user is None:
        return False
    return role_has_permission(user.role, permission)


def require_permission(user: KbUser | None, permission: str) -> KbUser:
    """Raise ``KbPermissionError`` unless ``user`` holds ``permission``."""
    if user is None:
        raise KbAuthError("No acting user")
    if not role_has_permission(user.role, permission):
        raise KbPermissionError(permission, user.role)
    return user


def can_view_restricted(user: KbUser | None) -> bool:
    return has_permission(user, PERM_VIEW_RESTRICTED)


def is_read_only(user: KbUser | None) -> bool:
    return user is not None and user.role == ROLE_READ_ONLY
