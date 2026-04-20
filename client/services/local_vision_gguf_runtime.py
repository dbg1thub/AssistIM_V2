"""Gemma 4 multimodal GGUF runtime backed by llama-cpp-python."""

from __future__ import annotations

import base64
import io
import mimetypes
import os
from pathlib import Path
from typing import Any

from client.services.local_gguf_runtime import LocalGGUFConfig, LocalGGUFRuntime, LocalGGUFRuntimeError


DEFAULT_VISION_PROJECTOR_GLOBS = (
    "*mmproj*gemma*4*e2b*.gguf",
    "*mmproj*gemma-4*e2b*.gguf",
    "mmproj-BF16.gguf",
    "mmproj-F16.gguf",
    "*mmproj*.gguf",
)
DEFAULT_VISION_IMAGE_MAX_TOKENS = 512
DEFAULT_VISION_UBATCH = 1024
DEFAULT_VISION_IMAGE_MAX_EDGE = 768
DEFAULT_VISION_IMAGE_JPEG_QUALITY = 85
VISION_IMAGE_COMPRESS_TRIGGER_EDGE = 1280
VISION_IMAGE_COMPRESS_TRIGGER_BYTES = 1_200_000
VISION_IMAGE_LOW_QUALITY_MIN_EDGE = 480
SUPPORTED_IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "image/bmp"}


def resolve_vision_projector_path(config: LocalGGUFConfig) -> Path:
    """Resolve the local Gemma 4 vision projector file or raise a stable runtime error."""
    metadata = dict(config.metadata or {})
    model_dir = Path(config.model_path).expanduser().resolve().parent
    model_id = str(config.model_id or metadata.get("selected_model") or "").strip().lower()
    supports_vision = bool(metadata.get("supports_vision")) or "gemma-4" in model_id

    candidates: list[Path] = []
    env_path = str(os.getenv("ASSISTIM_AI_VISION_MMPROJ_PATH", "") or "").strip()
    if env_path:
        candidates.append(Path(env_path).expanduser().resolve())
        supports_vision = True

    metadata_path = str(metadata.get("vision_mmproj_path") or "").strip()
    if metadata_path:
        candidates.append(Path(metadata_path).expanduser().resolve())

    metadata_file = str(metadata.get("vision_mmproj_file") or "").strip()
    if metadata_file:
        candidates.append((model_dir / metadata_file).resolve())

    if supports_vision:
        glob_text = str(metadata.get("vision_projector_globs") or "").strip()
        glob_patterns = tuple(item for item in glob_text.split("|") if item) or DEFAULT_VISION_PROJECTOR_GLOBS
        for pattern in glob_patterns:
            candidates.extend(sorted(model_dir.glob(pattern)))

    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()

    if not supports_vision:
        raise LocalGGUFRuntimeError(
            "AI_MODEL_VISION_UNSUPPORTED",
            f"Local model does not declare vision support: {config.model_id}",
        )

    hint = str(candidates[0]) if candidates else str(model_dir / "mmproj-*.gguf")
    raise LocalGGUFRuntimeError(
        "AI_VISION_PROJECTOR_NOT_FOUND",
        f"Gemma 4 vision projector file was not found: {hint}",
    )


