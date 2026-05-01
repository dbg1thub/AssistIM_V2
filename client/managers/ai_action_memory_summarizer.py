"""Local summarizer for AI assistant memory action results."""

from __future__ import annotations

import uuid
from typing import Any

from client.core import logging

logger = logging.get_logger(__name__)


class AIActionMemorySummarizer:
    """Summarize memory.search evidence into the final action answer."""

    PROMPT_VERSION = "ai_action_memory_summarizer:v1"
    DEFAULT_MAX_CONTEXT_CHARS = 3600
    DEFAULT_CHUNK_CONTEXT_CHARS = 1800
    DEFAULT_MAX_OUTPUT_CHARS = 1600
    DEFAULT_CHUNK_OUTPUT_CHARS = 700

    def __init__(
        self,
        *,
        task_manager: Any | None = None,
        max_context_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
        chunk_context_chars: int = DEFAULT_CHUNK_CONTEXT_CHARS,
        max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS,
        chunk_output_chars: int = DEFAULT_CHUNK_OUTPUT_CHARS,
    ) -> None:
        self._task_manager = task_manager
        self._max_context_chars = max(200, int(max_context_chars or self.DEFAULT_MAX_CONTEXT_CHARS))
        self._chunk_context_chars = max(200, int(chunk_context_chars or self.DEFAULT_CHUNK_CONTEXT_CHARS))
        self._max_output_chars = max(200, int(max_output_chars or self.DEFAULT_MAX_OUTPUT_CHARS))
        self._chunk_output_chars = max(100, int(chunk_output_chars or self.DEFAULT_CHUNK_OUTPUT_CHARS))

    async def summarize(
        self,
        *,
        question: str,
        context_lines: list[str],
        style: str = "summary",
        input_result_count: int = 0,
    ) -> dict[str, Any]:
        lines = [str(line or "").strip() for line in list(context_lines or []) if str(line or "").strip()]
        if not lines:
            return {
                "text": self._empty_text(question),
                "summary_model_id": self.PROMPT_VERSION,
                "model_chunk_count": 0,
                "chunk_count": 0,
            }

        chunks = _chunk_lines(lines, self._chunk_context_chars)
        if len(chunks) == 1 and sum(len(line) for line in lines) <= self._max_context_chars:
            text = await self._run_summary_request(
                question=question,
                evidence_lines=lines,
                style=style,
                stage="final",
                max_output_chars=self._max_output_chars,
                input_result_count=input_result_count,
            )
            return {
                "text": text,
                "summary_model_id": self.PROMPT_VERSION,
                "model_chunk_count": 0,
                "chunk_count": 1,
            }

        chunk_summaries: list[str] = []
        for index, chunk in enumerate(chunks, start=1):
            chunk_text = await self._run_summary_request(
                question=question,
                evidence_lines=chunk,
                style=style,
                stage="chunk",
                chunk_index=index,
                chunk_count=len(chunks),
                max_output_chars=self._chunk_output_chars,
                input_result_count=input_result_count,
            )
            if chunk_text:
                chunk_summaries.append(f"分块 {index}：{chunk_text}")

        if not chunk_summaries:
            raise RuntimeError("MEMORY_SUMMARIZE_EMPTY_OUTPUT")

        text = await self._run_summary_request(
            question=question,
            evidence_lines=chunk_summaries,
            style=style,
            stage="final",
            max_output_chars=self._max_output_chars,
            input_result_count=input_result_count,
        )
        return {
            "text": text,
            "summary_model_id": self.PROMPT_VERSION,
            "model_chunk_count": len(chunks),
            "chunk_count": len(chunks),
        }

    async def _run_summary_request(
        self,
        *,
        question: str,
        evidence_lines: list[str],
        style: str,
        stage: str,
        max_output_chars: int,
        input_result_count: int,
        chunk_index: int = 0,
        chunk_count: int = 0,
    ) -> str:
        task_manager = self._require_task_manager()
        request = self._build_request(
            question=question,
            evidence_lines=evidence_lines,
            style=style,
            stage=stage,
            max_output_chars=max_output_chars,
            input_result_count=input_result_count,
            chunk_index=chunk_index,
            chunk_count=chunk_count,
        )
        snapshot = await task_manager.run_once(request)
        error_code = getattr(snapshot, "error_code", None)
        if error_code:
            logger.warning(
                "AI action memory summarization failed stage=%s error=%s message=%s",
                stage,
                error_code,
                getattr(snapshot, "error_message", ""),
            )
            raise RuntimeError("MEMORY_SUMMARIZE_FAILED")
        text = " ".join(str(getattr(snapshot, "content", "") or "").split()).strip()
        if not text:
            raise RuntimeError("MEMORY_SUMMARIZE_EMPTY_OUTPUT")
        return text

    def _build_request(
        self,
        *,
        question: str,
        evidence_lines: list[str],
        style: str,
        stage: str,
        max_output_chars: int,
        input_result_count: int,
        chunk_index: int = 0,
        chunk_count: int = 0,
    ):
        from client.services.ai_service import AIPrivacyScope, AIRequest, AITaskType

        normalized_question = " ".join(str(question or "").split()) or "请总结这些本地记忆。"
        normalized_style = " ".join(str(style or "summary").split()) or "summary"
        evidence = "\n".join(f"- {line}" for line in evidence_lines)
        stage_label = "分块总结" if stage == "chunk" else "最终总结"
        system_prompt = (
            "你是 AssistIM 的本地聊天记忆总结器。\n"
            "只能依据提供的本机检索证据回答，不要编造证据外的信息。\n"
            "输出用户可直接阅读的自然语言答案，不要输出思考过程。"
        )
        user_prompt = (
            f"任务：{stage_label}\n"
            f"用户问题：{normalized_question}\n"
            f"输出风格：{normalized_style}\n"
            f"检索结果数量：{max(0, int(input_result_count or 0))}\n"
        )
        if stage == "chunk":
            user_prompt += f"当前分块：{chunk_index}/{chunk_count}\n"
        user_prompt += f"证据：\n{evidence}\n\n请基于证据回答用户问题。"

        return AIRequest(
            task_id=f"ai-action-memory-summary-{uuid.uuid4()}",
            session_id="ai_action_memory_summarize",
            task_type=AITaskType.CHAT,
            privacy_scope=AIPrivacyScope.GENERAL,
            must_be_local=True,
            stream=False,
            temperature=0.2,
            max_tokens=700,
            max_output_chars=max_output_chars,
            system_prompt=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            metadata={
                "source": "ai_action_memory_summarize",
                "summary_stage": stage,
                "prompt_version": self.PROMPT_VERSION,
                "chunk_index": chunk_index,
                "chunk_count": chunk_count,
                "input_result_count": max(0, int(input_result_count or 0)),
            },
        )

    def _require_task_manager(self) -> Any:
        if self._task_manager is None:
            from client.managers.ai_task_manager import get_ai_task_manager

            self._task_manager = get_ai_task_manager()
        return self._task_manager

    @staticmethod
    def _empty_text(question: str) -> str:
        normalized_question = " ".join(str(question or "").split())
        return f"没有找到相关记录。用户问题：{normalized_question or '本地记忆查询'}。"


def _chunk_lines(lines: list[str], max_chars: int) -> list[list[str]]:
    limit = max(200, int(max_chars or 200))
    chunks: list[list[str]] = []
    current: list[str] = []
    current_chars = 0
    for line in lines:
        text = str(line or "").strip()
        if not text:
            continue
        projected = current_chars + len(text)
        if current and projected > limit:
            chunks.append(current)
            current = []
            current_chars = 0
        current.append(text)
        current_chars += len(text)
    if current:
        chunks.append(current)
    return chunks
