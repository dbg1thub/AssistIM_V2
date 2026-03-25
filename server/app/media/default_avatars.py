"""Helpers for publishing bundled default avatars through the backend media path."""

from __future__ import annotations

import hashlib
import secrets
import shutil
from pathlib import Path

from app.core.config import Settings
from app.media.storage import LocalMediaStorage


_WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
_BUNDLED_AVATAR_DIR = _WORKSPACE_ROOT / "client" / "resources" / "avatars"
_DEFAULT_AVATAR_SUBDIR = "default_avatars"


def _normalize_avatar_gender_bucket(value: object) -> str:
    text = str(value or "").strip().lower()
    if text in {"female", "woman", "girl", "f"}:
        return "female"
    if text in {"male", "man", "boy", "m"}:
        return "male"
    return ""


def _default_avatar_pool(gender: object = "") -> list[Path]:
    normalized_gender = _normalize_avatar_gender_bucket(gender)
    all_variants = sorted(_BUNDLED_AVATAR_DIR.glob("avatar_default_*.svg"))
    gender_variants = (
        sorted(_BUNDLED_AVATAR_DIR.glob(f"avatar_default_{normalized_gender}_*.svg"))
        if normalized_gender
        else []
    )
    return gender_variants or all_variants


def _select_seeded_asset(*, gender: object = "", seed: object = "") -> Path | None:
    pool = _default_avatar_pool(gender)
    if not pool:
        return None

    seed_text = str(seed or "").strip()
    if not seed_text:
        return pool[0]

    digest = hashlib.sha256(seed_text.encode("utf-8")).digest()
    index = int.from_bytes(digest[:4], "big") % len(pool)
    return pool[index]


def _publish_asset(settings: Settings, asset_path: Path) -> str:
    target_dir = Path(settings.upload_dir) / _DEFAULT_AVATAR_SUBDIR
    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(asset_path, target_dir / asset_path.name)

    base_url = (settings.media_public_base_url or "/uploads").rstrip("/")
    if base_url.startswith(("http://", "https://")):
        return f"{base_url}/{_DEFAULT_AVATAR_SUBDIR}/{asset_path.name}"

    normalized_base = LocalMediaStorage._normalize_local_media_path(base_url or "/uploads")
    return f"{normalized_base}/{_DEFAULT_AVATAR_SUBDIR}/{asset_path.name}"


def sync_default_avatar_assets(settings: Settings) -> list[str]:
    """Publish the bundled default avatars into the backend media directory."""
    published_urls: list[str] = []
    for asset_path in _default_avatar_pool():
        published_urls.append(_publish_asset(settings, asset_path))
    return published_urls


def default_avatar_url_for_seed(settings: Settings, *, seed: object, gender: object = "") -> str | None:
    """Return one stable published default-avatar URL for a deterministic seed."""
    asset_path = _select_seeded_asset(gender=gender, seed=seed)
    if asset_path is None:
        return None
    return _publish_asset(settings, asset_path)


def random_default_avatar_url(settings: Settings, *, gender: object = "") -> str | None:
    """Return one randomly chosen published default-avatar URL."""
    pool = _default_avatar_pool(gender)
    if not pool:
        return None
    return _publish_asset(settings, pool[secrets.randbelow(len(pool))])
