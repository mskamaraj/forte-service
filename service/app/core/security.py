"""JWT creation/validation and SSM-backed secret retrieval."""

from datetime import datetime, timedelta, timezone
from functools import lru_cache

import boto3
import jwt

from app.core.config import settings


@lru_cache(maxsize=1)
def _get_jwt_secret() -> str:
    """
    Fetch the JWT signing secret from SSM Parameter Store.

    Cached for the lifetime of the Lambda container (cold start reads once).
    """
    if not settings.jwt_secret_param_name:
        raise RuntimeError("JWT_SECRET_PARAM_NAME is not configured")

    ssm = boto3.client("ssm")
    response = ssm.get_parameter(
        Name=settings.jwt_secret_param_name,
        WithDecryption=True,
    )
    return response["Parameter"]["Value"]


def create_access_token(user_id: str, email: str) -> tuple[str, int]:
    """
    Create a signed JWT for the given user.

    Returns (token, expires_in_seconds).
    """
    now = datetime.now(timezone.utc)
    expires_delta = timedelta(days=settings.jwt_expiry_days)
    expire = now + expires_delta

    payload = {
        "sub": user_id,
        "email": email,
        "iat": now,
        "exp": expire,
    }
    token = jwt.encode(payload, _get_jwt_secret(), algorithm=settings.jwt_algorithm)
    return token, int(expires_delta.total_seconds())


def decode_access_token(token: str) -> dict:
    """
    Decode and validate a JWT. Raises jwt.PyJWTError subclasses on failure
    (ExpiredSignatureError, InvalidTokenError, etc.).
    """
    return jwt.decode(
        token,
        _get_jwt_secret(),
        algorithms=[settings.jwt_algorithm],
    )
