"""Property-based test for the program lifecycle state machine.

Feature: coaching-programs, Property 4: Only allowed lifecycle transitions
succeed; all others leave state unchanged. For every (source, target) pair over
the four ``ProgramState`` values — all 4x4 = 16 combinations — a transition
requested by the Owning_Coach succeeds exactly when ``(source, target)`` is in
``ALLOWED_TRANSITIONS``: an allowed edge sets the Program_State to the target and
refreshes ``updated_at`` to a fresh ISO 8601 string (Requirement 3.1), while
every other edge — including an identical source/target or any edge out of
``archived`` — is rejected with HTTP 422 and leaves the stored Program_State
unchanged (Requirement 3.2).

Like the Property 5 / Property 6 tests, the property runs against the real
persistence path: the program is created through
``CoachingService.create_program`` and then seeded into the desired source state
directly in storage via ``ProgramRepository`` (``drafted`` is the only state
``create_program`` can produce), and the transition is driven through
``CoachingService.transition_state`` (writing through ``ProgramRepository`` to a
``moto``-backed DynamoDB engine). The outcome is asserted on both the returned
``ProgramResponse`` (on success) and the record read back from storage — so the
invariant holds for what callers see *and* for what is actually persisted.

Validates: Requirements 3.1, 3.2
"""

import os
from datetime import datetime
from decimal import Decimal

import boto3
import pytest
from fastapi import HTTPException, status
from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

from app.core.config import settings as app_settings
from app.models.program import (
    ALLOWED_TRANSITIONS,
    ProgramCreateRequest,
    ProgramState,
)
from app.repositories.program_repository import ProgramRepository
from app.services.coaching_service import CoachingService


# ──────────────────────────────────────────────────────────────────────────────
# Table creation — mirrors the programs table design (tasks 2.1 / 2.2), identical
# to the Property 5 / Property 6 tests.
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
# Generators
# ──────────────────────────────────────────────────────────────────────────────

# Coach identifiers are opaque non-empty strings (the JWT subject).
_coach_ids = st.text(
    alphabet=st.characters(blacklist_categories=("Cc", "Cs")),
    min_size=1,
    max_size=64,
).filter(lambda s: s.strip() != "")

# Titles 1–200 characters after trimming (same shape as the sibling tests).
_titles = st.text(
    alphabet=st.characters(blacklist_categories=("Cc", "Cs")),
    min_size=1,
    max_size=200,
).filter(lambda s: 1 <= len(s.strip()) <= 200)

# Descriptions 0–5000 characters (kept short to keep generation cheap).
_descriptions = st.text(
    alphabet=st.characters(blacklist_categories=("Cc", "Cs")),
    min_size=0,
    max_size=300,
)

# Valid prices: 0.00–999999.99 with at most two fractional digits.
_prices = st.decimals(
    min_value=Decimal("0.00"),
    max_value=Decimal("999999.99"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

# Enumerate ALL (source, target) ProgramState pairs — the full 4x4 = 16 grid.
_ALL_STATES = tuple(ProgramState)
_ALL_PAIRS = [
    (source, target) for source in _ALL_STATES for target in _ALL_STATES
]
assert len(_ALL_PAIRS) == 16

# Each example draws one of the 16 (source, target) pairs so, across runs, every
# edge — allowed and disallowed alike — is exercised.
_state_pairs = st.sampled_from(_ALL_PAIRS)


def _is_iso8601(value: str) -> bool:
    """True iff ``value`` parses as an ISO 8601 timestamp."""
    try:
        datetime.fromisoformat(value)
        return True
    except (TypeError, ValueError):
        return False


def _seed_source_state(
    repository: ProgramRepository, record_id: str, source: ProgramState
):
    """Place an existing program directly into ``source`` in storage.

    ``create_program`` can only produce ``drafted`` programs, so to exercise
    transitions *out of* ``active``/``paused``/``archived`` the stored record is
    rewritten into the desired source state (an ``update``/overwrite that leaves
    the program's identity untouched). Returns the refreshed record.
    """
    stored = repository.get_by_id(record_id)
    assert stored is not None
    seeded = stored.model_copy(update={"program_state": source})
    repository.update(seeded)
    return seeded


# ──────────────────────────────────────────────────────────────────────────────
# Property 4
# ──────────────────────────────────────────────────────────────────────────────


@settings(max_examples=100, deadline=None)
@given(
    coach_id=_coach_ids,
    title=_titles,
    description=_descriptions,
    price=_prices,
    pair=_state_pairs,
)
def test_only_allowed_transitions_succeed_others_leave_state_unchanged(
    coach_id, title, description, price, pair
):
    """Feature: coaching-programs, Property 4: Only allowed lifecycle
    transitions succeed; all others leave state unchanged.

    For a (source, target) pair drawn from the full 4x4 grid of ``ProgramState``
    values, seed an owned program into ``source`` and request a transition to
    ``target`` as the owner:
      * WHEN ``(source, target)`` is in ``ALLOWED_TRANSITIONS``, the transition
        succeeds — the Program_State becomes ``target`` and ``updated_at`` is a
        fresh ISO 8601 string not earlier than the prior value (Requirement
        3.1);
      * OTHERWISE — including an identical source/target or any edge out of
        ``archived`` — the transition is rejected with HTTP 422 and the stored
        Program_State is left unchanged (Requirement 3.2),
    and these hold for both the returned response (on success) and the record
    read back from storage.

    Validates: Requirements 3.1, 3.2
    """
    source, target = pair

    with mock_aws():
        dynamodb = boto3.resource("dynamodb")
        _create_programs_table(dynamodb)

        service = CoachingService()
        repository = ProgramRepository()

        # ── Seed: create a program, then force it into the source state ──────
        create_request = ProgramCreateRequest(
            title=title, description=description, price=price
        )
        created = service.create_program(coach_id=coach_id, payload=create_request)
        program_id = created.program_id
        original_created_at = created.created_at

        seeded = _seed_source_state(repository, program_id, source)
        prior_updated_at = seeded.updated_at
        assert seeded.program_state == source

        # ── Act: request the transition as the owning coach ──────────────────
        if (source, target) in ALLOWED_TRANSITIONS:
            # Allowed edge → state becomes target, updated_at refreshed (3.1).
            updated = service.transition_state(
                coach_id=coach_id,
                program_id=program_id,
                target_state=target,
            )

            assert updated.program_state == target
            assert _is_iso8601(updated.updated_at)
            # ISO 8601 UTC timestamps sort lexicographically in chronological
            # order, so a plain string comparison is a valid chronological one.
            assert updated.updated_at >= prior_updated_at
            # Identity and creation metadata are left untouched.
            assert updated.program_id == program_id
            assert updated.owner_coach_id == coach_id
            assert updated.created_at == original_created_at

            # The persisted record reflects the same transition.
            stored = repository.get_by_id(program_id)
            assert stored is not None
            assert stored.program_state == target
            assert stored.updated_at == updated.updated_at
            assert stored.created_at == original_created_at
        else:
            # Disallowed edge (incl. source == target and edges out of
            # archived) → 422, state unchanged (3.2).
            with pytest.raises(HTTPException) as exc_info:
                service.transition_state(
                    coach_id=coach_id,
                    program_id=program_id,
                    target_state=target,
                )
            assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

            # The stored Program_State is left exactly as it was seeded.
            stored = repository.get_by_id(program_id)
            assert stored is not None
            assert stored.program_state == source
            assert stored.updated_at == prior_updated_at
            assert stored.created_at == original_created_at
