from __future__ import annotations

import asyncio
import sys
import types

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

from client.managers.ai_assist_manager import (
    AIAssistResult,
    AIReplySuggestionItem,
    AIReplySuggestionState,
    AIReplySuggestionStatus,
)
from client.managers.ai_prompt_builder import AIAssistAction
from client.managers.ai_task_manager import AITaskState
from client.models.message import ChatMessage, MessageStatus, Session
from client.services.ai_service import AIErrorCode, AIModelInfo, AIProviderType
from client.services.ai_service import AIServiceError
from client.ui.controllers.ai_controller import AIController, AIHealthState


class FakeAssistManager:
    def __init__(self) -> None:
        self.draft_calls = []
        self.translation_calls = []
        self.suggestion_calls = []
        self.cleared: list[str] = []
        self.sent_invalidations: list[str] = []
        self.new_message_invalidations: list[tuple[str, str]] = []

    async def assist_draft(self, action, draft_text, *, session=None, target_language="中文"):
        self.draft_calls.append(
            {
                "action": action,
                "draft_text": draft_text,
                "session_id": getattr(session, "session_id", ""),
                "target_language": target_language,
            }
        )
        return AIAssistResult(
            task_id="task-draft",
            action=AIAssistAction.POLISH,
            text="edited draft",
            state=AITaskState.DONE,
        )

    async def translate_message(
        self,
        text,
        *,
        session=None,
        message_id="",
        target_language_code="zh-CN",
        mode="manual",
    ):
        self.translation_calls.append(
            {
                "text": text,
                "session_id": getattr(session, "session_id", ""),
                "message_id": message_id,
                "target_language_code": target_language_code,
                "mode": mode,
            }
        )
        return AIAssistResult(
            task_id="task-translate",
            action=AIAssistAction.TRANSLATE,
            text="译文",
            state=AITaskState.DONE,
        )

    def can_suggest_replies(self, session, messages, *, current_user_id=""):
        return True, ""

    async def suggest_replies(self, session, messages, *, current_user_id=""):
        self.suggestion_calls.append(
            {
                "session_id": session.session_id,
                "message_ids": [message.message_id for message in messages],
                "current_user_id": current_user_id,
            }
        )
        return AIReplySuggestionState(
            session_id=session.session_id,
            anchor_message_id="m1",
            status=AIReplySuggestionStatus.READY,
            items=[
                AIReplySuggestionItem(
                    text="好的，我看一下。",
                    rank=1,
                    anchor_message_id="m1",
                    task_id="task-reply",
                )
            ],
            task_id="task-reply",
        )

    def get_suggestions(self, session_id: str):
        return None

    def clear_suggestions(self, session_id: str) -> None:
        self.cleared.append(session_id)

    def invalidate_for_sent_message(self, session_id: str) -> None:
        self.sent_invalidations.append(session_id)

    def invalidate_for_new_message(self, session_id: str, message: ChatMessage) -> None:
        self.new_message_invalidations.append((session_id, message.message_id))


class FakeProvider:
    provider_type = AIProviderType.LOCAL


class FakeAIService:
    def __init__(self, info: AIModelInfo | None = None, provider=None) -> None:
        self._provider = FakeProvider() if provider is None and info is not None else provider
        self.info = info
        self.info_calls = 0
        self.warmup_calls = 0

    @property
    def provider(self):
        return self._provider

    async def get_model_info(self) -> AIModelInfo:
        self.info_calls += 1
        if self.info is None:
            raise AssertionError("model info was not configured")
        return self.info

    async def warmup(self) -> None:
        self.warmup_calls += 1


class FailingAIService(FakeAIService):
    def __init__(self, exc: Exception, provider=None) -> None:
        super().__init__(info=None, provider=provider or FakeProvider())
        self.exc = exc

    async def get_model_info(self) -> AIModelInfo:
        self.info_calls += 1
        raise self.exc


def test_ai_controller_delegates_draft_assist() -> None:
    async def scenario() -> None:
        fake = FakeAssistManager()
        controller = AIController(assist_manager=fake)
        session = Session(session_id="s1", name="Alice")

        result = await controller.assist_draft(session, "polish", "hello")

        assert result.text == "edited draft"
        assert fake.draft_calls == [
            {
                "action": "polish",
                "draft_text": "hello",
                "session_id": "s1",
                "target_language": "中文",
            }
        ]

    asyncio.run(scenario())


def test_ai_controller_delegates_message_translation() -> None:
    async def scenario() -> None:
        fake = FakeAssistManager()
        controller = AIController(assist_manager=fake)
        session = Session(session_id="s1", name="Alice")

        result = await controller.translate_message(
            session,
            "hello",
            message_id="m1",
            target_language_code="ko-KR",
            mode="manual",
        )

        assert result.text == "译文"
        assert fake.translation_calls == [
            {
                "text": "hello",
                "session_id": "s1",
                "message_id": "m1",
                "target_language_code": "ko-KR",
                "mode": "manual",
            }
        ]

    asyncio.run(scenario())


