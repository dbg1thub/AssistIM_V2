"""Read-only local model resource checks for the settings UI."""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from client.core.config_backend import Config, get_config
from client.services.local_ai_selection import LocalAICapabilityProfile, detect_local_ai_capabilities
from client.services.local_voice_transcription_service import LocalVoiceTranscriptionConfig


STATUS_READY = "ready"
STATUS_MISSING = "missing"
STATUS_DEPENDENCY_MISSING = "dependency_missing"
STATUS_CONFIG_DISABLED = "config_disabled"

FASTER_WHISPER_REQUIRED_FILES = ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt")


@dataclass(frozen=True, slots=True)
class LocalModelResourceItem:
    """One read-only local resource check result."""

    key: str
    title: str
    section: str
    status: str
    detail: str = ""
    model_id: str = ""
    path: str = ""
    exists: bool = False
    size_bytes: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LocalModelResourceReport:
    """Snapshot of local model files, dependency availability, and acceleration hints."""

    items: tuple[LocalModelResourceItem, ...]
    overall_status: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def by_key(self, key: str) -> LocalModelResourceItem:
        normalized = str(key or "").strip()
        for item in self.items:
            if item.key == normalized:
                return item
        raise KeyError(normalized)

    def section_items(self, section: str) -> tuple[LocalModelResourceItem, ...]:
        normalized = str(section or "").strip()
        return tuple(item for item in self.items if item.section == normalized)


def probe_local_model_resources(
    *,
    config: Config | Any | None = None,
    asr_config: LocalVoiceTranscriptionConfig | None = None,
    capability: LocalAICapabilityProfile | None = None,
    dependency_checker: Callable[[str], bool] | None = None,
) -> LocalModelResourceReport:
    """Build a settings-safe local model report without loading any model runtime."""
    app_config = config or get_config()
    ai_config = getattr(app_config, "ai", app_config)
    voice_config = asr_config or LocalVoiceTranscriptionConfig()
    local_capability = capability or detect_local_ai_capabilities()
    has_dependency = dependency_checker or _python_package_available

    items = [
        _chat_model_item(ai_config, local_capability),
        _embedding_model_item(ai_config),
        _voice_model_item(voice_config),
        _dependency_item(
            key="dependency_llama_cpp",
            title="llama-cpp-python",
            module_name="llama_cpp",
            has_dependency=has_dependency,
        ),
        _dependency_item(
            key="dependency_llama_cpp_embedding",
            title="llama-cpp-python embedding",
            module_name="llama_cpp.llama_embedding",
            has_dependency=has_dependency,
        ),
        _dependency_item(
            key="dependency_faster_whisper",
            title="faster-whisper",
            module_name="faster_whisper",
            has_dependency=has_dependency,
        ),
        _cuda_dependency_item(local_capability),
    ]
    return LocalModelResourceReport(
        items=tuple(items),
        overall_status=_overall_status(items),
        metadata={
            "cpu_count": int(local_capability.cpu_count or 0),
            "preferred_cpu_threads": int(local_capability.preferred_cpu_threads or 0),
            "total_memory_gb": local_capability.total_memory_gb,
            "available_memory_gb": local_capability.available_memory_gb,
            "gpu_name": local_capability.gpu_name,
            "gpu_total_memory_gb": local_capability.gpu_total_memory_gb,
            "gpu_free_memory_gb": local_capability.gpu_free_memory_gb,
        },
    )


def _chat_model_item(ai_config: Any, capability: LocalAICapabilityProfile) -> LocalModelResourceItem:
    provider = str(getattr(ai_config, "provider", "") or "").strip().lower()
    path = _resolve_path(getattr(ai_config, "model_path", ""))
    exists = path.is_file()
    status = STATUS_READY if exists else STATUS_MISSING
    detail = ""
    if provider and provider != "local_gguf":
        status = STATUS_CONFIG_DISABLED
        detail = f"provider={provider}"
    elif not exists:
        detail = "model file not found"

    gpu_enabled = bool(getattr(ai_config, "gpu_enabled", True))
    acceleration = "cpu"
    if gpu_enabled and capability.runtime_supports_gpu_offload:
        acceleration = "gpu"
    return LocalModelResourceItem(
        key="chat_model",
        title="Chat model",
        section="models",
        status=status,
        detail=detail,
        model_id=str(getattr(ai_config, "model_id", "") or "").strip(),
        path=str(path) if str(path) else "",
        exists=exists,
        size_bytes=_file_size(path) if exists else 0,
        metadata={
            "provider": provider or "local_gguf",
            "context_size": int(getattr(ai_config, "context_size", 0) or 0),
            "gpu_enabled": gpu_enabled,
            "gpu_layers": int(getattr(ai_config, "gpu_layers", 0) or 0),
            "cpu_threads": int(getattr(ai_config, "cpu_threads", 0) or capability.preferred_cpu_threads or 0),
            "acceleration": acceleration,
            "gpu_name": capability.gpu_name,
        },
    )


