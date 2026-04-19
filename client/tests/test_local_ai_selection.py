from __future__ import annotations

import json

from client.core.config_backend import AIConfig
from client.services import local_ai_selection as selection_module


def _write_manifest(tmp_path, models: list[dict]) -> tuple:
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({"models": models}), encoding="utf-8")
    return manifest_path, models_dir


def _capability(
    *,
    ram_gb: int = 32,
    available_ram_gb: int = 24,
    gpu: bool = False,
    vram_gb: int = 0,
    free_vram_gb: int = 0,
) -> selection_module.LocalAICapabilityProfile:
    return selection_module.LocalAICapabilityProfile(
        cpu_count=12,
        total_memory_bytes=ram_gb * 1024 ** 3,
        available_memory_bytes=available_ram_gb * 1024 ** 3,
        runtime_supports_gpu_offload=gpu,
        preferred_cpu_threads=8,
        gpu_name="NVIDIA RTX Test" if gpu else "",
        gpu_total_memory_bytes=vram_gb * 1024 ** 3,
        gpu_free_memory_bytes=free_vram_gb * 1024 ** 3,
        cuda_dependencies_present=gpu,
    )


def test_resolve_local_ai_selection_auto_picks_largest_installed_model_that_fits(monkeypatch, tmp_path) -> None:
    manifest_path, models_dir = _write_manifest(
        tmp_path,
        [
            {
                "model_id": "demo-0.8b",
                "file_name": "demo-0.8b.gguf",
                "parameter_billion": 0.8,
                "min_ram_gb": 4,
                "recommended_ram_gb": 8,
            },
            {
                "model_id": "demo-2b",
                "file_name": "demo-2b.gguf",
                "parameter_billion": 2,
                "min_ram_gb": 8,
                "recommended_ram_gb": 12,
            },
            {
                "model_id": "demo-4b",
                "file_name": "demo-4b.gguf",
                "parameter_billion": 4,
                "min_ram_gb": 16,
                "recommended_ram_gb": 24,
            },
        ],
    )
    (models_dir / "demo-0.8b.gguf").write_bytes(b"0.8b")
    (models_dir / "demo-2b.gguf").write_bytes(b"2b")
    (models_dir / "demo-4b.gguf").write_bytes(b"4b")

    monkeypatch.setattr(
        selection_module,
        "detect_local_ai_capabilities",
        lambda: selection_module.LocalAICapabilityProfile(
            cpu_count=12,
            total_memory_bytes=20 * 1024 ** 3,
            available_memory_bytes=14 * 1024 ** 3,
            runtime_supports_gpu_offload=False,
            preferred_cpu_threads=8,
        ),
    )

    resolved = selection_module.resolve_local_ai_selection(
        AIConfig(),
        manifest_path=manifest_path,
        models_dir=models_dir,
    )

    assert resolved.auto_selected is True
    assert resolved.selected_model is not None
    assert resolved.selected_model.model_id == "demo-2b"
    assert resolved.runtime_config.model_id == "demo-2b"
    assert resolved.runtime_config.gpu_layers == 0
    assert resolved.runtime_config.cpu_threads == 8
    assert resolved.runtime_config.metadata["selection_reason"] == "auto_best_installed"


def test_resolve_local_ai_selection_auto_enables_gpu_when_runtime_supports_it(monkeypatch, tmp_path) -> None:
    manifest_path, models_dir = _write_manifest(
        tmp_path,
        [
            {
                "model_id": "demo-2b",
                "file_name": "demo-2b.gguf",
                "parameter_billion": 2,
                "min_ram_gb": 8,
                "recommended_ram_gb": 12,
            }
        ],
    )
    (models_dir / "demo-2b.gguf").write_bytes(b"2b")

    monkeypatch.setattr(
        selection_module,
        "detect_local_ai_capabilities",
        lambda: selection_module.LocalAICapabilityProfile(
            cpu_count=8,
            total_memory_bytes=32 * 1024 ** 3,
            available_memory_bytes=28 * 1024 ** 3,
            runtime_supports_gpu_offload=True,
            preferred_cpu_threads=6,
        ),
    )

    resolved = selection_module.resolve_local_ai_selection(
        AIConfig(),
        manifest_path=manifest_path,
        models_dir=models_dir,
    )

    assert resolved.runtime_config.gpu_layers == -1
    assert resolved.runtime_config.auto_gpu_enabled is True
    assert resolved.runtime_config.metadata["acceleration_mode"] == "gpu"


