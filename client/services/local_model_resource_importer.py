"""Local model resource import helpers for the settings UI."""

from __future__ import annotations

import os
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from client.core.config_backend import DEFAULT_AI_EMBEDDING_MODEL_ID, DEFAULT_AI_EMBEDDING_MODEL_PATH
from client.services.local_ai_selection import MODEL_MANIFEST_PATH, MODELS_DIR, load_local_ai_model_specs
from client.services.local_model_resource_probe import FASTER_WHISPER_REQUIRED_FILES


@dataclass(frozen=True, slots=True)
class LocalModelImportResult:
    """One completed local model import."""

    kind: str
    model_id: str
    source_path: Path
    target_path: Path
    size_bytes: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class LocalModelImportError(RuntimeError):
    """Stable local model import error."""

    def __init__(self, code: str, message: str = "", *, metadata: dict[str, Any] | None = None) -> None:
        self.code = code
        self.metadata = dict(metadata or {})
        super().__init__(message or code)


class LocalModelResourceImporter:
    """Validate and import local AI model resources into the canonical models directory."""

    def __init__(
        self,
        *,
        models_dir: str | Path = MODELS_DIR,
        manifest_path: str | Path = MODEL_MANIFEST_PATH,
        embedding_target_path: str | Path = DEFAULT_AI_EMBEDDING_MODEL_PATH,
        voice_model_root: str | Path | None = None,
    ) -> None:
        self._models_dir = _resolve_path(models_dir)
        self._manifest_path = _resolve_path(manifest_path)
        self._embedding_target_path = _resolve_path(embedding_target_path)
        self._voice_model_root = _resolve_path(voice_model_root or self._models_dir / "faster-whisper")

    @property
    def models_dir(self) -> Path:
        return self._models_dir

    def import_chat_gguf(self, source_path: str | Path) -> LocalModelImportResult:
        """Import one manifest-declared chat GGUF model."""
        source = _require_file(source_path, suffix=".gguf")
        spec = self._manifest_spec_for_file(source.name)
        if spec is None:
            raise LocalModelImportError(
                "MODEL_NOT_IN_MANIFEST",
                f"Only GGUF files declared in manifest.json can be imported: {source.name}",
                metadata={"file_name": source.name},
            )

        target = (self._models_dir / spec.file_name).resolve()
        size = _copy_file_atomically(source, target)
        return LocalModelImportResult(
            kind="chat",
            model_id=spec.model_id,
            source_path=source,
            target_path=target,
            size_bytes=size,
            metadata={"file_name": spec.file_name},
        )

    def import_embedding_gguf(self, source_path: str | Path) -> LocalModelImportResult:
        """Import the default local embedding GGUF model."""
        source = _require_file(source_path, suffix=".gguf")
        target = self._embedding_target_path.resolve()
        size = _copy_file_atomically(source, target)
        return LocalModelImportResult(
            kind="embedding",
            model_id=DEFAULT_AI_EMBEDDING_MODEL_ID,
            source_path=source,
            target_path=target,
            size_bytes=size,
        )

    def import_faster_whisper_directory(self, source_dir: str | Path, *, model_id: str = "small") -> LocalModelImportResult:
        """Import one local faster-whisper model directory."""
        normalized_model_id = str(model_id or "small").strip() or "small"
        if normalized_model_id != "small":
            raise LocalModelImportError(
                "VOICE_MODEL_UNSUPPORTED",
                f"Only faster-whisper small is supported in the first import flow: {normalized_model_id}",
                metadata={"model_id": normalized_model_id},
            )

        source = _require_directory(source_dir)
        model_source = _resolve_voice_model_source(source, normalized_model_id)
        missing = _missing_required_files(model_source, FASTER_WHISPER_REQUIRED_FILES)
        if missing:
            raise LocalModelImportError(
                "VOICE_MODEL_INCOMPLETE",
                "Missing faster-whisper model files: " + ", ".join(missing),
                metadata={"missing_files": missing, "model_id": normalized_model_id},
            )

        target = (self._voice_model_root / normalized_model_id).resolve()
        size = _copy_directory_atomically(model_source, target)
        return LocalModelImportResult(
            kind="voice",
            model_id=normalized_model_id,
            source_path=model_source,
            target_path=target,
            size_bytes=size,
            metadata={"required_files": tuple(FASTER_WHISPER_REQUIRED_FILES)},
        )

    def _manifest_spec_for_file(self, file_name: str):
        normalized = str(file_name or "").strip().casefold()
        if not normalized:
            return None
        for spec in load_local_ai_model_specs(manifest_path=self._manifest_path):
            if spec.file_name.casefold() == normalized:
                return spec
        return None


