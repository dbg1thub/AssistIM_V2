"""Hardware probing and installed-model selection for local GGUF AI."""

from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from client.core.config_backend import AIConfig, DEFAULT_AI_MODEL_ID, DEFAULT_AI_MODEL_PATH
from client.services.local_gguf_runtime import LocalGGUFConfig, _candidate_cuda_toolkit_dependency_dirs


MODELS_DIR = Path(__file__).resolve().parents[1] / "resources" / "models"
MODEL_MANIFEST_PATH = MODELS_DIR / "manifest.json"
CUDA_DEPENDENCY_DLL_SETS = (
    ("cuda13", ("cudart64_13.dll", "cublas64_13.dll", "cublasLt64_13.dll")),
    ("cuda12", ("cudart64_12.dll", "cublas64_12.dll", "cublasLt64_12.dll")),
)


@dataclass(frozen=True, slots=True)
class LocalAIModelSpec:
    """One model candidate declared in the local manifest."""

    model_id: str
    file_name: str
    parameter_billion: float
    quantization: str = ""
    min_ram_gb: float = 0.0
    recommended_ram_gb: float = 0.0
    min_vram_gb: float = 0.0
    recommended_vram_gb: float = 0.0
    default_context_size: int = 4096
    supports_vision: bool = False
    vision_projector_file: str = ""
    vision_projector_globs: tuple[str, ...] = field(default_factory=tuple)
    vision_chat_handler: str = ""
    vision_image_max_tokens: int = 0

    @property
    def model_path(self) -> Path:
        return MODELS_DIR / self.file_name


@dataclass(frozen=True, slots=True)
class LocalAICapabilityProfile:
    """Best-effort local machine profile for AI runtime selection."""

    cpu_count: int
    total_memory_bytes: int
    available_memory_bytes: int
    runtime_supports_gpu_offload: bool
    preferred_cpu_threads: int
    gpu_name: str = ""
    gpu_total_memory_bytes: int = 0
    gpu_free_memory_bytes: int = 0
    cuda_dependencies_present: bool = False
    missing_cuda_dependencies: tuple[str, ...] = field(default_factory=tuple)
    runtime_gpu_probe_error: str = ""
    gpu_probe_error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def total_memory_gb(self) -> float:
        return round(self.total_memory_bytes / (1024 ** 3), 2) if self.total_memory_bytes > 0 else 0.0

    @property
    def available_memory_gb(self) -> float:
        return round(self.available_memory_bytes / (1024 ** 3), 2) if self.available_memory_bytes > 0 else 0.0

    @property
    def gpu_total_memory_gb(self) -> float:
        return round(self.gpu_total_memory_bytes / (1024 ** 3), 2) if self.gpu_total_memory_bytes > 0 else 0.0

    @property
    def gpu_free_memory_gb(self) -> float:
        return round(self.gpu_free_memory_bytes / (1024 ** 3), 2) if self.gpu_free_memory_bytes > 0 else 0.0


@dataclass(frozen=True, slots=True)
class LocalAIResolvedSelection:
    """Resolved runtime selection for local GGUF startup."""

    runtime_config: LocalGGUFConfig
    capability: LocalAICapabilityProfile
    selected_model: LocalAIModelSpec | None = None
    auto_selected: bool = False


