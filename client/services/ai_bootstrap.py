"""AI provider bootstrap helpers."""

from __future__ import annotations

from client.core import logging
from client.core.config_backend import AIConfig, Config, get_config
from client.core.logging import setup_logging
from client.services.local_ai_selection import resolve_local_ai_selection
from client.services.ai_service import AIErrorCode, AIService, AIServiceError, LocalGGUFProvider, get_ai_service
from client.services.local_gguf_runtime import LocalGGUFConfig, LocalGGUFRuntime

setup_logging()
logger = logging.get_logger(__name__)


LOCAL_PROVIDER_NAMES = {"local", "local_gguf", "gguf"}
DISABLED_PROVIDER_NAMES = {"", "none", "disabled", "off"}


def local_gguf_config_from_ai_config(config: AIConfig) -> LocalGGUFConfig:
    """Convert app AI config into the local GGUF runtime config."""
    return LocalGGUFConfig(
        model_path=config.model_path,
        model_id=config.model_id,
        context_size=config.context_size,
        max_output_tokens=config.max_output_tokens,
        temperature=config.temperature,
        gpu_layers=config.gpu_layers,
        cpu_threads=getattr(config, "cpu_threads", 0),
        verbose=config.verbose,
    )


def configure_default_ai_provider(
    config: Config | None = None,
    service: AIService | None = None,
) -> AIService:
    """Register the configured default AI provider without loading the model."""
    resolved_config = config or get_config()
    resolved_service = service or get_ai_service()
    ai_config = resolved_config.ai
    provider_name = str(ai_config.provider or "").strip().lower()

    if provider_name in DISABLED_PROVIDER_NAMES:
        logger.info("[ai-diag] provider_config_skipped provider=%s", provider_name or "disabled")
        return resolved_service

    if provider_name not in LOCAL_PROVIDER_NAMES:
        raise AIServiceError(
            AIErrorCode.AI_PROVIDER_UNAVAILABLE,
            f"Unsupported AI provider: {provider_name}",
        )

    resolved_selection = resolve_local_ai_selection(ai_config)
    runtime_config = resolved_selection.runtime_config
    runtime = LocalGGUFRuntime(runtime_config)
    resolved_service.set_provider(LocalGGUFProvider(runtime=runtime))
    logger.info(
        "[ai-diag] provider_configured provider=local_gguf model=%s path=%s lazy_load=True n_ctx=%s gpu_layers=%s "
        "cpu_threads=%s auto_selected=%s selection_reason=%s acceleration=%s acceleration_profile=%s acceleration_reason=%s "
        "runtime_gpu_offload=%s total_memory_gb=%s gpu_name=%s vram_total_gb=%s vram_free_gb=%s "
        "cuda_deps_present=%s missing_cuda_deps=%s",
        runtime_config.model_id,
        runtime_config.model_path,
        runtime_config.context_size,
        runtime_config.gpu_layers,
        runtime_config.cpu_threads,
        resolved_selection.auto_selected,
        str((runtime_config.metadata or {}).get("selection_reason") or ""),
        str((runtime_config.metadata or {}).get("acceleration_mode") or "cpu"),
        str((runtime_config.metadata or {}).get("acceleration_profile") or ""),
        str((runtime_config.metadata or {}).get("acceleration_reason") or ""),
        resolved_selection.capability.runtime_supports_gpu_offload,
        resolved_selection.capability.total_memory_gb,
        resolved_selection.capability.gpu_name,
        resolved_selection.capability.gpu_total_memory_gb,
        resolved_selection.capability.gpu_free_memory_gb,
        resolved_selection.capability.cuda_dependencies_present,
        ",".join(resolved_selection.capability.missing_cuda_dependencies),
    )
    return resolved_service
