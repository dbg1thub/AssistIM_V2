"""File service."""

from __future__ import annotations

import os
import shutil
import uuid

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.user import User
from app.repositories.file_repo import FileRepository


class FileService:
    def __init__(self, db: Session) -> None:
        self.files = FileRepository(db)
        self.settings = get_settings()

    def save_upload(self, current_user: User, file: UploadFile) -> dict:
        os.makedirs(self.settings.upload_dir, exist_ok=True)
        extension = os.path.splitext(file.filename or "")[1]
        stored_name = f"{uuid.uuid4()}{extension}"
        absolute_path = os.path.join(self.settings.upload_dir, stored_name)

        with open(absolute_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        record = self.files.create(
            user_id=current_user.id,
            file_url=f"/uploads/{stored_name}",
            file_type=file.content_type,
            file_name=file.filename or stored_name,
        )
        return self.serialize_file(record)

    def list_files(self, current_user: User) -> list[dict]:
        return [self.serialize_file(item) for item in self.files.list_by_user(current_user.id)]

    @staticmethod
    def serialize_file(item) -> dict:
        return {
            "id": item.id,
            "user_id": item.user_id,
            "file_url": item.file_url,
            "url": item.file_url,
            "file_type": item.file_type,
            "file_name": item.file_name,
            "name": item.file_name,
            "created_at": item.created_at.isoformat() if item.created_at else None,
        }
