"""Business logic for the coaching-programs domain.

Mirrors :class:`app.services.auth_service.AuthService`: the service orchestrates
the repository layer, raises ``fastapi.HTTPException`` with explicit status
codes, and maps internal Records to public Responses via private
``_to_*_response`` helpers. Field-level validation (Requirement 2) is enforced
by the Pydantic request models before a handler reaches this layer, so by the
time the service runs it only applies ownership and existence rules.
"""

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status

from app.models.content import (
    ChapterCreateRequest,
    ChapterNode,
    ChapterResponse,
    ChapterUpdateRequest,
    CompletionSummary,
    ContentNodeRecord,
    ContentTreeResponse,
    ExerciseCreateRequest,
    ExerciseNode,
    ExerciseResponse,
    ExerciseUpdateRequest,
    ModuleCreateRequest,
    ModuleNode,
    ModuleResponse,
    ModuleUpdateRequest,
    NodeType,
)
from app.models.completion import (
    ExerciseCompletionRecord,
    ExerciseCompletionResponse,
)
from app.models.enrollment import (
    EnrollmentRecord,
    EnrollmentResponse,
)
from app.models.program import (
    ALLOWED_TRANSITIONS,
    ProgramCreateRequest,
    ProgramRecord,
    ProgramResponse,
    ProgramState,
    ProgramUpdateRequest,
)
from app.repositories.completion_repository import CompletionRepository
from app.repositories.content_repository import ContentRepository
from app.repositories.enrollment_repository import EnrollmentRepository
from app.repositories.program_repository import ProgramRepository
from app.models.user import Role, UserResponse


