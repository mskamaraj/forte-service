"""Unit tests for content-node boundary values, empty updates, and malformed input.

Feature: coaching-programs — EXAMPLE criteria for the content-node and completion
request models that the field-validation property test (Property 9) does not pin
down with exact boundary values:

* The inclusive ``position`` lower boundary ``1`` is accepted for Module /
  Chapter / Exercise create and update requests (Requirements 5.4, 6.4, 7.5).
* An Exercise prompt of length exactly ``0`` (the lower boundary) and exactly
  ``10000`` (the upper boundary) is accepted for create and update requests
  (Requirement 7.4).
* An update request that supplies no updatable field for its node type is
  rejected — the "at least one field" ``@model_validator`` raises, which the
  route boundary turns into HTTP 422, leaving the stored node unchanged
  (Requirement 8.8).
* Malformed / non-enum values are rejected: a non-integer / non-coercible
  ``position``, an invalid ``NodeType`` on ``ContentNodeRecord``, and a
  missing or non-boolean ``completed`` value on ``CompletionUpdateRequest``
  (Requirement 13.6).

Every invalid-input case surfaces as a Pydantic ``ValidationError`` at model
construction, which the route boundary turns into HTTP 422; no validated request
model is produced, so nothing is stored and (on the update path) the stored node
is left unchanged.

Validates: Requirements 8.8, 13.6
"""

import pytest
from pydantic import ValidationError

from app.models.completion import CompletionUpdateRequest
from app.models.content import (
    ChapterCreateRequest,
    ChapterUpdateRequest,
    ContentNodeRecord,
    ExerciseCreateRequest,
    ExerciseUpdateRequest,
    ModuleCreateRequest,
    ModuleUpdateRequest,
    NodeType,
)

_VALID_TITLE = "A valid content title"
# Module and Chapter create/update share identical constraints (Chapter*
# subclasses Module*), so each case is asserted against both.
_TITLE_POSITION_CREATE_MODELS = (ModuleCreateRequest, ChapterCreateRequest)
_TITLE_POSITION_UPDATE_MODELS = (ModuleUpdateRequest, ChapterUpdateRequest)


# ──────────────────────────────────────────────────────────────────────────────
# Accepted boundary: position == 1 (Requirements 5.4, 6.4, 7.5)
# ──────────────────────────────────────────────────────────────────────────────


def test_module_chapter_position_one_create_accepted():
    """``position == 1`` (the inclusive lower boundary) is accepted for module
    and chapter create requests.

    Validates: Requirements 5.4, 6.4
    """
    for model in _TITLE_POSITION_CREATE_MODELS:
        req = model(title=_VALID_TITLE, position=1)
        assert req.position == 1
        assert req.title == _VALID_TITLE


def test_exercise_position_one_create_accepted():
    """``position == 1`` is accepted for exercise create requests.

    Validates: Requirements 7.5
    """
    req = ExerciseCreateRequest(title=_VALID_TITLE, prompt="", position=1)
    assert req.position == 1


def test_module_chapter_position_one_update_accepted():
    """``position == 1`` is accepted for module and chapter update requests
    (a position update is a valid single updatable field, Req 8.8).

    Validates: Requirements 5.4, 6.4, 8.8
    """
    for model in _TITLE_POSITION_UPDATE_MODELS:
        req = model(position=1)
        assert req.position == 1


def test_exercise_position_one_update_accepted():
    """``position == 1`` is accepted for exercise update requests.

    Validates: Requirements 7.5, 8.8
    """
    req = ExerciseUpdateRequest(position=1)
    assert req.position == 1


# ──────────────────────────────────────────────────────────────────────────────
# Accepted boundary: prompt length 0 and 10000 (Requirement 7.4)
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("length", [0, 10000], ids=["empty", "max"])
def test_exercise_prompt_length_boundaries_create_accepted(length):
    """An exercise prompt of length exactly 0 (lower boundary) and exactly
    10000 (upper boundary) is accepted on create.

    Validates: Requirements 7.4
    """
    prompt = "x" * length
    req = ExerciseCreateRequest(title=_VALID_TITLE, prompt=prompt, position=1)
    assert req.prompt == prompt
    assert len(req.prompt) == length


def test_exercise_prompt_defaults_to_empty_on_create():
    """An omitted exercise prompt defaults to the empty (length 0) string,
    confirming the length-0 lower boundary is the default.

    Validates: Requirements 7.4
    """
    req = ExerciseCreateRequest(title=_VALID_TITLE, position=1)
    assert req.prompt == ""


def test_exercise_prompt_length_boundary_max_update_accepted():
    """An exercise update whose prompt is exactly 10000 characters is accepted.

    Validates: Requirements 7.4, 8.8
    """
    prompt = "x" * 10000
    req = ExerciseUpdateRequest(prompt=prompt)
    assert len(req.prompt) == 10000


def test_exercise_prompt_length_zero_update_accepted():
    """An exercise update whose prompt is the empty string (length 0) is a valid
    updatable field and is accepted.

    Validates: Requirements 7.4, 8.8
    """
    req = ExerciseUpdateRequest(prompt="")
    assert req.prompt == ""


def test_exercise_prompt_over_max_create_rejected():
    """A prompt of length 10001 (just past the upper boundary) is rejected,
    confirming 10000 is the inclusive maximum.

    Validates: Requirements 7.4
    """
    with pytest.raises(ValidationError):
        ExerciseCreateRequest(
            title=_VALID_TITLE, prompt="x" * 10001, position=1
        )


