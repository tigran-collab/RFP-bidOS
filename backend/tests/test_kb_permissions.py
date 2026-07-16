"""Role-based access control: permission matrix + acting-user resolution."""

import pytest

from app.kb_models import KbUser
from app.kb_vocab import (
    PERM_APPROVE_CLAIMS,
    PERM_DRAFT_RESPONSES,
    PERM_MANAGE_USERS,
    PERM_UPLOAD_DOCUMENTS,
    ROLE_ADMIN,
    ROLE_PROPOSAL_WRITER,
    ROLE_READ_ONLY,
    ROLE_REVIEWER,
    role_has_permission,
)
from app.services.kb import permissions
from tests.kb_factories import make_admin, make_reader, make_user


def test_admin_has_all_permissions():
    for perm in (PERM_APPROVE_CLAIMS, PERM_MANAGE_USERS, PERM_UPLOAD_DOCUMENTS):
        assert role_has_permission(ROLE_ADMIN, perm)


def test_read_only_has_no_mutating_permissions():
    assert not role_has_permission(ROLE_READ_ONLY, PERM_UPLOAD_DOCUMENTS)
    assert not role_has_permission(ROLE_READ_ONLY, PERM_APPROVE_CLAIMS)


def test_reviewer_can_approve_not_manage_users():
    assert role_has_permission(ROLE_REVIEWER, PERM_APPROVE_CLAIMS)
    assert not role_has_permission(ROLE_REVIEWER, PERM_MANAGE_USERS)


def test_writer_can_draft_not_approve():
    assert role_has_permission(ROLE_PROPOSAL_WRITER, PERM_DRAFT_RESPONSES)
    assert not role_has_permission(ROLE_PROPOSAL_WRITER, PERM_APPROVE_CLAIMS)


def test_require_permission_raises_for_read_only(session):
    reader = make_reader(session)
    with pytest.raises(permissions.KbPermissionError):
        permissions.require_permission(reader, PERM_UPLOAD_DOCUMENTS)


def test_resolve_acting_user_defaults_to_admin(session):
    admin = make_admin(session)
    resolved = permissions.resolve_acting_user(session, None)
    assert resolved.id == admin.id


def test_resolve_unknown_user_raises(session):
    make_admin(session)
    with pytest.raises(permissions.KbAuthError):
        permissions.resolve_acting_user(session, 9999)


def test_resolve_inactive_user_raises(session):
    user = make_user(session, role="reviewer")
    user.active = False
    session.add(user)
    session.commit()
    with pytest.raises(permissions.KbAuthError):
        permissions.resolve_acting_user(session, user.id)


def test_resolve_no_users_raises(session):
    with pytest.raises(permissions.KbAuthError):
        permissions.resolve_acting_user(session, None)
