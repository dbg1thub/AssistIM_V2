"""AssistIM backend entrypoint."""

from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session

from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.database import configure_database, get_db, init_db
from app.core.errors import AppError, ErrorCode
from app.core.logging import configure_logging, logger
from app.core.rate_limit import rate_limiter
from app.core.security import decode_access_token
from app.dependencies.auth_dependency import get_current_user
from app.media.default_avatars import sync_default_avatar_assets
from app.media.storage import get_local_media_mount_path
from app.models.user import User
from app.repositories.file_repo import FileRepository
from app.utils.response import error_response, success_response
from app.websocket.chat_ws import websocket_router
from app.websocket.presence_ws import presence_router


configure_logging()


def _resolve_local_media_path(settings: Settings, storage_key: str) -> Path:
    normalized_key = (storage_key or "").strip().replace("\\", "/").lstrip("/")
    if not normalized_key:
        raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "media not found", 404)
    root = Path(settings.upload_dir).resolve()
    target_path = (root / Path(normalized_key)).resolve()
    try:
        target_path.relative_to(root)
    except ValueError as exc:
        raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "media not found", 404) from exc
    return target_path


def _is_server_generated_media(storage_key: str) -> bool:
    normalized_key = (storage_key or "").strip().replace("\\", "/").lstrip("/")
    return normalized_key.startswith(("default_avatars/", "group_avatars/"))


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create one FastAPI application from the current settings snapshot."""
    current_settings = settings or get_settings()
    configure_database(current_settings)
    rate_limiter.configure_from_settings(current_settings)
    os.makedirs(current_settings.upload_dir, exist_ok=True)
    sync_default_avatar_assets(current_settings)

    @asynccontextmanager
    async def app_lifespan(_: FastAPI):
        init_db(current_settings)
        yield

    app = FastAPI(
        title=current_settings.app_name,
        version=current_settings.app_version,
        lifespan=app_lifespan,
    )
    app.state.settings = current_settings

    allow_origins = list(current_settings.cors_origins)
    allow_credentials = "*" not in allow_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix=current_settings.api_v1_prefix)
    app.include_router(websocket_router)
    app.include_router(presence_router)
    if current_settings.media_storage_backend == "local":
        media_mount_path = get_local_media_mount_path(current_settings)

        @app.get(f"{media_mount_path}/{{storage_key:path}}")
        def serve_local_media(
            storage_key: str,
            current_user: User = Depends(get_current_user),
            db: Session = Depends(get_db),
        ) -> FileResponse:
            target_path = _resolve_local_media_path(current_settings, storage_key)
            if not target_path.is_file():
                raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "media not found", 404)
            if not _is_server_generated_media(storage_key):
                record = FileRepository(db).get_by_storage_key("local", storage_key)
                if record is None:
                    raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "media not found", 404)
            return FileResponse(target_path)

    @app.middleware("http")
    async def access_log_middleware(request: Request, call_next):
        start = time.perf_counter()
        user_id = "anonymous"
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1]
            try:
                payload = decode_access_token(token, settings=current_settings)
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

    @app.get("/")
    def healthcheck() -> dict:
        return success_response(
            data={
                "name": current_settings.app_name,
                "version": current_settings.app_version,
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

    return app


app = create_app()