def test_resolve_local_ai_selection_prefers_default_model_for_trial(monkeypatch, tmp_path) -> None:
    default_model_id = "demo-2b"
    default_model_file = "demo-2b.gguf"
    default_model_path = tmp_path / default_model_file
    manifest_path, models_dir = _write_manifest(
        tmp_path,
        [
            {
                "model_id": "demo-0.8b",
                "file_name": "demo-0.8b.gguf",
                "parameter_billion": 0.8,
                "min_ram_gb": 4,
                "recommended_ram_gb": 8,
                "min_vram_gb": 2,
                "recommended_vram_gb": 4,
            },
            {
                "model_id": default_model_id,
                "file_name": default_model_file,
                "parameter_billion": 2,
                "min_ram_gb": 8,
                "recommended_ram_gb": 12,
                "min_vram_gb": 4,
                "recommended_vram_gb": 6,
            },
        ],
    )
    (models_dir / "demo-0.8b.gguf").write_bytes(b"0.8b")
    (models_dir / default_model_file).write_bytes(b"2b")

    monkeypatch.setattr(selection_module, "DEFAULT_AI_MODEL_ID", default_model_id)
    monkeypatch.setattr(selection_module, "DEFAULT_AI_MODEL_PATH", default_model_path)
    monkeypatch.setattr(
        selection_module,
        "detect_local_ai_capabilities",
        lambda: _capability(ram_gb=16, available_ram_gb=12, gpu=True, vram_gb=2, free_vram_gb=2),
    )

    resolved = selection_module.resolve_local_ai_selection(
        AIConfig(model_id=default_model_id, model_path=str(default_model_path)),
        manifest_path=manifest_path,
        models_dir=models_dir,
    )

    assert resolved.selected_model is not None
    assert resolved.selected_model.model_id == default_model_id
    assert resolved.runtime_config.model_id == default_model_id
    assert resolved.runtime_config.metadata["selection_reason"] == "default_model_forced_trial"


def test_resolve_local_ai_selection_uses_vram_when_selecting_gpu_model(monkeypatch, tmp_path) -> None:
    manifest_path, models_dir = _write_manifest(
        tmp_path,
        [
            {
                "model_id": "demo-2b",
                "file_name": "demo-2b.gguf",
                "parameter_billion": 2,
                "min_ram_gb": 8,
                "recommended_ram_gb": 12,
                "min_vram_gb": 4,
                "recommended_vram_gb": 6,
            },
            {
                "model_id": "demo-4b",
                "file_name": "demo-4b.gguf",
                "parameter_billion": 4,
                "min_ram_gb": 16,
                "recommended_ram_gb": 24,
                "min_vram_gb": 8,
                "recommended_vram_gb": 10,
            },
            {
                "model_id": "demo-9b",
                "file_name": "demo-9b.gguf",
                "parameter_billion": 9,
                "min_ram_gb": 32,
                "recommended_ram_gb": 48,
                "min_vram_gb": 16,
                "recommended_vram_gb": 24,
            },
        ],
    )
    for name in ("demo-2b.gguf", "demo-4b.gguf", "demo-9b.gguf"):
        (models_dir / name).write_bytes(b"model")

    monkeypatch.setattr(
        selection_module,
        "detect_local_ai_capabilities",
        lambda: _capability(ram_gb=64, available_ram_gb=56, gpu=True, vram_gb=12, free_vram_gb=11),
    )

    resolved = selection_module.resolve_local_ai_selection(
        AIConfig(),
        manifest_path=manifest_path,
        models_dir=models_dir,
    )

    assert resolved.selected_model is not None
    assert resolved.selected_model.model_id == "demo-4b"
    assert resolved.runtime_config.gpu_layers == -1
    assert resolved.runtime_config.metadata["gpu_name"] == "NVIDIA RTX Test"
    assert resolved.runtime_config.metadata["vram_free_gb"] == 11.0


def test_resolve_local_ai_selection_downgrades_when_vram_is_low(monkeypatch, tmp_path) -> None:
    manifest_path, models_dir = _write_manifest(
        tmp_path,
        [
            {
                "model_id": "demo-0.8b",
                "file_name": "demo-0.8b.gguf",
                "parameter_billion": 0.8,
                "min_ram_gb": 4,
                "recommended_ram_gb": 8,
                "min_vram_gb": 2,
                "recommended_vram_gb": 4,
            },
            {
                "model_id": "demo-2b",
                "file_name": "demo-2b.gguf",
                "parameter_billion": 2,
                "min_ram_gb": 8,
                "recommended_ram_gb": 12,
                "min_vram_gb": 4,
                "recommended_vram_gb": 6,
            },
        ],
    )
    for name in ("demo-0.8b.gguf", "demo-2b.gguf"):
        (models_dir / name).write_bytes(b"model")

    monkeypatch.setattr(
        selection_module,
        "detect_local_ai_capabilities",
        lambda: _capability(ram_gb=64, available_ram_gb=56, gpu=True, vram_gb=8, free_vram_gb=5),
    )

    resolved = selection_module.resolve_local_ai_selection(
        AIConfig(),
        manifest_path=manifest_path,
        models_dir=models_dir,
    )

    assert resolved.selected_model is not None
    assert resolved.selected_model.model_id == "demo-0.8b"


