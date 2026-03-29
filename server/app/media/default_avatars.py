"""Helpers for publishing bundled default avatars through the backend media path."""

from __future__ import annotations

import hashlib
import secrets
import shutil
from pathlib import Path
from urllib.parse import urlsplit

from app.core.config import Settings
from app.media.storage import LocalMediaStorage


_WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
_BUNDLED_AVATAR_DIR = _WORKSPACE_ROOT / "client" / "resources" / "avatars"
_DEFAULT_AVATAR_SUBDIR = "default_avatars"


def normalize_avatar_gender_bucket(value: object) -> str:
    """Normalize one gender bucket for default-avatar selection."""
    text = str(value or "").strip().lower()
    if text in {"female", "woman", "girl", "f"}:
        return "female"
    if text in {"male", "man", "boy", "m"}:
        return "male"
    return ""


def _default_avatar_pool(gender: object = "") -> list[Path]:
    normalized_gender = normalize_avatar_gender_bucket(gender)
    all_variants = sorted(_BUNDLED_AVATAR_DIR.glob("avatar_default_*.svg"))
    gender_variants = (
        sorted(_BUNDLED_AVATAR_DIR.glob(f"avatar_default_{normalized_gender}_*.svg"))
        if normalized_gender
        else []
    )
    return gender_variants or all_variants


def list_default_avatar_keys(gender: object = "") -> list[str]:
    """Return every bundled default-avatar asset key for one bucket."""
    return [asset_path.name for asset_path in _default_avatar_pool(gender)]


def choose_random_default_avatar_key(gender: object = "") -> str | None:
    """Choose one random bundled default-avatar key."""
    keys = list_default_avatar_keys(gender)
    if not keys:
        return None
    return keys[secrets.randbelow(len(keys))]


def choose_seeded_default_avatar_key(seed: object, *, gender: object = "") -> str | None:
    """Choose one deterministic bundled default-avatar key from one stable seed."""
    keys = list_default_avatar_keys(gender)
    if not keys:
        return None

    seed_text = str(seed or "").strip()
    if not seed_text:
        return keys[0]

    digest = hashlib.sha256(seed_text.encode("utf-8")).digest()
    index = int.from_bytes(digest[:4], "big") % len(keys)
    return keys[index]


def resolve_default_avatar_asset_path(asset_key: str | None) -> Path | None:
    """Resolve one bundled default-avatar key to the source asset path."""
    key = str(asset_key or "").strip()
    if not key:
        return None

    candidate = (_BUNDLED_AVATAR_DIR / key).resolve()
    try:
        candidate.relative_to(_BUNDLED_AVATAR_DIR.resolve())
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate


def _publish_asset(settings: Settings, asset_path: Path) -> str:
    target_dir = Path(settings.upload_dir) / _DEFAULT_AVATAR_SUBDIR
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / asset_path.name
    if not target_path.exists():
        shutil.copyfile(asset_path, target_path)

    base_url = (settings.media_public_base_url or "/uploads").rstrip("/")
    if base_url.startswith(("http://", "https://")):
        return f"{base_url}/{_DEFAULT_AVATAR_SUBDIR}/{asset_path.name}"

    normalized_base = LocalMediaStorage._normalize_local_media_path(base_url or "/uploads")
    return f"{normalized_base}/{_DEFAULT_AVATAR_SUBDIR}/{asset_path.name}"


def default_avatar_url(settings: Settings, asset_key: str | None) -> str | None:
    """Return the published public URL for one default-avatar key."""
    asset_path = resolve_default_avatar_asset_path(asset_key)
    if asset_path is None:
        return None
    return _publish_asset(settings, asset_path)


def default_avatar_key_from_url(value: object) -> str | None:
    """Extract one bundled default-avatar key from a published avatar URL/path."""
    candidate = str(value or "").strip()
    if not candidate:
        return None

    path = urlsplit(candidate).path or candidate
    normalized = path.replace("\\", "/")
    if "/default_avatars/" not in normalized:
        return None
    key = normalized.rsplit("/", 1)[-1].strip()
    if not key:
        return None
    return key if resolve_default_avatar_asset_path(key) is not None else None


def sync_default_avatar_assets(settings: Settings) -> list[str]:
    """Publish the bundled default avatars into the backend media directory."""
    published_urls: list[str] = []
    for asset_path in _default_avatar_pool():
        published_urls.append(_publish_asset(settings, asset_path))
    return published_urls
