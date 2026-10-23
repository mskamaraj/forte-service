"""User-facing enrollment routes.

Mirrors ``app.api.v1.routes.programs``: a thin ``APIRouter`` that delegates every
handler to a freshly instantiated :class:`~app.services.coaching_service.CoachingService`
and relies on the Pydantic request models for field validation. Both routes
depend on ``require_user`` (which resolves the authenticated account from the
Bearer token, so a missing/invalid token yields 401 before the role check).
"""

from fastapi import APIRouter, Depends

from app.api.deps import require_user
from app.models.enrollment import EnrollRequest, EnrollmentResponse
from app.models.program import ProgramResponse
from app.models.user import UserResponse
from app.services.coaching_service import CoachingService

router = APIRouter(prefix="/enrollments", tags=["Enrollments"])


@router.post(
    "",
    response_model=EnrollmentResponse,
    status_code=201,
    summary="Enroll in a coaching program",
)
async def enroll(
    payload: EnrollRequest,
    current_user: UserResponse = Depends(require_user),
):
    """
    Enroll the authenticated user in an active program.

    Returns 404 when the program does not exist, 409 when the program is not
    open for enrollment, and 409 when the user is already enrolled. Requires the
    ``user`` role.
    """
    service = CoachingService()
    return service.enroll(current_user.user_id, payload.program_id)


@router.get(
    "/programs",
    response_model=list[ProgramResponse],
    summary="List the user's enrolled programs",
)
async def list_enrolled_programs(
    current_user: UserResponse = Depends(require_user),
):
    """
    Return the programs the authenticated user is enrolled in.

    Includes ``paused`` and ``archived`` programs, ordered most recently
    enrolled first. Requires the ``user`` role.
    """
    service = CoachingService()
    return service.list_enrolled(current_user.user_id)
