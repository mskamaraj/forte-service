"""Unit tests for program/transition not-found and Requirement 3.8 precedence.

These are EXAMPLE-criteria tests (not property tests) covering the error paths
of ``CoachingService`` for a single Program:

1. ``get_owned`` / ``update_program`` / ``transition_state`` against a Program
   that does not exist each raise ``HTTPException`` 404 (Requirements 4.3, 4.4,
   3.4).
2. Targeted adjacent-boundary tests for the Requirement 3.8 rejection ordering
   that this layer owns — Program not found (404) → requester not Owning_Coach
   (403) → invalid target state value (422) → disallowed transition (422). The
   401 token and 403 role checks sit in ``api/deps.py`` (upstream of the
   service) and are covered by the auth-boundary unit tests; here we verify that
   when two *service-owned* conditions apply at once, the earlier one wins.

Like the sibling property tests, these run against the real persistence path: a
``moto``-backed DynamoDB engine with the programs table created per the task
2.1 / 2.2 design, programs seeded through ``CoachingService.create_program`` and
``ProgramRepository`` (the only way to reach non-``drafted`` source states), and
assertions made on the raised ``HTTPException`` plus the record read back from
storage so a rejection is confirmed to leave the Program unchanged.

Validates: Requirements 3.4, 3.8, 4.3, 4.4
"""

import os
from decimal import Decimal

import boto3
import pytest
from fastapi import HTTPException, status
from moto import mock_aws

from app.core.config import settings as app_settings
from app.models.program import (
    ProgramCreateRequest,
    ProgramState,
    ProgramUpdateRequest,
)
from app.repositories.program_repository import ProgramRepository
from app.services.coaching_service import CoachingService


# ──────────────────────────────────────────────────────────────────────────────
# Table creation — mirrors the programs table design (tasks 2.1 / 2.2), identical
# to the Property 4 / 5 / 6 tests.
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


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _aws_env():
    """Pin a region and dummy credentials so the table created here and the
    repository's own ``boto3.resource("dynamodb")`` resolve to the same
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
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

_OWNER = "coach-owner"
_OTHER = "coach-other"
_MISSING_PROGRAM_ID = "00000000-0000-0000-0000-000000000000"


def _seed_program(
    service: CoachingService,
    repository: ProgramRepository,
    *,
    owner: str = _OWNER,
    state: ProgramState = ProgramState.drafted,
):
    """Create a program owned by ``owner`` and force it into ``state``.

    ``create_program`` can only produce ``drafted`` programs, so to reach
    ``active`` / ``paused`` / ``archived`` source states the stored record is
    rewritten (an ``update``/overwrite that leaves identity untouched). Returns
    the stored ``ProgramRecord``.
    """
    created = service.create_program(
        coach_id=owner,
        payload=ProgramCreateRequest(
            title="A Program", description="desc", price=Decimal("10.00")
        ),
    )
    if state is not ProgramState.drafted:
        stored = repository.get_by_id(created.program_id)
        assert stored is not None
        repository.update(stored.model_copy(update={"program_state": state}))
    return repository.get_by_id(created.program_id)


# ──────────────────────────────────────────────────────────────────────────────
# 1. Not-found → 404 for get / update / transition (Requirements 4.3, 4.4, 3.4)
# ──────────────────────────────────────────────────────────────────────────────


def test_get_owned_missing_program_is_404():
    """A single-program read against a Program that does not exist → 404
    (Requirement 4.3)."""
    with mock_aws():
        _create_programs_table(boto3.resource("dynamodb"))
        service = CoachingService()

        with pytest.raises(HTTPException) as exc_info:
            service.get_owned(coach_id=_OWNER, program_id=_MISSING_PROGRAM_ID)

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


def test_update_program_missing_program_is_404():
    """An update against a Program that does not exist → 404 (Requirement
    4.4)."""
    with mock_aws():
        _create_programs_table(boto3.resource("dynamodb"))
        service = CoachingService()

        with pytest.raises(HTTPException) as exc_info:
            service.update_program(
                coach_id=_OWNER,
                program_id=_MISSING_PROGRAM_ID,
                payload=ProgramUpdateRequest(
                    title="New", description="d", price=Decimal("1.00")
                ),
            )

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


def test_transition_state_missing_program_is_404():
    """A state transition against a Program that does not exist → 404
    (Requirement 3.4)."""
    with mock_aws():
        _create_programs_table(boto3.resource("dynamodb"))
        service = CoachingService()

        with pytest.raises(HTTPException) as exc_info:
            service.transition_state(
                coach_id=_OWNER,
                program_id=_MISSING_PROGRAM_ID,
                target_state=ProgramState.active,
            )

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


# ──────────────────────────────────────────────────────────────────────────────
# 2. Requirement 3.8 precedence — adjacent-boundary tests.
#
# Service-owned order (the 401/403-role checks are upstream in deps.py):
#   Program not found (404) → not Owning_Coach (403) → invalid target (422)
#   → disallowed transition (422).
# Each test makes TWO adjacent conditions true at once and asserts the earlier
# one wins.
# ──────────────────────────────────────────────────────────────────────────────


def test_precedence_not_found_beats_owner_check():
    """404 (not found) precedes 403 (not owner): a transition against a missing
    Program requested by a non-owner is reported 404, not 403 (Requirement
    3.8)."""
    with mock_aws():
        _create_programs_table(boto3.resource("dynamodb"))
        service = CoachingService()

        # Program does not exist AND the requester would not be its owner.
        with pytest.raises(HTTPException) as exc_info:
            service.transition_state(
                coach_id=_OTHER,
                program_id=_MISSING_PROGRAM_ID,
                target_state=ProgramState.active,
            )

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


def test_precedence_not_found_beats_invalid_target_and_disallowed_edge():
    """404 (not found) precedes both 422 conditions: a missing Program with an
    invalid target value is still reported 404 (Requirement 3.8)."""
    with mock_aws():
        _create_programs_table(boto3.resource("dynamodb"))
        service = CoachingService()

        # Program does not exist AND the target value is garbage (would be 422
        # invalid-target) — not-found must win.
        with pytest.raises(HTTPException) as exc_info:
            service.transition_state(
                coach_id=_OWNER,
                program_id=_MISSING_PROGRAM_ID,
                target_state="not-a-real-state",
            )

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


def test_precedence_owner_beats_invalid_target():
    """403 (not owner) precedes 422 (invalid target): an existing Program
    addressed by a non-owner with an invalid target value is reported 403, and
    the stored Program is left unchanged (Requirement 3.8)."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb")
        _create_programs_table(dynamodb)
        service = CoachingService()
        repository = ProgramRepository()

        seeded = _seed_program(
            service, repository, owner=_OWNER, state=ProgramState.drafted
        )

        # Existing program, non-owner requester, AND a garbage target value.
        with pytest.raises(HTTPException) as exc_info:
            service.transition_state(
                coach_id=_OTHER,
                program_id=seeded.program_id,
                target_state="not-a-real-state",
            )

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

        # State left unchanged on rejection.
        stored = repository.get_by_id(seeded.program_id)
        assert stored is not None
        assert stored.program_state == ProgramState.drafted