class LocalVisionGGUFRuntime(LocalGGUFRuntime):
    """Local GGUF runtime configured with Gemma 4's multimodal chat handler."""

    def __init__(self, config: LocalGGUFConfig | None = None) -> None:
        super().__init__(config)
        self._chat_handler = None

    def prepare_messages(
        self,
        messages: list[dict[str, Any]],
        attachments: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Attach the first local image to the latest user message in Gemma 4 format."""
        attachment = _first_image_attachment(attachments)
        if attachment is None:
            return [dict(message) for message in list(messages or [])]

        image_url = _image_attachment_data_uri(attachment)
        prepared = [dict(message) for message in list(messages or [])]
        latest_user_index = -1
        for index in range(len(prepared) - 1, -1, -1):
            if str(prepared[index].get("role") or "").strip().lower() == "user":
                latest_user_index = index
                break
        if latest_user_index < 0:
            raise LocalGGUFRuntimeError("AI_CONTEXT_TOO_LONG", "Vision request requires a user message")

        content = prepared[latest_user_index].get("content") or ""
        text = _text_from_message_content(content).strip()
        if not text:
            text = "请描述这张图片，并说明你能观察到的关键信息。"
        prepared[latest_user_index]["content"] = [
            {"type": "image_url", "image_url": {"url": image_url}},
            {"type": "text", "text": text},
        ]
        return prepared

    async def get_model_info(self):
        info = await super().get_model_info()
        metadata = dict(getattr(info, "metadata", {}) or {})
        metadata.update(
            {
                "vision_runtime": True,
                "supports_vision": True,
                "vision_mmproj_path": str(resolve_vision_projector_path(self.config)),
            }
        )
        info.metadata = metadata
        return info

    def _build_llama(self, model_path: Path, *, gpu_layers: int):
        from llama_cpp import Llama

        projector_path = resolve_vision_projector_path(self.config)
        chat_handler = self._build_chat_handler(projector_path, gpu_layers=gpu_layers)
        batch_size = _vision_batch_size(self.config)
        self._chat_handler = chat_handler
        kwargs: dict[str, Any] = {
            "model_path": str(model_path),
            "chat_handler": chat_handler,
            "n_ctx": self.config.context_size,
            "n_batch": batch_size,
            "n_ubatch": batch_size,
            "n_gpu_layers": gpu_layers,
            "verbose": self.config.verbose,
        }
        if self.config.cpu_threads > 0:
            kwargs["n_threads"] = self.config.cpu_threads
        return Llama(**kwargs)

    def _build_chat_handler(self, projector_path: Path, *, gpu_layers: int):
        handler_name = str((self.config.metadata or {}).get("vision_chat_handler") or "gemma4").strip().lower()
        use_gpu = gpu_layers != 0
        kwargs: dict[str, Any] = {
            "clip_model_path": str(projector_path),
            "verbose": self.config.verbose,
            "use_gpu": use_gpu,
        }
        kwargs["image_max_tokens"] = _vision_image_max_tokens(self.config)

        try:
            if handler_name in {"gemma4", "gemma-4", "gemma_4"}:
                from llama_cpp.llama_chat_format import Gemma4ChatHandler

                return Gemma4ChatHandler(enable_thinking=False, **kwargs)
            if handler_name in {"llava15", "llava-1.5", "llava"}:
                from llama_cpp.llama_chat_format import Llava15ChatHandler

                return Llava15ChatHandler(**kwargs)
        except ImportError as exc:
            raise LocalGGUFRuntimeError(
                "AI_VISION_RUNTIME_UNAVAILABLE",
                "Installed llama-cpp-python does not provide the requested vision chat handler",
            ) from exc

        raise LocalGGUFRuntimeError(
            "AI_MODEL_VISION_UNSUPPORTED",
            f"Unsupported local vision chat handler: {handler_name}",
        )

    async def close(self) -> None:
        chat_handler = self._chat_handler
        self._chat_handler = None
        await super().close()
        close = getattr(chat_handler, "close", None)
        if callable(close):
            close()


def _first_image_attachment(attachments: list[dict[str, Any]]) -> dict[str, Any] | None:
    for attachment in list(attachments or []):
        if str(attachment.get("type") or "").strip().lower() == "image":
            return dict(attachment)
    return None


def _vision_image_max_tokens(config: LocalGGUFConfig) -> int:
    raw_value = _parse_positive_int(os.getenv("ASSISTIM_AI_VISION_IMAGE_MAX_TOKENS"))
    if raw_value <= 0:
        raw_value = _parse_positive_int((config.metadata or {}).get("vision_image_max_tokens"))
    if raw_value <= 0:
        raw_value = DEFAULT_VISION_IMAGE_MAX_TOKENS
    return max(128, min(int(config.context_size or 2048), raw_value))


def _vision_batch_size(config: LocalGGUFConfig) -> int:
    image_tokens = _vision_image_max_tokens(config)
    raw_value = _parse_positive_int(os.getenv("ASSISTIM_AI_VISION_UBATCH"))
    if raw_value <= 0:
        raw_value = _parse_positive_int((config.metadata or {}).get("vision_batch_size"))
    if raw_value <= 0:
        raw_value = max(DEFAULT_VISION_UBATCH, image_tokens + 256)
    return max(image_tokens, min(int(config.context_size or raw_value), raw_value))


def _parse_positive_int(value: object) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


def _image_attachment_data_uri(attachment: dict[str, Any]) -> str:
    path = Path(str(attachment.get("local_path") or attachment.get("path") or "")).expanduser().resolve()
    if not path.is_file():
        raise LocalGGUFRuntimeError("AI_MODEL_NOT_FOUND", f"Image attachment was not found: {path}")
    mime_type = str(attachment.get("mime_type") or mimetypes.guess_type(str(path))[0] or "image/jpeg").strip()
    if mime_type not in SUPPORTED_IMAGE_MIME_TYPES:
        raise LocalGGUFRuntimeError("AI_MODEL_VISION_UNSUPPORTED", f"Unsupported image type: {mime_type}")
    image_bytes, payload_mime_type = _prepared_image_payload(path, mime_type)
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{payload_mime_type};base64,{encoded}"


def _prepared_image_payload(path: Path, mime_type: str) -> tuple[bytes, str]:
    original_bytes = path.read_bytes()
    try:
        from PIL import Image, ImageOps
    except Exception:
        return original_bytes, mime_type

    try:
        with Image.open(path) as image:
            image = ImageOps.exif_transpose(image)
            width, height = image.size
            if not _should_downscale_image(
                width=width,
                height=height,
                size_bytes=len(original_bytes),
                target_edge=_vision_image_max_edge(),
            ):
                return original_bytes, mime_type
            image.thumbnail(
                (_vision_image_max_edge(), _vision_image_max_edge()),
                getattr(Image, "Resampling", Image).LANCZOS,
            )
            image = _image_to_rgb(image)
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=_vision_image_jpeg_quality(), optimize=True)
            return buffer.getvalue(), "image/jpeg"
    except Exception:
        return original_bytes, mime_type


def _should_downscale_image(*, width: int, height: int, size_bytes: int, target_edge: int) -> bool:
    max_edge = max(int(width or 0), int(height or 0))
    min_edge = min(int(width or 0), int(height or 0))
    if max_edge <= 0 or min_edge <= 0:
        return False
    if max_edge <= target_edge:
        return False
    if min_edge < VISION_IMAGE_LOW_QUALITY_MIN_EDGE:
        return False
    if max_edge > VISION_IMAGE_COMPRESS_TRIGGER_EDGE:
        return True
    return size_bytes > VISION_IMAGE_COMPRESS_TRIGGER_BYTES and max_edge > target_edge


def _image_to_rgb(image):
    if image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info):
        from PIL import Image

        converted = image.convert("RGBA")
        background = Image.new("RGB", converted.size, (255, 255, 255))
        background.paste(converted, mask=converted.getchannel("A"))
        return background
    if image.mode != "RGB":
        return image.convert("RGB")
    return image


def _vision_image_max_edge() -> int:
    raw_value = _parse_positive_int(os.getenv("ASSISTIM_AI_VISION_IMAGE_MAX_EDGE"))
    if raw_value <= 0:
        raw_value = DEFAULT_VISION_IMAGE_MAX_EDGE
    return max(384, min(2048, raw_value))


def _vision_image_jpeg_quality() -> int:
    raw_value = _parse_positive_int(os.getenv("ASSISTIM_AI_VISION_JPEG_QUALITY"))
    if raw_value <= 0:
        raw_value = DEFAULT_VISION_IMAGE_JPEG_QUALITY
    return max(60, min(95, raw_value))


def _text_from_message_content(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and str(item.get("type") or "") == "text":
                parts.append(str(item.get("text") or ""))
        return "\n".join(parts)
    return str(content or "")
