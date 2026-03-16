"""File repository."""

from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models.file import StoredFile


class FileRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, user_id: str, file_url: str, file_type: str | None, file_name: str) -> StoredFile:
        stored = StoredFile(
            user_id=user_id,
            file_url=file_url,
            file_type=file_type,
            file_name=file_name,
        )
        self.db.add(stored)
        self.db.commit()
        self.db.refresh(stored)
        return stored

    def list_by_user(self, user_id: str) -> list[StoredFile]:
        stmt = select(StoredFile).where(StoredFile.user_id == user_id).order_by(desc(StoredFile.created_at))
        return list(self.db.execute(stmt).scalars().all())
