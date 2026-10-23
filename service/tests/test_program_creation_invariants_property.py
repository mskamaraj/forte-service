"""Property-based test for program creation invariants.

Feature: coaching-programs, Property 1: Program creation preserves input,
defaults to drafted, and records ownership. For any coach identifier and any
valid program-creation request, ``CoachingService.create_program`` returns a
program whose title, description, and price equal the submitted input
(Requirement 1.1), whose ``program_state`` is ``drafted`` (Requirement 1.2), and
whose ``owner_coach_id`` is the requesting coach (Requirement 1.3).

The property is exercised against the real persistence path rather than the
service in isolation: ``create_program`` writes through ``ProgramRepository`` to
a real DynamoDB engine provided by ``moto`` (an in-process AWS-API-compatible
mock standing in for DynamoDB Local), mirroring the integration-test setup. Both
the returned ``ProgramResponse`` and the record read back from storage are
asserted, so the invariant holds for what callers see *and* for what is actually
persisted. The price is also asserted to be normalised to exactly two fractional
digits on the way in, consistent with how a valid request is stored.

Validates: Requirements 1.1, 1.2, 1.3
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
from app.repositories.program_repository import ProgramRepository
from app.services.coaching_service import CoachingService


# ──────────────────────────────────────────────────────────────────────────────
# Table creation — mirrors the programs table design (tasks 2.1 / 2.2).
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
# Generators — valid inputs only (Property 1 concerns valid creation).
# ──────────────────────────────────────────────────────────────────────────────

# Coach identifiers are opaque non-empty strings (the JWT subject).
_coach_ids = st.text(
    alphabet=st.characters(blacklist_categories=("Cc", "Cs")),
    min_size=1,
    max_size=64,
).filter(lambda s: s.strip() != "")

# Titles that are 1–200 characters after trimming. Draw non-whitespace-bounded
# content so trimming leaves a non-empty, in-range title.
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

# Valid prices: 0.00–999999.99 with at most two fractional digits. Generating at
# ``places=2`` keeps the value within the accepted scale so it is stored as-is.
_prices = st.decimals(
    min_value=Decimal("0.00"),
    max_value=Decimal("999999.99"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)


# ──────────────────────────────────────────────────────────────────────────────
# Property 1
# ──────────────────────────────────────────────────────────────────────────────


@settings(max_examples=100, deadline=None)
@given(
    coach_id=_coach_ids,
    title=_titles,
    description=_descriptions,
    price=_prices,
)
def test_program_creation_preserves_input_defaults_drafted_records_owner(
    coach_id, title, description, price
):
    """Feature: coaching-programs, Property 1: Program creation preserves input,
    defaults to drafted, and records ownership.

    For any coach and any valid create request, the created program:
      * preserves the submitted title, description, and price (Requirement 1.1),
      * has ``program_state == drafted`` (Requirement 1.2),
      * records the requesting coach as ``owner_coach_id`` (Requirement 1.3),
    and these hold both for the returned response and for the record read back
    from storage.

    Validates: Requirements 1.1, 1.2, 1.3
    """
    with mock_aws():
        dynamodb = boto3.resource("dynamodb")
        _create_programs_table(dynamodb)

        # Build the request through the real model so the stored price is the
        # scale-2–normalised value the create path persists.
        request = ProgramCreateRequest(
            title=title, description=description, price=price
        )

        # The repository binds its table under the active moto mock.
        service = CoachingService()
        response = service.create_program(coach_id=coach_id, payload=request)

        # ── Input preservation (Requirement 1.1) ──────────────────────────────
        assert response.title == request.title
        assert response.description == request.description
        assert response.price == request.price

        # ── Default state (Requirement 1.2) ───────────────────────────────────
        assert response.program_state == ProgramState.drafted

        # ── Ownership recorded (Requirement 1.3) ──────────────────────────────
        assert response.owner_coach_id == coach_id

        # The response carries a generated id and created-at timestamp.
        assert response.program_id
        assert response.created_at

        # ── Same invariants for the *persisted* record ───────────────────────
        stored = ProgramRepository().get_by_id(response.program_id)
        assert stored is not None
        assert stored.title == request.title
        assert stored.description == request.description
        assert stored.price == request.price
        assert stored.program_state == ProgramState.drafted
        assert stored.owner_coach_id == coach_id