def resolve_local_ai_selection(
    config: AIConfig,
    *,
    manifest_path: Path = MODEL_MANIFEST_PATH,
    models_dir: Path = MODELS_DIR,
) -> LocalAIResolvedSelection:
    """Resolve the startup local-AI config from user config and local hardware."""
    capability = detect_local_ai_capabilities()
    installed_specs = installed_local_ai_model_specs(manifest_path=manifest_path, models_dir=models_dir)
    selected_model: LocalAIModelSpec | None = None
    auto_selected = False

    model_path = str(config.model_path or "").strip()
    model_id = str(config.model_id or "").strip()
    context_size = int(config.context_size or 4096)
    selection_reason = "explicit_config"

    if _should_auto_select_model(config) and installed_specs:
        selected_model = _preferred_default_model(installed_specs)
        if selected_model is not None:
            auto_selected = True
            selection_reason = "default_model_forced_trial"
            model_path = str((models_dir / selected_model.file_name).resolve())
            model_id = selected_model.model_id
            if context_size <= 0:
                context_size = selected_model.default_context_size
        else:
            selected_model = choose_best_local_model(installed_specs, capability=capability)
        if selected_model is not None:
            if not auto_selected:
                auto_selected = True
                selection_reason = "auto_best_installed"
                model_path = str((models_dir / selected_model.file_name).resolve())
                model_id = selected_model.model_id
                if context_size <= 0:
                    context_size = selected_model.default_context_size

    if selected_model is None and installed_specs:
        selected_model = _configured_model_spec(
            installed_specs,
            model_id=model_id,
            model_path=model_path,
            models_dir=models_dir,
        )

    cpu_threads = _resolve_cpu_threads(config, capability)
    gpu_layers, acceleration_mode, acceleration_reason = _resolve_gpu_layers(config, capability)
    metadata = {
        "selection_mode": "auto" if auto_selected else "manual",
        "selection_reason": selection_reason,
        "selected_model": model_id,
        "acceleration_mode": acceleration_mode,
        "acceleration_reason": acceleration_reason,
        "acceleration_profile": _classify_acceleration_profile(
            selected_model,
            capability=capability,
            acceleration_mode=acceleration_mode,
        ),
        "cpu_threads": cpu_threads,
        "runtime_supports_gpu_offload": capability.runtime_supports_gpu_offload,
        "runtime_gpu_probe_error": capability.runtime_gpu_probe_error,
        "cpu_count": capability.cpu_count,
        "total_memory_gb": capability.total_memory_gb,
        "available_memory_gb": capability.available_memory_gb,
        "gpu_name": capability.gpu_name,
        "vram_total_gb": capability.gpu_total_memory_gb,
        "vram_free_gb": capability.gpu_free_memory_gb,
        "cuda_deps_present": capability.cuda_dependencies_present,
        "missing_cuda_deps": ",".join(capability.missing_cuda_dependencies),
        "gpu_probe_error": capability.gpu_probe_error,
    }
    metadata.update(_vision_metadata_for_spec(selected_model, models_dir=models_dir))
    if selected_model is not None:
        metadata.update(
            {
                "manifest_model_id": selected_model.model_id,
                "manifest_model_size_b": selected_model.parameter_billion,
            }
        )

    runtime_config = LocalGGUFConfig(
        model_path=model_path or str(DEFAULT_AI_MODEL_PATH),
        model_id=model_id or DEFAULT_AI_MODEL_ID,
        context_size=context_size,
        max_output_tokens=config.max_output_tokens,
        temperature=config.temperature,
        gpu_layers=gpu_layers,
        verbose=config.verbose,
        cpu_threads=cpu_threads,
        auto_gpu_enabled=acceleration_mode == "gpu",
        allow_cpu_fallback=True,
        metadata=metadata,
    )
    return LocalAIResolvedSelection(
        runtime_config=runtime_config,
        capability=capability,
        selected_model=selected_model,
        auto_selected=auto_selected,
    )


def load_local_ai_model_specs(
    *,
    manifest_path: Path = MODEL_MANIFEST_PATH,
) -> list[LocalAIModelSpec]:
    """Load the local model manifest."""
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except json.JSONDecodeError:
        return []
    items = list(data.get("models") or [])
    specs: list[LocalAIModelSpec] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("model_id") or "").strip()
        file_name = str(item.get("file_name") or "").strip()
        if not model_id or not file_name:
            continue
        specs.append(
            LocalAIModelSpec(
                model_id=model_id,
                file_name=file_name,
                parameter_billion=float(item.get("parameter_billion") or 0.0),
                quantization=str(item.get("quantization") or "").strip(),
                min_ram_gb=float(item.get("min_ram_gb") or 0.0),
                recommended_ram_gb=float(item.get("recommended_ram_gb") or 0.0),
                min_vram_gb=float(item.get("min_vram_gb") or 0.0),
                recommended_vram_gb=float(item.get("recommended_vram_gb") or 0.0),
                default_context_size=int(item.get("default_context_size") or 4096),
                supports_vision=bool(item.get("supports_vision", False)),
                vision_projector_file=str(item.get("vision_projector_file") or "").strip(),
                vision_projector_globs=_parse_string_tuple(item.get("vision_projector_globs")),
                vision_chat_handler=str(item.get("vision_chat_handler") or "").strip(),
                vision_image_max_tokens=int(item.get("vision_image_max_tokens") or 0),
            )
        )
    return specs


def installed_local_ai_model_specs(
    *,
    manifest_path: Path = MODEL_MANIFEST_PATH,
    models_dir: Path = MODELS_DIR,
) -> list[LocalAIModelSpec]:
    """Return installed manifest models."""
    installed: list[LocalAIModelSpec] = []
    for spec in load_local_ai_model_specs(manifest_path=manifest_path):
        if (models_dir / spec.file_name).is_file():
            installed.append(spec)
    return installed


