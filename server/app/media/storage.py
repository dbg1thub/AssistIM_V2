"""Media storage boundaries and the local filesystem implementation."""

from __future__ import annotations

import hashlib
import os
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import UploadFile

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.utils.time import utcnow


@dataclass(slots=True, frozen=True)
class StoredMediaObject:
    """One normalized stored-media descriptor."""

    storage_provider: str
    storage_key: str
    public_url: str
    original_name: str
    content_type: str | None
    size_bytes: int
    checksum_sha256: str


class MediaStorage(ABC):
    """Abstract media storage boundary."""

    @abstractmethod
    def store_upload(self, file: UploadFile) -> StoredMediaObject:
        """Persist one upload and return one normalized descriptor."""


class LocalMediaStorage(MediaStorage):
    """Store uploads under the configured local directory."""

    provider_name = "local"
    _chunk_size = 1024 * 1024

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def store_upload(self, file: UploadFile) -> StoredMediaObject:
        original_name = self._normalize_original_name(file.filename)
        extension = Path(original_name).suffix
        storage_key = self._build_storage_key(extension)
        target_path = Path(self._settings.upload_dir) / Path(storage_key)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        checksum = hashlib.sha256()
        size_bytes = 0

        try:
            with target_path.open("wb") as buffer:
                while True:
                    chunk = file.file.read(self._chunk_size)
                    if not chunk:
                        break
                    size_bytes += len(chunk)
                    if size_bytes > self._settings.max_upload_bytes:
                        raise AppError(
                            ErrorCode.INVALID_REQUEST,
                            f"upload exceeds max size of {self._settings.max_upload_bytes} bytes",
                            413,
                        )
                    checksum.update(chunk)
                    buffer.write(chunk)
        except Exception:
            if target_path.exists():
                target_path.unlink(missing_ok=True)
            raise

        if size_bytes <= 0:
            target_path.unlink(missing_ok=True)
            raise AppError(ErrorCode.INVALID_REQUEST, "empty uploads are not allowed", 422)

        return StoredMediaObject(
            storage_provider=self.provider_name,
            storage_key=storage_key,
            public_url=self._public_url_for(storage_key),
            original_name=original_name,
            content_type=file.content_type or "application/octet-stream",
            size_bytes=size_bytes,
            checksum_sha256=checksum.hexdigest(),
        )

    @staticmethod
    def _normalize_original_name(filename: str | None) -> str:
        normalized = os.path.basename((filename or "").strip())
        return normalized or "upload.bin"

    def _build_storage_key(self, extension: str) -> str:
        now = utcnow()
        suffix = extension.lower() if extension else ""
        return f"{now.year:04d}/{now.month:02d}/{now.day:02d}/{uuid.uuid4().hex}{suffix}"

    def _public_url_for(self, storage_key: str) -> str:
        base_url = (self._settings.media_public_base_url or "/uploads").rstrip("/")
        if not base_url:
            base_url = "/uploads"
        if base_url.startswith(("http://", "https://")):
            return f"{base_url}/{storage_key}"

        normalized_base = self._normalize_local_media_path(base_url)
        return f"{normalized_base}/{storage_key}"

    @staticmethod
    def _normalize_local_media_path(path: str) -> str:
        split_result = urlsplit(path)
        if split_result.scheme and split_result.netloc:
            return split_result.path.rstrip("/") or "/uploads"
        normalized = path if path.startswith("/") else f"/{path}"
        return normalized.rstrip("/") or "/uploads"


def build_media_storage(settings: Settings) -> MediaStorage:
    """Return the configured media storage backend."""
    backend = (settings.media_storage_backend or "local").strip().lower()
    if backend == "local":
        return LocalMediaStorage(settings)
    raise ValueError(f"unsupported media storage backend: {backend}")


def get_local_media_mount_path(settings: Settings) -> str:
    """Return the local static mount path for the configured media base URL."""
    return LocalMediaStorage._normalize_local_media_path(settings.media_public_base_url or "/uploads")