class CoachingService:

    def __init__(self):
        self._programs = ProgramRepository()
        self._content = ContentRepository()
        self._enrollments = EnrollmentRepository()
        self._completion = CompletionRepository()

    # ── Program create / list / get / update ────────────────────────────────

    def create_program(
        self, coach_id: str, payload: ProgramCreateRequest
    ) -> ProgramResponse:
        """Create a program owned by ``coach_id``.

        The new program defaults to ``drafted`` (Requirement 1.2), records the
        requesting coach as the owner (Requirement 1.3), and is assigned a
        generated id plus ISO 8601 created/updated timestamps (Requirements 1.1,
        1.6).
        """
        now = datetime.now(timezone.utc).isoformat()
        record = ProgramRecord(
            program_id=str(uuid.uuid4()),
            owner_coach_id=coach_id,
            title=payload.title,
            description=payload.description,
            price=payload.price,
            program_state=ProgramState.drafted,
            created_at=now,
            updated_at=now,
        )
        saved = self._programs.create(record)
        return _to_program_response(saved)

    def list_owned(self, coach_id: str) -> list[ProgramResponse]:
        """Return the programs owned by ``coach_id``, or an empty list when the
        coach owns none (Requirement 4.1).
        """
        records = self._programs.list_by_coach(coach_id)
        return [_to_program_response(r) for r in records]

    def list_active_programs(self) -> list[ProgramResponse]:
        """Return every ``active`` program for the browse catalogue.

        Delegates to ``ProgramRepository.list_active`` — a query on the
        ``state-index`` GSI keyed on ``program_state == "active"`` (no table
        scan) — so only active programs are returned, each exposing its title,
        description, price, and state via ``_to_program_response`` (Requirements
        9.1, 9.2, 9.3).
        """
        records = self._programs.list_active()
        return [_to_program_response(r) for r in records]

    def list_enrolled(self, user_id: str) -> list[ProgramResponse]:
        """Return the programs a user is enrolled in, most recent first.

        Joins the user's enrollments to their programs: the enrollments are
        fetched with ``EnrollmentRepository.list_by_user`` and each is resolved
        to its program via ``ProgramRepository.get_by_id``. Programs are
        included regardless of lifecycle state — a ``paused`` or ``archived``
        program an enrolled user still owns access to is kept, not filtered
        (Requirement 11.2). The result is ordered by the enrollment's
        ``enrolled_at`` timestamp descending so the most recently enrolled
        program comes first (Requirement 11.3), and an empty list is returned
        when the user has no enrollments (Requirement 11.1).
        """
        enrollments = self._enrollments.list_by_user(user_id)
        # Most recently enrolled first. ISO 8601 UTC timestamps sort
        # lexicographically in chronological order, so a reverse string sort
        # yields descending chronological order.
        enrollments.sort(key=lambda e: e.enrolled_at, reverse=True)

        responses: list[ProgramResponse] = []
        for enrollment in enrollments:
            program = self._programs.get_by_id(enrollment.program_id)
            if program is not None:
                responses.append(_to_program_response(program))
        return responses

    def enroll(self, user_id: str, program_id: str) -> EnrollmentResponse:
        """Enroll ``user_id`` in ``program_id``, gating on program state.

        Applies the Requirement 10 rejection precedence (the 401 token check is
        enforced earlier by ``require_user`` in ``deps.py``):

        1. 404 when the program does not exist (Requirement 10.4),
        2. 409 "not open for enrollment" when the program's state is not
           ``active`` — i.e. ``drafted``/``paused``/``archived`` — a message
           distinct from the duplicate case (Requirement 10.2),
        3. the enrollment is written through ``EnrollmentRepository.create``,
           whose ``ConditionExpression="attribute_not_exists(user_id)"`` on the
           composite key makes a duplicate — or a losing racer under concurrency
           — fail conditionally; the repository surfaces that as ``ValueError``,
           which maps to 409 "already enrolled", a message distinct from the
           not-open case (Requirements 10.3, 10.8).

        On success a generated enrollment id and a UTC ISO 8601 ``enrolled_at``
        timestamp (second-or-finer precision, explicit UTC designator) are
        persisted and returned as a 201 ``EnrollmentResponse`` (Requirements
        10.1, 10.7). Because the conditional write is the single point of
        uniqueness, two concurrent enrollments for the same (user, active
        program) yield exactly one success and one 409 duplicate (Requirement
        10.8).
        """
        program = self._programs.get_by_id(program_id)
        if program is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Program not found",
            )
        if program.program_state != ProgramState.active:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Program is not open for enrollment",
            )

        record = EnrollmentRecord(
            user_id=user_id,
            program_id=program_id,
            enrollment_id=str(uuid.uuid4()),
            enrolled_at=datetime.now(timezone.utc).isoformat(),
        )
        try:
            saved = self._enrollments.create(record)
        except ValueError:
            # The conditional write failed: an enrollment with this composite
            # key already exists (duplicate or losing racer under concurrency).
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="You are already enrolled in this program",
            )
        return _to_enrollment_response(saved)

    def get_owned(self, coach_id: str, program_id: str) -> ProgramResponse:
        """Return a single program the requesting coach owns.

        Raises 404 when the program does not exist (Requirement 4.3) and 403
        when the requester is not the owning coach (Requirement 4.5).
        """
        record = self._get_owned_record(coach_id, program_id)
        return _to_program_response(record)

    def update_program(
        self, coach_id: str, program_id: str, payload: ProgramUpdateRequest
    ) -> ProgramResponse:
        """Update an owned program's title, description, and price.

        Enforces 404 for a missing program (Requirement 4.4) then owner-only
        access (Requirement 4.6) before applying any change, so a non-owner
        leaves the stored program unchanged. The request model has already
        validated the Requirement 2 field rules (Requirements 4.8, 4.9). On
        success the updated-at timestamp is refreshed (Requirement 4.8).
        """
        record = self._get_owned_record(coach_id, program_id)

        updated = record.model_copy(
            update={
                "title": payload.title,
                "description": payload.description,
                "price": payload.price,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        saved = self._programs.update(updated)
        return _to_program_response(saved)

    # ── Lifecycle ───────────────────────────────────────────────────────────

    def transition_state(
        self, coach_id: str, program_id: str, target_state: ProgramState
    ) -> ProgramResponse:
        """Move an owned program to ``target_state`` along the lifecycle.

        Applies the rejection precedence of Requirement 3.8 for the conditions
        this layer owns (the 401 token and 403 role checks are enforced earlier
        by ``require_coach`` in ``deps.py``):

        1. 404 when the program does not exist (Requirement 3.4),
        2. 403 when the requester is not the Owning_Coach (Requirement 3.5),
        3. 422 when ``target_state`` is not a ``ProgramState`` value
           (Requirement 3.3),
        4. 422 when ``(current, target)`` is not an allowed edge — including an
           identical source/target or any edge out of ``archived``
           (Requirements 3.1, 3.2).

        The program is left unchanged on every rejection; on success the
        conditional repository write sets the new state and refreshes
        ``updated_at`` to an ISO 8601 timestamp (Requirement 3.1).
        """
        # 404 missing → 403 non-owner (reuses the shared ownership guard).
        record = self._get_owned_record(coach_id, program_id)

        # Invalid-target precedes disallowed-edge (Requirement 3.8). The route's
        # ProgramStateTransitionRequest already coerces non-enum values to 422,
        # but the service guards the type so direct callers get the same answer.
        if not isinstance(target_state, ProgramState):
            try:
                target_state = ProgramState(target_state)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Invalid target state",
                )

        # Disallowed edge (including identical source/target and any edge out of
        # archived) → 422, state unchanged (Requirements 3.1, 3.2).
        if (record.program_state, target_state) not in ALLOWED_TRANSITIONS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Cannot transition program from '{record.program_state.value}' "
                    f"to '{target_state.value}'"
                ),
            )

        saved = self._programs.transition_state(
            program_id=program_id,
            expected_state=record.program_state,
            new_state=target_state,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        return _to_program_response(saved)

    # ── Content authoring (modules / chapters / exercises) ───────────────────

    def create_module(
        self, coach_id: str, program_id: str, payload: ModuleCreateRequest
    ) -> ModuleResponse:
        """Create a Module within an existing Program.

        Ancestry is verified before ownership (Requirement 5.5 precedes 5.6):
        a missing Program is reported 404 before the requester is checked
        against the Owning_Coach (403). On success a module identifier and an
        ISO 8601 created-at timestamp are generated (Requirements 5.1, 5.8).
        """
        self._require_owned_program(coach_id, program_id)

        record = ContentNodeRecord(
            program_id=program_id,
            node_type=NodeType.module,
            node_id=str(uuid.uuid4()),
            parent_id=None,
            title=payload.title,
            position=payload.position,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        saved = self._content.create(record)
        return _to_module_response(saved)

    def create_chapter(
        self,
        coach_id: str,
        program_id: str,
        module_id: str,
        payload: ChapterCreateRequest,
    ) -> ChapterResponse:
        """Create a Chapter within an existing Module.

        Verifies the full ancestry — Program then Module — as 404 before the
        ownership 403 (Requirement 6.5 precedes 6.6). On success a chapter
        identifier and an ISO 8601 created-at timestamp are generated
        (Requirements 6.1, 6.8).
        """
        self._require_owned_program(coach_id, program_id)
        self._require_node(program_id, NodeType.module, module_id)

        record = ContentNodeRecord(
            program_id=program_id,
            node_type=NodeType.chapter,
            node_id=str(uuid.uuid4()),
            parent_id=module_id,
            title=payload.title,
            position=payload.position,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        saved = self._content.create(record)
        return _to_chapter_response(saved)

    def create_exercise(
        self,
        coach_id: str,
        program_id: str,
        module_id: str,
        chapter_id: str,
        payload: ExerciseCreateRequest,
    ) -> ExerciseResponse:
        """Create an Exercise within an existing Chapter.

        Verifies the full ancestry — Program, Module, then Chapter — as 404
        before the ownership 403 (Requirement 7.6 precedes 7.7). On success an
        exercise identifier and an ISO 8601 created-at timestamp are generated
        (Requirements 7.1, 7.9).
        """
        self._require_owned_program(coach_id, program_id)
        self._require_node(program_id, NodeType.module, module_id)
        self._require_node(program_id, NodeType.chapter, chapter_id)

        record = ContentNodeRecord(
            program_id=program_id,
            node_type=NodeType.exercise,
            node_id=str(uuid.uuid4()),
            parent_id=chapter_id,
            title=payload.title,
            position=payload.position,
            prompt=payload.prompt,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        saved = self._content.create(record)
        return _to_exercise_response(saved)

    def update_module(
        self,
        coach_id: str,
        program_id: str,
        module_id: str,
        payload: ModuleUpdateRequest,
    ) -> ModuleResponse:
        """Update an existing Module's title and/or position.

        Applies the Requirement 8 rejection precedence (ancestry 404 →
        ownership 403 → field-validation 422):

        1. ``_require_owned_program`` reports a missing Program as 404 before
           the ownership 403 (Requirements 8.4, 8.5).
        2. ``_require_node`` reports a missing Module as 404 (Requirement 8.4).
        3. Field-validation 422, including the empty-update case, is enforced by
           ``ModuleUpdateRequest`` (its "at least one field" validator and the
           title/position rules) before the service runs (Requirements 8.6,
           8.8), so no service-level field check is needed here.

        Only the fields the payload actually set (non-``None``) are applied via
        ``model_copy``; ``created_at``, ``node_type``, ``parent_id`` and
        ``node_id`` are left unchanged. Every rejection happens before the
        write, so the stored node is left unchanged on rejection (Requirement
        8.5). On success the updated Module is returned (Requirement 8.1).
        """
        self._require_owned_program(coach_id, program_id)
        record = self._require_node(program_id, NodeType.module, module_id)

        changes = payload.model_dump(exclude_none=True)
        updated = record.model_copy(update=changes)
        saved = self._content.update_node(updated)
        return _to_module_response(saved)

    def update_chapter(
        self,
        coach_id: str,
        program_id: str,
        module_id: str,
        chapter_id: str,
        payload: ChapterUpdateRequest,
    ) -> ChapterResponse:
        """Update an existing Chapter's title and/or position.

        Applies the Requirement 8 rejection precedence (ancestry 404 →
        ownership 403 → field-validation 422):

        1. ``_require_owned_program`` reports a missing Program as 404 before
           the ownership 403 (Requirements 8.4, 8.5).
        2. ``_require_node`` verifies the enclosing Module then the target
           Chapter, reporting either as 404 (Requirement 8.4).
        3. Field-validation 422, including the empty-update case, is enforced by
           ``ChapterUpdateRequest`` before the service runs (Requirements 8.6,
           8.8), so no service-level field check is needed here.

        Only the fields the payload actually set (non-``None``) are applied via
        ``model_copy``, leaving ``created_at``, ``node_type``, ``parent_id`` and
        ``node_id`` unchanged. Every rejection happens before the write, so the
        stored node is left unchanged on rejection (Requirement 8.5). On success
        the updated Chapter is returned (Requirement 8.2).
        """
        self._require_owned_program(coach_id, program_id)
        self._require_node(program_id, NodeType.module, module_id)
        record = self._require_node(program_id, NodeType.chapter, chapter_id)

        changes = payload.model_dump(exclude_none=True)
        updated = record.model_copy(update=changes)
        saved = self._content.update_node(updated)
        return _to_chapter_response(saved)

    def update_exercise(
        self,
        coach_id: str,
        program_id: str,
        module_id: str,
        chapter_id: str,
        exercise_id: str,
        payload: ExerciseUpdateRequest,
    ) -> ExerciseResponse:
        """Update an existing Exercise's title, prompt, and/or position.

        Applies the Requirement 8 rejection precedence (ancestry 404 →
        ownership 403 → field-validation 422):

        1. ``_require_owned_program`` reports a missing Program as 404 before
           the ownership 403 (Requirements 8.4, 8.5).
        2. ``_require_node`` verifies the enclosing Module and Chapter then the
           target Exercise, reporting any as 404 (Requirement 8.4).
        3. Field-validation 422, including the empty-update case, is enforced by
           ``ExerciseUpdateRequest`` before the service runs (Requirements 8.6,
           8.8), so no service-level field check is needed here.

        Only the fields the payload actually set (non-``None``) are applied via
        ``model_copy``, leaving ``created_at``, ``node_type``, ``parent_id`` and
        ``node_id`` unchanged. Every rejection happens before the write, so the
        stored node is left unchanged on rejection (Requirement 8.5). On success
        the updated Exercise is returned (Requirement 8.3).
        """
        self._require_owned_program(coach_id, program_id)
        self._require_node(program_id, NodeType.module, module_id)
        self._require_node(program_id, NodeType.chapter, chapter_id)
        record = self._require_node(program_id, NodeType.exercise, exercise_id)

        changes = payload.model_dump(exclude_none=True)
        updated = record.model_copy(update=changes)
        saved = self._content.update_node(updated)
        return _to_exercise_response(saved)

    # ── Content delete (coach-only, no cascade) ──────────────────────────────

    def delete_module(
        self, coach_id: str, program_id: str, module_id: str
    ) -> None:
        """Delete a Module from an owned Program.

        Applies the authoring rejection precedence (ancestry 404 → ownership
        403), then refuses a non-empty Module:

        1. ``_require_owned_program`` reports a missing Program as 404 before the
           ownership 403.
        2. ``_require_node`` reports a missing Module as 404.
        3. 409 when the Module still has one or more Chapters — deletion does not
           cascade, so children must be removed first.

        On success the single Module node is removed.
        """
        self._require_owned_program(coach_id, program_id)
        self._require_node(program_id, NodeType.module, module_id)

        if self._has_children(program_id, NodeType.chapter, module_id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Module is not empty; delete its chapters first",
            )

        self._content.delete_node(program_id, NodeType.module.value, module_id)

    def delete_chapter(
        self, coach_id: str, program_id: str, module_id: str, chapter_id: str
    ) -> None:
        """Delete a Chapter from an owned Program.

        Applies ancestry 404 → ownership 403, verifies the Chapter belongs to
        the stated Module, then refuses a non-empty Chapter:

        1. ``_require_owned_program`` / ``_require_node`` report any missing
           ancestor (Program, Module) or the Chapter itself as 404.
        2. ``_require_child_node`` reports a Chapter not parented by the stated
           Module as 404.
        3. 409 when the Chapter still has one or more Exercises.

        On success the single Chapter node is removed.
        """
        self._require_owned_program(coach_id, program_id)
        self._require_node(program_id, NodeType.module, module_id)
        self._require_child_node(program_id, NodeType.chapter, chapter_id, module_id)

        if self._has_children(program_id, NodeType.exercise, chapter_id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Chapter is not empty; delete its exercises first",
            )

        self._content.delete_node(program_id, NodeType.chapter.value, chapter_id)

    def delete_exercise(
        self,
        coach_id: str,
        program_id: str,
        module_id: str,
        chapter_id: str,
        exercise_id: str,
    ) -> None:
        """Delete an Exercise from an owned Program.

        Applies ancestry 404 → ownership 403 and verifies the full parent chain
        (Module → Chapter → Exercise). An Exercise is a leaf, so there is no
        child check; on success the single Exercise node is removed.
        """
        self._require_owned_program(coach_id, program_id)
        self._require_node(program_id, NodeType.module, module_id)
        self._require_child_node(program_id, NodeType.chapter, chapter_id, module_id)
        self._require_child_node(
            program_id, NodeType.exercise, exercise_id, chapter_id
        )

        self._content.delete_node(program_id, NodeType.exercise.value, exercise_id)

    # ── Content view (enrolled user) ─────────────────────────────────────────

    def get_content_tree(self, user_id: str, program_id: str) -> ContentTreeResponse:
        """Return the completion-annotated content tree for an enrolled user.

        Applies the Requirement 12 rejection precedence (the 401 token and 403
        role checks are enforced earlier by ``require_user`` in ``deps.py``):

        1. 404 when the program does not exist (Requirement 12.5),
        2. 403 when the requester is not enrolled in the program (Requirement
           12.4).

        For an enrolled user the gate is state-agnostic: access is granted in
        any lifecycle state the enrollment covers, including ``paused`` and
        ``archived`` (Requirement 12.3). The program's full content hierarchy is
        loaded with a single ``ContentRepository.list_for_program`` query and the
        user's completion set with a single
        ``CompletionRepository.list_for_program`` query, then the pure
        ``_build_tree_with_completion`` rollup orders the tree and derives
        per-exercise and per-level completion (Requirements 12.1, 12.2, 12.7).
        """
        program = self._programs.get_by_id(program_id)
        if program is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Program not found",
            )

        enrollment = self._enrollments.get(user_id, program_id)
        if enrollment is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not enrolled in this program",
            )

        items = self._content.list_for_program(program_id)
        completions = self._completion.list_for_program(user_id, program_id)
        completed_exercise_ids = {
            c.exercise_id for c in completions if c.completed
        }

        return _build_tree_with_completion(
            program_id=program_id,
            program_state=program.program_state,
            items=items,
            completed_exercise_ids=completed_exercise_ids,
        )

    def set_completion(
        self,
        user_id: str,
        program_id: str,
        module_id: str,
        chapter_id: str,
        exercise_id: str,
        completed: bool,
    ) -> ExerciseCompletionResponse:
        """Toggle a user's completion of an exercise, idempotently.

        Applies the Requirement 13.9 rejection precedence (the 401 token check
        is enforced earlier by ``require_user`` in ``deps.py``, and the 422
        invalid-value check is enforced earlier by ``CompletionUpdateRequest``):

        1. 404 when any node in the ancestry — Program, Module, Chapter, then
           Exercise — does not exist (Requirement 13.5),
        2. 403 when the requester is not enrolled in the program (Requirement
           13.4).

        Both gates precede the write, so a rejected request leaves the stored
        completion unchanged (Requirements 13.4, 13.5). On success the toggle is
        written as an unconditional upsert, which is idempotent: marking an
        already-complete exercise complete leaves it complete and marking an
        already-incomplete one incomplete leaves it incomplete (Requirements
        13.1, 13.2); a never-recorded completion simply defaults to incomplete
        (Requirement 13.3). The ``updated_at`` timestamp is set to a UTC ISO
        8601 string at the time the value is stored (Requirement 13.8), and the
        stored ``ExerciseCompletionResponse`` is returned.
        """
        # 404: verify the full ancestry exists before the enrollment check
        # (Requirement 13.5, which precedes 13.4 per 13.9).
        program = self._programs.get_by_id(program_id)
        if program is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Program not found",
            )
        self._require_node(program_id, NodeType.module, module_id)
        self._require_node(program_id, NodeType.chapter, chapter_id)
        self._require_node(program_id, NodeType.exercise, exercise_id)

        # 403: the requester must be enrolled in the program (Requirement 13.4).
        enrollment = self._enrollments.get(user_id, program_id)
        if enrollment is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not enrolled in this program",
            )

        record = ExerciseCompletionRecord(
            user_id=user_id,
            program_id=program_id,
            exercise_id=exercise_id,
            completed=completed,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        saved = self._completion.put(record)
        return _to_completion_response(saved)

    # ── Content reads (owner coach or enrolled user) ─────────────────────────

    def list_modules(self, requester: UserResponse, program_id: str) -> list[ModuleResponse]:
        """Return a program's modules, ordered by (position, created_at).

        Access is granted to the owning coach or to a user enrolled in the
        program; otherwise 403. A missing program is 404 (checked before the
        access decision).
        """
        self._require_program_read_access(requester, program_id)
        modules = self._nodes_of_type(program_id, NodeType.module)
        return [_to_module_response(m) for m in modules]

    def get_module(
        self, requester: UserResponse, program_id: str, module_id: str
    ) -> ModuleResponse:
        """Return a single module by id. 404 when it does not exist."""
        self._require_program_read_access(requester, program_id)
        record = self._require_node(program_id, NodeType.module, module_id)
        return _to_module_response(record)

    def list_chapters(
        self, requester: UserResponse, program_id: str, module_id: str
    ) -> list[ChapterResponse]:
        """Return a module's chapters, ordered by (position, created_at).

        Verifies the module exists under the program (404) before listing.
        """
        self._require_program_read_access(requester, program_id)
        self._require_node(program_id, NodeType.module, module_id)
        chapters = [
            c
            for c in self._nodes_of_type(program_id, NodeType.chapter)
            if c.parent_id == module_id
        ]
        return [_to_chapter_response(c) for c in chapters]

    def get_chapter(
        self, requester: UserResponse, program_id: str, module_id: str, chapter_id: str
    ) -> ChapterResponse:
        """Return a single chapter by id, verifying it belongs to the module.

        404 when the module or chapter does not exist, or when the chapter is
        not a child of the stated module.
        """
        self._require_program_read_access(requester, program_id)
        self._require_node(program_id, NodeType.module, module_id)
        record = self._require_child_node(
            program_id, NodeType.chapter, chapter_id, module_id
        )
        return _to_chapter_response(record)

    def list_exercises(
        self, requester: UserResponse, program_id: str, module_id: str, chapter_id: str
    ) -> list[ExerciseResponse]:
        """Return a chapter's exercises, ordered by (position, created_at).

        Verifies the module and chapter exist, and that the chapter belongs to
        the module (404 otherwise), before listing.
        """
        self._require_program_read_access(requester, program_id)
        self._require_node(program_id, NodeType.module, module_id)
        self._require_child_node(program_id, NodeType.chapter, chapter_id, module_id)
        exercises = [
            e
            for e in self._nodes_of_type(program_id, NodeType.exercise)
            if e.parent_id == chapter_id
        ]
        return [_to_exercise_response(e) for e in exercises]

    def get_exercise(
        self,
        requester: UserResponse,
        program_id: str,
        module_id: str,
        chapter_id: str,
        exercise_id: str,
    ) -> ExerciseResponse:
        """Return a single exercise by id, verifying its full parent chain.

        404 when any node in the chain does not exist, when the chapter is not a
        child of the module, or when the exercise is not a child of the chapter.
        """
        self._require_program_read_access(requester, program_id)
        self._require_node(program_id, NodeType.module, module_id)
        self._require_child_node(program_id, NodeType.chapter, chapter_id, module_id)
        record = self._require_child_node(
            program_id, NodeType.exercise, exercise_id, chapter_id
        )
        return _to_exercise_response(record)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _require_program_read_access(
        self, requester: UserResponse, program_id: str
    ) -> ProgramRecord:
        """Authorize a content read: owning coach or enrolled user, else 403.

        A missing program is reported 404 before the access decision, matching
        the ``404 missing → 403 unauthorized`` precedence used elsewhere. Access
        is granted when the requester is the Owning_Coach of the program, or
        when the requester has an enrollment in it (any lifecycle state).
        """
        program = self._programs.get_by_id(program_id)
        if program is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Program not found",
            )

        # Owning coach always has access.
        if (
            requester.role == Role.coach
            and program.owner_coach_id == requester.user_id
        ):
            return program

        # Otherwise the requester must be enrolled in the program.
        enrollment = self._enrollments.get(requester.user_id, program_id)
        if enrollment is not None:
            return program

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this program's content",
        )

    def _nodes_of_type(
        self, program_id: str, node_type: NodeType
    ) -> list[ContentNodeRecord]:
        """Return a program's nodes of one type, ordered by (position, created_at).

        Reuses the single ``list_for_program`` query and filters/sorts in
        memory, matching how ``_build_tree_with_completion`` orders siblings.
        """
        nodes = [
            n
            for n in self._content.list_for_program(program_id)
            if n.node_type == node_type
        ]
        nodes.sort(key=lambda n: (n.position, n.created_at))
        return nodes

    def _has_children(
        self, program_id: str, child_type: NodeType, parent_id: str
    ) -> bool:
        """Return whether any node of ``child_type`` is parented by ``parent_id``.

        Reuses the single ``list_for_program`` query. Used by the delete flow to
        refuse removing a non-empty Module (has chapters) or Chapter (has
        exercises) — deletion does not cascade.
        """
        return any(
            n.node_type == child_type and n.parent_id == parent_id
            for n in self._content.list_for_program(program_id)
        )

    def _require_child_node(
        self,
        program_id: str,
        node_type: NodeType,
        node_id: str,
        expected_parent_id: str,
    ) -> ContentNodeRecord:
        """Assert a node exists AND is a child of ``expected_parent_id``, else 404.

        Extends ``_require_node`` with a parent-chain check so a node cannot be
        fetched through the wrong ancestor path (e.g. a chapter under a module
        that is not its parent).
        """
        record = self._require_node(program_id, node_type, node_id)
        if record.parent_id != expected_parent_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"{node_type.value.capitalize()} not found",
            )
        return record

    def _require_owned_program(self, coach_id: str, program_id: str) -> ProgramRecord:
        """Assert a Program exists (404) before asserting ownership (403).

        Shared by content authoring so ancestry not-found always precedes the
        ownership check (Requirements 5.5/5.6, 6.5/6.6, 7.6/7.7).
        """
        return self._get_owned_record(coach_id, program_id)

    def _require_node(
        self, program_id: str, node_type: NodeType, node_id: str
    ) -> ContentNodeRecord:
        """Assert an ancestor content node exists, else raise 404.

        Used to verify the Module (for chapters) and the Module + Chapter (for
        exercises) exist before a child is created (Requirements 6.5, 7.6).
        """
        node_sk = f"{node_type.value}#{node_id}"
        record = self._content.get_node(program_id, node_sk)
        if record is None or record.node_type != node_type:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"{node_type.value.capitalize()} not found",
            )
        return record

    def _get_owned_record(self, coach_id: str, program_id: str) -> ProgramRecord:
        """Load a program and assert the requester owns it.

        404 precedes 403: a missing program is reported as not found before any
        ownership comparison (Requirements 4.3/4.4 then 4.5/4.6).
        """
        record = self._programs.get_by_id(program_id)
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Program not found",
            )
        if record.owner_coach_id != coach_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not own this program",
            )
        return record


