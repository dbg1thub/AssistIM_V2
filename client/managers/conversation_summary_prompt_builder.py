from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from client.managers.ai_prompt_builder import privacy_scope_for_session
from client.models.message import ChatMessage, MessageType, Session
from client.services.ai_service import AIRequest, AITaskType


@dataclass(frozen=True, slots=True)
class ConversationSummaryRequest:
    """One bounded summary request for a single chat time bucket."""

    request: AIRequest
    message_count: int


class ConversationSummaryPromptBuilder:
    """Build one bounded AI summary request for a single chat time bucket."""

    MAX_BUCKET_MESSAGES = 24
    MAX_MESSAGE_CHARS = 280
    MAX_CONTEXT_CHARS = 3200
    MAX_OUTPUT_CHARS = 240

    def build_bucket_summary_request(
        self,
        session: Session,
        messages: Sequence[ChatMessage],
        *,
        task_id: str = "",
        bucket_start_ts: int = 0,
        bucket_end_ts: int = 0,
        is_open: bool = True,
    ) -> ConversationSummaryRequest | None:
        """Build a local-only summary request for one chat bucket."""
        context_lines = self._format_context(session, messages)
        if not context_lines:
            return None

        context = "\n".join(context_lines)
        prompt = self._build_open_bucket_prompt(context) if is_open else self._build_closed_bucket_prompt(context)

        request = AIRequest(
            task_id=task_id,
            session_id=session.session_id,
            task_type=AITaskType.SUMMARY,
            privacy_scope=privacy_scope_for_session(session),
            must_be_local=True,
            stream=False,
            temperature=0.2,
            max_tokens=192,
            max_output_chars=self.MAX_OUTPUT_CHARS,
            messages=[{"role": "user", "content": prompt}],
            metadata={
                "summary_kind": "conversation_bucket",
                "bucket_start_ts": int(bucket_start_ts or 0),
                "bucket_end_ts": int(bucket_end_ts or 0),
                "session_type": str(session.session_type or ""),
                "is_open_bucket": bool(is_open),
                "message_count": len(context_lines),
            },
        )
        return ConversationSummaryRequest(request=request, message_count=len(context_lines))

    @staticmethod
    def _build_open_bucket_prompt(context: str) -> str:
        return (
            "请基于下面同一时间段内的聊天记录，生成一段简短摘要，供后续本地推荐回复使用。\n"
            "这是一段当前仍在继续的聊天时间段。\n"
            "约束：只输出摘要正文；不要分点；不要解释；不要复述原话；"
            "突出当前在聊什么、已确认事实、待确认事项和整体语气；"
            "允许保留未完成状态；长度控制在 120 字以内。\n\n"
            f"聊天记录：\n{context}"
        )

    @staticmethod
    def _build_closed_bucket_prompt(context: str) -> str:
        return (
            "请基于下面同一时间段内的聊天记录，生成一段简短摘要，供后续本地推荐回复使用。\n"
            "这是一段已经结束的聊天时间段，请输出稳定的最终总结。\n"
            "约束：只输出摘要正文；不要分点；不要解释；不要复述原话；"
            "突出最终讨论主题、已达成的结论或决定、仍待后续跟进的遗留点和整体语气；"
            "不要使用“当前”“正在”“还在继续”等时间敏感措辞；不要写推测性语句；"
            "长度控制在 120 字以内。\n\n"
            f"聊天记录：\n{context}"
        )

    def normalize_summary_output(self, output: str) -> str:
        """Collapse one model response into a short single-paragraph summary."""
        text = re.sub(r"\s+", " ", str(output or "").strip())
        if len(text) > self.MAX_OUTPUT_CHARS:
            text = text[: self.MAX_OUTPUT_CHARS].rstrip()
        return text

    def _format_context(self, session: Session, messages: Sequence[ChatMessage]) -> list[str]:
        lines: list[str] = []
        total_chars = 0
        for message in reversed(list(messages or [])[-self.MAX_BUCKET_MESSAGES :]):
            if message.message_type != MessageType.TEXT:
                continue
            content = self._normalize_text(message.content, max_chars=self.MAX_MESSAGE_CHARS)
            if not content:
                continue
            line = f"{self._speaker_label(session, message)}: {content}"
            if total_chars + len(line) > self.MAX_CONTEXT_CHARS and lines:
                break
            lines.append(line)
            total_chars += len(line)
        lines.reverse()
        return lines

    @staticmethod
    def _speaker_label(session: Session, message: ChatMessage) -> str:
        if message.is_self:
            return "我"
        if str(session.session_type or "").strip() == "group":
            sender = str(message.sender_id or "").strip() or "成员"
            return f"成员[{sender}]"
        return "对方"

    @staticmethod
    def _normalize_text(value: str, *, max_chars: int) -> str:
        text = re.sub(r"\s+", " ", str(value or "").strip())
        if max_chars > 0 and len(text) > max_chars:
            return text[:max_chars].rstrip()
        return text
