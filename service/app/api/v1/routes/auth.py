from fastapi import APIRouter
from app.models.user import RegisterRequest, RegisterResponse
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=201,
    summary="Register a new user",
)
async def register(payload: RegisterRequest):
    """
    Create a new user account.

    - Email must be unique
    - Password must be ≥ 8 characters and include uppercase, lowercase,
      a digit, and a special character
    """
    service = AuthService()
    return service.register(payload)
