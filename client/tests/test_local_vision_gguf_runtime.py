from __future__ import annotations

import pytest

from client.services.local_gguf_runtime import LocalGGUFConfig, _messages_prompt_chars
from client.services.local_vision_gguf_runtime import (
    LocalVisionGGUFRuntime,
    _prepared_image_payload,
    _should_downscale_image,
    _vision_batch_size,
    _vision_image_max_tokens,
    resolve_vision_projector_path,
)


def test_resolve_vision_projector_path_uses_metadata_path(tmp_path) -> None:
    model = tmp_path / "gemma-4-E2B-it-Q4_K_M.gguf"
    projector = tmp_path / "mmproj-BF16.gguf"
    model.write_bytes(b"model")
    projector.write_bytes(b"mmproj")
    config = LocalGGUFConfig(
        model_path=str(model),
        model_id="gemma-4-E2B-it-Q4_K_M",
        metadata={"supports_vision": True, "vision_mmproj_path": str(projector)},
    )

    assert resolve_vision_projector_path(config) == projector.resolve()


def test_prepare_messages_places_image_before_text(tmp_path) -> None:
    model = tmp_path / "gemma-4-E2B-it-Q4_K_M.gguf"
    projector = tmp_path / "mmproj-BF16.gguf"
    image = tmp_path / "demo.png"
    model.write_bytes(b"model")
    projector.write_bytes(b"mmproj")
    image.write_bytes(b"png-bytes")
    runtime = LocalVisionGGUFRuntime(
        LocalGGUFConfig(
            model_path=str(model),
            model_id="gemma-4-E2B-it-Q4_K_M",
            metadata={"supports_vision": True, "vision_mmproj_path": str(projector)},
        )
    )

    messages = runtime.prepare_messages(
        [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "这张图里有什么？"},
        ],
        [
            {
                "type": "image",
                "local_path": str(image),
                "mime_type": "image/png",
                "name": "demo.png",
            }
        ],
    )

    user_content = messages[-1]["content"]
    assert user_content[0]["type"] == "image_url"
    assert user_content[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert user_content[1] == {"type": "text", "text": "这张图里有什么？"}


def test_vision_batch_size_covers_image_token_budget() -> None:
    config = LocalGGUFConfig(
        model_path="gemma-4-E2B-it-Q4_K_M.gguf",
        model_id="gemma-4-E2B-it-Q4_K_M",
        context_size=4096,
        metadata={"vision_image_max_tokens": 768},
    )

    assert _vision_image_max_tokens(config) == 768
    assert _vision_batch_size(config) >= 1024
    assert _vision_batch_size(config) >= _vision_image_max_tokens(config)


def test_prompt_char_count_does_not_count_image_base64_payload() -> None:
    data_uri = "data:image/png;base64," + ("a" * 10000)
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": data_uri}},
                {"type": "text", "text": "这张图里有什么？"},
            ],
        }
    ]

    assert _messages_prompt_chars(messages) == len("[image]") + len("这张图里有什么？")


def test_image_downscale_heuristic_skips_low_quality_images() -> None:
    assert _should_downscale_image(width=800, height=360, size_bytes=2_000_000, target_edge=768) is False
    assert _should_downscale_image(width=900, height=700, size_bytes=900_000, target_edge=768) is False
    assert _should_downscale_image(width=1920, height=1080, size_bytes=2_000_000, target_edge=768) is True


def test_prepared_image_payload_downscales_large_image(tmp_path, monkeypatch) -> None:
    image_module = pytest.importorskip("PIL.Image")
    image_path = tmp_path / "large.png"
    image_module.new("RGB", (1600, 1000), (120, 160, 200)).save(image_path)
    monkeypatch.setenv("ASSISTIM_AI_VISION_IMAGE_MAX_EDGE", "640")

    payload, mime_type = _prepared_image_payload(image_path, "image/png")

    assert mime_type == "image/jpeg"
    assert len(payload) < image_path.stat().st_size
