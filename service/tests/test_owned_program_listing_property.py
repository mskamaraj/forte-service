"""Property-based test for owned-program listing.

Feature: coaching-programs, Property 5: Owned-program listing is exactly the
coach's programs. For any collection of programs created across several coaches,
``CoachingService.list_owned(coach_id)`` returns exactly the programs whose
``owner_coach_id`` equals the requesting coach — no more and no less — with each
returned program carrying its ``program_state`` (Requirement 4.1). A coach who
owns no programs receives an empty list (Requirement 4.1).

Like the Property 1 test, the property runs against the real persistence path:
programs are created through ``CoachingService.create_program`` (writing through
``ProgramRepository`` to a ``moto``-backed DynamoDB engine with the real
``owner-index`` GSI the listing queries), and ``list_owned`` reads them back via
``ProgramRepository.list_by_coach``. Asserting against what the service actually
persisted and queries — rather than a stub — exercises the GSI-backed listing
end to end.

Validates: Requirements 4.1
"""

import os
from decimal import Decimal

import boto3
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

from app.core.config import settings as app_settings
from app.models.program import ProgramCreateRequest, ProgramState
from app.services.coaching_service import CoachingService


# ──────────────────────────────────────────────────────────────────────────────
# Table creation — mirrors the programs table design (tasks 2.1 / 2.2), identical
# to the Property 1 test so the listing exercises the real ``owner-index`` GSI.
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
# Generators — valid programs, each owned by one of a small pool of coaches.
# ──────────────────────────────────────────────────────────────────────────────

# A small fixed pool of coach identifiers keeps generation focused on the
# listing invariant: with only a few owners, examples routinely spread programs
# across coaches so the "exactly this coach's programs" split is meaningful, and
# some coaches in the pool own nothing (the empty-list case).
_coach_pool = st.sampled_from(["coach-a", "coach-b", "coach-c"])

# Titles 1–200 characters after trimming (same shape as the Property 1 test).
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

# One program is an (owner, title, description, price) tuple.
_programs = st.tuples(_coach_pool, _titles, _descriptions, _prices)


# ──────────────────────────────────────────────────────────────────────────────
# Property 5
# ──────────────────────────────────────────────────────────────────────────────


@settings(max_examples=100, deadline=None)
@given(
    programs=st.lists(_programs, min_size=0, max_size=12),
    queried_coach=_coach_pool,
)
def test_owned_program_listing_is_exactly_the_coachs_programs(programs, queried_coach):
    """Feature: coaching-programs, Property 5: Owned-program listing is exactly
    the coach's programs.

    Create a collection of programs spread across several coaches, then for a
    queried coach assert that ``list_owned`` returns:
      * exactly the set of programs whose ``owner_coach_id`` equals the queried
        coach — no foreign programs, and none of the coach's own omitted
        (Requirement 4.1),
      * each program carrying its ``program_state`` (Requirement 4.1),
      * an empty list when the queried coach owns nothing (Requirement 4.1).

    Validates: Requirements 4.1
    """
    with mock_aws():
        dynamodb = boto3.resource("dynamodb")
        _create_programs_table(dynamodb)

        service = CoachingService()

        # Create every generated program, tracking which ids belong to which
        # coach so the expected owned set is known independently of the listing.
        expected_ids_by_coach: dict[str, set[str]] = {}
        for owner, title, description, price in programs:
            request = ProgramCreateRequest(
                title=title, description=description, price=price
            )
            created = service.create_program(coach_id=owner, payload=request)
            expected_ids_by_coach.setdefault(owner, set()).add(created.program_id)

        expected_ids = expected_ids_by_coach.get(queried_coach, set())

        owned = service.list_owned(queried_coach)

        # ── Exactly the queried coach's programs (Requirement 4.1) ────────────
        returned_ids = [p.program_id for p in owned]
        # No duplicates in the listing.
        assert len(returned_ids) == len(set(returned_ids))
        # Set equality: no more, no less than the coach's own programs.
        assert set(returned_ids) == expected_ids

        # Every returned program is actually owned by the queried coach — no
        # foreign program leaks in.
        for program in owned:
            assert program.owner_coach_id == queried_coach
            # ── Program_State is included for each program (Requirement 4.1) ──
            assert isinstance(program.program_state, ProgramState)
            # Newly created programs default to drafted; the listing preserves
            # that state rather than dropping or altering it.
            assert program.program_state == ProgramState.drafted

        # ── Empty list when the coach owns nothing (Requirement 4.1) ──────────
        if not expected_ids:
            assert owned == []
