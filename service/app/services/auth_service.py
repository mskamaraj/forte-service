"""Business logic for registration and (later) authentication."""

import base64
import binascii
import json
import uuid
from datetime import datetime, timezone

import bcrypt
from fastapi import HTTPException, status

from app.core.security import create_access_token
from app.models.user import (
    LoginRequest,
    RegisterRequest,
    RegisterResponse,
    TokenResponse,
    UserListResponse,
    UserRecord,
    UserResponse,
)
from app.repositories.user_repository import UserRepository

# bcrypt work factor
_BCRYPT_ROUNDS = 12


class AuthService:

    def __init__(self):
        self._repo = UserRepository()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _hash_password(self, plain: str) -> str:
        # bcrypt hashes at most 72 bytes; truncate explicitly to avoid an error
        pw = plain.encode("utf-8")[:72]
        return bcrypt.hashpw(pw, bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode("utf-8")

    def verify_password(self, plain: str, hashed: str) -> bool:
        pw = plain.encode("utf-8")[:72]
        return bcrypt.checkpw(pw, hashed.encode("utf-8"))

    # ── Registration ──────────────────────────────────────────────────────────

    def register(self, payload: RegisterRequest) -> RegisterResponse:
        # 1. Normalise email to lowercase
        email = payload.email.lower().strip()

        # 2. Uniqueness check
        if self._repo.email_exists(email):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with this email already exists",
            )

        # 3. Build the record
        now = datetime.now(timezone.utc).isoformat()
        record = UserRecord(
            user_id=str(uuid.uuid4()),
            email=email,
            password_hash=self._hash_password(payload.password),
            first_name=payload.first_name.strip(),
            last_name=payload.last_name.strip(),
            is_active=True,
            is_verified=False,
            created_at=now,
            updated_at=now,
        )

        # 4. Persist
        saved = self._repo.create(record)

        # 5. Return public shape (no password_hash)
        return RegisterResponse(user=_to_user_response(saved))

    # ── Retrieval ─────────────────────────────────────────────────────────────

    def get_user(self, user_id: str) -> UserResponse:
        """Fetch a single user by ID, returning the public shape."""
        record = self._repo.get_by_id(user_id)
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )
        return _to_user_response(record)

    # ── Authentication ──────────────────────────────────────────────────────

    def login(self, payload: LoginRequest) -> TokenResponse:
        """Verify credentials and return a signed JWT access token."""
        email = payload.email.lower().strip()
        record = self._repo.get_by_email(email)

        # Use the same error for "no such user" and "wrong password"
        # so we don't reveal which emails are registered.
        invalid = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

        if record is None or not self.verify_password(payload.password, record.password_hash):
            raise invalid

        if not record.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is disabled",
            )

        token, expires_in = create_access_token(record.user_id, record.email)
        return TokenResponse(access_token=token, expires_in=expires_in)

    # ── Listing ─────────────────────────────────────────────────────────────

    def list_users(self, limit: int = 50, cursor: str | None = None) -> UserListResponse:
        """
        Return a page of users. `cursor` is an opaque token returned as
        `next_cursor` from a previous call; pass it back to get the next page.
        """
        start_key = _decode_cursor(cursor) if cursor else None

        records, last_key = self._repo.list_all(limit=limit, start_key=start_key)

        return UserListResponse(
            users=[_to_user_response(r) for r in records],
            count=len(records),
            next_cursor=_encode_cursor(last_key) if last_key else None,
        )


def _encode_cursor(key: dict) -> str:
    """Encode a DynamoDB LastEvaluatedKey as an opaque base64 token."""
    return base64.urlsafe_b64encode(json.dumps(key).encode("utf-8")).decode("utf-8")


def _decode_cursor(cursor: str) -> dict:
    """Decode an opaque cursor back into a DynamoDB ExclusiveStartKey."""
    try:
        return json.loads(base64.urlsafe_b64decode(cursor.encode("utf-8")))
    except (ValueError, binascii.Error, json.JSONDecodeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid pagination cursor",
        )


def _to_user_response(record: UserRecord) -> UserResponse:
    """Map an internal UserRecord to the public UserResponse (drops password_hash)."""
    return UserResponse(
        user_id=record.user_id,
        email=record.email,
        first_name=record.first_name,
        last_name=record.last_name,
        is_active=record.is_active,
        is_verified=record.is_verified,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )
