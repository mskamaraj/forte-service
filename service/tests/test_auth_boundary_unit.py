"""Unit tests for the auth 401 boundary and the 403 role body.

Feature: coaching-programs — EXAMPLE criteria for the authentication/authorization
boundary that the property test (Property 20) does not pin down with concrete
values:

* ``get_current_user`` rejects a missing, malformed, expired, or bad-signature
  bearer token with HTTP 401 (Requirement 15.4).
* ``require_coach`` / ``require_user`` reject a not-permitted role with HTTP 403
  and a response body that names the account's own role (Requirement 15.5).

These are example-based unit tests; the universal "authorize iff the role
matches" behaviour is covered by ``test_role_authorization_property.py``.

Validates: Requirements 15.4, 15.5
"""

from datetime import datetime, timedelta, timezone
from unittest import mock

import jwt
import pytest
from fastapi import HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials

from app.api import deps
from app.api.deps import get_current_user, require_coach, require_user
from app.models.user import Role, UserRecord, UserResponse

# A throwaway secret used only to mint the tokens the 401 tests feed in; the real
# signing secret lives in SSM and is never touched here.
_TEST_SECRET = "unit-test-signing-secret"
_WRONG_SECRET = "a-different-secret-entirely"
_ALGORITHM = "HS256"


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _credentials(token: str) -> HTTPAuthorizationCredentials:
    """Wrap a raw token the way ``HTTPBearer`` would hand it to the dependency."""
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def _mint(secret: str, *, sub: str = "u-123", expires_in_seconds: int = 3600) -> str:
    """Sign a JWT with ``secret`` and the given expiry offset (may be negative)."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": sub,
        "email": "person@example.com",
        "iat": now,
        "exp": now + timedelta(seconds=expires_in_seconds),
    }
    return jwt.encode(payload, secret, algorithm=_ALGORITHM)


def _active_record(role: Role = Role.user) -> UserRecord:
    now = datetime.now(timezone.utc).isoformat()
    return UserRecord(
        user_id="u-123",
        email="person@example.com",
        password_hash="x",
        first_name="Pat",
        last_name="Doe",
        role=role,
        is_active=True,
        is_verified=True,
        created_at=now,
        updated_at=now,
    )


def _make_user(role: Role) -> UserResponse:
    now = datetime.now(timezone.utc).isoformat()
    return UserResponse(
        user_id="u-123",
        email="person@example.com",
        first_name="Pat",
        last_name="Doe",
        role=role,
        is_active=True,
        is_verified=True,
        created_at=now,
        updated_at=now,
    )


@pytest.fixture(autouse=True)
def _signing_secret(monkeypatch):
    """
    Point ``decode_access_token`` at the test secret so the 401 tests can mint
    tokens without reaching SSM. ``get_current_user`` imports the symbol into
    its own module, so patch it there.
    """
    monkeypatch.setattr(
        deps,
        "decode_access_token",
        lambda token: jwt.decode(token, _TEST_SECRET, algorithms=[_ALGORITHM]),
    )


# ──────────────────────────────────────────────────────────────────────────────
# 401 boundary — get_current_user (Requirement 15.4)
# ──────────────────────────────────────────────────────────────────────────────


def test_missing_token_is_401():
    """An empty/absent bearer credential is rejected with 401."""
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(credentials=_credentials(""))
    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED


def test_malformed_token_is_401():
    """A token that is not a well-formed JWT is rejected with 401."""
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(credentials=_credentials("not-a-jwt"))
    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED


def test_expired_token_is_401():
    """A correctly-signed but expired token is rejected with 401."""
    expired = _mint(_TEST_SECRET, expires_in_seconds=-60)
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(credentials=_credentials(expired))
    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED


def test_bad_signature_token_is_401():
    """A token signed with the wrong secret is rejected with 401."""
    forged = _mint(_WRONG_SECRET)
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(credentials=_credentials(forged))
    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED


def test_valid_token_but_unknown_user_is_401():
    """A valid token whose subject no longer exists is rejected with 401."""
    valid = _mint(_TEST_SECRET)
    with mock.patch.object(deps, "UserRepository") as repo_cls:
        repo_cls.return_value.get_by_id.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            get_current_user(credentials=_credentials(valid))
    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED


def test_valid_token_for_active_user_returns_that_user():
    """A valid token for an active account resolves to that user (role surfaced)."""
    valid = _mint(_TEST_SECRET)
    with mock.patch.object(deps, "UserRepository") as repo_cls:
        repo_cls.return_value.get_by_id.return_value = _active_record(Role.coach)
        result = get_current_user(credentials=_credentials(valid))
    assert result.user_id == "u-123"
    assert result.role == Role.coach


# ──────────────────────────────────────────────────────────────────────────────
# 403 role body — require_coach / require_user (Requirement 15.5)
# ──────────────────────────────────────────────────────────────────────────────


def test_coach_only_action_by_user_is_403_naming_role():
    """A ``user`` hitting a coach-only action gets 403 whose body names 'user'."""
    with pytest.raises(HTTPException) as exc_info:
        require_coach(user=_make_user(Role.user))

    exc = exc_info.value
    assert exc.status_code == status.HTTP_403_FORBIDDEN
    # Body names the account's own role so the caller sees why it was refused.
    assert "user" in exc.detail
    assert "coach" in exc.detail  # also names the role the action requires


def test_user_only_action_by_coach_is_403_naming_role():
    """A ``coach`` hitting a user-only action gets 403 whose body names 'coach'."""
    with pytest.raises(HTTPException) as exc_info:
        require_user(user=_make_user(Role.coach))

    exc = exc_info.value
    assert exc.status_code == status.HTTP_403_FORBIDDEN
    assert "coach" in exc.detail
    assert "user" in exc.detail  # also names the role the action requires


def test_absent_role_is_403():
    """An account with no resolvable role is refused with 403."""
    user = UserResponse.model_construct(
        user_id="u-123",
        email="person@example.com",
        first_name="Pat",
        last_name="Doe",
        role=None,
        is_active=True,
        is_verified=True,
        created_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    with pytest.raises(HTTPException) as exc_info:
        require_coach(user=user)
    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


def test_garbage_role_is_403():
    """An account whose role is an unrecognized value is refused with 403."""
    user = UserResponse.model_construct(
        user_id="u-123",
        email="person@example.com",
        first_name="Pat",
        last_name="Doe",
        role="superadmin",
        is_active=True,
        is_verified=True,
        created_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    with pytest.raises(HTTPException) as exc_info:
        require_user(user=user)
    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
