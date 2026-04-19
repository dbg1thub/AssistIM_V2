from __future__ import annotations

import sys
import types
from pathlib import Path

if "aiohttp" not in sys.modules:
    aiohttp = types.ModuleType("aiohttp")

    class _DummyClientError(Exception):
        pass

    class _DummyClientTimeout:
        def __init__(self, total=None):
            self.total = total

    class _DummyFormData:
        def __init__(self):
            self.fields = []

        def add_field(self, name, value, **kwargs):
            self.fields.append({"name": name, "value": value, **kwargs})

    class _DummyClientSession:
        def __init__(self, *args, **kwargs):
            self.closed = False

        async def close(self) -> None:
            self.closed = True

    class _DummyClientResponse:
        status = 200

    aiohttp.ClientError = _DummyClientError
    aiohttp.FormData = _DummyFormData
    aiohttp.ClientTimeout = _DummyClientTimeout
    aiohttp.ClientSession = _DummyClientSession
    aiohttp.ClientResponse = _DummyClientResponse
    sys.modules["aiohttp"] = aiohttp

from client.core.config_backend import AIConfig, Config
from client.services.ai_bootstrap import configure_default_ai_provider, local_gguf_config_from_ai_config
from client.services.ai_service import AIErrorCode, AIProviderType, AIService, AIServiceError


def test_local_gguf_config_from_ai_config_preserves_runtime_options(tmp_path) -> None:
    model_path = str(tmp_path / "model.gguf")
    ai_config = AIConfig(
        provider="local_gguf",
        model_path=model_path,
        model_id="demo-model",
        context_size=8192,
        max_output_tokens=1024,
        temperature=0.2,
        gpu_layers=-1,
        cpu_threads=6,
        verbose=True,
    )

    runtime_config = local_gguf_config_from_ai_config(ai_config)

    assert runtime_config.model_path == model_path
    assert runtime_config.model_id == "demo-model"
    assert runtime_config.context_size == 8192
    assert runtime_config.max_output_tokens == 1024
    assert runtime_config.temperature == 0.2
    assert runtime_config.gpu_layers == -1
    assert runtime_config.cpu_threads == 6
    assert runtime_config.verbose is True


def test_configure_default_ai_provider_registers_local_without_loading_model(tmp_path) -> None:
    model_path = str(tmp_path / "missing-but-not-loaded.gguf")
    config = Config(
        ai=AIConfig(
            provider="local_gguf",
            model_path=model_path,
            model_id="demo-model",
        )
    )
    service = AIService()

    configured = configure_default_ai_provider(config=config, service=service)

    assert configured is service
    assert service.provider is not None
    assert service.provider.provider_type == AIProviderType.LOCAL
    runtime = service.provider._runtime
    assert runtime.config.model_path == model_path
    assert runtime.config.model_id == "demo-model"
    assert runtime._llm is None


def test_configure_default_ai_provider_can_be_disabled() -> None:
    config = Config(ai=AIConfig(provider="disabled"))
    service = AIService()

    configure_default_ai_provider(config=config, service=service)

    assert service.provider is None


def test_configure_default_ai_provider_rejects_unknown_provider() -> None:
    config = Config(ai=AIConfig(provider="remote-demo"))
    service = AIService()

    try:
        configure_default_ai_provider(config=config, service=service)
    except AIServiceError as exc:
        assert exc.code == AIErrorCode.AI_PROVIDER_UNAVAILABLE
    else:
        raise AssertionError("unknown provider should be rejected")


def test_ai_bootstrap_logs_acceleration_profile_boundary() -> None:
    bootstrap = (Path("client/services/ai_bootstrap.py")).read_text(encoding="utf-8")

    assert "acceleration_profile=%s" in bootstrap
