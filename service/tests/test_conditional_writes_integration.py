"""Integration tests for the repositories' conditional writes.

These tests exercise the real repository code paths against a real DynamoDB
engine provided by ``moto`` (an in-process AWS-API-compatible mock that stands
in for DynamoDB Local). Unlike the property tests, which inject a minimal
in-memory table stand-in, these tests let boto3 build and evaluate the actual
``ConditionExpression`` strings against moto's DynamoDB implementation, so they
validate that the condition guards behave as DynamoDB really does.

Covered:
  * ``ProgramRepository.create`` guards a duplicate program id with
    ``attribute_not_exists(program_id)`` — a second create with the same id
    fails the conditional check (Requirement 3.1).
  * ``EnrollmentRepository.create`` guards a duplicate enrollment with
    ``attribute_not_exists(user_id)`` on the (user_id, program_id) composite
    key — a second enrollment for the same pair fails the conditional check
    (Requirements 10.3, 10.8).
  * ``ProgramRepository.transition_state`` guards on
    ``program_state = :expected`` — a transition whose ``expected`` no longer
    matches the stored state fails the conditional check and leaves the state
    unchanged (Requirement 3.1).

Validates: Requirements 10.3, 10.8, 3.1
"""

import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

from app.core.config import settings
from app.models.enrollment import EnrollmentRecord
from app.models.program import ProgramRecord, ProgramState
from app.repositories.enrollment_repository import EnrollmentRepository
from app.repositories.program_repository import ProgramRepository


# ──────────────────────────────────────────────────────────────────────────────
# Table creation helpers — mirror the CDK table designs (tasks 2.1 / 2.2).
# ──────────────────────────────────────────────────────────────────────────────


