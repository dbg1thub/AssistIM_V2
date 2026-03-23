"""File service."""

from __future__ import annotations

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.media.storage import build_media_storage
from app.models.user import User
from app.repositories.file_repo import FileRepository


class FileService:
    def __init__(self, db: Session, settings: Settings | None = None) -> None:
        self.files = FileRepository(db)
        self.settings = settings or get_settings()
        self.storage = build_media_storage(self.settings)

    def save_upload(self, current_user: User, file: UploadFile) -> dict:
        stored_media = self.storage.store_upload(file)
        record = self.files.create(
            user_id=current_user.id,
            storage_provider=stored_media.storage_provider,
            storage_key=stored_media.storage_key,
            file_url=stored_media.public_url,
            file_type=stored_media.content_type,
            file_name=stored_media.original_name,
            size_bytes=stored_media.size_bytes,
            checksum_sha256=stored_media.checksum_sha256,
        )
        return self.serialize_file(record)

    def list_files(self, current_user: User) -> list[dict]:
        return [self.serialize_file(item) for item in self.files.list_by_user(current_user.id)]

    @staticmethod
    def serialize_file(item) -> dict:
        media = {
            "url": item.file_url,
            "storage_provider": item.storage_provider,
            "storage_key": item.storage_key,
            "mime_type": item.file_type,
            "size_bytes": int(item.size_bytes or 0),
            "checksum_sha256": item.checksum_sha256,
            "original_name": item.file_name,
        }
        return {
            "id": item.id,
            "user_id": item.user_id,
            "storage_provider": item.storage_provider,
            "storage_key": item.storage_key,
            "file_url": item.file_url,
            "url": item.file_url,
            "mime_type": item.file_type,
            "file_type": item.file_type,
            "original_name": item.file_name,
            "file_name": item.file_name,
            "name": item.file_name,
            "size_bytes": int(item.size_bytes or 0),
            "checksum_sha256": item.checksum_sha256,
            "media": media,
            "created_at": item.created_at.isoformat() if item.created_at else None,
        }
