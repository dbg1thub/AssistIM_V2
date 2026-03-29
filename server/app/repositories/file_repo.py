"""File repository."""

from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.media.storage import build_media_storage
from app.models.file import StoredFile


class FileRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        *,
        user_id: str,
        storage_provider: str,
        storage_key: str,
        file_url: str,
        file_type: str | None,
        file_name: str,
        size_bytes: int,
        checksum_sha256: str,
    ) -> StoredFile:
        stored = StoredFile(
            user_id=user_id,
            storage_provider=storage_provider,
            storage_key=storage_key,
            file_url=file_url,
            file_type=file_type,
            file_name=file_name,
            size_bytes=size_bytes,
            checksum_sha256=checksum_sha256,
        )
        self.db.add(stored)
        self.db.commit()
        self.db.refresh(stored)
        return stored

    def create_from_upload(self, user_id: str, file, *, settings) -> StoredFile:
        storage = build_media_storage(settings)
        stored_media = storage.store_upload(file)
        return self.create(
            user_id=user_id,
            storage_provider=stored_media.storage_provider,
            storage_key=stored_media.storage_key,
            file_url=stored_media.public_url,
            file_type=stored_media.content_type,
            file_name=stored_media.original_name,
            size_bytes=stored_media.size_bytes,
            checksum_sha256=stored_media.checksum_sha256,
        )

    def get_by_id(self, file_id: str) -> StoredFile | None:
        return self.db.get(StoredFile, file_id)

    def get_by_user_and_id(self, user_id: str, file_id: str) -> StoredFile | None:
        stmt = select(StoredFile).where(StoredFile.id == file_id, StoredFile.user_id == user_id).limit(1)
        return self.db.execute(stmt).scalar_one_or_none()

    def list_by_user(self, user_id: str) -> list[StoredFile]:
        stmt = select(StoredFile).where(StoredFile.user_id == user_id).order_by(desc(StoredFile.created_at))
        return list(self.db.execute(stmt).scalars().all())
