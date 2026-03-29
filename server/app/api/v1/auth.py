"""Auth routes."""

from __future__ import annotations

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


def _register_limit(request: Request) -> int:
    """Return the current register rate limit for this app snapshot."""
    return get_request_settings(request).rate_limit_register


def _login_limit(request: Request) -> int:
    """Return the current login rate limit for this app snapshot."""
    return get_request_settings(request).rate_limit_login


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

    auth_payload = auth_service.login_user(user, rotate_session=True)
    user = dict(auth_payload.get("user") or {})
    user_id = str(user.get("id", "") or "")
    if user_id and has_existing_session:
        became_offline = await connection_manager.disconnect_user_connections(
            user_id,
            close_code=4001,
            reason="session_replaced",
            payload=event_payload("force_logout", {"reason": "session_replaced"}),
        )
        if became_offline:
            await connection_manager.broadcast_json(event_payload("offline", {"user_id": user_id}))
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
    became_offline = await connection_manager.disconnect_user_connections(
        current_user.id,
        close_code=4001,
        reason="logout",
        payload=event_payload("force_logout", {"reason": "logout"}),
    )
    if became_offline:
        await connection_manager.broadcast_json(event_payload("offline", {"user_id": current_user.id}))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me")
def me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return success_response(UserService(db).get_user(current_user.id))
