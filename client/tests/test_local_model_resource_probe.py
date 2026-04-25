from __future__ import annotations

from types import SimpleNamespace

from client.core.config_backend import AIConfig
from client.services.local_ai_selection import LocalAICapabilityProfile
from client.services.local_voice_transcription_service import LocalVoiceTranscriptionConfig
from client.services.local_model_resource_probe import probe_local_model_resources


def _capability(*, gpu: bool = False, missing_cuda: tuple[str, ...] = ()) -> LocalAICapabilityProfile:
    return LocalAICapabilityProfile(
        cpu_count=12,
        total_memory_bytes=16 * 1024 ** 3,
        available_memory_bytes=10 * 1024 ** 3,
        runtime_supports_gpu_offload=gpu,
        preferred_cpu_threads=8,
        gpu_name="NVIDIA Test" if gpu else "",
        gpu_total_memory_bytes=2 * 1024 ** 3 if gpu else 0,
        gpu_free_memory_bytes=1 * 1024 ** 3 if gpu else 0,
        cuda_dependencies_present=not missing_cuda,
        missing_cuda_dependencies=missing_cuda,
    )


def test_local_model_resource_probe_reports_models_dependencies_and_asr_files(tmp_path) -> None:
    chat_model = tmp_path / "chat.gguf"
    chat_model.write_bytes(b"chat")
    asr_root = tmp_path / "faster-whisper"
    asr_model_dir = asr_root / "small"
    asr_model_dir.mkdir(parents=True)
    (asr_model_dir / "config.json").write_text("{}", encoding="utf-8")
    (asr_model_dir / "model.bin").write_bytes(b"model")

    report = probe_local_model_resources(
        config=SimpleNamespace(
            ai=AIConfig(
                provider="local_gguf",
                model_id="chat-model",
                model_path=str(chat_model),
                embedding_model_id="embed-model",
                embedding_model_path=str(tmp_path / "missing-embed.gguf"),
                gpu_enabled=True,
                gpu_layers=0,
                cpu_threads=0,
            )
        ),
        asr_config=LocalVoiceTranscriptionConfig(
            model_id="small",
            model_dir=str(asr_root),
            device="cpu",
            compute_type="int8",
            cpu_threads=4,
            allow_download=False,
        ),
        capability=_capability(gpu=True, missing_cuda=("cudart64_12.dll",)),
        dependency_checker=lambda module_name: module_name == "llama_cpp",
    )

    chat = report.by_key("chat_model")
    assert chat.status == "ready"
    assert chat.exists is True
    assert chat.size_bytes == 4
    assert chat.metadata["acceleration"] == "gpu"
    assert chat.metadata["gpu_name"] == "NVIDIA Test"

    embedding = report.by_key("embedding_model")
    assert embedding.status == "missing"
    assert embedding.exists is False

    asr = report.by_key("voice_transcription_model")
    assert asr.status == "missing"
    assert asr.path == str(asr_model_dir.resolve())
    assert "tokenizer.json" in asr.metadata["missing_files"]
    assert "vocabulary.txt" in asr.metadata["missing_files"]

    assert report.by_key("dependency_llama_cpp").status == "ready"
    assert report.by_key("dependency_llama_cpp_embedding").status == "dependency_missing"
    assert report.by_key("dependency_faster_whisper").status == "dependency_missing"
    assert report.by_key("dependency_cuda_12").status == "dependency_missing"
    assert report.overall_status == "dependency_missing"


def test_local_model_resource_probe_marks_non_local_chat_provider_disabled(tmp_path) -> None:
    chat_model = tmp_path / "chat.gguf"
    chat_model.write_bytes(b"chat")

    report = probe_local_model_resources(
        config=SimpleNamespace(
            ai=AIConfig(
                provider="remote",
                model_id="chat-model",
                model_path=str(chat_model),
                embedding_model_id="embed-model",
                embedding_model_path=str(chat_model),
            )
        ),
        asr_config=LocalVoiceTranscriptionConfig(model_id="small", model_dir=str(tmp_path / "asr")),
        capability=_capability(),
        dependency_checker=lambda _module_name: True,
    )

    chat = report.by_key("chat_model")
    assert chat.status == "config_disabled"
    assert chat.exists is True
    assert "remote" in chat.detail


def test_local_model_resource_probe_reports_ready_faster_whisper_directory(tmp_path) -> None:
    asr_root = tmp_path / "faster-whisper"
    asr_model_dir = asr_root / "small"
    asr_model_dir.mkdir(parents=True)
    for filename in ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt"):
        (asr_model_dir / filename).write_bytes(b"ok")

    model = tmp_path / "model.gguf"
    model.write_bytes(b"model")
    report = probe_local_model_resources(
        config=SimpleNamespace(
            ai=AIConfig(
                provider="local_gguf",
                model_id="chat-model",
                model_path=str(model),
                embedding_model_id="embed-model",
                embedding_model_path=str(model),
            )
        ),
        asr_config=LocalVoiceTranscriptionConfig(
            model_id="small",
            model_dir=str(asr_root),
            device="cpu",
            compute_type="int8",
            cpu_threads=8,
            allow_download=False,
        ),
        capability=_capability(),
        dependency_checker=lambda _module_name: True,
    )

    asr = report.by_key("voice_transcription_model")
    assert asr.status == "ready"
    assert asr.exists is True
    assert asr.metadata["device"] == "cpu"
    assert asr.metadata["compute_type"] == "int8"
    assert asr.metadata["cpu_threads"] == 8
    assert report.overall_status == "ready"
