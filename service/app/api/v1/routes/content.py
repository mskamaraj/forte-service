"""User-facing content-tree and exercise-completion routes.

Mirrors ``app.api.v1.routes.enrollments``: a thin ``APIRouter`` that delegates
every handler to a freshly instantiated
:class:`~app.services.coaching_service.CoachingService` and relies on the
Pydantic request models for field validation. Both routes depend on
``require_user`` (which resolves the authenticated account from the Bearer
token, so a missing/invalid token yields 401 before the role check).
"""

from fastapi import APIRouter, Depends

from app.api.deps import require_user
from app.models.completion import CompletionUpdateRequest, ExerciseCompletionResponse
from app.models.content import ContentTreeResponse
from app.models.user import UserResponse
from app.services.coaching_service import CoachingService

router = APIRouter(prefix="/programs", tags=["Content"])


@router.get(
    "/{pid}/content",
    response_model=ContentTreeResponse,
    summary="Get a program's content tree with per-user completion",
)
async def get_content_tree(
    pid: str,
    current_user: UserResponse = Depends(require_user),
):
    """
    Return the content tree for a program the authenticated user is enrolled in,
    annotated with that user's per-exercise and derived per-level completion.

    Returns 404 when the program does not exist and 403 when the user is not
    enrolled (access is granted in any lifecycle state the enrollment covers,
    including ``paused`` and ``archived``). Requires the ``user`` role.
    """
    service = CoachingService()
    return service.get_content_tree(current_user.user_id, pid)


@router.put(
    "/{pid}/modules/{mid}/chapters/{cid}/exercises/{eid}/completion",
    response_model=ExerciseCompletionResponse,
    summary="Set the completion state of an exercise",
)
async def set_exercise_completion(
    pid: str,
    mid: str,
    cid: str,
    eid: str,
    payload: CompletionUpdateRequest,
    current_user: UserResponse = Depends(require_user),
):
    """
    Toggle whether the authenticated user has completed an exercise.

    Returns 404 when any node in the ancestry (program, module, chapter,
    exercise) does not exist and 403 when the user is not enrolled. The write is
    an idempotent upsert. Requires the ``user`` role.
    """
    service = CoachingService()
    return service.set_completion(
        current_user.user_id, pid, mid, cid, eid, payload.completed
    )