def test_precedence_owner_beats_disallowed_edge():
    """403 (not owner) precedes 422 (disallowed edge): an existing Program
    addressed by a non-owner with a disallowed (but valid) target is reported
    403, and the stored Program is left unchanged (Requirement 3.8)."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb")
        _create_programs_table(dynamodb)
        service = CoachingService()
        repository = ProgramRepository()

        # archived is terminal: (archived, active) is a disallowed edge.
        seeded = _seed_program(
            service, repository, owner=_OWNER, state=ProgramState.archived
        )

        with pytest.raises(HTTPException) as exc_info:
            service.transition_state(
                coach_id=_OTHER,
                program_id=seeded.program_id,
                target_state=ProgramState.active,
            )

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

        stored = repository.get_by_id(seeded.program_id)
        assert stored is not None
        assert stored.program_state == ProgramState.archived


def test_precedence_invalid_target_beats_disallowed_edge():
    """422 (invalid target) precedes 422 (disallowed edge): for the owner of an
    archived Program (every edge out of archived is disallowed), an invalid
    target *value* is reported as the invalid-target 422 — distinguished by its
    message — rather than the disallowed-transition 422, and the stored Program
    is left unchanged (Requirement 3.8)."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb")
        _create_programs_table(dynamodb)
        service = CoachingService()
        repository = ProgramRepository()

        # Owner + archived source: any target is a disallowed edge, so the only
        # thing distinguishing the two 422 branches is the invalid-target check
        # running first.
        seeded = _seed_program(
            service, repository, owner=_OWNER, state=ProgramState.archived
        )

        with pytest.raises(HTTPException) as exc_info:
            service.transition_state(
                coach_id=_OWNER,
                program_id=seeded.program_id,
                target_state="not-a-real-state",
            )

        assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        # The invalid-target branch — not the disallowed-edge branch — fired.
        assert exc_info.value.detail == "Invalid target state"

        stored = repository.get_by_id(seeded.program_id)
        assert stored is not None
        assert stored.program_state == ProgramState.archived


def test_disallowed_edge_reports_its_own_422_for_a_valid_target():
    """Boundary neighbour of the test above: with the owner and a *valid* target
    that is nonetheless a disallowed edge (archived→active), the disallowed-edge
    422 fires — a distinct message from the invalid-target 422 — confirming the
    two branches are separable (Requirement 3.8)."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb")
        _create_programs_table(dynamodb)
        service = CoachingService()
        repository = ProgramRepository()

        seeded = _seed_program(
            service, repository, owner=_OWNER, state=ProgramState.archived
        )

        with pytest.raises(HTTPException) as exc_info:
            service.transition_state(
                coach_id=_OWNER,
                program_id=seeded.program_id,
                target_state=ProgramState.active,
            )

        assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        # The disallowed-edge branch, not the invalid-target branch.
        assert exc_info.value.detail != "Invalid target state"

        stored = repository.get_by_id(seeded.program_id)
        assert stored is not None
        assert stored.program_state == ProgramState.archived