# ──────────────────────────────────────────────────────────────────────────────
# Empty update body → 422 (Requirement 8.8)
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "model",
    [ModuleUpdateRequest, ChapterUpdateRequest, ExerciseUpdateRequest],
    ids=["module", "chapter", "exercise"],
)
def test_empty_update_body_is_rejected(model):
    """An update request that provides no updatable field is rejected: the
    "at least one field" validator raises, which the route turns into HTTP 422
    and leaves the stored node unchanged.

    Validates: Requirements 8.8
    """
    with pytest.raises(ValidationError):
        model()


@pytest.mark.parametrize(
    "model",
    [ModuleUpdateRequest, ChapterUpdateRequest, ExerciseUpdateRequest],
    ids=["module", "chapter", "exercise"],
)
def test_all_none_update_body_is_rejected(model):
    """Explicitly passing every updatable field as ``None`` is treated the same
    as an empty body and rejected (Requirement 8.8).

    Validates: Requirements 8.8
    """
    fields = {name: None for name in model.model_fields}
    with pytest.raises(ValidationError):
        model(**fields)


def test_single_field_update_is_accepted():
    """A single updatable field satisfies the "at least one field" rule, so the
    empty-update rejection is specific to a truly empty body (Requirement 8.8).

    Validates: Requirements 8.8
    """
    assert ModuleUpdateRequest(title=_VALID_TITLE).title == _VALID_TITLE
    assert ChapterUpdateRequest(position=3).position == 3
    assert ExerciseUpdateRequest(prompt="a prompt").prompt == "a prompt"


# ──────────────────────────────────────────────────────────────────────────────
# Malformed / non-enum values → 422
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "position_input",
    ["abc", "1.5", "", 1.5, [1], {"n": 1}, None],
    ids=["word", "decimal-str", "empty-str", "float", "list", "dict", "none"],
)
def test_malformed_position_create_rejected(position_input):
    """A ``position`` that is not a coercible integer is rejected for module,
    chapter, and exercise create requests.

    Validates: Requirements 8.8, 13.6
    """
    for model in _TITLE_POSITION_CREATE_MODELS:
        with pytest.raises(ValidationError):
            model(title=_VALID_TITLE, position=position_input)
    with pytest.raises(ValidationError):
        ExerciseCreateRequest(
            title=_VALID_TITLE, prompt="", position=position_input
        )


@pytest.mark.parametrize(
    "node_type_input",
    ["lesson", "Module", "", "section", 1, None],
    ids=["unknown", "wrong-case", "empty", "bogus", "int", "none"],
)
def test_invalid_node_type_rejected(node_type_input):
    """A ``node_type`` that is not a member of the ``NodeType`` enum is rejected
    when building a content-node record.

    Validates: Requirements 8.8
    """
    with pytest.raises(ValidationError):
        ContentNodeRecord(
            program_id="p1",
            node_type=node_type_input,
            node_id="n1",
            parent_id=None,
            title=_VALID_TITLE,
            position=1,
            created_at="2024-01-01T00:00:00+00:00",
        )


def test_valid_node_type_accepted():
    """Each ``NodeType`` member is accepted on a content-node record, confirming
    the rejection above is specific to non-enum values.

    Validates: Requirements 8.8
    """
    for node_type in NodeType:
        record = ContentNodeRecord(
            program_id="p1",
            node_type=node_type,
            node_id="n1",
            parent_id=None,
            title=_VALID_TITLE,
            position=1,
            created_at="2024-01-01T00:00:00+00:00",
        )
        assert record.node_type == node_type


# ──────────────────────────────────────────────────────────────────────────────
# Completion update: non-boolean / missing value → 422 (Requirement 13.6)
# ──────────────────────────────────────────────────────────────────────────────


# Values Pydantic does NOT accept as a boolean complete/incomplete indicator.
# (Pydantic's lax mode legitimately coerces "true"/"yes"/"on"/"1"/0/1 to bool —
# those *are* valid boolean indicators — so only genuinely non-boolean values
# are asserted to be rejected here.)
@pytest.mark.parametrize(
    "completed_input",
    ["maybe", "complete", "2", 2, -1, 1.5, [True], {"v": True}],
    ids=[
        "word",
        "complete-word",
        "numeric-str-2",
        "int-2",
        "int-neg",
        "float",
        "list",
        "dict",
    ],
)
def test_non_boolean_completion_value_rejected(completed_input):
    """A completion update whose ``completed`` value is not a boolean indicator
    is rejected with a validation error (HTTP 422 at the route boundary),
    leaving the stored completion unchanged.

    Validates: Requirements 13.6
    """
    with pytest.raises(ValidationError):
        CompletionUpdateRequest(completed=completed_input)


def test_missing_completion_value_rejected():
    """Omitting the required ``completed`` field is rejected.

    Validates: Requirements 13.6
    """
    with pytest.raises(ValidationError):
        CompletionUpdateRequest()


@pytest.mark.parametrize(
    "completed_input,expected",
    [(True, True), (False, False)],
    ids=["true", "false"],
)
def test_boolean_completion_value_accepted(completed_input, expected):
    """A genuine boolean completion value is accepted, confirming the rejection
    above is specific to non-boolean input.

    Validates: Requirements 13.6
    """
    req = CompletionUpdateRequest(completed=completed_input)
    assert req.completed is expected
