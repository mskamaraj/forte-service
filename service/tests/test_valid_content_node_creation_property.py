"""Property-based test for valid content-node creation.

Feature: coaching-programs, Property 8: Valid content nodes are created with
preserved fields and an id. For any valid Module / Chapter / Exercise create
request submitted to ``CoachingService.create_module`` /
``create_chapter`` / ``create_exercise`` against an existing owned ancestry,
the returned node carries every submitted field verbatim and is assigned a
non-empty generated identifier (Requirements 5.1, 6.1, 7.1).

  - Module creation with a title of 1–200 characters (after trim) and a
    position >= 1 returns the created Module with a generated module id
    (Requirement 5.1).
  - Chapter creation within an existing Module with a valid title/position
    returns the created Chapter with a generated chapter id (Requirement 6.1).
  - Exercise creation within an existing Chapter with a valid title, a prompt
    of 0–10,000 characters, and a position >= 1 returns the created Exercise
    with a generated exercise id (Requirement 7.1).

Like the sibling listing/creation property tests, this runs against the real
persistence path: programs and content nodes are created through the
``CoachingService`` wired to real repositories over a ``moto``-backed DynamoDB
engine, and the returned response is asserted against the submitted request.

Validates: Requirements 5.1, 6.1, 7.1
"""

import os
from decimal import Decimal

import boto3
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

from app.core.config import settings as app_settings
from app.models.content import (
    ChapterCreateRequest,
    ExerciseCreateRequest,
    ModuleCreateRequest,
)
from app.models.program import ProgramCreateRequest
from app.services.coaching_service import CoachingService


# ──────────────────────────────────────────────────────────────────────────────
# Table creation — mirrors the programs and content table designs (tasks 2.1 /
# 2.2), identical to the sibling property / integration tests.
# ──────────────────────────────────────────────────────────────────────────────