# ── Completion strings (Requirement 12.2) ───────────────────────────────────────

_COMPLETED = "completed"
_NOT_COMPLETED = "not_completed"


def _build_tree_with_completion(
    program_id: str,
    program_state: ProgramState,
    items: list[ContentNodeRecord],
    completed_exercise_ids: set[str],
) -> ContentTreeResponse:
    """Build the completion-annotated content tree (pure, in-memory).

    A pure function over ``(items, completed_exercise_ids)`` — no I/O — that the
    enrollment-gated ``get_content_tree`` flow (task 10.2) wraps around two
    bounded query results (the program's content hierarchy and the user's
    completed-exercise set). Keeping it pure makes the rollup deterministic and
    directly property-testable (design "Rollup computation").

    Steps (design "Rollup computation (`_build_tree_with_completion`)"):

    1. Group the content items by ``parent_id`` so each level's children are
       available in one lookup.
    2. Sort every sibling group by ``(position, created_at)`` ascending so the
       returned order is deterministic across repeated requests — ties on
       ``position`` break on the creation timestamp (Requirement 12.1).
    3. For each Exercise, set ``completion`` to ``completed`` iff its id is in
       ``completed_exercise_ids``, else ``not_completed``; an id absent from the
       set is therefore ``not_completed`` (unset ⇒ incomplete, Requirements
       13.3, 14.8).
    4. Roll ``completed_count`` / ``total_count`` up bottom-up: a Chapter sums
       its Exercises, a Module sums its Chapters, and the Program sums its
       Modules (Requirements 14.1–14.6).
    5. A level's ``completed`` boolean is ``total_count > 0 and completed_count
       == total_count`` — so an empty Chapter / Module / Program (no descendant
       exercises) is never complete (Requirements 12.2, 12.7).
    """
    # Step 1: group children by parent id, partitioned by node type.
    children_by_parent: dict[str | None, list[ContentNodeRecord]] = {}
    for item in items:
        children_by_parent.setdefault(item.parent_id, []).append(item)

    def _sorted(records: list[ContentNodeRecord]) -> list[ContentNodeRecord]:
        # Step 2: deterministic ordering by (position, created_at) ascending.
        return sorted(records, key=lambda r: (r.position, r.created_at))

    def _children(parent_id: str | None, node_type: NodeType) -> list[ContentNodeRecord]:
        return _sorted(
            [
                r
                for r in children_by_parent.get(parent_id, [])
                if r.node_type == node_type
            ]
        )

    module_nodes: list[ModuleNode] = []
    program_completed = 0
    program_total = 0

    for module in _children(None, NodeType.module):
        chapter_nodes: list[ChapterNode] = []
        module_completed = 0
        module_total = 0

        for chapter in _children(module.node_id, NodeType.chapter):
            exercise_nodes: list[ExerciseNode] = []
            chapter_completed = 0
            chapter_total = 0

            for exercise in _children(chapter.node_id, NodeType.exercise):
                # Step 3: unset ⇒ not_completed.
                is_done = exercise.node_id in completed_exercise_ids
                exercise_nodes.append(
                    ExerciseNode(
                        exercise_id=exercise.node_id,
                        title=exercise.title,
                        prompt=exercise.prompt or "",
                        position=exercise.position,
                        created_at=exercise.created_at,
                        completion=_COMPLETED if is_done else _NOT_COMPLETED,
                    )
                )
                chapter_total += 1
                if is_done:
                    chapter_completed += 1

            chapter_nodes.append(
                ChapterNode(
                    chapter_id=chapter.node_id,
                    title=chapter.title,
                    position=chapter.position,
                    created_at=chapter.created_at,
                    exercises=exercise_nodes,
                    completion=_summary(chapter_completed, chapter_total),
                )
            )
            # Step 4: module sums its chapters.
            module_completed += chapter_completed
            module_total += chapter_total

        module_nodes.append(
            ModuleNode(
                module_id=module.node_id,
                title=module.title,
                position=module.position,
                created_at=module.created_at,
                chapters=chapter_nodes,
                completion=_summary(module_completed, module_total),
            )
        )
        # Step 4: program sums its modules.
        program_completed += module_completed
        program_total += module_total

    return ContentTreeResponse(
        program_id=program_id,
        program_state=program_state,
        modules=module_nodes,
        completion=_summary(program_completed, program_total),
    )