def test_resolve_local_ai_selection_preserves_explicit_model_path(monkeypatch, tmp_path) -> None:
    manifest_path, models_dir = _write_manifest(tmp_path, [])
    monkeypatch.setattr(
        selection_module,
        "detect_local_ai_capabilities",
        lambda: selection_module.LocalAICapabilityProfile(
            cpu_count=8,
            total_memory_bytes=16 * 1024 ** 3,
            available_memory_bytes=12 * 1024 ** 3,
            runtime_supports_gpu_offload=True,
            preferred_cpu_threads=5,
        ),
    )

    resolved = selection_module.resolve_local_ai_selection(
        AIConfig(
            model_path="D:/models/custom.gguf",
            model_id="custom-model",
            gpu_layers=12,
            cpu_threads=4,
        ),
        manifest_path=manifest_path,
        models_dir=models_dir,
    )

    assert resolved.auto_selected is False
    assert resolved.selected_model is None
    assert resolved.runtime_config.model_id == "custom-model"
    assert resolved.runtime_config.model_path == "D:/models/custom.gguf"
    assert resolved.runtime_config.gpu_layers == 12
    assert resolved.runtime_config.cpu_threads == 4


def test_parse_nvidia_smi_memory_line() -> None:
    parsed = selection_module._parse_nvidia_smi_memory_line("NVIDIA GeForce RTX 4070, 12282, 10000")

    assert parsed == ("NVIDIA GeForce RTX 4070", 12282, 10000)


def test_detect_capability_records_missing_cuda_dependencies(monkeypatch) -> None:
    selection_module.detect_local_ai_capabilities.cache_clear()
    monkeypatch.setattr(selection_module, "_detect_physical_memory", lambda: (32 * 1024 ** 3, 24 * 1024 ** 3))
    monkeypatch.setattr(selection_module.os, "cpu_count", lambda: 12)
    monkeypatch.setattr(
        selection_module,
        "_detect_runtime_gpu_offload_support",
        lambda: (False, "RuntimeError: Failed to load shared library llama.dll"),
    )
    monkeypatch.setattr(
        selection_module,
        "_detect_nvidia_gpu_memory",
        lambda: ("NVIDIA RTX Test", 8 * 1024 ** 3, 6 * 1024 ** 3, ""),
    )
    monkeypatch.setattr(
        selection_module,
        "_missing_cuda_12_dependencies",
        lambda: ("cudart64_12.dll", "cublas64_12.dll"),
    )

    capability = selection_module.detect_local_ai_capabilities()
    try:
        gpu_layers, acceleration, reason = selection_module._resolve_gpu_layers(
            AIConfig(gpu_layers=-1),
            capability,
        )
    finally:
        selection_module.detect_local_ai_capabilities.cache_clear()

    assert capability.cuda_dependencies_present is False
    assert capability.missing_cuda_dependencies == ("cudart64_12.dll", "cublas64_12.dll")
    assert gpu_layers == 0
    assert acceleration == "cpu"
    assert reason == "cuda_dependencies_missing"


def test_resolve_local_ai_selection_respects_user_disabled_gpu(monkeypatch, tmp_path) -> None:
    manifest_path, models_dir = _write_manifest(
        tmp_path,
        [
            {
                "model_id": "demo-gemma",
                "file_name": "demo-gemma.gguf",
                "parameter_billion": 2,
                "min_ram_gb": 8,
                "recommended_ram_gb": 12,
                "min_vram_gb": 2,
                "recommended_vram_gb": 4,
            }
        ],
    )
    (models_dir / "demo-gemma.gguf").write_bytes(b"gemma")
    monkeypatch.setattr(
        selection_module,
        "detect_local_ai_capabilities",
        lambda: _capability(ram_gb=16, available_ram_gb=12, gpu=True, vram_gb=8, free_vram_gb=6),
    )

    resolved = selection_module.resolve_local_ai_selection(
        AIConfig(
            model_id="demo-gemma",
            model_path=str((models_dir / "demo-gemma.gguf").resolve()),
            gpu_enabled=False,
        ),
        manifest_path=manifest_path,
        models_dir=models_dir,
    )

    assert resolved.runtime_config.gpu_layers == 0
    assert resolved.runtime_config.auto_gpu_enabled is False
    assert resolved.runtime_config.metadata["acceleration_reason"] == "user_disabled_gpu"
