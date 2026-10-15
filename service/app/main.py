from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from botocore.exceptions import ClientError
from mangum import Mangum

from app.api.v1.router import api_router
from app.core.config import settings

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Forte authentication and registration service",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ClientError)
async def dynamodb_client_error_handler(request: Request, exc: ClientError):
    code = exc.response["Error"]["Code"]
    return JSONResponse(
        status_code=503,
        content={"error": "dynamodb_error", "message": f"DynamoDB error: {code}"},
    )


app.include_router(api_router)


@app.get("/", tags=["Root"])
async def root():
    return {"message": f"Welcome to {settings.app_name}", "version": settings.app_version}


# Lambda entry point
handler = Mangum(app, lifespan="off")
