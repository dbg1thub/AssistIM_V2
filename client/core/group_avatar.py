"""Helpers for generating WeChat-like composite group avatars."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Iterable

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPixmap

from client.core.avatar_rendering import get_avatar_image_store
from client.core.avatar_utils import avatar_seed


_WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
_GROUP_AVATAR_DIR = _WORKSPACE_ROOT / "data" / "group_avatars"
_OUTER_MARGIN = 8.0
_TILE_GAP = 3.0
_BACKGROUND = QColor("#F0F1F2")
_FALLBACK_TILE_BACKGROUND = QColor("#D7DEE8")
_FALLBACK_TILE_FOREGROUND = QColor("#27486B")


def build_group_avatar_path(
    members: Iterable[dict[str, Any]],
    *,
    group_id: object = "",
    group_name: object = "",
    size: int = 96,
) -> str:
    """Build and persist one composite avatar image for a group conversation."""
    normalized_members = _normalize_members(members)
    if not normalized_members:
        return ""

    token = str(group_id or "").strip()
    if not token:
        signature = "|".join(
            f"{member['id']}:{member['name']}:{member['avatar']}"
            for member in normalized_members
        )
        token = hashlib.sha1(signature.encode("utf-8")).hexdigest()[:16]

    _GROUP_AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    output_path = _GROUP_AVATAR_DIR / f"{token}_{max(32, int(size or 96))}.png"
    pixmap = _render_group_avatar(
        normalized_members,
        size=max(32, int(size or 96)),
        group_name=str(group_name or ""),
    )
    if pixmap.isNull():
        return ""

    pixmap.save(str(output_path), "PNG")
    return str(output_path)


def _normalize_members(members: Iterable[dict[str, Any]]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for item in members or []:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "id": str(item.get("id", "") or ""),
                "name": str(item.get("name", "") or item.get("display_name", "") or item.get("username", "") or ""),
                "avatar": str(item.get("avatar", "") or ""),
                "gender": str(item.get("gender", "") or ""),
                "username": str(item.get("username", "") or ""),
            }
        )

    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in normalized:
        identifier = item["id"] or item["name"] or item["username"]
        if not identifier or identifier in seen:
            continue
        seen.add(identifier)
        deduped.append(item)

    return deduped[:9]


def _render_group_avatar(members: list[dict[str, str]], *, size: int, group_name: str) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

    full_rect = QRectF(0, 0, float(size), float(size))
    clip_path = QPainterPath()
    clip_path.addRoundedRect(full_rect, 18, 18)
    painter.fillPath(clip_path, _BACKGROUND)
    painter.setClipPath(clip_path)

    for member, tile_rect in zip(members, _tile_rects(len(members), float(size)), strict=False):
        _draw_member_tile(painter, tile_rect, member, group_name=group_name)

    painter.end()
    return pixmap


def _tile_rects(count: int, size: float) -> list[QRectF]:
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
    rows = patterns.get(max(1, min(9, count)), [3, 3, 3])
    max_columns = max(rows)
    total_height = size - _OUTER_MARGIN * 2
    tile_size = min(
        (size - _OUTER_MARGIN * 2 - _TILE_GAP * (max_columns - 1)) / max_columns,
        (total_height - _TILE_GAP * (len(rows) - 1)) / len(rows),
    )
    cluster_height = tile_size * len(rows) + _TILE_GAP * (len(rows) - 1)
    top = (size - cluster_height) / 2

    rects: list[QRectF] = []
    for row_index, columns in enumerate(rows):
        row_width = tile_size * columns + _TILE_GAP * (columns - 1)
        left = (size - row_width) / 2
        y = top + row_index * (tile_size + _TILE_GAP)
        for column_index in range(columns):
            x = left + column_index * (tile_size + _TILE_GAP)
            rects.append(QRectF(x, y, tile_size, tile_size))
    return rects


def _draw_member_tile(painter: QPainter, rect: QRectF, member: dict[str, str], *, group_name: str) -> None:
    tile_path = QPainterPath()
    tile_path.addRoundedRect(rect, 6, 6)
    painter.save()
    painter.setClipPath(tile_path)

    tile_pixmap = _member_tile_pixmap(member, int(rect.width()), group_name=group_name)
    if tile_pixmap.isNull():
        painter.fillPath(tile_path, _FALLBACK_TILE_BACKGROUND)
    else:
        scaled = tile_pixmap.scaled(
            int(rect.width()),
            int(rect.height()),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        painter.drawPixmap(rect, scaled, QRectF(0, 0, scaled.width(), scaled.height()))

    painter.restore()


def _member_tile_pixmap(member: dict[str, str], size: int, *, group_name: str) -> QPixmap:
    store = get_avatar_image_store()
    seed = avatar_seed(member.get("id"), member.get("username"), member.get("name"), group_name)
    _source, display_path = store.resolve_display_path(
        member.get("avatar", ""),
        gender=member.get("gender", ""),
        seed=seed,
    )
    pixmap = QPixmap(display_path)
    if not pixmap.isNull():
        return pixmap
    return _fallback_tile_pixmap(member.get("name", "") or member.get("username", ""), size)


def _fallback_tile_pixmap(text: str, size: int) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    rect = QRectF(0, 0, float(size), float(size))
    path = QPainterPath()
    path.addRoundedRect(rect, 6, 6)
    painter.fillPath(path, _FALLBACK_TILE_BACKGROUND)
    painter.setPen(_FALLBACK_TILE_FOREGROUND)
    font = QFont()
    font.setBold(True)
    font.setPixelSize(max(10, int(size * 0.34)))
    painter.setFont(font)
    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, _fallback_text(text))
    painter.end()
    return pixmap


def _fallback_text(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return "?"
    return value[:1].upper()
