from fastapi import APIRouter, Query
from app.models.user import UserResponse, UserListResponse
from app.services.auth_service import AuthService

router = APIRouter(prefix="/users", tags=["Users"])


@router.get(
    "",
    response_model=UserListResponse,
    summary="List all users (paginated)",
)
async def list_users(
    limit: int = Query(50, ge=1, le=100, description="Max users to return per page"),
    cursor: str | None = Query(
        None, description="Opaque pagination token from a previous response"
    ),
):
    """
    Return a page of users.

    Pagination uses an opaque cursor (DynamoDB-native). When the response
    includes a `next_cursor`, pass it back as the `cursor` query param to
    fetch the next page. A null `next_cursor` means there are no more users.
    """
    service = AuthService()
    return service.list_users(limit=limit, cursor=cursor)


@router.get(
    "/{user_id}",
    response_model=UserResponse,
    summary="Get user details by ID",
)
async def get_user(user_id: str):
    """
    Fetch a single user's public details by their user_id.

    Returns 404 if no user exists with that ID.
    """
    service = AuthService()
    return service.get_user(user_id)
