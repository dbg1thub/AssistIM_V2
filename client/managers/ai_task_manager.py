"""AI task manager for local and remote provider work."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from client.core import logging
from client.core.logging import setup_logging
from client.events.event_bus import EventBus, get_event_bus
from client.services.ai_service import (
    AIErrorCode,
    AIRequest,
    AIResponse,
    AIService,
    AIServiceError,
    AIStreamEventType,
    get_ai_service,
)

setup_logging()
logger = logging.get_logger(__name__)


class AITaskState(Enum):
    """AI task lifecycle states owned by the manager."""

    QUEUED = "queued"
    RUNNING = "running"
    CANCELLING = "cancelling"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AITaskEvent:
    """EventBus names emitted by AI task manager."""

    STARTED = "ai_task_started"
    UPDATED = "ai_task_updated"
    FINISHED = "ai_task_finished"
    FAILED = "ai_task_failed"
    CANCELLED = "ai_task_cancelled"


TERMINAL_STATES = {
    AITaskState.DONE,
    AITaskState.FAILED,
    AITaskState.CANCELLED,
}


@dataclass(slots=True)
class AITaskSnapshot:
    """Current task state exposed to downstream managers and UI."""

    task_id: str
    session_id: str
    task_type: str
    provider: str = ""
    model: str = ""
    state: AITaskState = AITaskState.QUEUED
    content: str = ""
    error_code: Optional[AIErrorCode] = None
    error_message: str = ""
    finish_reason: str = ""
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    truncated: bool = False
    chunk_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def copy(self) -> "AITaskSnapshot":
        """Return a detached copy suitable for event payloads."""
        return AITaskSnapshot(
            task_id=self.task_id,
            session_id=self.session_id,
            task_type=self.task_type,
            provider=self.provider,
            model=self.model,
            state=self.state,
            content=self.content,
            error_code=self.error_code,
            error_message=self.error_message,
            finish_reason=self.finish_reason,
            created_at=self.created_at,
            started_at=self.started_at,
            finished_at=self.finished_at,
            truncated=self.truncated,
            chunk_count=self.chunk_count,
            metadata=dict(self.metadata),
        )


class AITaskManager:
    """Own AI task lifecycle, cancellation, output aggregation, and diagnostics."""

    FLUSH_INTERVAL_SECONDS = 0.05
    FLUSH_CHARS = 24

    def __init__(
        self,
        service: Optional[AIService] = None,
        event_bus: Optional[EventBus] = None,
        *,
        concurrency: int = 1,
    ) -> None:
        self._service = service or get_ai_service()
        self._event_bus = event_bus or get_event_bus()
        self._semaphore = asyncio.Semaphore(max(1, int(concurrency or 1)))
        self._lock = asyncio.Lock()
        self._tasks: dict[str, AITaskSnapshot] = {}
        self._cancel_requested: set[str] = set()
        self._runner_tasks: dict[str, asyncio.Task] = {}
        self._closed = False

    async def run_once(self, request: AIRequest) -> AITaskSnapshot:
        """Run one non-streaming AI task to completion."""
        snapshot = await self._register_task(request)
        await self._emit(AITaskEvent.UPDATED, snapshot)
        current_task = asyncio.current_task()
        if current_task is not None:
            self._runner_tasks[snapshot.task_id] = current_task

        try:
            async with self._semaphore:
                if await self._is_cancelled_before_start(snapshot.task_id):
                    return snapshot.copy()

                await self._mark_running(snapshot)
                response = await self._service.generate_once(request)
                if self._is_cancel_requested(snapshot.task_id):
                    await self._mark_cancelled(snapshot, finish_reason=AIErrorCode.AI_USER_CANCELLED.value)
                    return snapshot.copy()

                content = str(response.content or "")
                truncated = False
                if request.max_output_chars > 0 and len(content) > request.max_output_chars:
                    content = content[: request.max_output_chars]
                    truncated = True
                snapshot.content = content
                snapshot.provider = response.provider
                snapshot.model = response.model
                snapshot.finish_reason = (
                    AIErrorCode.AI_OUTPUT_TRUNCATED.value
                    if truncated
                    else str(response.finish_reason or "")
                )
                snapshot.truncated = truncated
                snapshot.chunk_count = 1 if content else 0
                snapshot.metadata.update(response.metadata)
                await self._mark_done(snapshot)
                return snapshot.copy()
        except asyncio.CancelledError:
            await self._mark_cancelled(snapshot, finish_reason=AIErrorCode.AI_USER_CANCELLED.value)
            raise
        except AIServiceError as exc:
            if exc.code == AIErrorCode.AI_USER_CANCELLED:
                await self._mark_cancelled(snapshot, finish_reason=exc.code.value)
            else:
                await self._mark_failed(snapshot, exc.code, str(exc))
            return snapshot.copy()
        except Exception:
            logger.exception("[ai-diag] task_failed_unexpected task_id=%s task_type=%s", snapshot.task_id, snapshot.task_type)
            await self._mark_failed(snapshot, AIErrorCode.AI_MODEL_UNAVAILABLE, "Unexpected AI task failure")
            return snapshot.copy()
        finally:
            self._runner_tasks.pop(snapshot.task_id, None)
            self._cancel_requested.discard(snapshot.task_id)

    async def stream(self, request: AIRequest) -> AITaskSnapshot:
        """Run one streaming AI task while coalescing provider chunks."""
        snapshot = await self._register_task(request)
        await self._emit(AITaskEvent.UPDATED, snapshot)
        current_task = asyncio.current_task()
        if current_task is not None:
            self._runner_tasks[snapshot.task_id] = current_task

        try:
            async with self._semaphore:
                if await self._is_cancelled_before_start(snapshot.task_id):
                    return snapshot.copy()

                await self._mark_running(snapshot)
                pending_chars = 0
                last_emit_at = time.monotonic()

                async for event in self._service.stream_chat(request):
                    if self._is_cancel_requested(snapshot.task_id):
                        await self._service.cancel(snapshot.task_id)
                        await self._mark_cancelled(snapshot, finish_reason=AIErrorCode.AI_USER_CANCELLED.value)
                        return snapshot.copy()

                    if event.event_type == AIStreamEventType.STARTED:
                        continue

                    if event.event_type == AIStreamEventType.DELTA:
                        delta = str(event.content or "")
                        if not delta:
                            continue
                        accepted, truncated = self._append_delta(snapshot, delta, request.max_output_chars)
                        if accepted:
                            pending_chars += len(accepted)
                            snapshot.chunk_count += 1
                        if truncated:
                            await self._service.cancel(snapshot.task_id)
                            snapshot.finish_reason = AIErrorCode.AI_OUTPUT_TRUNCATED.value
                            await self._emit(AITaskEvent.UPDATED, snapshot)
                            break
                        now = time.monotonic()
                        if (
                            pending_chars >= self.FLUSH_CHARS
                            or now - last_emit_at >= self.FLUSH_INTERVAL_SECONDS
                        ):
                            pending_chars = 0
                            last_emit_at = now
                            await self._emit(AITaskEvent.UPDATED, snapshot)
                        continue

                    if event.event_type == AIStreamEventType.DONE:
                        self._merge_done_response(snapshot, event.response)
                        if event.finish_reason:
                            snapshot.finish_reason = str(event.finish_reason)
                        break

                    if event.event_type == AIStreamEventType.ERROR:
                        code = event.error_code or AIErrorCode.AI_STREAM_INTERRUPTED
                        raise AIServiceError(code, code.value)

                if self._is_cancel_requested(snapshot.task_id):
                    await self._mark_cancelled(snapshot, finish_reason=AIErrorCode.AI_USER_CANCELLED.value)
                    return snapshot.copy()

                if snapshot.truncated:
                    snapshot.finish_reason = AIErrorCode.AI_OUTPUT_TRUNCATED.value
                elif not snapshot.finish_reason:
                    snapshot.finish_reason = "stop"
                await self._mark_done(snapshot)
                return snapshot.copy()
        except asyncio.CancelledError:
            await self._mark_cancelled(snapshot, finish_reason=AIErrorCode.AI_USER_CANCELLED.value)
            raise
        except AIServiceError as exc:
            if exc.code == AIErrorCode.AI_USER_CANCELLED:
                await self._mark_cancelled(snapshot, finish_reason=exc.code.value)
            else:
                await self._mark_failed(snapshot, exc.code, str(exc))
            return snapshot.copy()
        except Exception:
            logger.exception("[ai-diag] task_failed_unexpected task_id=%s task_type=%s", snapshot.task_id, snapshot.task_type)
            await self._mark_failed(snapshot, AIErrorCode.AI_STREAM_INTERRUPTED, "Unexpected AI stream failure")
            return snapshot.copy()
        finally:
            self._runner_tasks.pop(snapshot.task_id, None)
            self._cancel_requested.discard(snapshot.task_id)

    async def cancel(self, task_id: str) -> None:
        """Cancel a queued or running task."""
        normalized_task_id = str(task_id or "").strip()
        if not normalized_task_id:
            return

        snapshot = self._tasks.get(normalized_task_id)
        if snapshot is None or snapshot.state in TERMINAL_STATES:
            return

        self._cancel_requested.add(normalized_task_id)
        if snapshot.state == AITaskState.QUEUED:
            await self._mark_cancelled(snapshot, finish_reason=AIErrorCode.AI_USER_CANCELLED.value)
            return

        snapshot.state = AITaskState.CANCELLING
        await self._emit(AITaskEvent.UPDATED, snapshot)
        await self._service.cancel(normalized_task_id)

    def get_task(self, task_id: str) -> AITaskSnapshot | None:
        """Return one task snapshot copy."""
        snapshot = self._tasks.get(str(task_id or "").strip())
        return snapshot.copy() if snapshot is not None else None

    def list_tasks(self) -> list[AITaskSnapshot]:
        """Return all known task snapshots."""
        return [snapshot.copy() for snapshot in self._tasks.values()]

    async def close(self) -> None:
        """Cancel pending AI work and release the singleton."""
        self._closed = True
        task_ids = [
            task_id
            for task_id, snapshot in list(self._tasks.items())
            if snapshot.state not in TERMINAL_STATES
        ]
        for task_id in task_ids:
            await self.cancel(task_id)

        current_task = asyncio.current_task()
        runner_tasks = [
            task
            for task in list(self._runner_tasks.values())
            if task is not current_task and not task.done()
        ]
        for task in runner_tasks:
            task.cancel()
        if runner_tasks:
            await asyncio.gather(*runner_tasks, return_exceptions=True)

        global _ai_task_manager
        if _ai_task_manager is self:
            _ai_task_manager = None

    async def _register_task(self, request: AIRequest) -> AITaskSnapshot:
        if self._closed:
            raise RuntimeError("AI task manager is closed")
        snapshot = AITaskSnapshot(
            task_id=request.task_id,
            session_id=request.session_id,
            task_type=getattr(request.task_type, "value", str(request.task_type)),
            model=request.model,
        )
        async with self._lock:
            self._tasks[snapshot.task_id] = snapshot
        return snapshot

    async def _is_cancelled_before_start(self, task_id: str) -> bool:
        snapshot = self._tasks.get(task_id)
        if snapshot is None:
            return True
        if snapshot.state == AITaskState.CANCELLED or task_id in self._cancel_requested:
            await self._mark_cancelled(snapshot, finish_reason=AIErrorCode.AI_USER_CANCELLED.value)
            return True
        return False

    async def _mark_running(self, snapshot: AITaskSnapshot) -> None:
        snapshot.state = AITaskState.RUNNING
        snapshot.started_at = time.time()
        logger.info(
            "[ai-diag] task_started task_id=%s session_id=%s task_type=%s model=%s",
            snapshot.task_id,
            snapshot.session_id,
            snapshot.task_type,
            snapshot.model,
        )
        await self._emit(AITaskEvent.STARTED, snapshot)

    async def _mark_done(self, snapshot: AITaskSnapshot) -> None:
        snapshot.state = AITaskState.DONE
        snapshot.finished_at = time.time()
        logger.info(
            "[ai-diag] task_finished task_id=%s session_id=%s task_type=%s provider=%s model=%s state=%s "
            "duration_ms=%s chunk_count=%s error_code=None truncated=%s",
            snapshot.task_id,
            snapshot.session_id,
            snapshot.task_type,
            snapshot.provider,
            snapshot.model,
            snapshot.state.value,
            self._duration_ms(snapshot),
            snapshot.chunk_count,
            snapshot.truncated,
        )
        await self._emit(AITaskEvent.UPDATED, snapshot)
        await self._emit(AITaskEvent.FINISHED, snapshot)

    async def _mark_failed(self, snapshot: AITaskSnapshot, error_code: AIErrorCode, error_message: str = "") -> None:
        snapshot.state = AITaskState.FAILED
        snapshot.error_code = error_code
        snapshot.error_message = str(error_message or "")
        snapshot.finished_at = time.time()
        logger.warning(
            "[ai-diag] task_failed task_id=%s session_id=%s task_type=%s provider=%s model=%s "
            "duration_ms=%s chunk_count=%s error_code=%s",
            snapshot.task_id,
            snapshot.session_id,
            snapshot.task_type,
            snapshot.provider,
            snapshot.model,
            self._duration_ms(snapshot),
            snapshot.chunk_count,
            error_code.value,
        )
        await self._emit(AITaskEvent.UPDATED, snapshot)
        await self._emit(AITaskEvent.FAILED, snapshot)

    async def _mark_cancelled(self, snapshot: AITaskSnapshot, *, finish_reason: str) -> None:
        if snapshot.state == AITaskState.CANCELLED:
            return
        snapshot.state = AITaskState.CANCELLED
        snapshot.finish_reason = finish_reason
        snapshot.finished_at = time.time()
        logger.info(
            "[ai-diag] task_cancelled task_id=%s session_id=%s task_type=%s duration_ms=%s chunk_count=%s",
            snapshot.task_id,
            snapshot.session_id,
            snapshot.task_type,
            self._duration_ms(snapshot),
            snapshot.chunk_count,
        )
        await self._emit(AITaskEvent.UPDATED, snapshot)
        await self._emit(AITaskEvent.CANCELLED, snapshot)

    def _append_delta(self, snapshot: AITaskSnapshot, delta: str, max_output_chars: int) -> tuple[str, bool]:
        if max_output_chars <= 0:
            snapshot.content += delta
            return delta, False
        remaining = max_output_chars - len(snapshot.content)
        if remaining <= 0:
            snapshot.truncated = True
            return "", True
        accepted = delta[:remaining]
        snapshot.content += accepted
        truncated = len(delta) > remaining
        if truncated:
            snapshot.truncated = True
        return accepted, truncated

    @staticmethod
    def _merge_done_response(snapshot: AITaskSnapshot, response: AIResponse | None) -> None:
        if response is None:
            return
        snapshot.provider = response.provider or snapshot.provider
        snapshot.model = response.model or snapshot.model
        snapshot.truncated = bool(snapshot.truncated or response.truncated)
        if response.metadata:
            snapshot.metadata.update(response.metadata)

    def _is_cancel_requested(self, task_id: str) -> bool:
        return str(task_id or "").strip() in self._cancel_requested

    async def _emit(self, event_name: str, snapshot: AITaskSnapshot) -> None:
        await self._event_bus.emit(
            event_name,
            {
                "task": snapshot.copy(),
                "task_id": snapshot.task_id,
                "state": snapshot.state.value,
            },
        )

    @staticmethod
    def _duration_ms(snapshot: AITaskSnapshot) -> int:
        start = snapshot.started_at or snapshot.created_at
        end = snapshot.finished_at or time.time()
        return max(0, round((end - start) * 1000))


_ai_task_manager: Optional[AITaskManager] = None


def peek_ai_task_manager() -> Optional[AITaskManager]:
    """Return the existing AI task manager singleton when present."""
    return _ai_task_manager


def get_ai_task_manager() -> AITaskManager:
    """Return the global AI task manager singleton."""
    global _ai_task_manager
    if _ai_task_manager is None:
        _ai_task_manager = AITaskManager()
    return _ai_task_manager
