"""Shared helpers for resolving local avatar sources and default fallbacks."""

from __future__ import annotations

import hashlib
import secrets
from pathlib import Path


_WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
_AVATAR_RESOURCE_DIR = _WORKSPACE_ROOT / "client" / "resources" / "avatars"
_DATA_ROOT = _WORKSPACE_ROOT / "data"


def normalize_gender(value: object) -> str:
    """Normalize one gender value into a canonical profile bucket."""
    text = str(value or "").strip().lower()
    if text in {"female", "woman", "girl", "f"}:
        return "female"
    if text in {"male", "man", "boy", "m"}:
        return "male"
    return ""


def avatar_seed(*values: object) -> str:
    """Build one stable seed text for pseudo-random default avatar selection."""
    parts = [str(value or "").strip() for value in values if str(value or "").strip()]
    return "|".join(parts)


def _default_avatar_pool(gender: object = "") -> list[Path]:
    """Return the available default-avatar candidates for one gender bucket."""
    normalized_gender = normalize_gender(gender)
    all_variants = sorted(_AVATAR_RESOURCE_DIR.glob("avatar_default_*.svg"))
    gender_variants = sorted(_AVATAR_RESOURCE_DIR.glob(f"avatar_default_{normalized_gender}_*.svg")) if normalized_gender else []
    return gender_variants or all_variants


def resolve_local_image_path(value: object) -> str:
    """Resolve one avatar path to a local file path when possible."""
    text = str(value or "").strip()
    if not text:
        return ""

    candidate = Path(text)
    if candidate.is_file():
        return str(candidate.resolve())

    if not candidate.is_absolute():
        workspace_candidate = (_WORKSPACE_ROOT / candidate).resolve()
        if workspace_candidate.is_file():
            return str(workspace_candidate)

    if text.startswith("/uploads/") or text.startswith("uploads/"):
        upload_candidate = (_DATA_ROOT / Path(text.lstrip("/"))).resolve()
        if upload_candidate.is_file():
            return str(upload_candidate)

    if text.startswith("/client/resources/") or text.startswith("client/resources/"):
        resource_candidate = (_WORKSPACE_ROOT / Path(text.lstrip("/"))).resolve()
        if resource_candidate.is_file():
            return str(resource_candidate)

    return ""


def default_avatar_path(*, gender: object = "", seed: object = "") -> str:
    """Return one pseudo-random default avatar path, preferring gendered pools when available."""
    pool = _default_avatar_pool(gender)

    if not pool:
        return ""

    seed_text = str(seed or "").strip()
    if not seed_text:
        return str(pool[0].resolve())

    digest = hashlib.sha256(seed_text.encode("utf-8")).digest()
    index = int.from_bytes(digest[:4], "big") % len(pool)
    return str(pool[index].resolve())


def random_default_avatar_path(*, gender: object = "") -> str:
    """Return one randomly chosen default avatar path for first-time profile assignment."""
    pool = _default_avatar_pool(gender)
    if not pool:
        return ""
    return str(pool[secrets.randbelow(len(pool))].resolve())


def choose_avatar_image(
    avatar: object = "",
    *,
    gender: object = "",
    seed: object = "",
) -> str:
    """Return one local avatar image path or a pseudo-random default fallback."""
    resolved = resolve_local_image_path(avatar)
    if resolved:
        return resolved
    return default_avatar_path(gender=gender, seed=seed)
