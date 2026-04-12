"""File service."""

from __future__ import annotations

from contextlib import suppress

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.media.storage import build_media_storage
from app.models.file import StoredFile
from app.models.user import User
from app.repositories.file_repo import FileRepository


class FileService:
    def __init__(self, db: Session, settings: Settings | None = None) -> None:
        self.files = FileRepository(db)
        self.settings = settings or get_settings()
        self.storage = build_media_storage(self.settings)

    def save_upload(self, current_user: User, file: UploadFile) -> dict:
        return self.serialize_upload_result(self.save_upload_record(current_user, file))

    def save_upload_record(self, current_user: User, file: UploadFile) -> StoredFile:
        stored_media = self.storage.store_upload(file)
        try:
            return self.files.create(
                user_id=current_user.id,
                storage_provider=stored_media.storage_provider,
                storage_key=stored_media.storage_key,
                file_url=stored_media.public_url,
                file_type=stored_media.content_type,
                file_name=stored_media.original_name,
                size_bytes=stored_media.size_bytes,
                checksum_sha256=stored_media.checksum_sha256,
            )
        except Exception:
            with suppress(Exception):
                self.storage.delete_object(stored_media.storage_key)
            raise

    def list_files(self, current_user: User, *, limit: int = 50) -> list[dict]:
        return [self.serialize_file_summary(item) for item in self.files.list_by_user(current_user.id, limit=limit)]

    @staticmethod
    def serialize_file_summary(item) -> dict:
        return {
            "id": item.id,
            "url": item.file_url,
            "mime_type": item.file_type,
            "original_name": item.file_name,
            "size_bytes": int(item.size_bytes or 0),
        }

    @staticmethod
    def serialize_upload_result(item) -> dict:
        payload = FileService.serialize_file_summary(item)
        payload["created_at"] = item.created_at.isoformat() if item.created_at else None
        return payload