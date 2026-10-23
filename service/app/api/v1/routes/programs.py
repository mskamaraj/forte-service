"""Coach-facing program and content-authoring routes, plus the user browse route.

Mirrors ``app.api.v1.routes.auth``: a thin ``APIRouter`` that delegates every
handler to a freshly instantiated :class:`~app.services.coaching_service.CoachingService`
and relies on the Pydantic request models for field validation. Coach-only
routes depend on ``require_coach`` and the public browse route on
``require_user`` (both resolve the authenticated account from the Bearer token,
so a missing/invalid token yields 401 before the role check).
"""

from fastapi import APIRouter, Depends

from app.api.deps import require_coach, require_coach_or_user, require_user
from app.models.content import (
    ChapterCreateRequest,
    ChapterResponse,
    ChapterUpdateRequest,
    ExerciseCreateRequest,
    ExerciseResponse,
    ExerciseUpdateRequest,
    ModuleCreateRequest,
    ModuleResponse,
    ModuleUpdateRequest,
)
from app.models.program import (
    ProgramCreateRequest,
    ProgramResponse,
    ProgramStateTransitionRequest,
    ProgramUpdateRequest,
)
from app.models.user import UserResponse
from app.services.coaching_service import CoachingService

router = APIRouter(prefix="/programs", tags=["Programs"])


# ── Browse (user-facing) ────────────────────────────────────────────────────
# Registered BEFORE "/{pid}" so the literal path is not shadowed by the path
# parameter route.


@router.get(
    "/available",
    response_model=list[ProgramResponse],
    summary="List programs available to enroll in",
)
async def list_available_programs(
    current_user: UserResponse = Depends(require_user),
):
    """
    Return every program in the ``active`` state for the browse catalogue.

    Requires the ``user`` role.
    """
    service = CoachingService()
    return service.list_active_programs()


# ── Program CRUD (coach-only) ─────────────────────────────────────────────────


@router.post(
    "",
    response_model=ProgramResponse,
    status_code=201,
    summary="Create a coaching program",
)
async def create_program(
    payload: ProgramCreateRequest,
    current_user: UserResponse = Depends(require_coach),
):
    """
    Create a program owned by the authenticated coach.

    The new program defaults to the ``drafted`` state. Requires the ``coach`` role.
    """
    service = CoachingService()
    return service.create_program(current_user.user_id, payload)


@router.get(
    "",
    response_model=list[ProgramResponse],
    summary="List the coach's own programs",
)
async def list_programs(
    current_user: UserResponse = Depends(require_coach),
):
    """
    Return the programs owned by the authenticated coach.

    Requires the ``coach`` role.
    """
    service = CoachingService()
    return service.list_owned(current_user.user_id)


@router.get(
    "/{pid}",
    response_model=ProgramResponse,
    summary="Get one of the coach's programs",
)
async def get_program(
    pid: str,
    current_user: UserResponse = Depends(require_coach),
):
    """
    Return a single program the authenticated coach owns.

    Returns 404 when the program does not exist and 403 when the coach is not
    the owner. Requires the ``coach`` role.
    """
    service = CoachingService()
    return service.get_owned(current_user.user_id, pid)


@router.put(
    "/{pid}",
    response_model=ProgramResponse,
    summary="Update one of the coach's programs",
)
async def update_program(
    pid: str,
    payload: ProgramUpdateRequest,
    current_user: UserResponse = Depends(require_coach),
):
    """
    Update an owned program's title, description, and price.

    Requires the ``coach`` role.
    """
    service = CoachingService()
    return service.update_program(current_user.user_id, pid, payload)


# ── Lifecycle (coach-only) ────────────────────────────────────────────────────


@router.put(
    "/{pid}/state",
    response_model=ProgramResponse,
    summary="Transition a program's lifecycle state",
)
async def transition_program_state(
    pid: str,
    payload: ProgramStateTransitionRequest,
    current_user: UserResponse = Depends(require_coach),
):
    """
    Move an owned program to a new lifecycle state along an allowed edge.

    Requires the ``coach`` role.
    """
    service = CoachingService()
    return service.transition_state(current_user.user_id, pid, payload.target_state)


# ── Module authoring (coach-only) ─────────────────────────────────────────────


@router.post(
    "/{pid}/modules",
    response_model=ModuleResponse,
    status_code=201,
    summary="Create a module within a program",
)
async def create_module(
    pid: str,
    payload: ModuleCreateRequest,
    current_user: UserResponse = Depends(require_coach),
):
    """Create a module within an owned program. Requires the ``coach`` role."""
    service = CoachingService()
    return service.create_module(current_user.user_id, pid, payload)


@router.put(
    "/{pid}/modules/{mid}",
    response_model=ModuleResponse,
    summary="Update a module within a program",
)
async def update_module(
    pid: str,
    mid: str,
    payload: ModuleUpdateRequest,
    current_user: UserResponse = Depends(require_coach),
):
    """Update a module within an owned program. Requires the ``coach`` role."""
    service = CoachingService()
    return service.update_module(current_user.user_id, pid, mid, payload)


# ── Chapter authoring (coach-only) ────────────────────────────────────────────


