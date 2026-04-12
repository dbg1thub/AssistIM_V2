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

    @abstractmethod
    def delete_object(self, storage_key: str) -> None:
        """Delete one stored object if it exists."""


class LocalMediaStorage(MediaStorage):
    """Store uploads under the configured local directory."""

    provider_name = "local"
    _chunk_size = 1024 * 1024
    _max_original_name_length = 120
    _allowed_content_types = {
        "application/octet-stream",
        "application/pdf",
        "application/zip",
        "audio/mp4",
        "audio/mpeg",
        "audio/ogg",
        "audio/wav",
        "image/gif",
        "image/jpeg",
        "image/png",
        "image/webp",
        "text/plain",
        "video/mp4",
        "video/ogg",
        "video/quicktime",
        "video/webm",
        "video/x-matroska",
    }
    _content_types_by_extension = {
        ".bin": {"application/octet-stream"},
        ".gif": {"image/gif"},
        ".jpeg": {"image/jpeg"},
        ".jpg": {"image/jpeg"},
        ".m4a": {"audio/mp4"},
        ".mkv": {"video/x-matroska"},
        ".mov": {"video/quicktime"},
        ".mp3": {"audio/mpeg"},
        ".mp4": {"video/mp4"},
        ".ogg": {"audio/ogg", "video/ogg"},
        ".pdf": {"application/pdf"},
        ".png": {"image/png"},
        ".txt": {"text/plain"},
        ".wav": {"audio/wav"},
        ".webm": {"video/webm"},
        ".webp": {"image/webp"},
        ".zip": {"application/zip"},
    }

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def store_upload(self, file: UploadFile) -> StoredMediaObject:
        original_name = self._normalize_original_name(file.filename)
        extension = self._validate_upload_extension(original_name)
        storage_key = self._build_storage_key(extension)
        target_path = self._path_for_storage_key(storage_key)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        checksum = hashlib.sha256()
        size_bytes = 0
        sample = b""

        try:
            with target_path.open("wb") as buffer:
                while True:
                    chunk = file.file.read(self._chunk_size)
                    if not chunk:
                        break
                    if not sample:
                        sample = chunk[:512]
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

        content_type = self._detect_content_type(extension, sample)
        return StoredMediaObject(
            storage_provider=self.provider_name,
            storage_key=storage_key,
            public_url=self._public_url_for(storage_key),
            original_name=original_name,
            content_type=content_type,
            size_bytes=size_bytes,
            checksum_sha256=checksum.hexdigest(),
        )

    def delete_object(self, storage_key: str) -> None:
        self._path_for_storage_key(storage_key).unlink(missing_ok=True)

    @classmethod
    def _validate_upload_extension(cls, original_name: str) -> str:
        extension = Path(original_name).suffix.lower()
        if extension not in cls._content_types_by_extension:
            raise AppError(ErrorCode.INVALID_REQUEST, "upload file type is not allowed", 422)
        return extension

    @classmethod
    def _detect_content_type(cls, extension: str, sample: bytes) -> str:
        detected = cls._detect_content_type_from_sample(extension, sample)
        if detected not in cls._allowed_content_types:
            raise AppError(ErrorCode.INVALID_REQUEST, "upload file type is not allowed", 422)
        if detected not in cls._content_types_by_extension[extension]:
            raise AppError(ErrorCode.INVALID_REQUEST, "upload file type is not allowed", 422)
        return detected

    @classmethod
    def _detect_content_type_from_sample(cls, extension: str, sample: bytes) -> str:
        if sample.startswith(b"%PDF-"):
            return "application/pdf"
        if sample.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
            return "application/zip"
        if sample.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if sample.startswith((b"GIF87a", b"GIF89a")):
            return "image/gif"
        if sample.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if sample.startswith(b"RIFF") and sample[8:12] == b"WEBP":
            return "image/webp"
        if sample.startswith(b"RIFF") and sample[8:12] == b"WAVE":
            return "audio/wav"
        if sample.startswith(b"OggS"):
            return "video/ogg" if extension == ".ogg" and b"theora" in sample.lower() else "audio/ogg"
        if sample.startswith(b"ID3") or (len(sample) >= 2 and sample[0] == 0xFF and sample[1] & 0xE0 == 0xE0):
            return "audio/mpeg"
        if len(sample) >= 12 and sample[4:8] == b"ftyp":
            if extension == ".m4a":
                return "audio/mp4"
            if extension == ".mov":
                return "video/quicktime"
            return "video/mp4"
        if sample.startswith(b"\x1a\x45\xdf\xa3"):
            return "video/webm" if extension == ".webm" else "video/x-matroska"
        if extension == ".txt" and not cls._looks_like_text(sample):
            raise AppError(ErrorCode.INVALID_REQUEST, "upload file type is not allowed", 422)
        return sorted(cls._content_types_by_extension[extension])[0]

    @staticmethod
    def _looks_like_text(sample: bytes) -> bool:
        if b"\x00" in sample:
            return False
        try:
            sample.decode("utf-8")
        except UnicodeDecodeError:
            return False
        return True

    @classmethod
    def _normalize_original_name(cls, filename: str | None) -> str:
        basename = os.path.basename((filename or "").strip()) or "upload.bin"
        cleaned = "".join(cls._normalize_filename_char(char) for char in basename).strip(" ._")
        if not cleaned:
            cleaned = "upload.bin"
        if len(cleaned) <= cls._max_original_name_length:
            return cleaned

        suffix = Path(cleaned).suffix[:16]
        stem = Path(cleaned).stem or "upload"
        stem_limit = max(1, cls._max_original_name_length - len(suffix))
        return f"{stem[:stem_limit]}{suffix}"

    @staticmethod
    def _normalize_filename_char(char: str) -> str:
        if not char.isprintable() or char in '<>:"/\\|?*':
            return "_"
        return char

    def _build_storage_key(self, extension: str) -> str:
        now = utcnow()
        suffix = extension.lower() if extension else ""
        return f"{now.year:04d}/{now.month:02d}/{now.day:02d}/{uuid.uuid4().hex}{suffix}"

    def _path_for_storage_key(self, storage_key: str) -> Path:
        root = Path(self._settings.upload_dir).resolve()
        target_path = (root / Path(storage_key)).resolve()
        target_path.relative_to(root)
        return target_path

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