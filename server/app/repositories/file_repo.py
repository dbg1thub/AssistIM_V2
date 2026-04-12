"""File repository."""

from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

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

    def get_by_id(self, file_id: str) -> StoredFile | None:
        return self.db.get(StoredFile, file_id)

    def get_by_user_and_id(self, user_id: str, file_id: str) -> StoredFile | None:
        stmt = select(StoredFile).where(StoredFile.id == file_id, StoredFile.user_id == user_id).limit(1)
        return self.db.execute(stmt).scalar_one_or_none()

    def get_by_storage_key(self, storage_provider: str, storage_key: str) -> StoredFile | None:
        stmt = (
            select(StoredFile)
            .where(StoredFile.storage_provider == storage_provider, StoredFile.storage_key == storage_key)
            .limit(1)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list_by_user(self, user_id: str, *, limit: int = 50) -> list[StoredFile]:
        bounded_limit = min(200, max(1, int(limit or 50)))
        stmt = select(StoredFile).where(StoredFile.user_id == user_id).order_by(desc(StoredFile.created_at)).limit(bounded_limit)
        return list(self.db.execute(stmt).scalars().all())
