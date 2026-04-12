"""Auth routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import get_db
from app.core.errors import AppError, ErrorCode
from app.core.rate_limit import rate_limiter
from app.dependencies.auth_dependency import get_current_user
from app.dependencies.settings_dependency import get_request_settings
from app.models.user import User
from app.schemas.auth import LoginRequest, RefreshTokenRequest, RegisterRequest
from app.services.auth_service import AuthService
from app.services.user_service import UserService
from app.utils.response import success_response
from app.websocket.manager import connection_manager
from app.websocket.presence_ws import event_payload


router = APIRouter()
logger = logging.getLogger(__name__)


def _register_limit(request: Request) -> int:
    """Return the current register rate limit for this app snapshot."""
    return get_request_settings(request).rate_limit_register


def _login_limit(request: Request) -> int:
    """Return the current login rate limit for this app snapshot."""
    return get_request_settings(request).rate_limit_login


async def _disconnect_auth_connections(user_id: str, *, reason: str, strict_disconnect: bool) -> None:
    """Disconnect existing realtime runtime for one committed or soon-to-be-committed auth change."""
    payload = event_payload("force_logout", {"reason": reason})
    try:
        became_offline = await connection_manager.disconnect_user_connections(
            user_id,
            close_code=4001,
            reason=reason,
            payload=payload,
        )
    except Exception:
        logger.exception("Auth connection disconnect failed during auth connection replacement")
        if strict_disconnect:
            raise AppError(ErrorCode.INTERNAL_ERROR, "failed to replace existing session", 500)
        return

    if not became_offline:
        return
    try:
        await connection_manager.broadcast_json(event_payload("offline", {"user_id": user_id}))
    except Exception:
        logger.exception("Auth offline fanout failed after auth connection disconnect")


@router.post("/register", dependencies=[Depends(rate_limiter.dynamic_dependency("register", _register_limit))])
async def register(
    payload: RegisterRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_request_settings),
) -> dict:
    auth_payload = AuthService(db, settings).register(payload.username, payload.password, payload.nickname)
    return success_response(auth_payload)


@router.post("/login", dependencies=[Depends(rate_limiter.dynamic_dependency("login", _login_limit))])
async def login(
    payload: LoginRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_request_settings),
) -> dict:
    auth_service = AuthService(db, settings)
    user = auth_service.authenticate_credentials(payload.username, payload.password)
    user_id = str(user.id or "")
    has_existing_session = bool(user_id) and connection_manager.has_user_connections(user_id)
    if has_existing_session and not payload.force:
        raise AppError(ErrorCode.SESSION_CONFLICT, "account already online", 409)

    if user_id and has_existing_session:
        await _disconnect_auth_connections(user_id, reason="session_replaced", strict_disconnect=True)

    auth_payload = auth_service.login_user(user, rotate_session=True)
    return success_response(auth_payload)


@router.post("/refresh")
def refresh(
    payload: RefreshTokenRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_request_settings),
) -> dict:
    return success_response(AuthService(db, settings).refresh(payload.refresh_token))


@router.delete("/session", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    AuthService(db).logout(current_user)
    await _disconnect_auth_connections(current_user.id, reason="logout", strict_disconnect=False)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me")
def me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return success_response(UserService(db).get_user(current_user.id))
