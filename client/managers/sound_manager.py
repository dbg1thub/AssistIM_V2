"""Audio manager for notification sounds and future UI sound effects."""

from __future__ import annotations

import json
import time
import wave
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from qfluentwidgets import Theme

from client.core import logging
from client.core.config import cfg
from client.core.logging import setup_logging
from client.events.event_bus import get_event_bus
from client.managers.message_manager import MessageEvent
from client.managers.session_manager import peek_session_manager


setup_logging()
logger = logging.get_logger(__name__)

_WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
_AUDIO_ROOT = _WORKSPACE_ROOT / "client" / "resources" / "audio"
_AUDIO_MANIFEST_PATH = _AUDIO_ROOT / "manifest.json"


class AppSound(str, Enum):
    MESSAGE_INCOMING = "message_incoming"
    CALL_OUTGOING_RING = "call_outgoing_ring"
    CALL_INCOMING_RING = "call_incoming_ring"
    CALL_CONNECTED = "call_connected"
    CALL_ENDED = "call_ended"


@dataclass(frozen=True)
class SoundAsset:
    sound_id: str
    category: str
    variants: dict[str, Path]
    volume: float = 1.0
    polyphony: int = 1
    cooldown_ms: int = 0
    loop: bool = False
    fade_in_ms: int = 0
    fade_out_ms: int = 0
    duration_ms: int = 0


@dataclass
class _FadeJob:
    effect: Any
    start_volume: float
    end_volume: float
    started_at: float
    duration_ms: int
    stop_after: bool = False


def _create_sound_effect(path: Path, volume: float, *, loop: bool = False):
    try:
        from PySide6.QtCore import QUrl
        from PySide6.QtMultimedia import QSoundEffect
    except Exception:
        return None

    effect = QSoundEffect()
    effect.setSource(QUrl.fromLocalFile(str(path)))
    infinite_loop_count = getattr(QSoundEffect, "Infinite", -2)
    try:
        infinite_loop_count = int(infinite_loop_count)
    except (TypeError, ValueError):
        infinite_loop_count = -2
    effect.setLoopCount(infinite_loop_count if loop else 1)
    effect.setVolume(volume)
    return effect


def _normalize_sound_id(sound_id: AppSound | str) -> str:
    if isinstance(sound_id, Enum):
        return str(sound_id.value)
    return str(sound_id)


