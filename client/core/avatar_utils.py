"""Shared helpers for resolving local avatar sources and default fallbacks."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from client.core.config_backend import get_config


_WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
_DATA_ROOT = _WORKSPACE_ROOT / "data"
_REMOTE_PREFIXES = ("http://", "https://")
_SERVER_MEDIA_PREFIXES = ("/uploads/", "uploads/")


def normalize_gender(value: object) -> str:
    """Normalize one gender value into a canonical profile bucket."""
    text = str(value or "").strip().lower()
    if text in {"female", "woman", "girl", "f"}:
        return "female"
    if text in {"male", "man", "boy", "m"}:
        return "male"
    return ""


def avatar_seed(*values: object) -> str:
    """Build one stable seed text for text-placeholder avatar rendering."""
    parts = [str(value or "").strip() for value in values if str(value or "").strip()]
    return "|".join(parts)


def profile_avatar_seed(
    *,
    user_id: object = "",
    username: object = "",
    display_name: object = "",
    fallback: object = "",
) -> str:
    """Build one stable avatar seed that prefers identity fields over mutable display names."""
    stable_user_id = str(user_id or "").strip()
    stable_username = str(username or "").strip()
    if stable_user_id or stable_username:
        return avatar_seed(stable_user_id, stable_username)
    return avatar_seed(display_name, fallback)


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


def resolve_avatar_source(
    avatar: object = "",
    *,
    gender: object = "",
    seed: object = "",
) -> str:
    """Return one canonical avatar source, preserving remote URLs when present."""
    resolved = resolve_local_image_path(avatar)
    if resolved:
        return resolved

    text = str(avatar or "").strip()
    if text.startswith(_REMOTE_PREFIXES):
        return text

    remote_media = resolve_server_avatar_source(text)
    if remote_media:
        return remote_media

    return ""


def resolve_server_avatar_source(value: object) -> str:
    """Resolve one server-root avatar media path against the configured origin."""
    text = str(value or "").strip()
    if not text.startswith(_SERVER_MEDIA_PREFIXES):
        return ""
    normalized_path = text if text.startswith("/") else f"/{text}"
    return f"{get_config().server.origin_url.rstrip('/')}{normalized_path}"


def should_authenticate_avatar_source(source: object) -> bool:
    """Return whether one avatar request targets protected same-origin media."""
    source_text = str(source or "").strip()
    if not source_text:
        return False

    split_result = urlsplit(source_text)
    if not split_result.scheme and source_text.startswith(_SERVER_MEDIA_PREFIXES):
        return True
    if not split_result.scheme or not split_result.netloc:
        return False

    origin = urlsplit(get_config().server.origin_url)
    return (
        split_result.scheme == origin.scheme
        and split_result.netloc == origin.netloc
        and split_result.path.startswith("/uploads/")
    )


def choose_avatar_image(
    avatar: object = "",
    *,
    gender: object = "",
    seed: object = "",
) -> str:
    """Return one local avatar image path; missing avatars render as text placeholders."""
    source = resolve_avatar_source(avatar, gender=gender, seed=seed)
    if source.startswith(_REMOTE_PREFIXES):
        return ""
    return source
