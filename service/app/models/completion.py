from pydantic import BaseModel


# ── Request ───────────────────────────────────────────────────────────────────

class CompletionUpdateRequest(BaseModel):
    # A missing or non-boolean value fails coercion -> 422 (Requirement 13.6).
    completed: bool


# ── Internal (stored in DynamoDB, never serialised to clients) ────────────────

class ExerciseCompletionRecord(BaseModel):
    user_id: str
    program_id: str
    exercise_id: str
    completed: bool
    updated_at: str  # UTC ISO 8601 (Requirement 13.8)


# ── Response ──────────────────────────────────────────────────────────────────

class ExerciseCompletionResponse(BaseModel):
    exercise_id: str
    completed: bool
    updated_at: str