def choose_best_local_model(
    installed_specs: list[LocalAIModelSpec],
    *,
    capability: LocalAICapabilityProfile,
) -> LocalAIModelSpec | None:
    """Choose the largest installed model that fits this machine conservatively."""
    if not installed_specs:
        return None
    use_vram_limits = _should_apply_vram_model_limits(capability)
    recommended = [
        spec
        for spec in installed_specs
        if _model_fits_recommended(spec, capability, use_vram_limits=use_vram_limits)
    ]
    if recommended:
        return max(recommended, key=lambda item: item.parameter_billion)
    minimum = [
        spec
        for spec in installed_specs
        if _model_fits_minimum(spec, capability, use_vram_limits=use_vram_limits)
    ]
    if minimum:
        return max(minimum, key=lambda item: item.parameter_billion)
    return min(installed_specs, key=lambda item: item.parameter_billion)


def _preferred_default_model(installed_specs: list[LocalAIModelSpec]) -> LocalAIModelSpec | None:
    for spec in installed_specs:
        if spec.model_id == DEFAULT_AI_MODEL_ID:
            return spec
    return None


def _configured_model_spec(
    installed_specs: list[LocalAIModelSpec],
    *,
    model_id: str,
    model_path: str,
    models_dir: Path,
) -> LocalAIModelSpec | None:
    normalized_model_id = str(model_id or "").strip()
    if normalized_model_id:
        for spec in installed_specs:
            if spec.model_id == normalized_model_id:
                return spec
    if model_path:
        try:
            normalized_path = Path(model_path).expanduser().resolve()
        except Exception:
            normalized_path = Path(model_path)
        for spec in installed_specs:
            try:
                if (models_dir / spec.file_name).resolve() == normalized_path:
                    return spec
            except Exception:
                continue
    return None


def _vision_metadata_for_spec(spec: LocalAIModelSpec | None, *, models_dir: Path) -> dict[str, Any]:
    env_projector_path = str(os.getenv("ASSISTIM_AI_VISION_MMPROJ_PATH", "") or "").strip()
    supports_vision = bool((spec and spec.supports_vision) or env_projector_path)
    metadata: dict[str, Any] = {
        "supports_vision": supports_vision,
        "vision_chat_handler": str(getattr(spec, "vision_chat_handler", "") or "gemma4"),
        "vision_mmproj_file": str(getattr(spec, "vision_projector_file", "") or ""),
        "vision_mmproj_path": "",
        "vision_mmproj_available": False,
        "vision_image_max_tokens": int(getattr(spec, "vision_image_max_tokens", 0) or 0),
    }
    if not supports_vision:
        return metadata

    projector_path = _resolve_vision_projector_path_for_spec(spec, models_dir=models_dir)
    if projector_path is not None:
        metadata["vision_mmproj_path"] = str(projector_path)
        metadata["vision_mmproj_available"] = projector_path.is_file()
    if spec is not None and spec.vision_projector_globs:
        metadata["vision_projector_globs"] = "|".join(spec.vision_projector_globs)
    return metadata


def _resolve_vision_projector_path_for_spec(
    spec: LocalAIModelSpec | None,
    *,
    models_dir: Path,
) -> Path | None:
    env_projector_path = str(os.getenv("ASSISTIM_AI_VISION_MMPROJ_PATH", "") or "").strip()
    if env_projector_path:
        return Path(env_projector_path).expanduser().resolve()
    if spec is None or not spec.supports_vision:
        return None
    if spec.vision_projector_file:
        return (models_dir / spec.vision_projector_file).resolve()
    for pattern in spec.vision_projector_globs:
        matches = sorted(models_dir.glob(pattern))
        for candidate in matches:
            if candidate.is_file():
                return candidate.resolve()
    return None


def _parse_string_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        values = [value]
    else:
        values = list(value or []) if isinstance(value, (list, tuple)) else []
    return tuple(str(item or "").strip() for item in values if str(item or "").strip())


