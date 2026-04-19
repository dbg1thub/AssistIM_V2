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

from client.managers.ai_task_manager import AITaskEvent, AITaskManager, AITaskState
from client.services.ai_service import (
    AIErrorCode,
    AIRequest,
    AIResponse,
    AIServiceError,
    AIStreamEvent,
    AIStreamEventType,
)


class FakeEventBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def emit(self, event_type: str, data=None) -> None:
        self.events.append((event_type, dict(data or {})))

    def snapshots(self, event_type: str):
        return [payload["task"] for name, payload in self.events if name == event_type]


class FakeAIService:
    def __init__(
        self,
        *,
        response: AIResponse | None = None,
        chunks: list[str] | None = None,
        error: AIServiceError | None = None,
        block_until_cancel: bool = False,
    ) -> None:
        self.response = response or AIResponse(content="ok", model="fake-model", provider="fake")
        self.chunks = list(chunks or [])
        self.error = error
        self.block_until_cancel = block_until_cancel
        self.cancelled: list[str] = []
        self.generate_calls: list[str] = []
        self.stream_calls: list[str] = []
        self.started = asyncio.Event()
        self.cancel_event = asyncio.Event()

    async def generate_once(self, request: AIRequest) -> AIResponse:
        self.generate_calls.append(request.task_id)
        if self.error is not None:
            raise self.error
        return AIResponse(
            content=self.response.content,
            model=self.response.model,
            task_id=request.task_id,
            provider=self.response.provider,
            finish_reason=self.response.finish_reason,
            metadata=dict(self.response.metadata),
        )

    async def stream_chat(self, request: AIRequest):
        self.stream_calls.append(request.task_id)
        self.started.set()
        yield AIStreamEvent(task_id=request.task_id, event_type=AIStreamEventType.STARTED)
        if self.error is not None:
            raise self.error
        if self.block_until_cancel:
            await self.cancel_event.wait()
            raise AIServiceError(AIErrorCode.AI_USER_CANCELLED, "cancelled")
        for chunk in self.chunks:
            await asyncio.sleep(0)
            yield AIStreamEvent(
                task_id=request.task_id,
                event_type=AIStreamEventType.DELTA,
                content=chunk,
            )
        yield AIStreamEvent(
            task_id=request.task_id,
            event_type=AIStreamEventType.DONE,
            finish_reason="stop",
            response=AIResponse(
                content="".join(self.chunks),
                model="fake-model",
                task_id=request.task_id,
                provider="fake",
                finish_reason="stop",
            ),
        )

    async def cancel(self, task_id: str) -> None:
        self.cancelled.append(task_id)
        self.cancel_event.set()


def _request(task_id: str, *, max_output_chars: int = 0) -> AIRequest:
    return AIRequest(
        task_id=task_id,
        session_id="session-1",
        messages=[{"role": "user", "content": "hello"}],
        model="fake-model",
        max_output_chars=max_output_chars,
    )


class PriorityService:
    def __init__(self) -> None:
        self.started_order: list[str] = []
        self.cancelled: list[str] = []
        self._events: dict[str, asyncio.Event] = {}

    def release(self, task_id: str) -> None:
        self._events.setdefault(task_id, asyncio.Event()).set()

    async def generate_once(self, request: AIRequest) -> AIResponse:
        self.started_order.append(request.task_id)
        await self._events.setdefault(request.task_id, asyncio.Event()).wait()
        return AIResponse(content=request.task_id, model="fake-model", task_id=request.task_id, provider="fake")

    async def stream_chat(self, request: AIRequest):
        if False:
            yield request

    async def cancel(self, task_id: str) -> None:
        self.cancelled.append(task_id)
        self.release(task_id)


def test_ai_task_manager_run_once_success_transitions_to_done() -> None:
    async def scenario() -> None:
        event_bus = FakeEventBus()
        service = FakeAIService(response=AIResponse(content="answer", model="fake-model", provider="fake"))
        manager = AITaskManager(service=service, event_bus=event_bus)

        snapshot = await manager.run_once(_request("task-run"))

        assert snapshot.state == AITaskState.DONE
        assert snapshot.content == "answer"
        assert snapshot.provider == "fake"
        assert service.generate_calls == ["task-run"]
        assert [event for event, _payload in event_bus.events] == [
            AITaskEvent.UPDATED,
            AITaskEvent.STARTED,
            AITaskEvent.UPDATED,
            AITaskEvent.FINISHED,
        ]

    asyncio.run(scenario())


def test_ai_task_manager_stream_coalesces_small_chunks() -> None:
    async def scenario() -> None:
        event_bus = FakeEventBus()
        service = FakeAIService(chunks=["a", "b", "c", "d", "e"])
        manager = AITaskManager(service=service, event_bus=event_bus)

        snapshot = await manager.stream(_request("task-stream"))

        assert snapshot.state == AITaskState.DONE
        assert snapshot.content == "abcde"
        assert snapshot.chunk_count == 5
        updated_snapshots = event_bus.snapshots(AITaskEvent.UPDATED)
        assert len(updated_snapshots) < 5
        assert updated_snapshots[-1].content == "abcde"

    asyncio.run(scenario())