class SoundManager:
    """Load sound assets from a manifest and play them in response to app events."""

    def __init__(self) -> None:
        self._event_bus = get_event_bus()
        self._assets: dict[str, SoundAsset] = {}
        self._effect_pools: dict[tuple[str, str], list[Any]] = {}
        self._event_subscriptions: list[tuple[str, Any]] = []
        self._last_played_at: dict[str, float] = {}
        self._pending_loaded_callbacks: dict[tuple[str, str, int], Any] = {}
        self._fade_jobs: dict[int, _FadeJob] = {}
        self._effect_generations: dict[int, int] = {}
        self._fade_timer = None
        self._initialized = False
        self._init_fade_timer()

    async def initialize(self) -> None:
        if self._initialized:
            return

        self._load_manifest()
        self._prime_effect_pool()
        self._event_subscriptions.append((MessageEvent.RECEIVED, self._on_message_received))
        await self._event_bus.subscribe(MessageEvent.RECEIVED, self._on_message_received)
        self._initialized = True
        logger.info("Sound manager initialized with %s sound assets", len(self._assets))

    def available_sounds(self) -> list[str]:
        return sorted(self._assets.keys())

    def has_sound(self, sound_id: AppSound | str) -> bool:
        return _normalize_sound_id(sound_id) in self._assets

    def play(self, sound_id: AppSound | str, *, force: bool = False) -> bool:
        asset = self._assets.get(_normalize_sound_id(sound_id))
        if asset is None:
            logger.debug("Unknown sound requested: %s", sound_id)
            return False

        if not self._is_sound_enabled(asset):
            return False

        now = time.monotonic()
        last_played_at = self._last_played_at.get(asset.sound_id, 0.0)
        if not force and asset.cooldown_ms > 0:
            elapsed_ms = (now - last_played_at) * 1000
            if elapsed_ms < asset.cooldown_ms:
                return False

        variant_name, variant_path = self._resolve_variant(asset)
        if not variant_path.is_file():
            logger.warning("Sound asset missing on disk: %s", variant_path)
            return False

        effect = self._acquire_effect(asset, variant_name, variant_path)
        if effect is None:
            logger.warning("No audio backend available for sound asset: %s", asset.sound_id)
            return False

        target_volume = self._effective_volume(asset)
        self._cancel_fade(effect)
        generation = self._effect_generations.get(id(effect), 0) + 1
        self._effect_generations[id(effect)] = generation
        if asset.fade_in_ms > 0 and self._qt_app_available():
            effect.setVolume(0.0)
        else:
            effect.setVolume(target_volume)
        if not self._play_effect(asset, variant_name, effect):
            return False
        if asset.fade_in_ms > 0 and self._qt_app_available():
            self._schedule_fade(effect, start_volume=0.0, end_volume=target_volume, duration_ms=asset.fade_in_ms)
        self._schedule_auto_fade_out(asset, effect, generation)
        self._last_played_at[asset.sound_id] = now
        return True

    def stop(self, sound_id: AppSound | str) -> None:
        normalized_sound_id = _normalize_sound_id(sound_id)
        asset = self._assets.get(normalized_sound_id)
        for (asset_id, _variant_name), effects in self._effect_pools.items():
            if asset_id != normalized_sound_id:
                continue
            for effect in effects:
                if asset is not None and asset.fade_out_ms > 0 and self._qt_app_available():
                    current_volume = self._effect_volume(effect)
                    if current_volume > 0 and getattr(effect, "isPlaying", lambda: False)():
                        self._schedule_fade(
                            effect,
                            start_volume=current_volume,
                            end_volume=0.0,
                            duration_ms=asset.fade_out_ms,
                            stop_after=True,
                        )
                        continue
                if hasattr(effect, "stop"):
                    effect.stop()

    def is_playing(self, sound_id: AppSound | str) -> bool:
        normalized_sound_id = _normalize_sound_id(sound_id)
        for (asset_id, _variant_name), effects in self._effect_pools.items():
            if asset_id != normalized_sound_id:
                continue
            for effect in effects:
                if getattr(effect, "isPlaying", lambda: False)():
                    return True
        return False

    def ensure_playing(self, sound_id: AppSound | str) -> bool:
        """Start one sound only if it is not already playing."""
        asset = self._assets.get(_normalize_sound_id(sound_id))
        if asset is None or not self._is_sound_enabled(asset):
            return False

        variant_name, variant_path = self._resolve_variant(asset)
        if not variant_path.is_file():
            return False

        effect = self._acquire_effect(asset, variant_name, variant_path)
        if effect is None:
            return False

        target_volume = self._effective_volume(asset)
        self._cancel_fade(effect)
        effect.setVolume(target_volume)

        if hasattr(effect, "isPlaying") and effect.isPlaying():
            return True

        if hasattr(effect, "isLoaded"):
            try:
                if not effect.isLoaded() and self._queue_play_when_loaded(asset, variant_name, effect):
                    return True
            except Exception:
                pass

        effect.play()
        self._last_played_at[asset.sound_id] = time.monotonic()
        return True

    async def close(self) -> None:
        global _sound_manager
        if not self._initialized:
            if _sound_manager is self:
                _sound_manager = None
            return

        while self._event_subscriptions:
            event_type, handler = self._event_subscriptions.pop()
            await self._event_bus.unsubscribe(event_type, handler)

        for effects in self._effect_pools.values():
            for effect in effects:
                try:
                    effect.stop()
                except Exception:
                    continue

        self._effect_pools.clear()
        self._fade_jobs.clear()
        self._effect_generations.clear()
        self._last_played_at.clear()
        self._pending_loaded_callbacks.clear()
        if self._fade_timer is not None and hasattr(self._fade_timer, "stop"):
            self._fade_timer.stop()
        self._initialized = False
        if _sound_manager is self:
            _sound_manager = None

    async def _on_message_received(self, payload: dict) -> None:
        message = payload.get("message")
        session_id = str(getattr(message, "session_id", "") or payload.get("session_id", "") or "")
        session_manager = peek_session_manager()
        if session_manager is not None and session_id and session_manager.is_session_muted(session_id):
            return
        self.play(AppSound.MESSAGE_INCOMING)

    def _load_manifest(self) -> None:
        if not _AUDIO_MANIFEST_PATH.is_file():
            logger.warning("Audio manifest not found: %s", _AUDIO_MANIFEST_PATH)
            self._assets = {}
            return

        payload = json.loads(_AUDIO_MANIFEST_PATH.read_text(encoding="utf-8"))
        sounds = payload.get("sounds", {})
        assets: dict[str, SoundAsset] = {}

        for sound_id, raw_config in sounds.items():
            if not isinstance(raw_config, dict):
                continue

            variants: dict[str, Path] = {}
            for variant_name, relative_path in dict(raw_config.get("variants") or {}).items():
                resolved_path = (_AUDIO_ROOT / str(relative_path)).resolve()
                variants[str(variant_name)] = resolved_path

            if not variants:
                continue

            assets[str(sound_id)] = SoundAsset(
                sound_id=str(sound_id),
                category=str(raw_config.get("category", "general") or "general"),
                variants=variants,
                volume=max(0.0, min(1.0, float(raw_config.get("volume", 1.0) or 1.0))),
                polyphony=max(1, int(raw_config.get("polyphony", 1) or 1)),
                cooldown_ms=max(0, int(raw_config.get("cooldown_ms", 0) or 0)),
                loop=bool(raw_config.get("loop", False)),
                fade_in_ms=max(0, int(raw_config.get("fade_in_ms", 0) or 0)),
                fade_out_ms=max(0, int(raw_config.get("fade_out_ms", 0) or 0)),
                duration_ms=self._sound_duration_ms(next(iter(variants.values()))),
            )

        self._assets = assets

    def _prime_effect_pool(self) -> None:
        """Preload one effect per variant so the first notification sound is ready to play."""
        for asset in self._assets.values():
            for variant_name, path in asset.variants.items():
                pool_key = (asset.sound_id, variant_name)
                pool = self._effect_pools.setdefault(pool_key, [])
                if pool:
                    continue

                effect = _create_sound_effect(path, self._effective_volume(asset), loop=asset.loop)
                if effect is not None:
                    pool.append(effect)

    def _is_sound_enabled(self, asset: SoundAsset) -> bool:
        if not bool(cfg.get(cfg.soundEnabled)):
            return False

        if asset.category == "messages" and not bool(cfg.get(cfg.messageSoundEnabled)):
            return False

        return True

    def _effective_volume(self, asset: SoundAsset) -> float:
        try:
            global_volume = float(cfg.get(cfg.soundVolume) or 0) / 100.0
        except Exception:
            global_volume = 0.85
        return max(0.0, min(1.0, global_volume * asset.volume))

    def _resolve_variant(self, asset: SoundAsset) -> tuple[str, Path]:
        preferred = "dark" if self._is_dark_theme() else "light"
        if preferred in asset.variants:
            return preferred, asset.variants[preferred]
        if "default" in asset.variants:
            return "default", asset.variants["default"]

        variant_name = next(iter(asset.variants))
        return variant_name, asset.variants[variant_name]

    def _acquire_effect(self, asset: SoundAsset, variant_name: str, path: Path):
        pool_key = (asset.sound_id, variant_name)
        pool = self._effect_pools.setdefault(pool_key, [])

        for effect in pool:
            if not hasattr(effect, "isPlaying") or not effect.isPlaying():
                return effect

        if len(pool) < asset.polyphony:
            effect = _create_sound_effect(path, self._effective_volume(asset), loop=asset.loop)
            if effect is not None:
                pool.append(effect)
            return effect

        return pool[0] if pool else None

    def _queue_play_when_loaded(self, asset: SoundAsset, variant_name: str, effect: Any) -> bool:
        signal = getattr(effect, "loadedChanged", None)
        if signal is None or not hasattr(signal, "connect"):
            return False

        callback_key = (asset.sound_id, variant_name, id(effect))
        if callback_key in self._pending_loaded_callbacks:
            return True

        def _on_loaded() -> None:
            try:
                if hasattr(effect, "isLoaded") and not effect.isLoaded():
                    return
                if hasattr(effect, "isPlaying") and effect.isPlaying():
                    effect.stop()
                effect.play()
            finally:
                self._pending_loaded_callbacks.pop(callback_key, None)
                try:
                    signal.disconnect(_on_loaded)
                except Exception:
                    pass

        self._pending_loaded_callbacks[callback_key] = _on_loaded
        signal.connect(_on_loaded)
        return True

    def _play_effect(self, asset: SoundAsset, variant_name: str, effect: Any) -> bool:
        if hasattr(effect, "isLoaded"):
            try:
                if not effect.isLoaded() and self._queue_play_when_loaded(asset, variant_name, effect):
                    return True
            except Exception:
                pass

        if hasattr(effect, "isPlaying") and effect.isPlaying():
            effect.stop()
        effect.play()
        return True

    def _init_fade_timer(self) -> None:
        try:
            from PySide6.QtCore import QTimer
        except Exception:
            self._fade_timer = None
            return

        self._fade_timer = QTimer()
        self._fade_timer.setInterval(30)
        self._fade_timer.timeout.connect(self._advance_fades)

    @staticmethod
    def _qt_app_available() -> bool:
        try:
            from PySide6.QtCore import QCoreApplication
        except Exception:
            return False
        return QCoreApplication.instance() is not None

    @staticmethod
    def _effect_volume(effect: Any) -> float:
        getter = getattr(effect, "volume", None)
        if callable(getter):
            try:
                return float(getter())
            except Exception:
                return 0.0
        return 0.0

    def _schedule_fade(
        self,
        effect: Any,
        *,
        start_volume: float,
        end_volume: float,
        duration_ms: int,
        stop_after: bool = False,
    ) -> None:
        if self._fade_timer is None or duration_ms <= 0:
            if hasattr(effect, "setVolume"):
                effect.setVolume(end_volume)
            if stop_after and hasattr(effect, "stop"):
                effect.stop()
            return

        self._fade_jobs[id(effect)] = _FadeJob(
            effect=effect,
            start_volume=start_volume,
            end_volume=end_volume,
            started_at=time.monotonic(),
            duration_ms=duration_ms,
            stop_after=stop_after,
        )
        if hasattr(effect, "setVolume"):
            effect.setVolume(start_volume)
        is_active = bool(getattr(self._fade_timer, "isActive", lambda: False)())
        if not is_active and hasattr(self._fade_timer, "start"):
            self._fade_timer.start()

    def _cancel_fade(self, effect: Any) -> None:
        self._fade_jobs.pop(id(effect), None)
        if self._fade_timer is not None and not self._fade_jobs and hasattr(self._fade_timer, "stop"):
            self._fade_timer.stop()

    def _advance_fades(self) -> None:
        if not self._fade_jobs:
            if self._fade_timer is not None and hasattr(self._fade_timer, "stop"):
                self._fade_timer.stop()
            return

        now = time.monotonic()
        completed: list[int] = []
        for effect_id, job in list(self._fade_jobs.items()):
            progress = min(1.0, max(0.0, ((now - job.started_at) * 1000.0) / max(1, job.duration_ms)))
            volume = job.start_volume + ((job.end_volume - job.start_volume) * progress)
            if hasattr(job.effect, "setVolume"):
                job.effect.setVolume(volume)
            if progress >= 1.0:
                if job.stop_after and hasattr(job.effect, "stop"):
                    job.effect.stop()
                completed.append(effect_id)

        for effect_id in completed:
            self._fade_jobs.pop(effect_id, None)

        if self._fade_timer is not None and not self._fade_jobs and hasattr(self._fade_timer, "stop"):
            self._fade_timer.stop()

    def _schedule_auto_fade_out(self, asset: SoundAsset, effect: Any, generation: int) -> None:
        if asset.loop or asset.fade_out_ms <= 0 or asset.duration_ms <= asset.fade_out_ms:
            return
        if not self._qt_app_available():
            return
        try:
            from PySide6.QtCore import QTimer
        except Exception:
            return

        delay_ms = max(0, asset.duration_ms - asset.fade_out_ms)
        QTimer.singleShot(
            delay_ms,
            lambda eff=effect, sound_id=asset.sound_id, expected_generation=generation, fade_out_ms=asset.fade_out_ms: self._fade_out_if_current(
                eff,
                sound_id=sound_id,
                expected_generation=expected_generation,
                fade_out_ms=fade_out_ms,
            ),
        )

    def _fade_out_if_current(self, effect: Any, *, sound_id: str, expected_generation: int, fade_out_ms: int) -> None:
        if self._effect_generations.get(id(effect)) != expected_generation:
            return
        if not getattr(effect, "isPlaying", lambda: False)():
            return
        current_volume = self._effect_volume(effect)
        if current_volume <= 0:
            return
        self._schedule_fade(
            effect,
            start_volume=current_volume,
            end_volume=0.0,
            duration_ms=fade_out_ms,
            stop_after=True,
        )

    @staticmethod
    def _sound_duration_ms(path: Path) -> int:
        try:
            with wave.open(str(path), "rb") as handle:
                frames = handle.getnframes()
                frame_rate = handle.getframerate()
                if frame_rate <= 0:
                    return 0
                return max(0, int((frames / float(frame_rate)) * 1000))
        except Exception:
            return 0

    @staticmethod
    def _is_dark_theme() -> bool:
        theme_mode = cfg.get(cfg.themeMode)
        if theme_mode == Theme.DARK:
            return True
        if theme_mode == Theme.LIGHT:
            return False

        try:
            from qfluentwidgets import isDarkTheme

            return bool(isDarkTheme())
        except Exception:
            return False


_sound_manager: SoundManager | None = None


def get_sound_manager() -> SoundManager:
    global _sound_manager
    if _sound_manager is None:
        _sound_manager = SoundManager()
    return _sound_manager


def peek_sound_manager() -> SoundManager | None:
    return _sound_manager
