from fastapi import APIRouter
from app.api.v1.routes import health, auth, users, programs, enrollments, content

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(programs.router)
api_router.include_router(enrollments.router)
api_router.include_router(content.router)
