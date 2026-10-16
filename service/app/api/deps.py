"""Reusable FastAPI dependencies."""

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import decode_access_token
from app.models.user import UserResponse
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
