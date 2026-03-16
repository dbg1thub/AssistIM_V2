"""AssistIM backend entrypoint."""

from __future__ import annotations

import os
import time

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_router, legacy_chat_router
from app.core.config import get_settings
from app.core.database import init_db
from app.core.errors import AppError, ErrorCode
from app.core.logging import configure_logging, logger
from app.core.security import decode_access_token
from app.utils.response import error_response, success_response
from app.websocket.chat_ws import websocket_router
from app.websocket.presence_ws import presence_router


configure_logging()
settings = get_settings()
os.makedirs(settings.upload_dir, exist_ok=True)

app = FastAPI(title=settings.app_name, version=settings.app_version)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins) or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.api_v1_prefix)
app.include_router(api_router, prefix=settings.api_compat_prefix)
app.include_router(legacy_chat_router)
app.include_router(legacy_chat_router, prefix=settings.api_compat_prefix)
app.include_router(websocket_router)
app.include_router(presence_router)
app.mount("/uploads", StaticFiles(directory=settings.upload_dir), name="uploads")


@app.middleware("http")
async def access_log_middleware(request: Request, call_next):
    start = time.perf_counter()
    user_id = "anonymous"
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1]
        try:
            payload = decode_access_token(token)
            user_id = payload.get("sub", "anonymous")
        except Exception:
            user_id = "invalid-token"

    response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    logger.info(
        "timestamp=%s user_id=%s endpoint=%s method=%s status_code=%s duration_ms=%s",
        int(time.time()),
        user_id,
        request.url.path,
        request.method,
        response.status_code,
        duration_ms,
    )
    return response


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/")
def healthcheck() -> dict:
    return success_response(
        data={
            "name": settings.app_name,
            "version": settings.app_version,
        }
    )


@app.exception_handler(AppError)
async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=error_response(exc.code, exc.message),
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=error_response(ErrorCode.INVALID_REQUEST, str(exc)),
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled_error path=%s method=%s", request.url.path, request.method)
    return JSONResponse(
        status_code=500,
        content=error_response(ErrorCode.INTERNAL_ERROR, "internal server error"),
    )
