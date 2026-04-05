"""Device routes for private-chat E2EE bootstrap."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies.auth_dependency import get_current_user
from app.models.user import User
from app.schemas.device import DeviceKeysRefreshRequest, DeviceRegisterRequest
from app.services.device_service import DeviceService
from app.utils.response import success_response


router = APIRouter()


@router.post("/register")
def register_device(
    payload: DeviceRegisterRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return success_response(DeviceService(db).register_device(current_user, payload.model_dump()))


@router.get("")
def list_devices(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return success_response(DeviceService(db).list_my_devices(current_user))


@router.post("/{device_id}/keys/refresh")
def refresh_device_keys(
    device_id: str,
    payload: DeviceKeysRefreshRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return success_response(DeviceService(db).refresh_my_device_keys(current_user, device_id, payload.model_dump()))


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_device(
    device_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    DeviceService(db).delete_my_device(current_user, device_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
