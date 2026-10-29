"""Integration tests for the content-read service methods.

Exercises ``CoachingService`` list/get methods for modules, chapters, and
exercises against moto-backed DynamoDB tables (programs, content, enrollments).
These back the six GET endpoints added to ``routes/programs.py``:

  GET /programs/{pid}/modules
  GET /programs/{pid}/modules/{mid}
  GET /programs/{pid}/modules/{mid}/chapters
  GET /programs/{pid}/modules/{mid}/chapters/{cid}
  GET /programs/{pid}/modules/{mid}/chapters/{cid}/exercises
  GET /programs/{pid}/modules/{mid}/chapters/{cid}/exercises/{eid}

Covered behaviours:
  * Ordering by (position, created_at) for every list method.
  * Owner coach and enrolled user both get read access.
  * A non-owning coach / non-enrolled user is refused with 403.
  * A missing program/node is 404, and a node fetched through the wrong parent
    chain is 404 (strict ancestry).
"""

import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import boto3
import pytest
from fastapi import HTTPException
from moto import mock_aws

from app.core.config import settings
from app.models.content import ContentNodeRecord, NodeType
from app.models.enrollment import EnrollmentRecord
from app.models.program import ProgramRecord, ProgramState
from app.models.user import Role, UserResponse
from app.repositories.content_repository import ContentRepository
from app.repositories.enrollment_repository import EnrollmentRepository
from app.repositories.program_repository import ProgramRepository
from app.services.coaching_service import CoachingService


# ── Table creation helpers (mirror the CDK table designs) ─────────────────────


