"""Property-based test for role-based authorization guards.

Feature: coaching-programs, Property 20: Role authorization matches the required
role. For any coach-only action and any authenticated account, the action is
authorized exactly when the account's role is ``coach``; for any participant
action, it is authorized exactly when the role is ``user``; and for any account
whose role is absent or not one of ``coach``/``user``, the request is rejected
with HTTP 403.

Validates: Requirements 1.4, 3.6, 15.2, 15.3, 15.6
"""

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException, status
from hypothesis import given, settings
from hypothesis import strategies as st

from app.api.deps import require_coach, require_user
from app.models.user import Role, UserResponse

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _make_user(role) -> UserResponse:
    """
    Build a ``UserResponse`` carrying an arbitrary ``role`` value.

    ``model_construct`` is used deliberately so that absent (``None``) or
    garbage (arbitrary string / non-``Role``) role values can be placed on the
    response exactly as a backfilled, legacy, or corrupted record could surface
    them to the guards. This lets the test exercise the guard's own defensive
    checks rather than Pydantic's field coercion.
    """
    now = datetime.now(timezone.utc).isoformat()
    return UserResponse.model_construct(
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


# Reserved strings that collide with the real role values; excluded from the
# "garbage" space so a generated garbage role is genuinely neither known role.
_RESERVED = {Role.coach.value, Role.user.value}

# Valid roles, the absent role, and arbitrary garbage strings (never a real role).
_roles = st.one_of(
    st.sampled_from([Role.coach, Role.user]),
    st.none(),
    st.text().filter(lambda s: s not in _RESERVED),
)


# ──────────────────────────────────────────────────────────────────────────────
# Property 20
# ──────────────────────────────────────────────────────────────────────────────


@settings(max_examples=200)
@given(role=_roles)
def test_require_coach_authorizes_iff_role_is_coach(role):
    """
    Feature: coaching-programs, Property 20: Role authorization matches the
    required role.

    ``require_coach`` returns the authenticated user exactly when the resolved
    role is ``coach``; for every other value (the ``user`` role, an absent role,
    or any garbage role) it rejects with HTTP 403.

    Validates: Requirements 3.6, 15.2, 15.6
    """
    user = _make_user(role)

    if role == Role.coach:
        assert require_coach(user) is user
    else:
        with pytest.raises(HTTPException) as exc_info:
            require_coach(user)
        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


@settings(max_examples=200)
@given(role=_roles)
def test_require_user_authorizes_iff_role_is_user(role):
    """
    Feature: coaching-programs, Property 20: Role authorization matches the
    required role.

    ``require_user`` returns the authenticated user exactly when the resolved
    role is ``user``; for every other value (the ``coach`` role, an absent role,
    or any garbage role) it rejects with HTTP 403.

    Validates: Requirements 1.4, 15.3, 15.6
    """
    user = _make_user(role)

    if role == Role.user:
        assert require_user(user) is user
    else:
        with pytest.raises(HTTPException) as exc_info:
            require_user(user)
        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
