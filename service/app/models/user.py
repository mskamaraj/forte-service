from datetime import datetime
from pydantic import BaseModel, EmailStr, Field, field_validator
import re


# ── Request ───────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    first_name: str = Field(..., min_length=1, max_length=50)
    last_name: str = Field(..., min_length=1, max_length=50)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        """Require at least one uppercase, one lowercase, one digit, one special char."""
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit")
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", v):
            raise ValueError("Password must contain at least one special character")
        return v

    @field_validator("first_name", "last_name")
    @classmethod
    def name_no_digits(cls, v: str) -> str:
        if re.search(r"\d", v):
            raise ValueError("Name must not contain digits")
        return v.strip()


# ── Internal (stored in DynamoDB, never serialised to clients) ────────────────

class UserRecord(BaseModel):
    user_id: str
    email: str
    password_hash: str
    first_name: str
    last_name: str
    is_active: bool = True
    is_verified: bool = False
    created_at: str
    updated_at: str


# ── Response ──────────────────────────────────────────────────────────────────

class UserResponse(BaseModel):
    """Public-facing user shape — password_hash is never included."""
    user_id: str
    email: str
    first_name: str
    last_name: str
    is_active: bool
    is_verified: bool
    created_at: str
    updated_at: str


class RegisterResponse(BaseModel):
    message: str = "User registered successfully"
    user: UserResponse


class UserListResponse(BaseModel):
    """A page of users plus an opaque cursor for the next page."""
    users: list[UserResponse]
    count: int
    next_cursor: str | None = None