@router.post(
    "/{pid}/modules/{mid}/chapters",
    response_model=ChapterResponse,
    status_code=201,
    summary="Create a chapter within a module",
)
async def create_chapter(
    pid: str,
    mid: str,
    payload: ChapterCreateRequest,
    current_user: UserResponse = Depends(require_coach),
):
    """Create a chapter within an owned program's module. Requires the ``coach`` role."""
    service = CoachingService()
    return service.create_chapter(current_user.user_id, pid, mid, payload)


@router.put(
    "/{pid}/modules/{mid}/chapters/{cid}",
    response_model=ChapterResponse,
    summary="Update a chapter within a module",
)
async def update_chapter(
    pid: str,
    mid: str,
    cid: str,
    payload: ChapterUpdateRequest,
    current_user: UserResponse = Depends(require_coach),
):
    """Update a chapter within an owned program's module. Requires the ``coach`` role."""
    service = CoachingService()
    return service.update_chapter(current_user.user_id, pid, mid, cid, payload)


# ── Exercise authoring (coach-only) ───────────────────────────────────────────


@router.post(
    "/{pid}/modules/{mid}/chapters/{cid}/exercises",
    response_model=ExerciseResponse,
    status_code=201,
    summary="Create an exercise within a chapter",
)
async def create_exercise(
    pid: str,
    mid: str,
    cid: str,
    payload: ExerciseCreateRequest,
    current_user: UserResponse = Depends(require_coach),
):
    """Create an exercise within an owned program's chapter. Requires the ``coach`` role."""
    service = CoachingService()
    return service.create_exercise(current_user.user_id, pid, mid, cid, payload)


@router.put(
    "/{pid}/modules/{mid}/chapters/{cid}/exercises/{eid}",
    response_model=ExerciseResponse,
    summary="Update an exercise within a chapter",
)
async def update_exercise(
    pid: str,
    mid: str,
    cid: str,
    eid: str,
    payload: ExerciseUpdateRequest,
    current_user: UserResponse = Depends(require_coach),
):
    """Update an exercise within an owned program's chapter. Requires the ``coach`` role."""
    service = CoachingService()
    return service.update_exercise(current_user.user_id, pid, mid, cid, eid, payload)


# ── Content reads (owner coach or enrolled user) ──────────────────────────────
# GET endpoints for the content hierarchy. Open to the owning coach or any user
# enrolled in the program; per-resource authorization is applied in the service
# (a missing program/node is 404, an unauthorized requester is 403).


@router.get(
    "/{pid}/modules",
    response_model=list[ModuleResponse],
    summary="List a program's modules",
)
async def list_modules(
    pid: str,
    current_user: UserResponse = Depends(require_coach_or_user),
):
    """List every module in a program, ordered by position then creation time.

    Accessible to the owning coach or an enrolled user. Returns 404 when the
    program does not exist and 403 when the requester has no access.
    """
    service = CoachingService()
    return service.list_modules(current_user, pid)


@router.get(
    "/{pid}/modules/{mid}",
    response_model=ModuleResponse,
    summary="Get one module by id",
)
async def get_module(
    pid: str,
    mid: str,
    current_user: UserResponse = Depends(require_coach_or_user),
):
    """Return a single module. Returns 404 when the program or module is absent."""
    service = CoachingService()
    return service.get_module(current_user, pid, mid)


@router.get(
    "/{pid}/modules/{mid}/chapters",
    response_model=list[ChapterResponse],
    summary="List a module's chapters",
)
async def list_chapters(
    pid: str,
    mid: str,
    current_user: UserResponse = Depends(require_coach_or_user),
):
    """List every chapter in a module, ordered by position then creation time.

    Returns 404 when the program or module is absent and 403 when the requester
    has no access.
    """
    service = CoachingService()
    return service.list_chapters(current_user, pid, mid)


@router.get(
    "/{pid}/modules/{mid}/chapters/{cid}",
    response_model=ChapterResponse,
    summary="Get one chapter by id",
)
async def get_chapter(
    pid: str,
    mid: str,
    cid: str,
    current_user: UserResponse = Depends(require_coach_or_user),
):
    """Return a single chapter, verifying it belongs to the stated module.

    Returns 404 when the program, module, or chapter is absent, or when the
    chapter is not a child of the module.
    """
    service = CoachingService()
    return service.get_chapter(current_user, pid, mid, cid)


@router.get(
    "/{pid}/modules/{mid}/chapters/{cid}/exercises",
    response_model=list[ExerciseResponse],
    summary="List a chapter's exercises",
)
async def list_exercises(
    pid: str,
    mid: str,
    cid: str,
    current_user: UserResponse = Depends(require_coach_or_user),
):
    """List every exercise in a chapter, ordered by position then creation time.

    Returns 404 when the program, module, or chapter is absent (or the chapter
    is not a child of the module) and 403 when the requester has no access.
    """
    service = CoachingService()
    return service.list_exercises(current_user, pid, mid, cid)


@router.get(
    "/{pid}/modules/{mid}/chapters/{cid}/exercises/{eid}",
    response_model=ExerciseResponse,
    summary="Get one exercise by id",
)
async def get_exercise(
    pid: str,
    mid: str,
    cid: str,
    eid: str,
    current_user: UserResponse = Depends(require_coach_or_user),
):
    """Return a single exercise, verifying its full module/chapter parent chain.

    Returns 404 when any node in the chain is absent or mis-parented.
    """
    service = CoachingService()
    return service.get_exercise(current_user, pid, mid, cid, eid)