def _create_programs_table(dynamodb):
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
                "KeySchema": [{"AttributeName": "owner_coach_id", "KeyType": "HASH"}],
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
    return dynamodb.create_table(
        TableName=settings.dynamodb_content_table,
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


def _create_enrollments_table(dynamodb):
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


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _aws_env():
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


COACH_ID = "coach-owner"
OTHER_COACH_ID = "coach-other"
ENROLLED_USER_ID = "user-enrolled"
STRANGER_USER_ID = "user-stranger"
PROGRAM_ID = "program-1"


def _coach(user_id: str = COACH_ID) -> UserResponse:
    now = datetime.now(timezone.utc).isoformat()
    return UserResponse(
        user_id=user_id,
        email=f"{user_id}@example.com",
        first_name="Co",
        last_name="Ach",
        role=Role.coach,
        is_active=True,
        is_verified=True,
        created_at=now,
        updated_at=now,
    )


def _user(user_id: str) -> UserResponse:
    now = datetime.now(timezone.utc).isoformat()
    return UserResponse(
        user_id=user_id,
        email=f"{user_id}@example.com",
        first_name="Us",
        last_name="Er",
        role=Role.user,
        is_active=True,
        is_verified=True,
        created_at=now,
        updated_at=now,
    )


def _node(node_type, node_id, parent_id, position, created_at):
    return ContentNodeRecord(
        program_id=PROGRAM_ID,
        node_type=node_type,
        node_id=node_id,
        parent_id=parent_id,
        title=f"{node_type.value}-{node_id}",
        position=position,
        prompt="do it" if node_type == NodeType.exercise else None,
        created_at=created_at,
    )


@pytest.fixture
def seeded():
    """Seed a program with two modules, a chapter, and two exercises."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb")
        _create_programs_table(dynamodb)
        _create_content_table(dynamodb)
        _create_enrollments_table(dynamodb)

        now = datetime.now(timezone.utc).isoformat()
        ProgramRepository().create(
            ProgramRecord(
                program_id=PROGRAM_ID,
                owner_coach_id=COACH_ID,
                title="Prog",
                description="",
                price=Decimal("0.00"),
                program_state=ProgramState.active,
                created_at=now,
                updated_at=now,
            )
        )

        content = ContentRepository()
        # Two modules with deliberately out-of-order positions to test sorting.
        content.create(_node(NodeType.module, "m2", None, 2, now))
        content.create(_node(NodeType.module, "m1", None, 1, now))
        # One chapter under m1.
        content.create(_node(NodeType.chapter, "c1", "m1", 1, now))
        # Two exercises under c1, positions out of order.
        content.create(_node(NodeType.exercise, "e2", "c1", 2, now))
        content.create(_node(NodeType.exercise, "e1", "c1", 1, now))

        # Enroll one user.
        EnrollmentRepository().create(
            EnrollmentRecord(
                user_id=ENROLLED_USER_ID,
                program_id=PROGRAM_ID,
                enrollment_id=str(uuid.uuid4()),
                enrolled_at=now,
            )
        )

        yield CoachingService()


# ── List ordering + content ──────────────────────────────────────────────────


def test_list_modules_ordered(seeded):
    modules = seeded.list_modules(_coach(), PROGRAM_ID)
    assert [m.module_id for m in modules] == ["m1", "m2"]


def test_get_module(seeded):
    module = seeded.get_module(_coach(), PROGRAM_ID, "m1")
    assert module.module_id == "m1"


def test_list_chapters(seeded):
    chapters = seeded.list_chapters(_coach(), PROGRAM_ID, "m1")
    assert [c.chapter_id for c in chapters] == ["c1"]


def test_get_chapter(seeded):
    chapter = seeded.get_chapter(_coach(), PROGRAM_ID, "m1", "c1")
    assert chapter.chapter_id == "c1"


def test_list_exercises_ordered(seeded):
    exercises = seeded.list_exercises(_coach(), PROGRAM_ID, "m1", "c1")
    assert [e.exercise_id for e in exercises] == ["e1", "e2"]


def test_get_exercise(seeded):
    exercise = seeded.get_exercise(_coach(), PROGRAM_ID, "m1", "c1", "e1")
    assert exercise.exercise_id == "e1"
    assert exercise.prompt == "do it"


# ── Access control ────────────────────────────────────────────────────────────


def test_enrolled_user_can_read(seeded):
    modules = seeded.list_modules(_user(ENROLLED_USER_ID), PROGRAM_ID)
    assert {m.module_id for m in modules} == {"m1", "m2"}


def test_non_enrolled_user_is_403(seeded):
    with pytest.raises(HTTPException) as exc:
        seeded.list_modules(_user(STRANGER_USER_ID), PROGRAM_ID)
    assert exc.value.status_code == 403


def test_non_owning_coach_is_403(seeded):
    with pytest.raises(HTTPException) as exc:
        seeded.list_modules(_coach(OTHER_COACH_ID), PROGRAM_ID)
    assert exc.value.status_code == 403


# ── Not-found / strict ancestry ───────────────────────────────────────────────


def test_missing_program_is_404(seeded):
    with pytest.raises(HTTPException) as exc:
        seeded.list_modules(_coach(), "no-such-program")
    assert exc.value.status_code == 404


def test_missing_module_is_404(seeded):
    with pytest.raises(HTTPException) as exc:
        seeded.get_module(_coach(), PROGRAM_ID, "no-such-module")
    assert exc.value.status_code == 404


def test_chapter_under_wrong_module_is_404(seeded):
    # c1 belongs to m1, not m2 — strict ancestry rejects it.
    with pytest.raises(HTTPException) as exc:
        seeded.get_chapter(_coach(), PROGRAM_ID, "m2", "c1")
    assert exc.value.status_code == 404


def test_exercise_under_wrong_chapter_is_404(seeded):
    # e1 belongs to c1; fetching it through a non-existent chapter path is 404.
    with pytest.raises(HTTPException) as exc:
        seeded.get_exercise(_coach(), PROGRAM_ID, "m1", "no-such-chapter", "e1")
    assert exc.value.status_code == 404


# ── Delete (coach-only, no cascade) ───────────────────────────────────────────


def test_delete_exercise_removes_leaf(seeded):
    # e1 is a leaf under c1; deleting it leaves only e2.
    seeded.delete_exercise(COACH_ID, PROGRAM_ID, "m1", "c1", "e1")
    remaining = seeded.list_exercises(_coach(), PROGRAM_ID, "m1", "c1")
    assert [e.exercise_id for e in remaining] == ["e2"]


def test_delete_chapter_with_exercises_is_409(seeded):
    # c1 still has exercises e1, e2.
    with pytest.raises(HTTPException) as exc:
        seeded.delete_chapter(COACH_ID, PROGRAM_ID, "m1", "c1")
    assert exc.value.status_code == 409
    # Chapter is untouched.
    assert [c.chapter_id for c in seeded.list_chapters(_coach(), PROGRAM_ID, "m1")] == ["c1"]


def test_delete_chapter_after_emptying_succeeds(seeded):
    seeded.delete_exercise(COACH_ID, PROGRAM_ID, "m1", "c1", "e1")
    seeded.delete_exercise(COACH_ID, PROGRAM_ID, "m1", "c1", "e2")
    seeded.delete_chapter(COACH_ID, PROGRAM_ID, "m1", "c1")
    assert seeded.list_chapters(_coach(), PROGRAM_ID, "m1") == []


def test_delete_module_with_chapters_is_409(seeded):
    # m1 still has chapter c1.
    with pytest.raises(HTTPException) as exc:
        seeded.delete_module(COACH_ID, PROGRAM_ID, "m1")
    assert exc.value.status_code == 409


def test_delete_empty_module_succeeds(seeded):
    # m2 has no chapters.
    seeded.delete_module(COACH_ID, PROGRAM_ID, "m2")
    assert [m.module_id for m in seeded.list_modules(_coach(), PROGRAM_ID)] == ["m1"]


def test_delete_module_missing_is_404(seeded):
    with pytest.raises(HTTPException) as exc:
        seeded.delete_module(COACH_ID, PROGRAM_ID, "no-such-module")
    assert exc.value.status_code == 404


def test_delete_exercise_non_owner_is_403(seeded):
    with pytest.raises(HTTPException) as exc:
        seeded.delete_exercise(OTHER_COACH_ID, PROGRAM_ID, "m1", "c1", "e1")
    assert exc.value.status_code == 403


def test_delete_chapter_wrong_module_is_404(seeded):
    # c1 belongs to m1, not m2 — strict ancestry rejects the delete.
    with pytest.raises(HTTPException) as exc:
        seeded.delete_chapter(COACH_ID, PROGRAM_ID, "m2", "c1")
    assert exc.value.status_code == 404


# ── Module description field ──────────────────────────────────────────────────


def test_create_module_persists_description(seeded):
    from app.models.content import ModuleCreateRequest

    created = seeded.create_module(
        COACH_ID, PROGRAM_ID, ModuleCreateRequest(title="M3", description="Intro week", position=3)
    )
    assert created.description == "Intro week"

    # And it round-trips on read.
    fetched = seeded.get_module(_coach(), PROGRAM_ID, created.module_id)
    assert fetched.description == "Intro week"


def test_create_module_description_defaults_empty(seeded):
    from app.models.content import ModuleCreateRequest

    created = seeded.create_module(
        COACH_ID, PROGRAM_ID, ModuleCreateRequest(title="M4", position=4)
    )
    assert created.description == ""


def test_update_module_description(seeded):
    from app.models.content import ModuleUpdateRequest

    updated = seeded.update_module(
        COACH_ID, PROGRAM_ID, "m1", ModuleUpdateRequest(description="Updated summary")
    )
    assert updated.description == "Updated summary"
    # Title is untouched by a description-only update.
    assert updated.title == "module-m1"


def test_existing_module_without_description_reads_as_empty(seeded):
    # m1 was seeded via a raw ContentNodeRecord with no description, mirroring
    # pre-existing data. It must read back as "" rather than failing.
    fetched = seeded.get_module(_coach(), PROGRAM_ID, "m1")
    assert fetched.description == ""