@lru_cache(maxsize=1)
def detect_local_ai_capabilities() -> LocalAICapabilityProfile:
    """Return one cached best-effort hardware profile for local AI."""
    total_memory_bytes, available_memory_bytes = _detect_physical_memory()
    cpu_count = max(1, int(os.cpu_count() or 1))
    preferred_cpu_threads = max(1, min(8, cpu_count - 1 if cpu_count > 2 else cpu_count))
    runtime_supports_gpu_offload, runtime_gpu_probe_error = _detect_runtime_gpu_offload_support()
    gpu_name, gpu_total_memory_bytes, gpu_free_memory_bytes, gpu_probe_error = _detect_nvidia_gpu_memory()
    missing_cuda_dependencies = _missing_cuda_dependencies()
    return LocalAICapabilityProfile(
        cpu_count=cpu_count,
        total_memory_bytes=total_memory_bytes,
        available_memory_bytes=available_memory_bytes,
        runtime_supports_gpu_offload=runtime_supports_gpu_offload,
        preferred_cpu_threads=preferred_cpu_threads,
        gpu_name=gpu_name,
        gpu_total_memory_bytes=gpu_total_memory_bytes,
        gpu_free_memory_bytes=gpu_free_memory_bytes,
        cuda_dependencies_present=not missing_cuda_dependencies,
        missing_cuda_dependencies=tuple(missing_cuda_dependencies),
        runtime_gpu_probe_error=runtime_gpu_probe_error,
        gpu_probe_error=gpu_probe_error,
        metadata={"platform": os.name},
    )


def _should_auto_select_model(config: AIConfig) -> bool:
    model_path = str(config.model_path or "").strip()
    model_id = str(config.model_id or "").strip()
    normalized_default_path = str(Path(DEFAULT_AI_MODEL_PATH).resolve())
    normalized_model_path = str(Path(model_path).expanduser().resolve()) if model_path else normalized_default_path
    return (
        not model_id
        or not model_path
        or (
            model_id == DEFAULT_AI_MODEL_ID
            and normalized_model_path == normalized_default_path
        )
    )


def _resolve_cpu_threads(config: AIConfig, capability: LocalAICapabilityProfile) -> int:
    configured_threads = int(getattr(config, "cpu_threads", 0) or 0)
    if configured_threads > 0:
        return configured_threads
    return capability.preferred_cpu_threads


def _resolve_gpu_layers(
    config: AIConfig,
    capability: LocalAICapabilityProfile,
) -> tuple[int, str, str]:
    if not bool(getattr(config, "gpu_enabled", True)):
        return 0, "cpu", "user_disabled_gpu"
    requested_gpu_layers = int(config.gpu_layers or 0)
    if requested_gpu_layers > 0:
        if capability.runtime_supports_gpu_offload:
            return requested_gpu_layers, "gpu", "explicit_gpu_layers"
        return 0, "cpu", _gpu_unavailable_reason(capability)
    if requested_gpu_layers < 0:
        if capability.runtime_supports_gpu_offload:
            return requested_gpu_layers, "gpu", "explicit_auto_gpu_layers"
        return 0, "cpu", _gpu_unavailable_reason(capability)
    if capability.runtime_supports_gpu_offload:
        return -1, "gpu", "auto_gpu_enabled"
    return 0, "cpu", _gpu_unavailable_reason(capability)


