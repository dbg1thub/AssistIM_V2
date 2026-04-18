"""Controller boundary for chat AI assist interactions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from importlib import util as importlib_util
from pathlib import Path
from typing import Optional, Sequence

from client.core import logging
from client.core.logging import setup_logging
from client.managers.ai_assist_manager import (
    AIAssistManager,
    AIAssistResult,
    AIReplySuggestionState,
    get_ai_assist_manager,
)
from client.managers.ai_prompt_builder import AIAssistAction
from client.models.message import ChatMessage, Session
from client.services.ai_service import AIErrorCode, AIModelInfo, AIService, AIServiceError, get_ai_service

setup_logging()
logger = logging.get_logger(__name__)


class AIHealthState(Enum):
    """Lightweight AI availability states for UI prompts."""

    DISABLED = "disabled"
    LOADING = "loading"
    READY_NOT_LOADED = "ready_not_loaded"
    READY_LOADED = "ready_loaded"
    MODEL_MISSING = "model_missing"
    DEPENDENCY_MISSING = "dependency_missing"
    PROVIDER_UNAVAILABLE = "provider_unavailable"


@dataclass(frozen=True, slots=True)
class AIHealthStatus:
    """AI runtime status that can be queried without loading the model."""

    state: AIHealthState
    provider: str = ""
    model: str = ""
    model_path: str = ""
    runtime: str = ""
    local: bool = False
    loaded: bool = False
    loading: bool = False
    detail: str = ""


class AIController:
    """UI controller for draft assistance and reply suggestions."""

    def __init__(
        self,
        assist_manager: AIAssistManager | None = None,
        ai_service: AIService | None = None,
    ) -> None:
        self._assist_manager = assist_manager or get_ai_assist_manager()
        self._ai_service = ai_service or get_ai_service()
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the lightweight AI controller."""
        if self._initialized:
            return
        self._initialized = True
        logger.info("AI controller initialized")

    async def assist_draft(
        self,
        session: Session | None,
        action: AIAssistAction | str,
        draft_text: str,
        *,
        target_language: str = "中文",
    ) -> AIAssistResult:
        """Return one AI-edited draft without sending it."""
        return await self._assist_manager.assist_draft(
            action,
            draft_text,
            session=session,
            target_language=target_language,
        )

    def can_suggest_replies(
        self,
        session: Session,
        messages: Sequence[ChatMessage],
        *,
        current_user_id: str = "",
    ) -> tuple[bool, str]:
        """Return whether reply suggestions are eligible for this context."""
        return self._assist_manager.can_suggest_replies(
            session,
            messages,
            current_user_id=current_user_id,
        )

    async def suggest_replies(
        self,
        session: Session,
        messages: Sequence[ChatMessage],
        *,
        current_user_id: str = "",
    ) -> AIReplySuggestionState:
        """Generate reply candidates for a private conversation."""
        return await self._assist_manager.suggest_replies(
            session,
            messages,
            current_user_id=current_user_id,
        )

    def get_suggestions(self, session_id: str) -> AIReplySuggestionState | None:
        """Return current in-memory reply suggestions for a session."""
        return self._assist_manager.get_suggestions(session_id)

    def clear_suggestions(self, session_id: str) -> None:
        """Clear reply candidates for a session."""
        self._assist_manager.clear_suggestions(session_id)

    async def get_health_status(self) -> AIHealthStatus:
        """Return AI provider/model status without loading the local model."""
        provider = self._ai_service.provider
        if provider is None:
            return AIHealthStatus(state=AIHealthState.DISABLED)

        try:
            info = await self._ai_service.get_model_info()
        except AIServiceError as exc:
            return AIHealthStatus(
                state=AIHealthState.PROVIDER_UNAVAILABLE,
                provider=_provider_name(provider),
                detail=str(exc) or exc.code.value,
            )
        except Exception as exc:
            logger.warning("AI health status check failed: %s", exc)
            return AIHealthStatus(
                state=AIHealthState.PROVIDER_UNAVAILABLE,
                provider=_provider_name(provider),
                detail=str(exc),
            )

        status = _health_status_from_model_info(info)
        if _is_local_gguf_info(info):
            model_path = Path(info.model_path).expanduser() if info.model_path else None
            if model_path is not None and not model_path.is_file():
                return _with_health_state(status, AIHealthState.MODEL_MISSING)
            if not _is_python_package_available("llama_cpp"):
                return _with_health_state(
                    status,
                    AIHealthState.DEPENDENCY_MISSING,
                    detail="llama-cpp-python is not installed",
                )
        return status

    async def is_model_loaded(self) -> bool:
        """Return whether AI can run without triggering the first local model load."""
        status = await self.get_health_status()
        return status.state == AIHealthState.READY_LOADED and status.loaded

    async def warmup(self) -> None:
        """Warm up the active AI provider without generating output."""
        await self._ai_service.warmup()

    def user_message_for_error(
        self,
        error_code: AIErrorCode | str | None,
        *,
        detail: str = "",
    ) -> str:
        """Return a user-facing explanation for one AI error."""
        return user_message_for_ai_error(error_code, detail=detail)

    def invalidate_for_sent_message(self, session_id: str) -> None:
        """Discard reply candidates after the user sends a message."""
        self._assist_manager.invalidate_for_sent_message(session_id)

    def invalidate_for_new_message(self, session_id: str, message: ChatMessage) -> None:
        """Discard candidates when a newer message supersedes them."""
        self._assist_manager.invalidate_for_new_message(session_id, message)

    async def close(self) -> None:
        """Close controller-local state and retire the singleton."""
        self._initialized = False
        close = getattr(self._assist_manager, "close", None)
        if callable(close):
            await close()
        global _ai_controller
        if _ai_controller is self:
            _ai_controller = None