def test_ai_controller_reports_disabled_ai_provider() -> None:
    async def scenario() -> None:
        controller = AIController(assist_manager=FakeAssistManager(), ai_service=FakeAIService(provider=None))

        status = await controller.get_health_status()

        assert status.state == AIHealthState.DISABLED

    asyncio.run(scenario())


def test_ai_controller_detects_local_model_not_loaded_without_loading(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        model_path = tmp_path / "demo.gguf"
        model_path.write_bytes(b"gguf")
        info = AIModelInfo(
            provider="local_gguf",
            model="demo",
            local=True,
            loaded=False,
            runtime="llama-cpp-python",
            model_path=str(model_path),
        )
        service = FakeAIService(info=info)
        controller = AIController(assist_manager=FakeAssistManager(), ai_service=service)
        monkeypatch.setattr(
            "client.ui.controllers.ai_controller._is_python_package_available",
            lambda _module_name: True,
        )

        status = await controller.get_health_status()
        loaded = await controller.is_model_loaded()

        assert status.state == AIHealthState.READY_NOT_LOADED
        assert status.loaded is False
        assert loaded is False
        assert service.info_calls == 2

    asyncio.run(scenario())


def test_ai_controller_loaded_local_model_allows_background_ai(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        model_path = tmp_path / "demo.gguf"
        model_path.write_bytes(b"gguf")
        info = AIModelInfo(
            provider="local_gguf",
            model="demo",
            local=True,
            loaded=True,
            runtime="llama-cpp-python",
            model_path=str(model_path),
        )
        controller = AIController(assist_manager=FakeAssistManager(), ai_service=FakeAIService(info=info))
        monkeypatch.setattr(
            "client.ui.controllers.ai_controller._is_python_package_available",
            lambda _module_name: True,
        )

        assert await controller.is_model_loaded() is True

    asyncio.run(scenario())


def test_ai_controller_health_status_preserves_local_runtime_metadata(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        model_path = tmp_path / "demo.gguf"
        model_path.write_bytes(b"gguf")
        info = AIModelInfo(
            provider="local_gguf",
            model="demo",
            local=True,
            loaded=True,
            runtime="llama-cpp-python",
            model_path=str(model_path),
            metadata={
                "selected_model": "demo-2b",
                "acceleration_mode": "gpu",
                "gpu_name": "NVIDIA RTX Test",
            },
        )
        controller = AIController(assist_manager=FakeAssistManager(), ai_service=FakeAIService(info=info))
        monkeypatch.setattr(
            "client.ui.controllers.ai_controller._is_python_package_available",
            lambda _module_name: True,
        )

        status = await controller.get_health_status()

        assert status.state == AIHealthState.READY_LOADED
        assert status.metadata == {
            "selected_model": "demo-2b",
            "acceleration_mode": "gpu",
            "gpu_name": "NVIDIA RTX Test",
        }

    asyncio.run(scenario())


def test_ai_controller_reports_loading_local_model(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        model_path = tmp_path / "demo.gguf"
        model_path.write_bytes(b"gguf")
        info = AIModelInfo(
            provider="local_gguf",
            model="demo",
            local=True,
            loaded=False,
            loading=True,
            runtime="llama-cpp-python",
            model_path=str(model_path),
        )
        controller = AIController(assist_manager=FakeAssistManager(), ai_service=FakeAIService(info=info))
        monkeypatch.setattr(
            "client.ui.controllers.ai_controller._is_python_package_available",
            lambda _module_name: True,
        )

        status = await controller.get_health_status()

        assert status.state == AIHealthState.LOADING
        assert status.loading is True
        assert status.loaded is False

    asyncio.run(scenario())


def test_ai_controller_health_status_detects_missing_model_file(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        info = AIModelInfo(
            provider="local_gguf",
            model="demo",
            local=True,
            loaded=False,
            runtime="llama-cpp-python",
            model_path=str(tmp_path / "missing.gguf"),
        )
        controller = AIController(assist_manager=FakeAssistManager(), ai_service=FakeAIService(info=info))
        monkeypatch.setattr(
            "client.ui.controllers.ai_controller._is_python_package_available",
            lambda _module_name: True,
        )

        status = await controller.get_health_status()

        assert status.state == AIHealthState.MODEL_MISSING

    asyncio.run(scenario())


def test_ai_controller_health_status_detects_missing_llama_cpp(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        model_path = tmp_path / "demo.gguf"
        model_path.write_bytes(b"gguf")
        info = AIModelInfo(
            provider="local_gguf",
            model="demo",
            local=True,
            loaded=False,
            runtime="llama-cpp-python",
            model_path=str(model_path),
        )
        controller = AIController(assist_manager=FakeAssistManager(), ai_service=FakeAIService(info=info))
        monkeypatch.setattr(
            "client.ui.controllers.ai_controller._is_python_package_available",
            lambda _module_name: False,
        )

        status = await controller.get_health_status()

        assert status.state == AIHealthState.DEPENDENCY_MISSING
        assert status.detail == "llama-cpp-python is not installed"

    asyncio.run(scenario())


def test_ai_controller_health_status_detects_missing_cuda_runtime(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        model_path = tmp_path / "demo.gguf"
        model_path.write_bytes(b"gguf")
        info = AIModelInfo(
            provider="local_gguf",
            model="demo",
            local=True,
            loaded=False,
            runtime="llama-cpp-python",
            model_path=str(model_path),
            metadata={
                "missing_cuda_deps": "cudart64_12.dll,cublas64_12.dll",
                "acceleration_reason": "cuda_dependencies_missing",
                "runtime_gpu_probe_error": "RuntimeError: Failed to load shared library llama.dll",
            },
        )
        controller = AIController(assist_manager=FakeAssistManager(), ai_service=FakeAIService(info=info))
        monkeypatch.setattr(
            "client.ui.controllers.ai_controller._is_python_package_available",
            lambda _module_name: True,
        )

        status = await controller.get_health_status()

        assert status.state == AIHealthState.DEPENDENCY_MISSING
        assert status.detail == "cuda_dependencies_missing:cudart64_12.dll,cublas64_12.dll"
        assert status.metadata is not None
        assert status.metadata["missing_cuda_deps"] == "cudart64_12.dll,cublas64_12.dll"

    asyncio.run(scenario())


def test_ai_controller_health_status_hides_ai_service_error_text() -> None:
    async def scenario() -> None:
        controller = AIController(
            assist_manager=FakeAssistManager(),
            ai_service=FailingAIService(
                AIServiceError(AIErrorCode.AI_PROVIDER_UNAVAILABLE, "shared library llama.dll failed"),
            ),
        )

        status = await controller.get_health_status()

        assert status.state == AIHealthState.PROVIDER_UNAVAILABLE
        assert status.detail == AIErrorCode.AI_PROVIDER_UNAVAILABLE.value

    asyncio.run(scenario())


def test_ai_controller_health_status_hides_unexpected_exception_text() -> None:
    async def scenario() -> None:
        controller = AIController(
            assist_manager=FakeAssistManager(),
            ai_service=FailingAIService(RuntimeError("cuda dll missing from PATH")),
        )

        status = await controller.get_health_status()

        assert status.state == AIHealthState.PROVIDER_UNAVAILABLE
        assert status.detail == ""

    asyncio.run(scenario())


def test_ai_controller_delegates_reply_suggestions_and_invalidations() -> None:
    async def scenario() -> None:
        fake = FakeAssistManager()
        controller = AIController(assist_manager=fake)
        session = Session(session_id="s1", name="Alice")
        message = ChatMessage("m1", "s1", "peer", "ping", status=MessageStatus.RECEIVED)

        state = await controller.suggest_replies(session, [message], current_user_id="me")
        controller.invalidate_for_new_message("s1", message)
        controller.invalidate_for_sent_message("s1")
        controller.clear_suggestions("s1")

        assert [item.text for item in state.items] == ["好的，我看一下。"]
        assert fake.suggestion_calls == [
            {
                "session_id": "s1",
                "message_ids": ["m1"],
                "current_user_id": "me",
            }
        ]
        assert fake.new_message_invalidations == [("s1", "m1")]
        assert fake.sent_invalidations == ["s1"]
        assert fake.cleared == ["s1"]

    asyncio.run(scenario())


def test_ai_controller_warmup_delegates_to_service() -> None:
    async def scenario() -> None:
        service = FakeAIService(
            info=AIModelInfo(
                provider="local_gguf",
                model="demo",
                local=True,
                loaded=False,
                runtime="llama-cpp-python",
                model_path="demo.gguf",
            )
        )
        controller = AIController(assist_manager=FakeAssistManager(), ai_service=service)

        await controller.warmup()

        assert service.warmup_calls == 1

    asyncio.run(scenario())


def test_ai_controller_maps_common_ai_errors_to_user_messages() -> None:
    controller = AIController(assist_manager=FakeAssistManager())

    assert controller.user_message_for_error(
        AIErrorCode.AI_PROVIDER_UNAVAILABLE,
        detail="llama-cpp-python is not installed",
    ) == "Local AI runtime is missing. Install llama-cpp-python and restart AssistIM."
    assert controller.user_message_for_error(
        AIErrorCode.AI_MODEL_NOT_FOUND
    ) == "Local AI model file was not found. Check ASSISTIM_AI_MODEL_PATH."
    assert controller.user_message_for_error(
        AIErrorCode.AI_LOCAL_REQUIRED_UNAVAILABLE
    ) == "This encrypted chat can only use local AI. Enable the local GGUF provider first."
