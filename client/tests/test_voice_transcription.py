from __future__ import annotations

import asyncio
import builtins
import sys
import types
from pathlib import Path

from client.core.voice_transcription import VOICE_TRANSCRIPT_EXTRA_KEY, voice_transcript_display_text
from client.services.local_voice_transcription_service import (
    LocalVoiceTranscriptionConfig,
    LocalVoiceTranscriptionRuntime,
    LocalVoiceTranscriptionRuntimeError,
)


def test_voice_transcript_display_text_maps_runtime_statuses() -> None:
    assert voice_transcript_display_text({VOICE_TRANSCRIPT_EXTRA_KEY: {"status": "pending"}}) == "正在转文字..."
    assert voice_transcript_display_text({VOICE_TRANSCRIPT_EXTRA_KEY: {"status": "ready", "text": "你好"}}) == "你好"
    assert voice_transcript_display_text({VOICE_TRANSCRIPT_EXTRA_KEY: {"status": "failed"}}) == "转文字失败"
    assert voice_transcript_display_text({VOICE_TRANSCRIPT_EXTRA_KEY: {"status": "failed", "reason": "model_missing"}}) == "未找到语音转文字模型"
    assert voice_transcript_display_text({VOICE_TRANSCRIPT_EXTRA_KEY: {"status": "skipped", "reason": "audio_too_long"}}) == "语音超过 30 秒，暂不支持转文字"


def test_faster_whisper_runtime_defaults_to_local_model_only(monkeypatch, tmp_path) -> None:
    calls: dict[str, object] = {}

    class FakeSegment:
        def __init__(self, text: str) -> None:
            self.text = text
            self.start = 0.0
            self.end = 1.0

    class FakeInfo:
        language = "zh"
        language_probability = 0.93

    class FakeWhisperModel:
        def __init__(self, model_size_or_path, **kwargs) -> None:
            calls["model_size_or_path"] = model_size_or_path
            calls["kwargs"] = dict(kwargs)

        def transcribe(self, audio_path, **kwargs):
            calls["audio_path"] = audio_path
            calls["transcribe_kwargs"] = dict(kwargs)
            return [FakeSegment(" 今晚八点开会 "), FakeSegment(" 不要迟到")], FakeInfo()

    fake_module = types.ModuleType("faster_whisper")
    fake_module.WhisperModel = FakeWhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)

    audio_path = tmp_path / "voice.wav"
    audio_path.write_bytes(b"fake")
    local_model_dir = tmp_path / "models" / "small"
    local_model_dir.mkdir(parents=True)

    runtime = LocalVoiceTranscriptionRuntime(
        LocalVoiceTranscriptionConfig(
            model_id="small",
            model_dir=str(tmp_path / "models"),
            device="cpu",
            compute_type="int8",
            cpu_threads=4,
            beam_size=1,
        )
    )

    async def scenario() -> None:
        result = await runtime.transcribe(str(audio_path), duration_seconds=12)
        assert result.text == "今晚八点开会 不要迟到"
        assert result.language == "zh"
        assert result.language_probability == 0.93

    asyncio.run(scenario())

    assert calls["model_size_or_path"] == str(local_model_dir.resolve())
    assert calls["kwargs"]["device"] == "cpu"
    assert calls["kwargs"]["compute_type"] == "int8"
    assert calls["kwargs"]["cpu_threads"] == 4
    assert Path(calls["kwargs"]["download_root"]).name == "models"
    assert calls["kwargs"]["local_files_only"] is True
    assert calls["audio_path"] == str(audio_path)
    assert calls["transcribe_kwargs"]["beam_size"] == 1


def test_faster_whisper_runtime_rejects_missing_local_model_without_importing(monkeypatch, tmp_path) -> None:
    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "faster_whisper":
            raise AssertionError("faster_whisper should not be imported when local model is missing")
        return real_import(name, globals, locals, fromlist, level)

    real_import = builtins.__import__
    monkeypatch.setattr(builtins, "__import__", fake_import)

    audio_path = tmp_path / "voice.wav"
    audio_path.write_bytes(b"fake")

    runtime = LocalVoiceTranscriptionRuntime(
        LocalVoiceTranscriptionConfig(model_id="small", model_dir=str(tmp_path / "models"))
    )

    async def scenario() -> None:
        try:
            await runtime.transcribe(str(audio_path), duration_seconds=3)
        except LocalVoiceTranscriptionRuntimeError as exc:
            assert exc.code == "VOICE_TRANSCRIPT_MODEL_NOT_FOUND"
            assert "ASSISTIM_ASR_ALLOW_DOWNLOAD=1" in str(exc)
        else:
            raise AssertionError("expected missing local model to be reported")

    asyncio.run(scenario())


def test_faster_whisper_runtime_allows_download_only_when_explicitly_enabled(monkeypatch, tmp_path) -> None:
    calls: dict[str, object] = {}

    class FakeWhisperModel:
        def __init__(self, model_size_or_path, **kwargs) -> None:
            calls["model_size_or_path"] = model_size_or_path
            calls["kwargs"] = dict(kwargs)

        def transcribe(self, audio_path, **kwargs):
            return [], types.SimpleNamespace(language="", language_probability=0.0)

    fake_module = types.ModuleType("faster_whisper")
    fake_module.WhisperModel = FakeWhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)

    audio_path = tmp_path / "voice.wav"
    audio_path.write_bytes(b"fake")

    runtime = LocalVoiceTranscriptionRuntime(
        LocalVoiceTranscriptionConfig(model_id="small", model_dir=str(tmp_path / "models"), allow_download=True)
    )

    async def scenario() -> None:
        await runtime.transcribe(str(audio_path), duration_seconds=3)

    asyncio.run(scenario())

    assert calls["model_size_or_path"] == "small"
    assert calls["kwargs"]["local_files_only"] is False


def test_faster_whisper_runtime_rejects_overlong_voice_before_loading(monkeypatch, tmp_path) -> None:
    monkeypatch.delitem(sys.modules, "faster_whisper", raising=False)
    audio_path = tmp_path / "voice.wav"
    audio_path.write_bytes(b"fake")

    runtime = LocalVoiceTranscriptionRuntime(
        LocalVoiceTranscriptionConfig(model_id="small", model_dir=str(tmp_path / "models"), max_duration_seconds=30)
    )

    async def scenario() -> None:
        try:
            await runtime.transcribe(str(audio_path), duration_seconds=31)
        except LocalVoiceTranscriptionRuntimeError as exc:
            assert exc.code == "VOICE_TRANSCRIPT_AUDIO_TOO_LONG"
        else:
            raise AssertionError("expected overlong audio to be rejected")

    asyncio.run(scenario())


def test_faster_whisper_runtime_missing_dependency_has_stable_error(monkeypatch, tmp_path) -> None:
    monkeypatch.delitem(sys.modules, "faster_whisper", raising=False)

    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "faster_whisper":
            raise ImportError("blocked by test")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    audio_path = tmp_path / "voice.wav"
    audio_path.write_bytes(b"fake")
    (tmp_path / "small").mkdir()

    runtime = LocalVoiceTranscriptionRuntime(LocalVoiceTranscriptionConfig(model_id="small", model_dir=str(tmp_path)))

    async def scenario() -> None:
        try:
            await runtime.transcribe(str(audio_path), duration_seconds=3)
        except LocalVoiceTranscriptionRuntimeError as exc:
            assert exc.code == "VOICE_TRANSCRIPT_DEPENDENCY_MISSING"
        else:
            raise AssertionError("expected missing dependency to be reported")

    asyncio.run(scenario())
