from fastapi import APIRouter, Depends
from app.api.deps import get_current_user
from app.models.user import (
    LoginRequest,
    RegisterRequest,
    RegisterResponse,
    TokenResponse,
    UserResponse,
)
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


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Log in and receive a JWT access token",
)
async def login(payload: LoginRequest):
    """
    Authenticate with email + password.

    Returns a Bearer token valid for 7 days. The same error is returned for
    an unknown email and a wrong password.
    """
    service = AuthService()
    return service.login(payload)


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get the currently authenticated user",
)
async def me(current_user: UserResponse = Depends(get_current_user)):
    """
    Return the authenticated user's details.

    Requires a valid `Authorization: Bearer <token>` header.
    """
    return current_user