def test_ai_task_manager_stream_can_flush_each_delta() -> None:
    async def scenario() -> None:
        event_bus = FakeEventBus()
        service = FakeAIService(chunks=["a", "b", "c"])
        manager = AITaskManager(service=service, event_bus=event_bus)
        request = _request("task-stream-immediate")
        request.metadata["stream_flush"] = "immediate"

        snapshot = await manager.stream(request)

        assert snapshot.state == AITaskState.DONE
        assert snapshot.content == "abc"
        streamed_contents = [item.content for item in event_bus.snapshots(AITaskEvent.UPDATED) if item.content]
        assert streamed_contents[:3] == ["a", "ab", "abc"]

    asyncio.run(scenario())


def test_ai_task_manager_stream_hard_truncates_and_cancels_provider() -> None:
    async def scenario() -> None:
        event_bus = FakeEventBus()
        service = FakeAIService(chunks=["hello", " world"])
        manager = AITaskManager(service=service, event_bus=event_bus)

        snapshot = await manager.stream(_request("task-truncate", max_output_chars=7))

        assert snapshot.state == AITaskState.DONE
        assert snapshot.content == "hello w"
        assert snapshot.truncated is True
        assert snapshot.finish_reason == AIErrorCode.AI_OUTPUT_TRUNCATED.value
        assert service.cancelled == ["task-truncate"]

    asyncio.run(scenario())


def test_ai_task_manager_running_cancel_marks_cancelled() -> None:
    async def scenario() -> None:
        event_bus = FakeEventBus()
        service = FakeAIService(block_until_cancel=True)
        manager = AITaskManager(service=service, event_bus=event_bus)

        task = asyncio.create_task(manager.stream(_request("task-cancel")))
        await service.started.wait()
        await manager.cancel("task-cancel")
        snapshot = await task

        assert snapshot.state == AITaskState.CANCELLED
        assert snapshot.finish_reason == AIErrorCode.AI_USER_CANCELLED.value
        assert service.cancelled == ["task-cancel"]
        assert event_bus.snapshots(AITaskEvent.CANCELLED)[-1].task_id == "task-cancel"

    asyncio.run(scenario())


def test_ai_task_manager_queued_cancel_does_not_call_provider() -> None:
    async def scenario() -> None:
        event_bus = FakeEventBus()
        service = FakeAIService(block_until_cancel=True)
        manager = AITaskManager(service=service, event_bus=event_bus, concurrency=1)

        running = asyncio.create_task(manager.stream(_request("task-running")))
        await service.started.wait()
        queued = asyncio.create_task(manager.stream(_request("task-queued")))
        await asyncio.sleep(0)

        await manager.cancel("task-queued")
        await manager.cancel("task-running")
        running_snapshot = await running
        queued_snapshot = await queued

        assert queued_snapshot.state == AITaskState.CANCELLED
        assert running_snapshot.state == AITaskState.CANCELLED
        assert service.stream_calls == ["task-running"]

    asyncio.run(scenario())


def test_ai_task_manager_provider_error_marks_failed() -> None:
    async def scenario() -> None:
        event_bus = FakeEventBus()
        service = FakeAIService(error=AIServiceError(AIErrorCode.AI_MODEL_NOT_FOUND, "missing"))
        manager = AITaskManager(service=service, event_bus=event_bus)

        snapshot = await manager.stream(_request("task-fail"))

        assert snapshot.state == AITaskState.FAILED
        assert snapshot.error_code == AIErrorCode.AI_MODEL_NOT_FOUND
        assert event_bus.snapshots(AITaskEvent.FAILED)[-1].task_id == "task-fail"

    asyncio.run(scenario())


def test_ai_task_manager_close_cancels_running_tasks() -> None:
    async def scenario() -> None:
        event_bus = FakeEventBus()
        service = FakeAIService(block_until_cancel=True)
        manager = AITaskManager(service=service, event_bus=event_bus)

        running = asyncio.create_task(manager.stream(_request("task-close")))
        await service.started.wait()
        await manager.close()

        assert running.done()
        snapshot = manager.get_task("task-close")
        assert snapshot is not None
        assert snapshot.state == AITaskState.CANCELLED
        assert service.cancelled == ["task-close"]

    asyncio.run(scenario())