def _require_file(path: str | Path, *, suffix: str) -> Path:
    resolved = _resolve_path(path)
    if not resolved.is_file():
        raise LocalModelImportError("MODEL_FILE_NOT_FOUND", f"Model file not found: {resolved}")
    normalized_suffix = str(suffix or "").strip().lower()
    if normalized_suffix and resolved.suffix.lower() != normalized_suffix:
        raise LocalModelImportError(
            "MODEL_FILE_TYPE_UNSUPPORTED",
            f"Unsupported model file type: {resolved.name}",
            metadata={"suffix": resolved.suffix},
        )
    return resolved


def _require_directory(path: str | Path) -> Path:
    resolved = _resolve_path(path)
    if not resolved.is_dir():
        raise LocalModelImportError("MODEL_DIRECTORY_NOT_FOUND", f"Model directory not found: {resolved}")
    return resolved


def _resolve_voice_model_source(source: Path, model_id: str) -> Path:
    if not _missing_required_files(source, FASTER_WHISPER_REQUIRED_FILES):
        return source
    nested = source / model_id
    if nested.is_dir():
        return nested.resolve()
    return source


def _copy_file_atomically(source: Path, target: Path) -> int:
    source = source.resolve()
    target = target.resolve()
    if source == target:
        return _file_size(target)

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp-{uuid.uuid4().hex}")
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, target)
    except Exception as exc:
        _remove_file_quietly(temporary)
        raise LocalModelImportError("IMPORT_COPY_FAILED", f"Failed to import model file: {exc}") from exc
    return _file_size(target)


def _copy_directory_atomically(source: Path, target: Path) -> int:
    source = source.resolve()
    target = target.resolve()
    if source == target:
        return _path_size(target)

    target.parent.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    temporary = target.parent / f".{target.name}.tmp-{token}"
    backup = target.parent / f".{target.name}.bak-{token}"
    moved_existing = False
    try:
        shutil.copytree(source, temporary)
        if target.exists():
            target.rename(backup)
            moved_existing = True
        temporary.rename(target)
    except Exception as exc:
        _remove_tree_quietly(temporary)
        if moved_existing and backup.exists() and not target.exists():
            try:
                backup.rename(target)
            except OSError:
                pass
        raise LocalModelImportError("IMPORT_COPY_FAILED", f"Failed to import model directory: {exc}") from exc
    finally:
        _remove_tree_quietly(backup)
    return _path_size(target)


def _resolve_path(value: str | Path) -> Path:
    raw = value if isinstance(value, Path) else Path(str(value or ""))
    try:
        return raw.expanduser().resolve()
    except OSError:
        return raw.expanduser()


def _missing_required_files(directory: Path, filenames: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(filename for filename in filenames if not (directory / filename).is_file())


def _file_size(path: Path) -> int:
    try:
        return int(path.stat().st_size)
    except OSError:
        return 0


def _path_size(path: Path) -> int:
    if path.is_file():
        return _file_size(path)
    if not path.is_dir():
        return 0
    total = 0
    try:
        for candidate in path.rglob("*"):
            if candidate.is_file():
                total += _file_size(candidate)
    except OSError:
        return total
    return total


def _remove_file_quietly(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def _remove_tree_quietly(path: Path) -> None:
    try:
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
    except OSError:
        pass
