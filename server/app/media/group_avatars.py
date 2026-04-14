"""Server-side generated group avatar helpers."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
import os
from urllib.parse import urlsplit

from PIL import Image, ImageDraw, ImageOps

from app.core.config import Settings
from app.media.storage import LocalMediaStorage
from app.media.svg_rasterizer import ensure_rasterized_svg


_GROUP_AVATAR_SUBDIR = "group_avatars"
_OUTER_MARGIN = 8.0
_TILE_GAP = 3.0
_BACKGROUND = "#FFFFFF"
_FALLBACK_TILE_BACKGROUND = "#E7EDF4"
_FALLBACK_TILE_FOREGROUND = "#35516E"
_TILE_RADIUS = 6


def group_avatar_storage_key(group_id: str, version: int) -> str:
    """Return the storage key for one generated group avatar."""
    normalized_group_id = str(group_id or "").strip()
    normalized_version = max(1, int(version or 1))
    return f"{_GROUP_AVATAR_SUBDIR}/{normalized_group_id}_v{normalized_version}.png"


def group_avatar_public_url(settings: Settings, group_id: str, version: int) -> str:
    """Return the public URL for one generated group avatar."""
    storage_key = group_avatar_storage_key(group_id, version)
    base_url = (settings.media_public_base_url or "/uploads").rstrip("/")
    if base_url.startswith(("http://", "https://")):
        return f"{base_url}/{storage_key}"
    normalized_base = LocalMediaStorage._normalize_local_media_path(base_url or "/uploads")
    return f"{normalized_base}/{storage_key}"


def build_group_avatar(
    settings: Settings,
    *,
    group_id: str,
    version: int,
    group_name: str,
    members: Iterable[dict[str, str]],
    size: int = 96,
) -> str:
    """Generate and persist one white-background WeChat-style group avatar."""
    normalized_group_id = str(group_id or "").strip()
    if not normalized_group_id:
        return ""

    normalized_members = _normalize_members(members)
    if not normalized_members:
        return ""

    output_size = max(32, int(size or 96))
    target_path = Path(settings.upload_dir) / Path(group_avatar_storage_key(normalized_group_id, version))
    target_path.parent.mkdir(parents=True, exist_ok=True)

    image = Image.new("RGBA", (output_size, output_size), _BACKGROUND)
    for member, tile_rect in zip(
        normalized_members,
        _tile_rects(len(normalized_members), float(output_size)),
        strict=False,
    ):
        _draw_member_tile(
            image,
            tile_rect,
            member,
            settings=settings,
            group_name=group_name,
        )

    temporary_path = target_path.with_name(f".{target_path.name}.tmp")
    image.save(temporary_path, format="PNG")
    os.replace(temporary_path, target_path)
    return group_avatar_public_url(settings, normalized_group_id, version)


def _normalize_members(members: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in members or []:
        if not isinstance(item, dict):
            continue
        member = {
            "id": str(item.get("id", "") or item.get("user_id", "") or ""),
            "name": str(item.get("name", "") or item.get("nickname", "") or item.get("username", "") or ""),
            "username": str(item.get("username", "") or ""),
            "avatar": str(item.get("avatar", "") or ""),
            "gender": str(item.get("gender", "") or ""),
        }
        identifier = member["id"] or member["username"] or member["name"]
        if not identifier or identifier in seen:
            continue
        seen.add(identifier)
        normalized.append(member)
    return normalized[:9]


def _tile_rows(count: int) -> list[int]:
    normalized_count = max(1, min(9, int(count or 1)))
    patterns = {
        1: [1],
        2: [2],
        3: [1, 2],
        4: [2, 2],
        5: [2, 3],
        6: [3, 3],
        7: [1, 3, 3],
        8: [2, 3, 3],
        9: [3, 3, 3],
    }
    return patterns[normalized_count]


def _tile_rects(count: int, size: float) -> list[tuple[int, int, int, int]]:
    rows = _tile_rows(count)
    max_columns = max(rows)
    total_height = size - _OUTER_MARGIN * 2
    tile_size = min(
        (size - _OUTER_MARGIN * 2 - _TILE_GAP * (max_columns - 1)) / max_columns,
        (total_height - _TILE_GAP * (len(rows) - 1)) / len(rows),
    )
    cluster_height = tile_size * len(rows) + _TILE_GAP * (len(rows) - 1)
    top = (size - cluster_height) / 2

    rects: list[tuple[int, int, int, int]] = []
    for row_index, columns in enumerate(rows):
        row_width = tile_size * columns + _TILE_GAP * (columns - 1)
        left = (size - row_width) / 2
        y = top + row_index * (tile_size + _TILE_GAP)
        for column_index in range(columns):
            x = left + column_index * (tile_size + _TILE_GAP)
            rects.append((int(round(x)), int(round(y)), int(round(tile_size)), int(round(tile_size))))
    return rects


def _draw_member_tile(
    canvas: Image.Image,
    rect: tuple[int, int, int, int],
    member: dict[str, str],
    *,
    settings: Settings,
    group_name: str,
) -> None:
    x, y, width, height = rect
    tile_image = _load_member_image(member, settings=settings, size=max(width, height))
    if tile_image is None:
        tile_image = _fallback_member_image(member, max(width, height), group_name=group_name)

    fitted = ImageOps.fit(tile_image.convert("RGBA"), (width, height), method=Image.Resampling.LANCZOS)
    mask = Image.new("L", (width, height), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle((0, 0, width, height), radius=_TILE_RADIUS, fill=255)
    canvas.paste(fitted, (x, y), mask)


def _load_member_image(member: dict[str, str], *, settings: Settings, size: int) -> Image.Image | None:
    path = _resolve_avatar_source_to_local_path(settings, member.get("avatar", ""))
    if path is None:
        return None
    if path.suffix.lower() == ".svg":
        raster_path = ensure_rasterized_svg(path, Path(settings.upload_dir) / "svg_raster_cache", size=max(128, size))
        if raster_path is None:
            return None
        path = raster_path
    try:
        return Image.open(path).convert("RGBA")
    except Exception:
        return None


def _fallback_member_image(member: dict[str, str], size: int, *, group_name: str) -> Image.Image:
    tile_image = Image.new("RGBA", (size, size), _FALLBACK_TILE_BACKGROUND)
    draw = ImageDraw.Draw(tile_image)
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=_TILE_RADIUS, fill=_FALLBACK_TILE_BACKGROUND)
    text = (member.get("name", "") or member.get("username", "") or "?").strip()[:1].upper() or "?"
    text_bbox = draw.textbbox((0, 0), text)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    draw.text(
        ((size - text_width) / 2, (size - text_height) / 2 - 1),
        text,
        fill=_FALLBACK_TILE_FOREGROUND,
    )
    del group_name
    return tile_image


def _resolve_avatar_source_to_local_path(settings: Settings, source: str) -> Path | None:
    text = str(source or "").strip()
    if not text:
        return None

    candidate = Path(text)
    if candidate.is_file():
        return candidate.resolve()

    if not candidate.is_absolute():
        workspace_candidate = (Path.cwd() / candidate).resolve()
        if workspace_candidate.is_file():
            return workspace_candidate

    path_text = urlsplit(text).path or text
    media_mount = LocalMediaStorage._normalize_local_media_path(settings.media_public_base_url or "/uploads")
    if path_text.startswith(media_mount):
        relative_path = path_text[len(media_mount):].lstrip("/\\")
        upload_candidate = (Path(settings.upload_dir) / relative_path).resolve()
        if upload_candidate.is_file():
            return upload_candidate

    return None
