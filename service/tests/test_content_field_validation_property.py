"""Property-based test for content-node field validation.

Feature: coaching-programs, Property 9: Invalid content-node fields are rejected
without storing. For any Module / Chapter / Exercise create or update request
whose title, position, or prompt violates a field constraint, model construction
raises a Pydantic ``ValidationError`` -- the request never yields a validated
model, so the service can never build a ``ContentNodeRecord`` from it and nothing
is stored. At the route boundary this ``ValidationError`` surfaces as HTTP 422
and, for the update path, leaves the stored node unchanged.

Create-path constraints asserted here:
  - Module/Chapter: title empty/whitespace-only or > 200 after trim (Req 5.3,
    6.3); position not an integer >= 1 (Req 5.4, 6.4).
  - Exercise: title empty/whitespace-only or > 200 after trim (Req 7.3); prompt
    longer than 10,000 characters (Req 7.4); position not an integer >= 1
    (Req 7.5).

Update-path constraints asserted here (Req 8.6): title empty after trim or
> 200, position not an integer >= 1, and (exercise) prompt > 10,000. Update
models additionally require at least one updatable field, but the "no field
provided" case belongs to the dedicated empty-update unit test; here every case
supplies exactly one field, and that field is invalid.

Validates: Requirements 5.3, 5.4, 6.3, 6.4, 7.3, 7.4, 7.5, 8.6
"""

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from app.models.content import (
    ChapterCreateRequest,
    ChapterUpdateRequest,
    ExerciseCreateRequest,
    ExerciseUpdateRequest,
    ModuleCreateRequest,
    ModuleUpdateRequest,
)

# Module and Chapter create requests carry identical field constraints
# (ChapterCreateRequest subclasses ModuleCreateRequest), as do their update
# requests. Asserting against both covers Req 5/6 (modules/chapters) with the
# same generators.
_TITLE_POSITION_CREATE_MODELS = (ModuleCreateRequest, ChapterCreateRequest)
_TITLE_POSITION_UPDATE_MODELS = (ModuleUpdateRequest, ChapterUpdateRequest)

# Valid baselines, used so that exactly one field is invalid at a time and the
# rejection is unambiguously attributable to that field.
_VALID_TITLE = "A valid content title"
_VALID_PROMPT = "A valid exercise prompt"
_VALID_POSITION = 1


def _assert_rejected(models, **fields) -> None:
    """Every model in ``models`` must reject ``fields`` with a ValidationError.

    A raised ``ValidationError`` means no validated request model is produced,
    so the service can never construct a ``ContentNodeRecord`` from it -- i.e.
    the invalid request is rejected "without storing".
    """
    for model in models:
        with pytest.raises(ValidationError):
            model(**fields)


# ──────────────────────────────────────────────────────────────────────────────
# Generators for invalid field values
# ──────────────────────────────────────────────────────────────────────────────

# Titles that are empty or whitespace-only -> empty after trimming.
_blank_titles = st.text(alphabet=" \t\n\r\f\v", max_size=10)

# Titles that exceed 200 characters after trimming. Use non-whitespace content
# so trimming does not shrink it below the limit.
_overlong_titles = st.text(
    alphabet=st.characters(blacklist_categories=("Cc", "Cs", "Zs", "Zl", "Zp")),
    min_size=201,
    max_size=400,
).filter(lambda s: len(s.strip()) > 200)

# Positions that are not an integer of 1 or greater (zero or negative). The
# non-integer branch (floats, strings) is covered by the malformed-value unit
# test; here we exercise the ``ge=1`` integer boundary.
_invalid_positions = st.integers(min_value=-1000, max_value=0)

# Prompts longer than 10,000 characters (Req 7.4). Built by padding a small
# excess onto the limit so Hypothesis' smallest natural input stays modest.
_overlong_prompts = st.integers(min_value=1, max_value=200).map(
    lambda excess: "x" * (10000 + excess)
)


# ──────────────────────────────────────────────────────────────────────────────
# Property 9 -- Module / Chapter create
# ──────────────────────────────────────────────────────────────────────────────