_ai_controller: Optional[AIController] = None


def peek_ai_controller() -> Optional[AIController]:
    """Return the existing AI controller singleton if it was created."""
    return _ai_controller


def get_ai_controller() -> AIController:
    """Return the global AI controller singleton."""
    global _ai_controller
    if _ai_controller is None:
        _ai_controller = AIController()
    return _ai_controller


def _provider_name(provider: object) -> str:
    provider_type = getattr(provider, "provider_type", "")
    return str(getattr(provider_type, "value", provider_type) or "")


def _is_python_package_available(module_name: str) -> bool:
    try:
        return importlib_util.find_spec(module_name) is not None
    except (ImportError, ValueError):
        return False


def _is_local_gguf_info(info: AIModelInfo) -> bool:
    return (
        bool(info.local)
        and (info.provider == "local_gguf" or info.runtime == "llama-cpp-python")
    )


def _health_status_from_model_info(info: AIModelInfo) -> AIHealthStatus:
    if info.loading:
        state = AIHealthState.LOADING
    else:
        state = AIHealthState.READY_LOADED if info.loaded else AIHealthState.READY_NOT_LOADED
    return AIHealthStatus(
        state=state,
        provider=info.provider,
        model=info.model,
        model_path=info.model_path,
        runtime=info.runtime,
        local=info.local,
        loaded=info.loaded,
        loading=info.loading,
    )


def _with_health_state(
    status: AIHealthStatus,
    state: AIHealthState,
    *,
    detail: str = "",
) -> AIHealthStatus:
    return AIHealthStatus(
        state=state,
        provider=status.provider,
        model=status.model,
        model_path=status.model_path,
        runtime=status.runtime,
        local=status.local,
        loaded=status.loaded,
        loading=status.loading,
        detail=detail or status.detail,
    )


def user_message_for_ai_error(error_code: AIErrorCode | str | None, *, detail: str = "") -> str:
    """Map stable AI error codes to concise UI messages."""
    if error_code is None:
        return "AI could not complete this request."

    code = AIErrorCode.coerce(error_code, default=AIErrorCode.AI_MODEL_UNAVAILABLE)
    normalized_detail = str(detail or "")
    if code == AIErrorCode.AI_PROVIDER_UNAVAILABLE:
        if "llama-cpp-python" in normalized_detail:
            return "Local AI runtime is missing. Install llama-cpp-python and restart AssistIM."
        return "AI provider is not configured. Check the local AI settings."
    if code == AIErrorCode.AI_MODEL_NOT_FOUND:
        return "Local AI model file was not found. Check ASSISTIM_AI_MODEL_PATH."
    if code == AIErrorCode.AI_LOCAL_REQUIRED_UNAVAILABLE:
        return "This encrypted chat can only use local AI. Enable the local GGUF provider first."
    if code == AIErrorCode.AI_MODEL_LOAD_FAILED:
        return "Local AI model could not be loaded. Check the model file and runtime settings."
    if code == AIErrorCode.AI_RESOURCE_EXHAUSTED:
        return "Local AI does not have enough memory for this model. Try a smaller model or lower context size."
    if code == AIErrorCode.AI_CONTEXT_TOO_LONG:
        return "The AI context is too long. Try a shorter draft or fewer messages."
    if code == AIErrorCode.AI_OUTPUT_INVALID:
        return "AI returned an unusable response. Try again."
    return "AI could not complete this request."
