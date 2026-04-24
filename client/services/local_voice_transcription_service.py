"""Local voice transcription runtime backed by faster-whisper."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from client.core import logging
from client.core.config_backend import CLIENT_ROOT
from client.core.voice_transcription import VOICE_TRANSCRIPT_MAX_SECONDS

logger = logging.get_logger(__name__)


def _parse_int_env(name: str, default: int) -> int:
    raw_value = str(os.getenv(name, "") or "").strip()
    if not raw_value:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


def _default_cpu_threads() -> int:
    return max(1, min(8, os.cpu_count() or 1))


@dataclass(slots=True)
class LocalVoiceTranscriptionConfig:
    """Configuration for one faster-whisper ASR runtime."""

    model_id: str = field(default_factory=lambda: str(os.getenv("ASSISTIM_ASR_MODEL_ID", "small") or "small").strip())
    model_path: str = field(default_factory=lambda: str(os.getenv("ASSISTIM_ASR_MODEL_PATH", "") or "").strip())
    model_dir: str = field(
        default_factory=lambda: str(
            Path(os.getenv("ASSISTIM_ASR_MODEL_DIR", "") or CLIENT_ROOT / "resources" / "models" / "faster-whisper")
        )
    )
    device: str = field(default_factory=lambda: str(os.getenv("ASSISTIM_ASR_DEVICE", "cpu") or "cpu").strip().lower())
    compute_type: str = field(default_factory=lambda: str(os.getenv("ASSISTIM_ASR_COMPUTE_TYPE", "int8") or "int8").strip())
    cpu_threads: int = field(default_factory=lambda: _parse_int_env("ASSISTIM_ASR_CPU_THREADS", _default_cpu_threads()))
    beam_size: int = field(default_factory=lambda: _parse_int_env("ASSISTIM_ASR_BEAM_SIZE", 1))
    language: str = field(default_factory=lambda: str(os.getenv("ASSISTIM_ASR_LANGUAGE", "") or "").strip())
    max_duration_seconds: int = field(
        default_factory=lambda: _parse_int_env("ASSISTIM_ASR_MAX_SECONDS", VOICE_TRANSCRIPT_MAX_SECONDS)
    )


@dataclass(slots=True)
class LocalVoiceTranscriptionResult:
    """One completed local voice transcription result."""

    text: str
    language: str = ""
    language_probability: float = 0.0
    duration_seconds: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class LocalVoiceTranscriptionRuntimeError(RuntimeError):
    """Stable local voice transcription error."""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        super().__init__(message or code)


class LocalVoiceTranscriptionRuntime:
    """Lazy faster-whisper wrapper for short local voice messages."""

    def __init__(self, config: LocalVoiceTranscriptionConfig | None = None) -> None:
        self._config = config or LocalVoiceTranscriptionConfig()
        self._model = None
        self._load_lock = asyncio.Lock()
        self._closed = False

    @property
    def config(self) -> LocalVoiceTranscriptionConfig:
        return self._config

    async def close(self) -> None:
        self._closed = True
        self._model = None

    async def transcribe(self, audio_path: str, *, duration_seconds: int | None = None) -> LocalVoiceTranscriptionResult:
        """Transcribe one local audio file."""
        path = self._assert_audio_available(audio_path)
        normalized_duration = self._normalize_duration(duration_seconds)
        if normalized_duration > int(self._config.max_duration_seconds or VOICE_TRANSCRIPT_MAX_SECONDS):
            raise LocalVoiceTranscriptionRuntimeError(
                "VOICE_TRANSCRIPT_AUDIO_TOO_LONG",
                f"Voice transcription only supports audio up to {self._config.max_duration_seconds} seconds",
            )

        await self.load()
        try:
            return await asyncio.to_thread(self._transcribe_sync, str(path), normalized_duration)
        except LocalVoiceTranscriptionRuntimeError:
            raise
        except Exception as exc:
            raise LocalVoiceTranscriptionRuntimeError(
                "VOICE_TRANSCRIPT_GENERATION_FAILED",
                f"Local voice transcription failed: {exc}",
            ) from exc

    async def load(self) -> None:
        """Load faster-whisper lazily."""
        if self._closed:
            raise LocalVoiceTranscriptionRuntimeError("VOICE_TRANSCRIPT_RUNTIME_CLOSED", "Voice transcription runtime is closed")
        if self._model is not None:
            return
        async with self._load_lock:
            if self._model is not None:
                return
            try:
                self._model = await asyncio.to_thread(self._load_sync)
            except LocalVoiceTranscriptionRuntimeError:
                raise
            except Exception as exc:
                raise LocalVoiceTranscriptionRuntimeError(
                    "VOICE_TRANSCRIPT_MODEL_LOAD_FAILED",
                    f"Local voice transcription model failed to load: {exc}",
                ) from exc

    def _load_sync(self):
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise LocalVoiceTranscriptionRuntimeError(
                "VOICE_TRANSCRIPT_DEPENDENCY_MISSING",
                "faster-whisper is not installed",
            ) from exc

        model_dir = Path(self._config.model_dir).expanduser().resolve()
        model_dir.mkdir(parents=True, exist_ok=True)
        model_size_or_path = self._model_size_or_path(model_dir)
        kwargs: dict[str, Any] = {
            "device": self._config.device or "cpu",
            "compute_type": self._config.compute_type or "int8",
            "cpu_threads": max(1, int(self._config.cpu_threads or _default_cpu_threads())),
            "download_root": str(model_dir),
        }
        logger.info(
            "[voice-asr] load_start provider=faster-whisper model=%s device=%s compute_type=%s cpu_threads=%s",
            model_size_or_path,
            kwargs["device"],
            kwargs["compute_type"],
            kwargs["cpu_threads"],
        )
        model = WhisperModel(model_size_or_path, **kwargs)
        logger.info("[voice-asr] load_done provider=faster-whisper model=%s", model_size_or_path)
        return model

    def _transcribe_sync(self, audio_path: str, duration_seconds: int) -> LocalVoiceTranscriptionResult:
        model = self._model
        if model is None:
            raise LocalVoiceTranscriptionRuntimeError("VOICE_TRANSCRIPT_MODEL_NOT_LOADED", "Voice transcription model is not loaded")

        kwargs: dict[str, Any] = {"beam_size": max(1, int(self._config.beam_size or 1))}
        if self._config.language:
            kwargs["language"] = self._config.language
        segments, info = model.transcribe(audio_path, **kwargs)
        collected = list(segments)
        text = " ".join(str(getattr(segment, "text", "") or "").strip() for segment in collected if str(getattr(segment, "text", "") or "").strip())
        return LocalVoiceTranscriptionResult(
            text=" ".join(text.split()),
            language=str(getattr(info, "language", "") or ""),
            language_probability=float(getattr(info, "language_probability", 0.0) or 0.0),
            duration_seconds=duration_seconds,
            metadata={
                "engine": "faster-whisper",
                "model_id": self._config.model_id,
                "device": self._config.device,
                "compute_type": self._config.compute_type,
                "beam_size": max(1, int(self._config.beam_size or 1)),
            },
        )

    def _model_size_or_path(self, model_dir: Path) -> str:
        explicit_path = str(self._config.model_path or "").strip()
        if explicit_path:
            return str(Path(explicit_path).expanduser().resolve())

        model_id = str(self._config.model_id or "small").strip() or "small"
        local_dir = model_dir / model_id
        if local_dir.is_dir():
            return str(local_dir)
        return model_id

    @staticmethod
    def _assert_audio_available(audio_path: str) -> Path:
        path = Path(str(audio_path or "")).expanduser()
        if not str(path):
            raise LocalVoiceTranscriptionRuntimeError("VOICE_TRANSCRIPT_AUDIO_NOT_FOUND", "Voice audio path is required")
        try:
            resolved = path.resolve()
        except OSError as exc:
            raise LocalVoiceTranscriptionRuntimeError("VOICE_TRANSCRIPT_AUDIO_NOT_FOUND", str(exc)) from exc
        if not resolved.is_file():
            raise LocalVoiceTranscriptionRuntimeError("VOICE_TRANSCRIPT_AUDIO_NOT_FOUND", f"Voice audio not found: {resolved}")
        return resolved

    @staticmethod
    def _normalize_duration(duration_seconds: int | None) -> int:
        if duration_seconds in (None, ""):
            return 0
        try:
            return max(0, int(float(duration_seconds)))
        except (TypeError, ValueError):
            return 0


_runtime: LocalVoiceTranscriptionRuntime | None = None


def get_local_voice_transcription_runtime() -> LocalVoiceTranscriptionRuntime:
    """Return the process-wide local voice transcription runtime."""
    global _runtime
    if _runtime is None:
        _runtime = LocalVoiceTranscriptionRuntime()
    return _runtime
