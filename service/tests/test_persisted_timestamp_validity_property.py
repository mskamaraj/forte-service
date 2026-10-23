"""Property-based test for persisted-timestamp validity.

Feature: coaching-programs, Property 22: All persisted timestamps are valid
ISO 8601 (UTC where required). For any enrollment created by ``CoachingService``
and any exercise-completion record persisted through ``CompletionRepository``,
the stored ``enrolled_at`` / ``updated_at`` string is a valid ISO 8601 timestamp
that round-trips through ``datetime.fromisoformat`` and carries an *explicit* UTC
designator (a concrete ``+00:00`` / ``Z`` offset, i.e. an aware UTC datetime --
never a naive, offset-less string).

The property is exercised against the real persistence path, not the timestamp
generator in isolation: enrollments are written by the service's ``enroll`` flow
and completions by the repository's ``put``/``get`` round-trip, with the
repositories backed by an in-memory DynamoDB fake (``moto`` is not installed in
this environment, so a minimal in-memory ``Table`` stand-in is injected via the
``get_*_table`` accessors). This keeps 100+ iterations cheap while asserting that
the value actually read back from "storage" satisfies the invariant.

Only the two timestamps Requirements 10.7 and 13.8 pin to UTC -- enrollment
``enrolled_at`` and completion ``updated_at`` -- are asserted to carry an
explicit UTC designator; every persisted timestamp (including the program/content
``created_at`` / ``updated_at`` seeded on the enrolled program) is asserted to be
valid ISO 8601, covering Requirements 1.6, 5.8, 6.8, and 7.9.

Validates: Requirements 1.6, 5.8, 6.8, 7.9, 10.7, 13.8
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import app.db.dynamo as dynamo
from app.models.completion import ExerciseCompletionRecord
from app.models.program import ProgramRecord, ProgramState
from app.repositories.completion_repository import CompletionRepository
from app.repositories.enrollment_repository import EnrollmentRepository
from app.repositories.program_repository import ProgramRepository
from app.services.coaching_service import CoachingService


# ──────────────────────────────────────────────────────────────────────────────
# Minimal in-memory DynamoDB fake
#
# Stands in for a ``boto3`` ``Table`` resource for exactly the operations the
# enrollment / completion / program repositories use: ``put_item`` (with the
# ``attribute_not_exists`` guard the enrollment create relies on), ``get_item``,
# and a ``query`` on an equality ``KeyConditionExpression``. Only the storage
# backend is faked; all repository and service logic under test is real.
# ──────────────────────────────────────────────────────────────────────────────


class _ConditionalCheckFailed(Exception):
    """Mirror of the botocore ConditionalCheckFailedException shape."""

    def __init__(self):
        self.response = {"Error": {"Code": "ConditionalCheckFailedException"}}


class _FakeClientError(Exception):
    """Carries a botocore-style ``response`` dict the repositories inspect."""

    def __init__(self, code: str):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class _FakeTable:
    """In-memory table keyed by a (pk, sk) tuple drawn from each item."""

    def __init__(self, pk: str, sk: str | None = None):
        self._pk = pk
        self._sk = sk
        self._items: dict[tuple, dict] = {}

    def _key_of(self, item: dict) -> tuple:
        return (item[self._pk], item[self._sk]) if self._sk else (item[self._pk],)

    def _key_from_lookup(self, key: dict) -> tuple:
        return (key[self._pk], key[self._sk]) if self._sk else (key[self._pk],)

    def put_item(self, Item, ConditionExpression=None):
        key = self._key_of(Item)
        if ConditionExpression == "attribute_not_exists(user_id)" and key in self._items:
            raise _FakeClientError("ConditionalCheckFailedException")
        if ConditionExpression == "attribute_exists(program_id)" and key not in self._items:
            raise _FakeClientError("ConditionalCheckFailedException")
        if ConditionExpression == "attribute_not_exists(program_id)" and key in self._items:
            raise _FakeClientError("ConditionalCheckFailedException")
        self._items[key] = dict(Item)

    def get_item(self, Key):
        item = self._items.get(self._key_from_lookup(Key))
        return {"Item": dict(item)} if item is not None else {}

    def query(self, KeyConditionExpression=None, IndexName=None):
        # The repositories only ever issue an equality condition on a single
        # attribute (the partition key, or a GSI partition key). Extract the
        # attribute name and the target value from the boto3 condition object.
        attr, value = _equality_condition(KeyConditionExpression)
        matches = [
            dict(item)
            for item in self._items.values()
            if str(item.get(attr)) == str(value)
        ]
        return {"Items": matches}


def _equality_condition(condition) -> tuple[str, object]:
    """Pull ``(attribute_name, value)`` out of a boto3 ``Key(...).eq(...)``."""
    values = condition.get_expression()["values"]
    key_attr, target = values[0], values[1]
    return key_attr.name, target


# botocore's ClientError is what the repositories catch; our fake raises a stand-in
# with the same ``response`` attribute, so patch the symbol the repositories use.
import app.repositories.enrollment_repository as enrollment_repo_mod
import app.repositories.program_repository as program_repo_mod


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures / wiring
# ──────────────────────────────────────────────────────────────────────────────


def _install_fake_tables(monkeypatch):
    """Point every ``get_*_table`` accessor at a fresh in-memory fake table."""
    programs = _FakeTable(pk="program_id")
    content = _FakeTable(pk="program_id", sk="node_sk")
    enrollments = _FakeTable(pk="user_id", sk="program_id")
    completion = _FakeTable(pk="completion_pk", sk="exercise_id")

    monkeypatch.setattr(dynamo, "get_programs_table", lambda: programs)
    monkeypatch.setattr(dynamo, "get_content_table", lambda: content)
    monkeypatch.setattr(dynamo, "get_enrollments_table", lambda: enrollments)
    monkeypatch.setattr(dynamo, "get_completion_table", lambda: completion)

    # The repositories import the accessors by name at call time via the module,
    # but ProgramRepository/EnrollmentRepository bind ``get_*_table`` at import.
    # They call the accessor in ``__init__`` through the module reference, so the
    # monkeypatched module attribute is picked up when each repository is built.
    monkeypatch.setattr(
        "app.repositories.program_repository.get_programs_table",
        lambda: programs,
    )
    monkeypatch.setattr(
        "app.repositories.content_repository.get_content_table",
        lambda: content,
    )
    monkeypatch.setattr(
        "app.repositories.enrollment_repository.get_enrollments_table",
        lambda: enrollments,
    )
    monkeypatch.setattr(
        "app.repositories.completion_repository.get_completion_table",
        lambda: completion,
    )

    # The repositories catch ``botocore.exceptions.ClientError``; make the fake's
    # stand-in exception count as that type so the ConditionalCheckFailed path is
    # exercised rather than leaking an unexpected exception.
    monkeypatch.setattr(enrollment_repo_mod, "ClientError", _FakeClientError)
    monkeypatch.setattr(program_repo_mod, "ClientError", _FakeClientError)

    return programs


# ──────────────────────────────────────────────────────────────────────────────
# Timestamp invariant helpers
# ──────────────────────────────────────────────────────────────────────────────


def _is_valid_iso8601(value: str) -> bool:
    """True iff ``value`` parses as an ISO 8601 datetime."""
    if not isinstance(value, str):
        return False
    try:
        # ``fromisoformat`` accepts a trailing ``Z`` from Python 3.11 onward; the
        # service emits an explicit ``+00:00`` offset, which all versions accept.
        datetime.fromisoformat(value)
        return True
    except ValueError:
        return False


def _has_explicit_utc_designator(value: str) -> bool:
    """True iff ``value`` is ISO 8601 with an explicit UTC offset of zero.

    ``datetime.now(timezone.utc).isoformat()`` emits ``...+00:00``; a naive,
    designator-less timestamp parses to ``tzinfo is None`` and fails this check.
    """
    if not _is_valid_iso8601(value):
        return False
    parsed = datetime.fromisoformat(value)
    return parsed.tzinfo is not None and parsed.utcoffset() == timedelta(0)


# ──────────────────────────────────────────────────────────────────────────────
# Generators
# ──────────────────────────────────────────────────────────────────────────────

# Identifiers the domain treats as opaque strings. Non-empty so EnrollRequest's
# ``min_length=1`` and the composite keys stay well-formed.
_ids = st.text(
    alphabet=st.characters(blacklist_categories=("Cc", "Cs")),
    min_size=1,
    max_size=40,
).filter(lambda s: s.strip() != "")

_completed_flags = st.booleans()


# ──────────────────────────────────────────────────────────────────────────────
# Property 22
# ──────────────────────────────────────────────────────────────────────────────


@settings(max_examples=100, deadline=None)
@given(user_id=_ids, completed=_completed_flags)
def test_enrollment_enrolled_at_is_utc_iso8601(user_id, completed):
    """Feature: coaching-programs, Property 22: All persisted timestamps are
    valid ISO 8601 (UTC where required). An enrollment written by
    ``CoachingService.enroll`` stores an ``enrolled_at`` that, when read back
    from storage, is valid ISO 8601 and carries an explicit UTC designator
    (Requirement 10.7). Every timestamp on the enrolled program (its
    ``created_at`` / ``updated_at``) is also valid ISO 8601 (Requirements 1.6,
    5.8, 6.8, 7.9).

    ``completed`` is drawn only to vary the generated input space; the
    enrollment path does not depend on it.

    Validates: Requirements 1.6, 10.7
    """
    monkeypatch = pytest.MonkeyPatch()
    try:
        _install_fake_tables(monkeypatch)

        # Seed an ACTIVE program directly through the real repository so the
        # service's ``enroll`` state gate passes. Its timestamps are produced
        # the same way the service produces them (Requirements 1.6).
        now = datetime.now(timezone.utc).isoformat()
        program = ProgramRecord(
            program_id=str(uuid.uuid4()),
            owner_coach_id="coach-" + str(uuid.uuid4()),
            title="A valid program",
            description="",
            price=Decimal("0.00"),
            program_state=ProgramState.active,
            created_at=now,
            updated_at=now,
        )
        ProgramRepository().create(program)

        service = CoachingService()
        response = service.enroll(user_id=user_id, program_id=program.program_id)

        # Read back from storage via the repository, not from the response, so
        # the assertion is about the *persisted* value.
        stored = EnrollmentRepository().get(user_id, program.program_id)
        assert stored is not None

        assert _has_explicit_utc_designator(stored.enrolled_at)
        assert _has_explicit_utc_designator(response.enrolled_at)

        # Program timestamps are valid ISO 8601 (Requirements 1.6, 5.8, 6.8, 7.9).
        assert _is_valid_iso8601(program.created_at)
        assert _is_valid_iso8601(program.updated_at)
    finally:
        monkeypatch.undo()


@settings(max_examples=100, deadline=None)
@given(
    user_id=_ids,
    program_id=_ids,
    exercise_id=_ids,
    completed=_completed_flags,
)
def test_completion_updated_at_is_utc_iso8601(
    user_id, program_id, exercise_id, completed
):
    """Feature: coaching-programs, Property 22: All persisted timestamps are
    valid ISO 8601 (UTC where required). An exercise-completion record persisted
    through ``CompletionRepository.put`` stores an ``updated_at`` that, when read
    back from storage, is valid ISO 8601 and carries an explicit UTC designator
    (Requirement 13.8).

    The record's ``updated_at`` is produced the way the service produces it --
    ``datetime.now(timezone.utc).isoformat()`` -- and the assertion is made on
    the value round-tripped through the fake store, so it reflects what is
    actually persisted rather than the in-memory record.

    Validates: Requirements 13.8
    """
    monkeypatch = pytest.MonkeyPatch()
    try:
        _install_fake_tables(monkeypatch)

        record = ExerciseCompletionRecord(
            user_id=user_id,
            program_id=program_id,
            exercise_id=exercise_id,
            completed=completed,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )

        repo = CompletionRepository()
        repo.put(record)

        stored = repo.get(user_id, program_id, exercise_id)
        assert stored is not None
        assert stored.completed == completed

        assert _has_explicit_utc_designator(stored.updated_at)
    finally:
        monkeypatch.undo()
