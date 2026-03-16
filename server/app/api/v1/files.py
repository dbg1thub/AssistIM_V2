"""File routes and upload aliases."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies.auth_dependency import get_current_user
from app.models.user import User
from app.services.file_service import FileService
from app.utils.response import success_response


router = APIRouter()


@router.get("/files")
def list_files(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return success_response(FileService(db).list_files(current_user))


@router.post("/files/upload")
def upload_file(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return success_response(FileService(db).save_upload(current_user, file))


@router.post("/upload")
def upload_file_alias(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return success_response(FileService(db).save_upload(current_user, file))