def _embedding_model_item(ai_config: Any) -> LocalModelResourceItem:
    path = _resolve_path(getattr(ai_config, "embedding_model_path", ""))
    exists = path.is_file()
    return LocalModelResourceItem(
        key="embedding_model",
        title="Embedding model",
        section="models",
        status=STATUS_READY if exists else STATUS_MISSING,
        detail="" if exists else "embedding model file not found",
        model_id=str(getattr(ai_config, "embedding_model_id", "") or "").strip(),
        path=str(path) if str(path) else "",
        exists=exists,
        size_bytes=_file_size(path) if exists else 0,
        metadata={
            "context_size": int(getattr(ai_config, "embedding_context_size", 0) or 0),
            "gpu_layers": int(getattr(ai_config, "embedding_gpu_layers", 0) or 0),
        },
    )


def _voice_model_item(config: LocalVoiceTranscriptionConfig) -> LocalModelResourceItem:
    explicit_path = str(getattr(config, "model_path", "") or "").strip()
    if explicit_path:
        path = _resolve_path(explicit_path)
        exists = path.exists()
        missing_files: tuple[str, ...] = ()
        if exists and path.is_dir():
            missing_files = _missing_required_files(path, FASTER_WHISPER_REQUIRED_FILES)
        status = STATUS_READY if exists and not missing_files else STATUS_MISSING
        return LocalModelResourceItem(
            key="voice_transcription_model",
            title="Voice transcription model",
            section="models",
            status=status,
            detail="" if status == STATUS_READY else "voice transcription model is incomplete or missing",
            model_id=str(config.model_id or "").strip(),
            path=str(path) if str(path) else "",
            exists=exists,
            size_bytes=_path_size(path) if exists else 0,
            metadata=_voice_metadata(config, missing_files=missing_files),
        )

    model_id = str(config.model_id or "small").strip() or "small"
    path = _resolve_path(Path(str(config.model_dir or "")) / model_id)
    exists = path.is_dir()
    missing_files = _missing_required_files(path, FASTER_WHISPER_REQUIRED_FILES) if exists else FASTER_WHISPER_REQUIRED_FILES
    status = STATUS_READY if exists and not missing_files else STATUS_MISSING
    return LocalModelResourceItem(
        key="voice_transcription_model",
        title="Voice transcription model",
        section="models",
        status=status,
        detail="" if status == STATUS_READY else "local faster-whisper model files are missing",
        model_id=model_id,
        path=str(path) if str(path) else "",
        exists=exists,
        size_bytes=_path_size(path) if exists else 0,
        metadata=_voice_metadata(config, missing_files=missing_files),
    )


def _voice_metadata(config: LocalVoiceTranscriptionConfig, *, missing_files: tuple[str, ...]) -> dict[str, Any]:
    return {
        "device": str(config.device or "").strip(),
        "compute_type": str(config.compute_type or "").strip(),
        "cpu_threads": int(config.cpu_threads or 0),
        "allow_download": bool(config.allow_download),
        "missing_files": tuple(missing_files),
    }


def _dependency_item(
    *,
    key: str,
    title: str,
    module_name: str,
    has_dependency: Callable[[str], bool],
) -> LocalModelResourceItem:
    available = bool(has_dependency(module_name))
    return LocalModelResourceItem(
        key=key,
        title=title,
        section="dependencies",
        status=STATUS_READY if available else STATUS_DEPENDENCY_MISSING,
        detail="" if available else f"Python package is unavailable: {module_name}",
        metadata={"module": module_name},
    )


def _cuda_dependency_item(capability: LocalAICapabilityProfile) -> LocalModelResourceItem:
    missing = tuple(str(item or "").strip() for item in capability.missing_cuda_dependencies if str(item or "").strip())
    status = STATUS_READY if not missing else STATUS_DEPENDENCY_MISSING
    return LocalModelResourceItem(
        key="dependency_cuda_12",
        title="CUDA 12 runtime",
        section="dependencies",
        status=status,
        detail="" if status == STATUS_READY else "Missing CUDA DLLs: " + ", ".join(missing),
        metadata={
            "missing_files": missing,
            "runtime_supports_gpu_offload": bool(capability.runtime_supports_gpu_offload),
            "runtime_gpu_probe_error": str(capability.runtime_gpu_probe_error or ""),
        },
    )


def _python_package_available(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(str(module_name or "").strip()) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _resolve_path(value: str | Path) -> Path:
    if isinstance(value, Path):
        raw = value
    else:
        raw = Path(str(value or ""))
    if not str(raw):
        return raw
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


def _overall_status(items: list[LocalModelResourceItem]) -> str:
    statuses = {item.status for item in items}
    for status in (STATUS_DEPENDENCY_MISSING, STATUS_MISSING, STATUS_CONFIG_DISABLED):
        if status in statuses:
            return status
    return STATUS_READY
