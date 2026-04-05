"""Prekey bundle routes for private-chat E2EE bootstrap."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies.auth_dependency import get_current_user
from app.models.user import User
from app.schemas.device import PreKeyClaimRequest
from app.services.device_service import DeviceService
from app.utils.response import success_response


router = APIRouter()


@router.get("/prekey-bundle/{user_id}")
def get_prekey_bundle(
    user_id: str,
    exclude_device_id: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return success_response(
        DeviceService(db).list_prekey_bundles(
            current_user,
            user_id,
            exclude_device_id=exclude_device_id,
        )
    )


@router.post("/prekeys/claim")
def claim_prekeys(
    payload: PreKeyClaimRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return success_response(DeviceService(db).claim_prekeys(current_user, payload.device_ids))