@settings(max_examples=100)
@given(title=_blank_titles)
def test_module_chapter_blank_title_create_rejected(title):
    """Feature: coaching-programs, Property 9: Invalid content-node fields are
    rejected without storing. A module/chapter create with an empty or
    whitespace-only title (empty after trimming) is rejected.

    Validates: Requirements 5.3, 6.3
    """
    _assert_rejected(
        _TITLE_POSITION_CREATE_MODELS, title=title, position=_VALID_POSITION
    )


@settings(max_examples=100)
@given(title=_overlong_titles)
def test_module_chapter_overlong_title_create_rejected(title):
    """Feature: coaching-programs, Property 9: Invalid content-node fields are
    rejected without storing. A module/chapter create whose title exceeds 200
    characters after trimming is rejected.

    Validates: Requirements 5.3, 6.3
    """
    assume(len(title.strip()) > 200)
    _assert_rejected(
        _TITLE_POSITION_CREATE_MODELS, title=title, position=_VALID_POSITION
    )


@settings(max_examples=100)
@given(position=_invalid_positions)
def test_module_chapter_invalid_position_create_rejected(position):
    """Feature: coaching-programs, Property 9: Invalid content-node fields are
    rejected without storing. A module/chapter create with a position that is
    not an integer of 1 or greater is rejected.

    Validates: Requirements 5.4, 6.4
    """
    _assert_rejected(
        _TITLE_POSITION_CREATE_MODELS, title=_VALID_TITLE, position=position
    )


# ──────────────────────────────────────────────────────────────────────────────
# Property 9 -- Exercise create
# ──────────────────────────────────────────────────────────────────────────────


@settings(max_examples=100)
@given(title=_blank_titles)
def test_exercise_blank_title_create_rejected(title):
    """Feature: coaching-programs, Property 9: Invalid content-node fields are
    rejected without storing. An exercise create with an empty or
    whitespace-only title is rejected.

    Validates: Requirements 7.3
    """
    _assert_rejected(
        (ExerciseCreateRequest,),
        title=title,
        prompt=_VALID_PROMPT,
        position=_VALID_POSITION,
    )


@settings(max_examples=100)
@given(title=_overlong_titles)
def test_exercise_overlong_title_create_rejected(title):
    """Feature: coaching-programs, Property 9: Invalid content-node fields are
    rejected without storing. An exercise create whose title exceeds 200
    characters after trimming is rejected.

    Validates: Requirements 7.3
    """
    assume(len(title.strip()) > 200)
    _assert_rejected(
        (ExerciseCreateRequest,),
        title=title,
        prompt=_VALID_PROMPT,
        position=_VALID_POSITION,
    )


@settings(max_examples=100)
@given(prompt=_overlong_prompts)
def test_exercise_overlong_prompt_create_rejected(prompt):
    """Feature: coaching-programs, Property 9: Invalid content-node fields are
    rejected without storing. An exercise create whose prompt exceeds 10,000
    characters is rejected.

    Validates: Requirements 7.4
    """
    assume(len(prompt) > 10000)
    _assert_rejected(
        (ExerciseCreateRequest,),
        title=_VALID_TITLE,
        prompt=prompt,
        position=_VALID_POSITION,
    )


