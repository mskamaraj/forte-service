from decimal import Decimal
from enum import Enum
from pydantic import BaseModel, Field, field_validator


_PRICE_MIN = Decimal("0.00")
_PRICE_MAX = Decimal("999999.99")


# ── Lifecycle ─────────────────────────────────────────────────────────────────

class ProgramState(str, Enum):
    drafted = "drafted"
    active = "active"
    paused = "paused"
    archived = "archived"


# Allowed lifecycle edges (Requirement 3.1). Archived is terminal; identical
# source/target and any edge out of archived are absent and therefore rejected
# (Requirement 3.2).
ALLOWED_TRANSITIONS: set[tuple[ProgramState, ProgramState]] = {
    (ProgramState.drafted, ProgramState.active),
    (ProgramState.drafted, ProgramState.archived),
    (ProgramState.active, ProgramState.paused),
    (ProgramState.active, ProgramState.archived),
    (ProgramState.paused, ProgramState.active),
    (ProgramState.paused, ProgramState.archived),
}


# ── Shared field validators ───────────────────────────────────────────────────

def _validate_title(v: str) -> str:
    """Title must be 1–200 characters after trimming (Requirements 2.1, 2.2)."""
    v = v.strip()
    if not v:
        raise ValueError("Title must not be empty")
    if len(v) > 200:
        raise ValueError("Title must be at most 200 characters")
    return v


def _validate_price(v: Decimal) -> Decimal:
    """Reject >2 fractional digits, then normalize to scale 2 (Requirements 2.4, 2.5)."""
    # ``exponent`` is negative for fractional digits (e.g. -2 for "1.23"); a
    # positive or zero exponent means an integer value with no fractional part.
    exponent = v.as_tuple().exponent
    fractional_digits = -exponent if isinstance(exponent, int) and exponent < 0 else 0
    if fractional_digits > 2:
        raise ValueError("Price must have at most 2 fractional digits")
    return v.quantize(Decimal("0.01"))


# ── Request ───────────────────────────────────────────────────────────────────

class ProgramCreateRequest(BaseModel):
    title: str = Field(..., max_length=200)
    description: str = Field("", max_length=5000)
    price: Decimal = Field(..., ge=_PRICE_MIN, le=_PRICE_MAX)

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, v: str) -> str:
        return _validate_title(v)

    @field_validator("price")
    @classmethod
    def price_scale(cls, v: Decimal) -> Decimal:
        return _validate_price(v)


class ProgramUpdateRequest(ProgramCreateRequest):
    """Same field constraints as create (Requirements 4.8, 4.9)."""


class ProgramStateTransitionRequest(BaseModel):
    # A value outside the ProgramState enum fails coercion -> 422 (Requirement 3.3).
    target_state: ProgramState


# ── Internal (stored in DynamoDB, never serialised to clients) ────────────────

class ProgramRecord(BaseModel):
    program_id: str
    owner_coach_id: str
    title: str
    description: str
    price: Decimal  # stored with scale 2
    program_state: ProgramState = ProgramState.drafted  # Requirement 1.2
    created_at: str
    updated_at: str


# ── Response ──────────────────────────────────────────────────────────────────

class ProgramResponse(BaseModel):
    program_id: str
    owner_coach_id: str
    title: str
    description: str
    price: Decimal
    program_state: ProgramState
    created_at: str
    updated_at: str