def _create_programs_table(dynamodb):
    """PK ``program_id``; GSI ``owner-index`` (owner_coach_id); GSI
    ``state-index`` (program_state + created_at)."""
    return dynamodb.create_table(
        TableName=settings.dynamodb_programs_table,
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


def _create_enrollments_table(dynamodb):
    """PK ``user_id``, SK ``program_id``."""
    return dynamodb.create_table(
        TableName=settings.dynamodb_enrollments_table,
        KeySchema=[
            {"AttributeName": "user_id", "KeyType": "HASH"},
            {"AttributeName": "program_id", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "user_id", "AttributeType": "S"},
            {"AttributeName": "program_id", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )


def _make_program(
    program_id: str | None = None,
    state: ProgramState = ProgramState.drafted,
) -> ProgramRecord:
    now = datetime.now(timezone.utc).isoformat()
    return ProgramRecord(
        program_id=program_id or str(uuid.uuid4()),
        owner_coach_id="coach-" + str(uuid.uuid4()),
        title="A valid program",
        description="",
        price=Decimal("0.00"),
        program_state=state,
        created_at=now,
        updated_at=now,
    )


def _make_enrollment(user_id: str, program_id: str) -> EnrollmentRecord:
    return EnrollmentRecord(
        user_id=user_id,
        program_id=program_id,
        enrollment_id=str(uuid.uuid4()),
        enrolled_at=datetime.now(timezone.utc).isoformat(),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _aws_env():
    """Pin a region and dummy credentials so the table created here and the
    repository's own ``boto3.resource("dynamodb")`` (which takes no explicit
    region) resolve to the same moto-backed endpoint."""
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


@pytest.fixture
def dynamodb_programs():
    """A moto-backed programs table; yields the live repository."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb")
        _create_programs_table(dynamodb)
        # The repository binds its table in __init__ via get_programs_table(),
        # which resolves under the active moto mock.
        yield ProgramRepository()


@pytest.fixture
def dynamodb_enrollments():
    """A moto-backed enrollments table; yields the live repository."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb")
        _create_enrollments_table(dynamodb)
        yield EnrollmentRepository()


# ──────────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────────


def test_duplicate_program_create_fails_conditionally(dynamodb_programs):
    """A second ``create`` with the same program_id fails the
    ``attribute_not_exists(program_id)`` guard (Requirement 3.1)."""
    repo = dynamodb_programs
    program = _make_program()

    # First create succeeds.
    repo.create(program)

    # A second create of the same id is rejected by the conditional guard;
    # the repository maps the conditional failure to a ValueError.
    duplicate = _make_program(program_id=program.program_id)
    with pytest.raises(ValueError, match="already exists"):
        repo.create(duplicate)

    # The original record is untouched — the losing write stored nothing.
    stored = repo.get_by_id(program.program_id)
    assert stored is not None
    assert stored.owner_coach_id == program.owner_coach_id


def test_duplicate_enrollment_create_fails_conditionally(dynamodb_enrollments):
    """A second enrollment for the same (user_id, program_id) composite key
    raises the conditional-check failure (Requirements 10.3, 10.8)."""
    repo = dynamodb_enrollments
    user_id = "user-" + str(uuid.uuid4())
    program_id = "program-" + str(uuid.uuid4())

    # First enrollment succeeds.
    repo.create(_make_enrollment(user_id, program_id))

    # A second enrollment for the same composite key is rejected; the repository
    # surfaces the conditional failure as a ValueError the service maps to 409.
    with pytest.raises(ValueError, match="already enrolled"):
        repo.create(_make_enrollment(user_id, program_id))

    # Only one enrollment is stored for the user.
    enrollments = repo.list_by_user(user_id)
    assert len(enrollments) == 1


def test_enrollment_same_user_different_program_succeeds(dynamodb_enrollments):
    """The composite-key guard is per (user_id, program_id): the same user may
    enroll in a different program (Requirement 10.3)."""
    repo = dynamodb_enrollments
    user_id = "user-" + str(uuid.uuid4())
    program_a = "program-" + str(uuid.uuid4())
    program_b = "program-" + str(uuid.uuid4())

    repo.create(_make_enrollment(user_id, program_a))
    repo.create(_make_enrollment(user_id, program_b))

    enrollments = repo.list_by_user(user_id)
    assert {e.program_id for e in enrollments} == {program_a, program_b}


def test_transition_state_fails_when_current_state_does_not_match_expected(
    dynamodb_programs,
):
    """``transition_state`` fails when the stored state no longer matches
    ``expected`` (``ConditionExpression="program_state = :expected"``), leaving
    the state unchanged (Requirement 3.1)."""
    repo = dynamodb_programs
    program = _make_program(state=ProgramState.drafted)
    repo.create(program)

    # Move drafted -> active. Afterwards the stored state is ``active``.
    now = datetime.now(timezone.utc).isoformat()
    repo.transition_state(
        program_id=program.program_id,
        expected_state=ProgramState.drafted,
        new_state=ProgramState.active,
        updated_at=now,
    )

    # A transition that still expects ``drafted`` now mismatches the stored
    # ``active`` state, so the conditional guard rejects it.
    with pytest.raises(ValueError, match="not in expected state"):
        repo.transition_state(
            program_id=program.program_id,
            expected_state=ProgramState.drafted,
            new_state=ProgramState.paused,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )

    # The rejected transition left the state unchanged at ``active``.
    stored = repo.get_by_id(program.program_id)
    assert stored is not None
    assert stored.program_state == ProgramState.active


def test_transition_state_succeeds_when_expected_matches(dynamodb_programs):
    """A transition whose ``expected`` matches the stored state succeeds and
    advances the state (positive control for the conditional guard)."""
    repo = dynamodb_programs
    program = _make_program(state=ProgramState.drafted)
    repo.create(program)

    updated = repo.transition_state(
        program_id=program.program_id,
        expected_state=ProgramState.drafted,
        new_state=ProgramState.active,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )

    assert updated.program_state == ProgramState.active
    stored = repo.get_by_id(program.program_id)
    assert stored is not None
    assert stored.program_state == ProgramState.active