def _summary(completed_count: int, total_count: int) -> CompletionSummary:
    """Build a ``CompletionSummary`` for one level of the tree.

    ``completed`` is ``total_count > 0 and completed_count == total_count``, so
    an empty level (``total_count == 0``) is never reported complete
    (Requirements 12.2, 12.7, 14.1–14.6).
    """
    return CompletionSummary(
        completed_count=completed_count,
        total_count=total_count,
        completed=total_count > 0 and completed_count == total_count,
    )


def _to_program_response(record: ProgramRecord) -> ProgramResponse:
    """Map an internal ProgramRecord to the public ProgramResponse."""
    return ProgramResponse(
        program_id=record.program_id,
        owner_coach_id=record.owner_coach_id,
        title=record.title,
        description=record.description,
        price=record.price,
        program_state=record.program_state,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _to_completion_response(
    record: ExerciseCompletionRecord,
) -> ExerciseCompletionResponse:
    """Map an internal ExerciseCompletionRecord to the public response."""
    return ExerciseCompletionResponse(
        exercise_id=record.exercise_id,
        completed=record.completed,
        updated_at=record.updated_at,
    )


def _to_enrollment_response(record: EnrollmentRecord) -> EnrollmentResponse:
    """Map an internal EnrollmentRecord to the public EnrollmentResponse."""
    return EnrollmentResponse(
        enrollment_id=record.enrollment_id,
        user_id=record.user_id,
        program_id=record.program_id,
        enrolled_at=record.enrolled_at,
    )


def _to_module_response(record: ContentNodeRecord) -> ModuleResponse:
    """Map a module ContentNodeRecord to the public ModuleResponse."""
    return ModuleResponse(
        module_id=record.node_id,
        title=record.title,
        position=record.position,
        created_at=record.created_at,
    )


def _to_chapter_response(record: ContentNodeRecord) -> ChapterResponse:
    """Map a chapter ContentNodeRecord to the public ChapterResponse."""
    return ChapterResponse(
        chapter_id=record.node_id,
        title=record.title,
        position=record.position,
        created_at=record.created_at,
    )


def _to_exercise_response(record: ContentNodeRecord) -> ExerciseResponse:
    """Map an exercise ContentNodeRecord to the public ExerciseResponse."""
    return ExerciseResponse(
        exercise_id=record.node_id,
        title=record.title,
        prompt=record.prompt or "",
        position=record.position,
        created_at=record.created_at,
    )
