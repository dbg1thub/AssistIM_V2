"""Auth routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.rate_limit import rate_limiter
from app.dependencies.auth_dependency import get_current_user
from app.models.user import User
from app.schemas.auth import LoginRequest, RefreshTokenRequest, RegisterRequest
from app.services.auth_service import AuthService
from app.services.user_service import UserService
from app.utils.response import success_response


router = APIRouter()
settings = get_settings()


@router.post("/register", dependencies=[Depends(rate_limiter.dependency("register", settings.rate_limit_register))])
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> dict:
    return success_response(AuthService(db).register(payload.username, payload.password, payload.nickname))


@router.post("/users", status_code=status.HTTP_201_CREATED, dependencies=[Depends(rate_limiter.dependency("register", settings.rate_limit_register))])
def register_user(payload: RegisterRequest, db: Session = Depends(get_db)) -> dict:
    return success_response(AuthService(db).register_user_only(payload.username, payload.password, payload.nickname))


@router.post("/login", dependencies=[Depends(rate_limiter.dependency("login", settings.rate_limit_login))])
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> dict:
    return success_response(AuthService(db).login(payload.username, payload.password))


@router.post("/refresh")
def refresh(payload: RefreshTokenRequest, db: Session = Depends(get_db)) -> dict:
    return success_response(AuthService(db).refresh(payload.refresh_token))


@router.post("/token")
def refresh_token(payload: RefreshTokenRequest, db: Session = Depends(get_db)) -> dict:
    return success_response(AuthService(db).refresh_access_token(payload.refresh_token))


@router.delete("/session", status_code=status.HTTP_204_NO_CONTENT)
def logout(current_user: User = Depends(get_current_user)) -> Response:
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me")
def me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return success_response(UserService(db).get_user(current_user.id))
