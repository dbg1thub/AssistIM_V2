"""Server-side generated user avatar helpers."""

from __future__ import annotations

import colorsys
import hashlib
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.core.config import Settings
from app.media.storage import LocalMediaStorage


_GENERATED_AVATAR_SUBDIR = "generated_avatars"
_AVATAR_RENDER_VERSION = "cjk-v2"


def build_generated_user_avatar(
    settings: Settings,
    *,
    user_id: object,
    nickname: object,
    username: object = "",
    size: int = 192,
) -> str:
    """Generate and persist one nickname-initial avatar for a user."""
    normalized_user_id = str(user_id or "").strip()
    if not normalized_user_id:
        return ""

    initial = _avatar_initial(nickname, username=username)
    seed = f"{_AVATAR_RENDER_VERSION}|{normalized_user_id}|{str(username or '').strip()}|{initial}|{str(nickname or '').strip()}"
    background = _background_color(seed)
    foreground = _foreground_color(background)
    output_size = max(64, int(size or 192))
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]

    storage_key = f"{_GENERATED_AVATAR_SUBDIR}/{normalized_user_id}_{digest}.png"
    target_path = Path(settings.upload_dir) / Path(storage_key)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    image = Image.new("RGBA", (output_size, output_size), background)
    draw = ImageDraw.Draw(image)
    font = _avatar_font(output_size, initial)
    try:
        bbox = draw.textbbox((0, 0), initial, font=font)
    except UnicodeEncodeError as exc:
        if _requires_cjk_font(initial):
            raise RuntimeError("CJK avatar font cannot render generated avatar initial") from exc
        initial = "?"
        bbox = draw.textbbox((0, 0), initial, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    draw.text(
        ((output_size - text_width) / 2 - bbox[0], (output_size - text_height) / 2 - bbox[1]),
        initial,
        font=font,
        fill=foreground,
        stroke_width=max(1, output_size // 96),
        stroke_fill=foreground,
    )

    temporary_path = target_path.with_name(f".{target_path.name}.tmp")
    image.save(temporary_path, format="PNG")
    os.replace(temporary_path, target_path)
    return generated_user_avatar_public_url(settings, storage_key)


def generated_user_avatar_public_url(settings: Settings, storage_key: str) -> str:
    """Return the public URL for one generated avatar storage key."""
    normalized_key = str(storage_key or "").strip().replace("\\", "/").lstrip("/")
    if not normalized_key:
        return ""
    base_url = (settings.media_public_base_url or "/uploads").rstrip("/")
    if base_url.startswith(("http://", "https://")):
        return f"{base_url}/{normalized_key}"
    normalized_base = LocalMediaStorage._normalize_local_media_path(base_url or "/uploads")
    return f"{normalized_base}/{normalized_key}"


def _avatar_initial(nickname: object, *, username: object = "") -> str:
    for source in (nickname, username):
        text = str(source or "").strip()
        for char in text:
            if char.isspace():
                continue
            return char.upper() if char.isascii() else char
    return "?"


def _background_color(seed: str) -> tuple[int, int, int, int]:
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    hue = int.from_bytes(digest[:2], "big") / 65535.0
    saturation = 0.32 + (digest[2] / 255.0) * 0.16
    value = 0.88 + (digest[3] / 255.0) * 0.08
    red, green, blue = colorsys.hsv_to_rgb(hue, saturation, value)
    return (round(red * 255), round(green * 255), round(blue * 255), 255)


def _foreground_color(background: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    red, green, blue, _alpha = background
    return (max(0, red - 72), max(0, green - 72), max(0, blue - 72), 255)


def _avatar_font(size: int, initial: object = "") -> ImageFont.ImageFont:
    font_size = max(24, int(size * 0.46))
    needs_cjk = _requires_cjk_font(initial)
    for font_path in _candidate_font_paths(initial):
        try:
            if font_path.is_file():
                return ImageFont.truetype(str(font_path), font_size)
        except Exception:
            continue
    if needs_cjk:
        raise RuntimeError("CJK avatar font not found; install fonts-noto-cjk in the server runtime")
    return ImageFont.load_default()


def _requires_cjk_font(value: object) -> bool:
    return any(_is_cjk_char(char) for char in str(value or ""))


def _is_cjk_char(char: str) -> bool:
    if not char:
        return False
    codepoint = ord(char)
    return (
        0x1100 <= codepoint <= 0x11FF
        or 0x2E80 <= codepoint <= 0x2EFF
        or 0x2F00 <= codepoint <= 0x2FDF
        or 0x3040 <= codepoint <= 0x30FF
        or 0x3130 <= codepoint <= 0x318F
        or 0x3400 <= codepoint <= 0x4DBF
        or 0x4E00 <= codepoint <= 0x9FFF
        or 0xAC00 <= codepoint <= 0xD7AF
        or 0xF900 <= codepoint <= 0xFAFF
        or 0x20000 <= codepoint <= 0x2FA1F
    )


def _candidate_cjk_font_paths() -> tuple[Path, ...]:
    return (
        Path("C:/Windows/Fonts/msyhbd.ttc"),
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"),
        Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
        Path("/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"),
        Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
    )


def _candidate_latin_font_paths() -> tuple[Path, ...]:
    return (
        Path("C:/Windows/Fonts/arialbd.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    )


def _candidate_font_paths(initial: object = "") -> tuple[Path, ...]:
    if _requires_cjk_font(initial):
        return _candidate_cjk_font_paths()
    return (
        *_candidate_latin_font_paths(),
        *_candidate_cjk_font_paths(),
    )
