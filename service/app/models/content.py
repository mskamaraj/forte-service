from enum import Enum
from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.program import ProgramState


# ── Node type ─────────────────────────────────────────────────────────────────

class NodeType(str, Enum):
    module = "module"
    chapter = "chapter"
    exercise = "exercise"


# ── Shared field validators ───────────────────────────────────────────────────

def _validate_title(v: str) -> str:
    """Title must be 1–200 characters after trimming (Requirements 5.3, 6.3, 7.3)."""
    v = v.strip()
    if not v:
        raise ValueError("Title must not be empty")
    if len(v) > 200:
        raise ValueError("Title must be at most 200 characters")
    return v


# ── Create requests ────────────────────────────────────────────────────────────

class ModuleCreateRequest(BaseModel):
    title: str
    position: int = Field(..., ge=1)  # integer >= 1 (Requirement 5.4)

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, v: str) -> str:
        return _validate_title(v)


class ChapterCreateRequest(ModuleCreateRequest):
    """Same constraints as module create (Requirement 6)."""


class ExerciseCreateRequest(BaseModel):
    title: str
    prompt: str = Field("", max_length=10000)  # 0..10000 (Requirement 7.4)
    position: int = Field(..., ge=1)

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, v: str) -> str:
        return _validate_title(v)


# ── Update requests (all fields optional; at least one required, Req 8.8) ──────

class ModuleUpdateRequest(BaseModel):
    title: str | None = None
    position: int | None = Field(None, ge=1)

    @field_validator("title")
    @classmethod
    def title_rule(cls, v: str | None) -> str | None:
        return _validate_title(v) if v is not None else v

    @model_validator(mode="after")
    def at_least_one(self) -> "ModuleUpdateRequest":
        if self.title is None and self.position is None:
            raise ValueError("No updatable field provided")  # Requirement 8.8
        return self


class ChapterUpdateRequest(ModuleUpdateRequest):
    """Same as module update (Requirement 8.2)."""


class ExerciseUpdateRequest(BaseModel):
    title: str | None = None
    prompt: str | None = Field(None, max_length=10000)
    position: int | None = Field(None, ge=1)

    @field_validator("title")
    @classmethod
    def title_rule(cls, v: str | None) -> str | None:
        return _validate_title(v) if v is not None else v

    @model_validator(mode="after")
    def at_least_one(self) -> "ExerciseUpdateRequest":
        if self.title is None and self.prompt is None and self.position is None:
            raise ValueError("No updatable field provided")  # Requirement 8.8
        return self


# ── Internal (stored in DynamoDB, one content table discriminated by node_type)─

class ContentNodeRecord(BaseModel):
    program_id: str
    node_type: NodeType
    node_id: str                    # uuid4
    parent_id: str | None           # module -> None; chapter -> module_id; exercise -> chapter_id
    title: str
    position: int
    prompt: str | None = None       # exercises only
    created_at: str


# ── Responses (flat per-node) ──────────────────────────────────────────────────

class ModuleResponse(BaseModel):
    module_id: str
    title: str
    position: int
    created_at: str


class ChapterResponse(BaseModel):
    chapter_id: str
    title: str
    position: int
    created_at: str


class ExerciseResponse(BaseModel):
    exercise_id: str
    title: str
    prompt: str
    position: int
    created_at: str


# ── Completion-annotated tree (Requirement 12.2) ────────────────────────────────

class CompletionSummary(BaseModel):
    completed_count: int
    total_count: int
    completed: bool          # total_count > 0 and completed_count == total_count


class ExerciseNode(ExerciseResponse):
    completion: str          # "completed" | "not_completed"


class ChapterNode(ChapterResponse):
    exercises: list[ExerciseNode]
    completion: CompletionSummary


class ModuleNode(ModuleResponse):
    chapters: list[ChapterNode]
    completion: CompletionSummary


class ContentTreeResponse(BaseModel):
    program_id: str
    program_state: ProgramState
    modules: list[ModuleNode]
    completion: CompletionSummary