@settings(max_examples=100)
@given(position=_invalid_positions)
def test_exercise_invalid_position_create_rejected(position):
    """Feature: coaching-programs, Property 9: Invalid content-node fields are
    rejected without storing. An exercise create with a position that is not an
    integer of 1 or greater is rejected.

    Validates: Requirements 7.5
    """
    _assert_rejected(
        (ExerciseCreateRequest,),
        title=_VALID_TITLE,
        prompt=_VALID_PROMPT,
        position=position,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Property 9 -- Update requests (Req 8.6)
# ──────────────────────────────────────────────────────────────────────────────


@settings(max_examples=100)
@given(title=_blank_titles)
def test_module_chapter_blank_title_update_rejected(title):
    """Feature: coaching-programs, Property 9: Invalid content-node fields are
    rejected without storing. A module/chapter update whose title is empty
    after trimming is rejected, leaving the stored node unchanged.

    Validates: Requirements 8.6
    """
    _assert_rejected(_TITLE_POSITION_UPDATE_MODELS, title=title)


@settings(max_examples=100)
@given(title=_overlong_titles)
def test_module_chapter_overlong_title_update_rejected(title):
    """Feature: coaching-programs, Property 9: Invalid content-node fields are
    rejected without storing. A module/chapter update whose title exceeds 200
    characters after trimming is rejected.

    Validates: Requirements 8.6
    """
    assume(len(title.strip()) > 200)
    _assert_rejected(_TITLE_POSITION_UPDATE_MODELS, title=title)


@settings(max_examples=100)
@given(position=_invalid_positions)
def test_module_chapter_invalid_position_update_rejected(position):
    """Feature: coaching-programs, Property 9: Invalid content-node fields are
    rejected without storing. A module/chapter update with a position that is
    not an integer of 1 or greater is rejected.

    Validates: Requirements 8.6
    """
    _assert_rejected(_TITLE_POSITION_UPDATE_MODELS, position=position)


@settings(max_examples=100)
@given(title=_blank_titles)
def test_exercise_blank_title_update_rejected(title):
    """Feature: coaching-programs, Property 9: Invalid content-node fields are
    rejected without storing. An exercise update whose title is empty after
    trimming is rejected.

    Validates: Requirements 8.6
    """
    _assert_rejected((ExerciseUpdateRequest,), title=title)


@settings(max_examples=100)
@given(title=_overlong_titles)
def test_exercise_overlong_title_update_rejected(title):
    """Feature: coaching-programs, Property 9: Invalid content-node fields are
    rejected without storing. An exercise update whose title exceeds 200
    characters after trimming is rejected.

    Validates: Requirements 8.6
    """
    assume(len(title.strip()) > 200)
    _assert_rejected((ExerciseUpdateRequest,), title=title)


@settings(max_examples=100)
@given(position=_invalid_positions)
def test_exercise_invalid_position_update_rejected(position):
    """Feature: coaching-programs, Property 9: Invalid content-node fields are
    rejected without storing. An exercise update with a position that is not an
    integer of 1 or greater is rejected.

    Validates: Requirements 8.6
    """
    _assert_rejected((ExerciseUpdateRequest,), position=position)


@settings(max_examples=100)
@given(prompt=_overlong_prompts)
def test_exercise_overlong_prompt_update_rejected(prompt):
    """Feature: coaching-programs, Property 9: Invalid content-node fields are
    rejected without storing. An exercise update whose prompt exceeds 10,000
    characters is rejected.

    Validates: Requirements 8.6
    """
    assume(len(prompt) > 10000)
    _assert_rejected((ExerciseUpdateRequest,), prompt=prompt)


# ──────────────────────────────────────────────────────────────────────────────
# Property 9 -- any single invalid field across all node kinds
# ──────────────────────────────────────────────────────────────────────────────


@settings(max_examples=100)
@given(data=st.data())
def test_any_single_invalid_field_is_rejected(data):
    """Feature: coaching-programs, Property 9: Invalid content-node fields are
    rejected without storing. For an otherwise-valid create request, corrupting
    any one field (title, position, or -- for exercises -- prompt) with an
    out-of-constraint value causes rejection, so no validated model, and
    therefore no stored content node, can result.

    Validates: Requirements 5.3, 5.4, 6.3, 6.4, 7.3, 7.4, 7.5
    """
    invalid_title = st.one_of(_blank_titles, _overlong_titles)

    kind = data.draw(st.sampled_from(("module_chapter", "exercise")))

    if kind == "module_chapter":
        field = data.draw(st.sampled_from(("title", "position")))
        fields = {"title": _VALID_TITLE, "position": _VALID_POSITION}
        if field == "title":
            fields["title"] = data.draw(invalid_title)
            assume(
                len(fields["title"].strip()) > 200
                or not fields["title"].strip()
            )
        else:
            fields["position"] = data.draw(_invalid_positions)
        _assert_rejected(_TITLE_POSITION_CREATE_MODELS, **fields)
    else:
        field = data.draw(st.sampled_from(("title", "prompt", "position")))
        fields = {
            "title": _VALID_TITLE,
            "prompt": _VALID_PROMPT,
            "position": _VALID_POSITION,
        }
        if field == "title":
            fields["title"] = data.draw(invalid_title)
            assume(
                len(fields["title"].strip()) > 200
                or not fields["title"].strip()
            )
        elif field == "prompt":
            fields["prompt"] = data.draw(_overlong_prompts)
            assume(len(fields["prompt"]) > 10000)
        else:
            fields["position"] = data.draw(_invalid_positions)
        _assert_rejected((ExerciseCreateRequest,), **fields)
