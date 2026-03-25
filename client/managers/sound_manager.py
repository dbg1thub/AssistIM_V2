"""Audio manager for notification sounds and future UI sound effects."""

from __future__ import annotations

import json
import time
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


setup_logging()
logger = logging.get_logger(__name__)

_WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
_AUDIO_ROOT = _WORKSPACE_ROOT / "client" / "resources" / "audio"
_AUDIO_MANIFEST_PATH = _AUDIO_ROOT / "manifest.json"


class AppSound(str, Enum):
    MESSAGE_INCOMING = "message_incoming"


@dataclass(frozen=True)
class SoundAsset:
    sound_id: str
    category: str
    variants: dict[str, Path]
    volume: float = 1.0
    polyphony: int = 1
    cooldown_ms: int = 0


def _create_sound_effect(path: Path, volume: float):
    try:
        from PySide6.QtCore import QUrl
        from PySide6.QtMultimedia import QSoundEffect
    except Exception:
        return None

    effect = QSoundEffect()
    effect.setSource(QUrl.fromLocalFile(str(path)))
    effect.setLoopCount(1)
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
        self._initialized = False

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

        effect.setVolume(self._effective_volume(asset))
        if not self._play_effect(asset, variant_name, effect):
            return False
        self._last_played_at[asset.sound_id] = now
        return True

    async def close(self) -> None:
        if not self._initialized:
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
        self._last_played_at.clear()
        self._pending_loaded_callbacks.clear()
        self._initialized = False

    async def _on_message_received(self, _payload: dict) -> None:
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

                effect = _create_sound_effect(path, self._effective_volume(asset))
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
            effect = _create_sound_effect(path, self._effective_volume(asset))
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
