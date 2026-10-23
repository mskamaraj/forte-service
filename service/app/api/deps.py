"""Reusable FastAPI dependencies."""

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import decode_access_token
from app.models.user import Role, UserResponse
from app.repositories.user_repository import UserRepository
from app.services.auth_service import _to_user_response

# Parses the "Authorization: Bearer <token>" header
_bearer = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> UserResponse:
    """
    Validate the Bearer token and return the authenticated user.

    Raises 401 if the token is missing, invalid, expired, or the user
    no longer exists.
    """
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.PyJWTError:
        raise invalid

    user_id = payload.get("sub")
    if not user_id:
        raise invalid

    record = UserRepository().get_by_id(user_id)
    if record is None or not record.is_active:
        raise invalid

    return _to_user_response(record)


def _require_role(user: UserResponse, required: Role) -> UserResponse:
    """
    Authorize `user` for an action restricted to `required`.

    Raises 403 when the resolved role is absent, not one of the known roles
    ({coach, user}), or does not match the required role. The error body names
    the account's role so the caller can see why the request was refused.
    """
    role = user.role

    # Role absent or not a recognised value → 403 (Requirement 15.6).
    if role is None or role not in (Role.coach, Role.user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account role is missing or unrecognized; this action is not permitted",
        )

    # Valid role but not the one this action requires → 403 (Requirements 15.2, 15.3, 15.5).
    if role != required:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"This action requires the '{required.value}' role, "
                f"but your account's role is '{role.value}'"
            ),
        )

    return user


def require_coach(
    user: UserResponse = Depends(get_current_user),
) -> UserResponse:
    """
    Authorize a coach-only action.

    Depends on `get_current_user`, so a missing/invalid/expired token yields 401
    first. Raises 403 when the account's role is not `coach` (Requirements 15.2,
    15.5, 15.6).
    """
    return _require_role(user, Role.coach)


def require_user(
    user: UserResponse = Depends(get_current_user),
) -> UserResponse:
    """
    Authorize a participant (user-only) action.

    Depends on `get_current_user`, so a missing/invalid/expired token yields 401
    first. Raises 403 when the account's role is not `user` (Requirements 15.3,
    15.5, 15.6).
    """
    return _require_role(user, Role.user)

def require_coach_or_user(
    user: UserResponse = Depends(get_current_user),
) -> UserResponse:
    """
    Authorize an action open to either known role.

    Depends on `get_current_user`, so a missing/invalid/expired token yields 401
    first. Raises 403 only when the account's role is absent or not one of the
    recognized roles ({coach, user}); both `coach` and `user` are accepted. The
    caller (service layer) is responsible for any per-resource authorization,
    e.g. owner-or-enrolled access to a program's content (Requirement 15.6).
    """
    role = user.role
    if role is None or role not in (Role.coach, Role.user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account role is missing or unrecognized; this action is not permitted",
        )
    return user