def _detect_runtime_gpu_offload_support() -> tuple[bool, str]:
    try:
        import llama_cpp
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    supports = getattr(llama_cpp, "llama_supports_gpu_offload", None)
    if not callable(supports):
        return False, "llama_supports_gpu_offload_unavailable"
    try:
        return bool(supports()), ""
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _detect_nvidia_gpu_memory() -> tuple[str, int, int, str]:
    executable = shutil.which("nvidia-smi")
    if not executable:
        return "", 0, 0, "nvidia_smi_not_found"
    try:
        completed = subprocess.run(
            [
                executable,
                "--query-gpu=name,memory.total,memory.free",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            check=False,
            text=True,
            timeout=3,
        )
    except Exception as exc:
        return "", 0, 0, f"{type(exc).__name__}: {exc}"

    if completed.returncode != 0:
        detail = str(completed.stderr or completed.stdout or "").strip()
        return "", 0, 0, detail or f"nvidia_smi_failed_{completed.returncode}"

    candidates: list[tuple[str, int, int]] = []
    for line in str(completed.stdout or "").splitlines():
        parsed = _parse_nvidia_smi_memory_line(line)
        if parsed is not None:
            candidates.append(parsed)
    if not candidates:
        return "", 0, 0, "nvidia_smi_no_gpu_rows"

    name, total_mib, free_mib = max(candidates, key=lambda item: (item[2], item[1]))
    return name, total_mib * 1024 ** 2, free_mib * 1024 ** 2, ""


def _parse_nvidia_smi_memory_line(line: str) -> tuple[str, int, int] | None:
    parts = [part.strip() for part in str(line or "").split(",")]
    if len(parts) < 3:
        return None
    name = ",".join(parts[:-2]).strip()
    try:
        total_mib = int(float(parts[-2]))
        free_mib = int(float(parts[-1]))
    except ValueError:
        return None
    if not name or total_mib <= 0:
        return None
    return name, max(0, total_mib), max(0, free_mib)


def _missing_cuda_dependencies() -> tuple[str, ...]:
    best_missing: tuple[str, ...] | None = None
    for _label, filenames in CUDA_DEPENDENCY_DLL_SETS:
        missing = tuple(filename for filename in filenames if not _find_file_on_path(filename))
        if not missing:
            return ()
        if best_missing is None or len(missing) < len(best_missing):
            best_missing = missing
    return best_missing or ()


def _find_file_on_path(filename: str) -> Path | None:
    search_dirs = [
        Path(raw_dir.strip('"'))
        for raw_dir in str(os.getenv("PATH", "") or "").split(os.pathsep)
        if raw_dir
    ]
    search_dirs.extend(_candidate_cuda_toolkit_dependency_dirs())
    seen: set[str] = set()
    for directory in search_dirs:
        key = os.path.normcase(str(directory))
        if key in seen:
            continue
        seen.add(key)
        try:
            candidate = directory / filename
        except Exception:
            continue
        if candidate.is_file():
            return candidate
    return None


def _gpu_unavailable_reason(capability: LocalAICapabilityProfile) -> str:
    if capability.missing_cuda_dependencies and (
        capability.gpu_name
        or "dll" in capability.runtime_gpu_probe_error.lower()
        or "shared library" in capability.runtime_gpu_probe_error.lower()
    ):
        return "cuda_dependencies_missing"
    return "runtime_has_no_gpu_offload_support"


def _classify_acceleration_profile(
    spec: LocalAIModelSpec | None,
    *,
    capability: LocalAICapabilityProfile,
    acceleration_mode: str,
) -> str:
    normalized_mode = str(acceleration_mode or "").strip().lower()
    if normalized_mode != "gpu":
        return normalized_mode or "cpu"
    if spec is None:
        return "gpu_mixed"
    available_vram = _available_vram_gb(capability)
    if available_vram <= 0:
        return "gpu_mixed"
    if spec.recommended_vram_gb > 0 and available_vram >= spec.recommended_vram_gb:
        return "gpu_only"
    if spec.recommended_vram_gb <= 0 and spec.min_vram_gb > 0 and available_vram >= spec.min_vram_gb:
        return "gpu_only"
    return "gpu_mixed"


def _should_apply_vram_model_limits(capability: LocalAICapabilityProfile) -> bool:
    return bool(capability.runtime_supports_gpu_offload and capability.gpu_total_memory_bytes > 0)


def _model_fits_recommended(
    spec: LocalAIModelSpec,
    capability: LocalAICapabilityProfile,
    *,
    use_vram_limits: bool,
) -> bool:
    if capability.total_memory_gb < max(spec.recommended_ram_gb, spec.min_ram_gb):
        return False
    if not use_vram_limits:
        return True
    return _available_vram_gb(capability) >= max(spec.recommended_vram_gb, spec.min_vram_gb)


def _model_fits_minimum(
    spec: LocalAIModelSpec,
    capability: LocalAICapabilityProfile,
    *,
    use_vram_limits: bool,
) -> bool:
    if capability.total_memory_gb < spec.min_ram_gb:
        return False
    if not use_vram_limits:
        return True
    return _available_vram_gb(capability) >= spec.min_vram_gb


def _available_vram_gb(capability: LocalAICapabilityProfile) -> float:
    if capability.gpu_free_memory_gb > 0:
        return capability.gpu_free_memory_gb
    return capability.gpu_total_memory_gb


def _detect_physical_memory() -> tuple[int, int]:
    if os.name == "nt":
        try:
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = MEMORYSTATUSEX()
            status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.ullTotalPhys), int(status.ullAvailPhys)
        except Exception:
            pass
    try:
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        total_pages = int(os.sysconf("SC_PHYS_PAGES"))
        available_pages = int(os.sysconf("SC_AVPHYS_PAGES"))
        return page_size * total_pages, page_size * available_pages
    except Exception:
        return 0, 0
