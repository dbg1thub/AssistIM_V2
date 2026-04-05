"""Call-related REST APIs."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import get_db
from app.dependencies.auth_dependency import get_current_user
from app.dependencies.settings_dependency import get_request_settings
from app.models.user import User
from app.services.call_service import CallService
from app.utils.response import success_response


router = APIRouter()


@router.get("/ice-servers")
def get_ice_servers(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_request_settings),
) -> dict:
    return success_response(CallService(db, settings=settings).get_ice_servers(user_id=str(current_user.id or "")))
