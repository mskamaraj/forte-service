"""Property-based test for owner updates with a fresh timestamp.

Feature: coaching-programs, Property 6: Owner updates apply with a fresh
timestamp. For any program owned by a coach, a valid update submitted by that
owner replaces the targeted fields (title, description, price) with the new
values and sets ``updated_at`` to a fresh ISO 8601 timestamp strictly later than
or equal to the prior value, while the generated id, owner, state, and
``created_at`` are left unchanged (Requirement 4.8).

Like the Property 1 and Property 5 tests, the property runs against the real
persistence path: the program is created through
``CoachingService.create_program`` and updated through
``CoachingService.update_program`` (both writing through ``ProgramRepository``
to a ``moto``-backed DynamoDB engine), and the outcome is asserted on both the
returned ``ProgramResponse`` and the record read back from storage — so the
invariant holds for what callers see *and* for what is actually persisted.

Validates: Requirements 4.8
"""

import os
from datetime import datetime
from decimal import Decimal

import boto3
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
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
# to the Property 1 / Property 5 tests.
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
# Generators — valid inputs only (Property 6 concerns a *valid* owner update).
# ──────────────────────────────────────────────────────────────────────────────

# Coach identifiers are opaque non-empty strings (the JWT subject).
_coach_ids = st.text(
    alphabet=st.characters(blacklist_categories=("Cc", "Cs")),
    min_size=1,
    max_size=64,
).filter(lambda s: s.strip() != "")

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


def _is_iso8601(value: str) -> bool:
    """True iff ``value`` parses as an ISO 8601 timestamp."""
    try:
        datetime.fromisoformat(value)
        return True
    except (TypeError, ValueError):
        return False


# ──────────────────────────────────────────────────────────────────────────────
# Property 6
# ──────────────────────────────────────────────────────────────────────────────


@settings(max_examples=100, deadline=None)
@given(
    coach_id=_coach_ids,
    title=_titles,
    description=_descriptions,
    price=_prices,
    new_title=_titles,
    new_description=_descriptions,
    new_price=_prices,
)
def test_owner_update_applies_with_fresh_timestamp(
    coach_id, title, description, price, new_title, new_description, new_price
):
    """Feature: coaching-programs, Property 6: Owner updates apply with a fresh
    timestamp.

    Create a program owned by a coach, then submit a valid update as that owner.
    The update:
      * replaces title, description, and price with the submitted values
        (Requirement 4.8),
      * sets ``updated_at`` to a valid ISO 8601 string that is strictly later
        than or equal to the prior ``updated_at`` (Requirement 4.8),
      * leaves the id, owner, state, and ``created_at`` unchanged,
    and these hold for both the returned response and the record read back from
    storage.

    Validates: Requirements 4.8
    """
    with mock_aws():
        dynamodb = boto3.resource("dynamodb")
        _create_programs_table(dynamodb)

        service = CoachingService()

        # ── Seed: create the program the owner will later update ──────────────
        create_request = ProgramCreateRequest(
            title=title, description=description, price=price
        )
        created = service.create_program(coach_id=coach_id, payload=create_request)

        prior_updated_at = created.updated_at
        original_created_at = created.created_at
        original_id = created.program_id

        # The prior timestamp is itself a valid ISO 8601 string.
        assert _is_iso8601(prior_updated_at)

        # ── Act: a valid owner update ─────────────────────────────────────────
        update_request = ProgramUpdateRequest(
            title=new_title, description=new_description, price=new_price
        )
        updated = service.update_program(
            coach_id=coach_id,
            program_id=original_id,
            payload=update_request,
        )

        # ── Fields replaced with the new values (Requirement 4.8) ─────────────
        assert updated.title == update_request.title
        assert updated.description == update_request.description
        assert updated.price == update_request.price

        # ── Fresh ISO 8601 updated-at, not earlier than the prior value ───────
        # ISO 8601 UTC timestamps sort lexicographically in chronological order,
        # so a plain string comparison is a valid chronological comparison here.
        assert _is_iso8601(updated.updated_at)
        assert updated.updated_at >= prior_updated_at

        # ── Identity and creation metadata are left unchanged ─────────────────
        assert updated.program_id == original_id
        assert updated.owner_coach_id == coach_id
        assert updated.program_state == ProgramState.drafted
        assert updated.created_at == original_created_at

        # ── Same invariants for the *persisted* record ────────────────────────
        stored = ProgramRepository().get_by_id(original_id)
        assert stored is not None
        assert stored.title == update_request.title
        assert stored.description == update_request.description
        assert stored.price == update_request.price
        assert stored.updated_at == updated.updated_at
        assert _is_iso8601(stored.updated_at)
        assert stored.updated_at >= prior_updated_at
        assert stored.created_at == original_created_at
        assert stored.owner_coach_id == coach_id
        assert stored.program_state == ProgramState.drafted