def test_ai_task_manager_reply_suggestion_preempts_queued_summary() -> None:
    async def scenario() -> None:
        event_bus = FakeEventBus()
        service = PriorityService()
        manager = AITaskManager(service=service, event_bus=event_bus, concurrency=1)

        running = asyncio.create_task(manager.run_once(_request("task-running")))
        await asyncio.sleep(0)
        queued_summary = asyncio.create_task(
            manager.run_once(
                AIRequest(
                    task_id="task-summary",
                    session_id="session-1",
                    messages=[{"role": "user", "content": "summary"}],
                    model="fake-model",
                    task_type="summary",
                )
            )
        )
        await asyncio.sleep(0)
        queued_reply = asyncio.create_task(
            manager.run_once(
                AIRequest(
                    task_id="task-reply",
                    session_id="session-1",
                    messages=[{"role": "user", "content": "reply"}],
                    model="fake-model",
                    task_type="reply_suggestion",
                )
            )
        )
        await asyncio.sleep(0)

        service.release("task-running")
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert service.started_order[:2] == ["task-running", "task-reply"]

        service.release("task-reply")
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        first = await running
        second = await queued_reply
        third = await queued_summary

        assert first.state == AITaskState.DONE
        assert second.state == AITaskState.DONE
        assert third.state == AITaskState.CANCELLED
        assert service.started_order == ["task-running", "task-reply"]
        assert service.cancelled == []

    asyncio.run(scenario())


def test_ai_task_manager_reply_suggestion_preempts_running_summary() -> None:
    async def scenario() -> None:
        event_bus = FakeEventBus()
        service = PriorityService()
        manager = AITaskManager(service=service, event_bus=event_bus, concurrency=1)

        running_summary = asyncio.create_task(
            manager.run_once(
                AIRequest(
                    task_id="task-summary",
                    session_id="session-1",
                    messages=[{"role": "user", "content": "summary"}],
                    model="fake-model",
                    task_type="summary",
                )
            )
        )
        await asyncio.sleep(0)
        assert service.started_order == ["task-summary"]

        reply = asyncio.create_task(
            manager.run_once(
                AIRequest(
                    task_id="task-reply",
                    session_id="session-1",
                    messages=[{"role": "user", "content": "reply"}],
                    model="fake-model",
                    task_type="reply_suggestion",
                )
            )
        )
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert service.cancelled == ["task-summary"]

        service.release("task-reply")
        summary_snapshot = await running_summary
        reply_snapshot = await reply

        assert summary_snapshot.state == AITaskState.CANCELLED
        assert reply_snapshot.state == AITaskState.DONE
        assert service.started_order == ["task-summary", "task-reply"]

    asyncio.run(scenario())


def test_ai_task_manager_translate_preempts_running_summary() -> None:
    async def scenario() -> None:
        event_bus = FakeEventBus()
        service = PriorityService()
        manager = AITaskManager(service=service, event_bus=event_bus, concurrency=1)

        running_summary = asyncio.create_task(
            manager.run_once(
                AIRequest(
                    task_id="task-summary",
                    session_id="session-1",
                    messages=[{"role": "user", "content": "summary"}],
                    model="fake-model",
                    task_type="summary",
                )
            )
        )
        await asyncio.sleep(0)
        assert service.started_order == ["task-summary"]

        translate = asyncio.create_task(
            manager.run_once(
                AIRequest(
                    task_id="task-translate",
                    session_id="session-1",
                    messages=[{"role": "user", "content": "translate"}],
                    model="fake-model",
                    task_type="translate",
                    metadata={"mode": "manual"},
                )
            )
        )
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert service.cancelled == ["task-summary"]

        service.release("task-translate")
        summary_snapshot = await running_summary
        translate_snapshot = await translate

        assert summary_snapshot.state == AITaskState.CANCELLED
        assert translate_snapshot.state == AITaskState.DONE
        assert service.started_order == ["task-summary", "task-translate"]

    asyncio.run(scenario())


def test_ai_task_manager_translate_does_not_preempt_running_reply_suggestion() -> None:
    async def scenario() -> None:
        event_bus = FakeEventBus()
        service = PriorityService()
        manager = AITaskManager(service=service, event_bus=event_bus, concurrency=1)

        running_reply = asyncio.create_task(
            manager.run_once(
                AIRequest(
                    task_id="task-reply",
                    session_id="session-1",
                    messages=[{"role": "user", "content": "reply"}],
                    model="fake-model",
                    task_type="reply_suggestion",
                )
            )
        )
        await asyncio.sleep(0)
        assert service.started_order == ["task-reply"]

        translate = asyncio.create_task(
            manager.run_once(
                AIRequest(
                    task_id="task-translate",
                    session_id="session-1",
                    messages=[{"role": "user", "content": "translate"}],
                    model="fake-model",
                    task_type="translate",
                    metadata={"mode": "manual"},
                )
            )
        )
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert service.cancelled == []

        service.release("task-reply")
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert service.started_order[:2] == ["task-reply", "task-translate"]

        service.release("task-translate")
        reply_snapshot = await running_reply
        translate_snapshot = await translate

        assert reply_snapshot.state == AITaskState.DONE
        assert translate_snapshot.state == AITaskState.DONE

    asyncio.run(scenario())
