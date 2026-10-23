from pydantic import BaseModel, Field


# ── Request ───────────────────────────────────────────────────────────────────

class EnrollRequest(BaseModel):
    # A missing/empty program_id fails validation -> 422 (Requirement 10.6).
    program_id: str = Field(..., min_length=1)


# ── Internal (stored in DynamoDB, never serialised to clients) ────────────────

class EnrollmentRecord(BaseModel):
    user_id: str
    program_id: str
    enrollment_id: str  # uuid4 surrogate id for the response
    enrolled_at: str    # UTC ISO 8601 (Requirement 10.7)


# ── Response ──────────────────────────────────────────────────────────────────

class EnrollmentResponse(BaseModel):
    enrollment_id: str
    user_id: str
    program_id: str
    enrolled_at: str