def _create_programs_table(dynamodb):
    """PK ``program_id``; GSI ``owner-index`` (owner_coach_id); GSI
    ``state-index`` (program_state + created_at)."""
    return dynamodb.create_table(
        TableName=app_settings.dynamodb_programs_table,
        KeySchema=[{"AttributeName": "program_id", "KeyType": "HASH"}],
        AttributeDefinitions=[
            {"AttributeName": "program_id", "AttributeType": "S"},
            {"AttributeName": "owner_coach_id", "AttributeType": "S"},
            {"AttributeName": "program_state", "AttributeType": "S"},
            {"AttributeName": "created_at", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "owner-index",
                "KeySchema": [
                    {"AttributeName": "owner_coach_id", "KeyType": "HASH"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
            {
                "IndexName": "state-index",
                "KeySchema": [
                    {"AttributeName": "program_state", "KeyType": "HASH"},
                    {"AttributeName": "created_at", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
        BillingMode="PAY_PER_REQUEST",
    )


def _create_content_table(dynamodb):
    """PK ``program_id``, SK ``node_sk``."""
    return dynamodb.create_table(
        TableName=app_settings.dynamodb_content_table,
        KeySchema=[
            {"AttributeName": "program_id", "KeyType": "HASH"},
            {"AttributeName": "node_sk", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "program_id", "AttributeType": "S"},
            {"AttributeName": "node_sk", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _aws_env():
    """Pin a region and dummy credentials so the tables created here and the
    repositories' own ``boto3.resource("dynamodb")`` resolve to the same
    moto-backed endpoint."""
    previous = {
        key: os.environ.get(key)
        for key in (
            "AWS_DEFAULT_REGION",
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_SESSION_TOKEN",
        )
    }
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


# ──────────────────────────────────────────────────────────────────────────────
# Generators — valid content-node fields.
# ──────────────────────────────────────────────────────────────────────────────

# Titles 1–200 characters after trimming. The service/model trim the title, so
# the generated value and the stored value may differ by surrounding
# whitespace; the test compares against the trimmed form.
_titles = st.text(
    alphabet=st.characters(blacklist_categories=("Cc", "Cs")),
    min_size=1,
    max_size=200,
).filter(lambda s: 1 <= len(s.strip()) <= 200)

# Positions are integers >= 1.
_positions = st.integers(min_value=1, max_value=100000)

# Prompts 0–10,000 characters (Requirement 7.4). Kept modest in size to keep
# generation cheap while still spanning the empty and populated cases.
_prompts = st.text(
    alphabet=st.characters(blacklist_categories=("Cc", "Cs")),
    min_size=0,
    max_size=500,
)

# A coach who owns the program/content being created.
_coach = st.text(
    alphabet=st.characters(blacklist_categories=("Cc", "Cs", "Zs")),
    min_size=1,
    max_size=40,
).filter(lambda s: s.strip() == s and s != "")


def _make_program(service: CoachingService, coach_id: str) -> str:
    """Create a valid program owned by ``coach_id`` and return its id."""
    created = service.create_program(
        coach_id=coach_id,
        payload=ProgramCreateRequest(
            title="A valid program",
            description="",
            price=Decimal("0.00"),
        ),
    )
    return created.program_id


# ──────────────────────────────────────────────────────────────────────────────
# Property 8 — Module creation
# ──────────────────────────────────────────────────────────────────────────────


@settings(max_examples=100, deadline=None)
@given(coach_id=_coach, title=_titles, position=_positions)
def test_valid_module_creation_preserves_fields_and_assigns_id(
    coach_id, title, position
):
    """Feature: coaching-programs, Property 8: Valid content nodes are created
    with preserved fields and an id.

    A module created with a valid title (1–200 chars after trim) and a position
    >= 1 is returned with those fields preserved and a non-empty generated
    module id (Requirement 5.1).

    Validates: Requirements 5.1
    """
    with mock_aws():
        dynamodb = boto3.resource("dynamodb")
        _create_programs_table(dynamodb)
        _create_content_table(dynamodb)

        service = CoachingService()
        program_id = _make_program(service, coach_id)

        request = ModuleCreateRequest(title=title, position=position)
        module = service.create_module(
            coach_id=coach_id, program_id=program_id, payload=request
        )

        # A non-empty generated id is assigned (Requirement 5.1).
        assert isinstance(module.module_id, str)
        assert module.module_id != ""

        # Submitted fields are preserved (title compared against its trimmed
        # form, since the model trims the title before storing).
        assert module.title == title.strip()
        assert module.position == position

        # A created-at timestamp is generated.
        assert isinstance(module.created_at, str)
        assert module.created_at != ""


# ──────────────────────────────────────────────────────────────────────────────
# Property 8 — Chapter creation
# ──────────────────────────────────────────────────────────────────────────────


@settings(max_examples=100, deadline=None)
@given(
    coach_id=_coach,
    module_title=_titles,
    module_position=_positions,
    chapter_title=_titles,
    chapter_position=_positions,
)
def test_valid_chapter_creation_preserves_fields_and_assigns_id(
    coach_id, module_title, module_position, chapter_title, chapter_position
):
    """Feature: coaching-programs, Property 8: Valid content nodes are created
    with preserved fields and an id.

    A chapter created within an existing module with a valid title/position is
    returned with those fields preserved and a non-empty generated chapter id
    (Requirement 6.1).

    Validates: Requirements 6.1
    """
    with mock_aws():
        dynamodb = boto3.resource("dynamodb")
        _create_programs_table(dynamodb)
        _create_content_table(dynamodb)

        service = CoachingService()
        program_id = _make_program(service, coach_id)

        module = service.create_module(
            coach_id=coach_id,
            program_id=program_id,
            payload=ModuleCreateRequest(
                title=module_title, position=module_position
            ),
        )

        request = ChapterCreateRequest(
            title=chapter_title, position=chapter_position
        )
        chapter = service.create_chapter(
            coach_id=coach_id,
            program_id=program_id,
            module_id=module.module_id,
            payload=request,
        )

        # A non-empty generated id is assigned (Requirement 6.1).
        assert isinstance(chapter.chapter_id, str)
        assert chapter.chapter_id != ""

        # Submitted fields are preserved.
        assert chapter.title == chapter_title.strip()
        assert chapter.position == chapter_position

        assert isinstance(chapter.created_at, str)
        assert chapter.created_at != ""


# ──────────────────────────────────────────────────────────────────────────────
# Property 8 — Exercise creation
# ──────────────────────────────────────────────────────────────────────────────


@settings(max_examples=100, deadline=None)
@given(
    coach_id=_coach,
    module_title=_titles,
    module_position=_positions,
    chapter_title=_titles,
    chapter_position=_positions,
    exercise_title=_titles,
    exercise_prompt=_prompts,
    exercise_position=_positions,
)
def test_valid_exercise_creation_preserves_fields_and_assigns_id(
    coach_id,
    module_title,
    module_position,
    chapter_title,
    chapter_position,
    exercise_title,
    exercise_prompt,
    exercise_position,
):
    """Feature: coaching-programs, Property 8: Valid content nodes are created
    with preserved fields and an id.

    An exercise created within an existing chapter with a valid title, a prompt
    of 0–10,000 characters, and a position >= 1 is returned with those fields
    preserved and a non-empty generated exercise id (Requirement 7.1).

    Validates: Requirements 7.1
    """
    with mock_aws():
        dynamodb = boto3.resource("dynamodb")
        _create_programs_table(dynamodb)
        _create_content_table(dynamodb)

        service = CoachingService()
        program_id = _make_program(service, coach_id)

        module = service.create_module(
            coach_id=coach_id,
            program_id=program_id,
            payload=ModuleCreateRequest(
                title=module_title, position=module_position
            ),
        )
        chapter = service.create_chapter(
            coach_id=coach_id,
            program_id=program_id,
            module_id=module.module_id,
            payload=ChapterCreateRequest(
                title=chapter_title, position=chapter_position
            ),
        )

        request = ExerciseCreateRequest(
            title=exercise_title,
            prompt=exercise_prompt,
            position=exercise_position,
        )
        exercise = service.create_exercise(
            coach_id=coach_id,
            program_id=program_id,
            module_id=module.module_id,
            chapter_id=chapter.chapter_id,
            payload=request,
        )

        # A non-empty generated id is assigned (Requirement 7.1).
        assert isinstance(exercise.exercise_id, str)
        assert exercise.exercise_id != ""

        # Submitted fields are preserved (title trimmed; prompt verbatim).
        assert exercise.title == exercise_title.strip()
        assert exercise.prompt == exercise_prompt
        assert exercise.position == exercise_position

        assert isinstance(exercise.created_at, str)
        assert exercise.created_at != ""
