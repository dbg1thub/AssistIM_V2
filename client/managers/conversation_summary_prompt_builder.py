from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Sequence

from client.core.file_text_extraction import extracted_file_context_text
from client.core.voice_transcription import VOICE_TRANSCRIPT_EXTRA_KEY
from client.managers.ai_prompt_builder import privacy_scope_for_session
from client.models.message import ChatMessage, MessageType, Session
from client.services.ai_service import AIRequest, AITaskType


@dataclass(frozen=True, slots=True)
class ConversationSummaryRequest:
    """One bounded summary request for a single chat bucket."""

    request: AIRequest
    message_count: int


@dataclass(frozen=True, slots=True)
class StructuredConversationSummary:
    """Structured summary fields parsed from one deterministic 8-line model output."""

    display_summary: str
    topics: tuple[str, ...]
    facts: tuple[str, ...]
    decisions: tuple[str, ...]
    pending_items: tuple[str, ...]
    tone: str
    participants: tuple[str, ...]
    keywords: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key in ("topics", "facts", "decisions", "pending_items", "participants", "keywords"):
            data[key] = list(data[key])
        return data


class ConversationSummaryPromptBuilder:
    """Build one bounded summary request and parse its deterministic output."""

    MAX_BUCKET_MESSAGES = 24
    MAX_MESSAGE_CHARS = 280
    MAX_CONTEXT_CHARS = 3200
    MAX_OUTPUT_CHARS = 720
    DISPLAY_SUMMARY_MAX_CHARS = 180
    TOPIC_MAX_ITEMS = 4
    FACT_MAX_ITEMS = 4
    DECISION_MAX_ITEMS = 3
    PENDING_MAX_ITEMS = 3
    PARTICIPANT_MAX_ITEMS = 8
    KEYWORD_MAX_ITEMS = 12
    OUTPUT_FIELDS = (
        "DISPLAY_SUMMARY",
        "TOPICS",
        "FACTS",
        "DECISIONS",
        "PENDING_ITEMS",
        "TONE",
        "PARTICIPANTS",
        "KEYWORDS",
    )
    EMPTY_MARKERS = {"", "无", "暂无", "未提及", "无明确", "无明显", "无特殊"}

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
        system_prompt = (
            "你是 AssistIM 的会话摘要助手。\n"
            "使用标准聊天角色，不要输出思考过程，不要解释，只输出固定格式结果。"
        )
        prompt = self._build_open_bucket_prompt(context) if is_open else self._build_closed_bucket_prompt(context)

        request = AIRequest(
            task_id=task_id,
            session_id=session.session_id,
            task_type=AITaskType.SUMMARY,
            privacy_scope=privacy_scope_for_session(session),
            must_be_local=True,
            stream=False,
            temperature=0.2,
            max_tokens=256,
            max_output_chars=self.MAX_OUTPUT_CHARS,
            system_prompt=system_prompt,
            messages=[{"role": "user", "content": prompt}],
            metadata={
                "summary_kind": "conversation_bucket",
                "bucket_start_ts": int(bucket_start_ts or 0),
                "bucket_end_ts": int(bucket_end_ts or 0),
                "session_type": str(session.session_type or ""),
                "is_open_bucket": bool(is_open),
                "message_count": len(context_lines),
                "summary_output_format": "fixed_lines_v2",
            },
        )
        return ConversationSummaryRequest(request=request, message_count=len(context_lines))

    @classmethod
    def parse_summary_output(cls, output: str) -> StructuredConversationSummary | None:
        """Parse the deterministic 8-line summary output into structured fields."""
        normalized_lines = [
            str(line or "").strip()
            for line in re.split(r"\r?\n", str(output or ""))
            if str(line or "").strip()
        ]
        if len(normalized_lines) != len(cls.OUTPUT_FIELDS):
            return None

        parsed: dict[str, str] = {}
        for expected_field, line in zip(cls.OUTPUT_FIELDS, normalized_lines):
            prefix = f"{expected_field}:"
            if not line.startswith(prefix):
                return None
            parsed[expected_field] = line[len(prefix) :].strip()

        display_summary = cls._normalize_scalar(parsed["DISPLAY_SUMMARY"], max_chars=cls.DISPLAY_SUMMARY_MAX_CHARS)
        tone = cls._normalize_scalar(parsed["TONE"], max_chars=64)
        if not display_summary or not tone:
            return None

        return StructuredConversationSummary(
            display_summary=display_summary,
            topics=cls._normalize_list(parsed["TOPICS"], limit=cls.TOPIC_MAX_ITEMS, item_max_chars=48),
            facts=cls._normalize_list(parsed["FACTS"], limit=cls.FACT_MAX_ITEMS, item_max_chars=64),
            decisions=cls._normalize_list(parsed["DECISIONS"], limit=cls.DECISION_MAX_ITEMS, item_max_chars=64),
            pending_items=cls._normalize_list(parsed["PENDING_ITEMS"], limit=cls.PENDING_MAX_ITEMS, item_max_chars=64),
            tone=tone,
            participants=cls._normalize_list(
                parsed["PARTICIPANTS"],
                limit=cls.PARTICIPANT_MAX_ITEMS,
                item_max_chars=48,
            ),
            keywords=cls._normalize_list(parsed["KEYWORDS"], limit=cls.KEYWORD_MAX_ITEMS, item_max_chars=32),
        )

    @classmethod
    def normalize_summary_output(cls, output: str) -> str:
        """Return the human-facing summary text from one fixed-line model output."""
        parsed = cls.parse_summary_output(output)
        if parsed is None:
            text = re.sub(r"\s+", " ", str(output or "").strip())
            if len(text) > cls.DISPLAY_SUMMARY_MAX_CHARS:
                text = text[: cls.DISPLAY_SUMMARY_MAX_CHARS].rstrip()
            return text
        return parsed.display_summary

    @classmethod
    def build_retrieval_summary(
        cls,
        structured: StructuredConversationSummary,
        *,
        bucket_start_ts: int,
        bucket_end_ts: int,
    ) -> str:
        """Build one retrieval-oriented summary text from structured fields."""
        participants = cls._join_or_default(structured.participants, default="无")
        topics = cls._join_or_default(structured.topics, default="无")
        facts = cls._join_or_default(structured.facts, default="无")
        decisions = cls._join_or_default(structured.decisions, default="无")
        pending_items = cls._join_or_default(structured.pending_items, default="无")
        tone = cls._normalize_scalar(structured.tone, max_chars=64) or "无"
        time_range = cls._format_time_range(bucket_start_ts, bucket_end_ts)
        return "\n".join(
            [
                f"会话对象：{participants}",
                f"时间范围：{time_range}",
                f"主题：{topics}",
                f"已确认：{facts}",
                f"已决定：{decisions}",
                f"待跟进：{pending_items}",
                f"整体语气：{tone}",
            ]
        )

    @classmethod
    def _build_open_bucket_prompt(cls, context: str) -> str:
        return (
            "请基于下面同一时间段内的聊天记录，输出结构化时间段摘要。\n"
            "这是一段当前仍在继续的聊天时间段。\n"
            "严格要求：\n"
            "1. 只输出正好 8 行，不要输出其他内容。\n"
            "2. 字段顺序必须固定如下：\n"
            "DISPLAY_SUMMARY:\nTOPICS:\nFACTS:\nDECISIONS:\nPENDING_ITEMS:\nTONE:\nPARTICIPANTS:\nKEYWORDS:\n"
            "3. 列表字段用 \" | \" 分隔；没有内容时写“无”。\n"
            "4. DISPLAY_SUMMARY 用自然语言简短描述当前这段聊天的核心进展。\n"
            "5. FACTS 强调已确认事实；PENDING_ITEMS 强调仍待确认事项；允许保留未完成状态。\n"
            "6. 不要复述原话，不要解释，不要输出 JSON。\n\n"
            f"聊天记录：\n{context}"
        )

    @classmethod
    def _build_closed_bucket_prompt(cls, context: str) -> str:
        return (
            "请基于下面同一时间段内的聊天记录，输出结构化时间段摘要。\n"
            "这是一段已经结束的聊天时间段，请输出稳定的最终总结。\n"
            "严格要求：\n"
            "1. 只输出正好 8 行，不要输出其他内容。\n"
            "2. 字段顺序必须固定如下：\n"
            "DISPLAY_SUMMARY:\nTOPICS:\nFACTS:\nDECISIONS:\nPENDING_ITEMS:\nTONE:\nPARTICIPANTS:\nKEYWORDS:\n"
            "3. 列表字段用 \" | \" 分隔；没有内容时写“无”。\n"
            "4. DISPLAY_SUMMARY 用自然语言简短总结这段聊天的最终结果。\n"
            "5. DECISIONS 强调已达成的决定；不要使用“当前”“正在”“还在继续”等进行时措辞。\n"
            "6. 不要复述原话，不要解释，不要输出 JSON。\n\n"
            f"聊天记录：\n{context}"
        )

    def _format_context(self, session: Session, messages: Sequence[ChatMessage]) -> list[str]:
        lines: list[str] = []
        total_chars = 0
        for message in reversed(list(messages or [])[-self.MAX_BUCKET_MESSAGES :]):
            content = self._message_context_text(message, max_chars=self.MAX_MESSAGE_CHARS)
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

    @classmethod
    def _message_context_text(cls, message: ChatMessage, *, max_chars: int) -> str:
        if message.message_type == MessageType.TEXT:
            return cls._normalize_scalar(message.content, max_chars=max_chars)
        if message.message_type == MessageType.IMAGE:
            return "[图片]"
        if message.message_type == MessageType.FILE:
            name = cls._attachment_name(message)
            file_text = extracted_file_context_text(message.extra, max_chars=max_chars)
            if file_text:
                return f"[文件内容: {name}: {file_text}]" if name else f"[文件内容: {file_text}]"
            return f"[文件: {name}]" if name else "[文件]"
        if message.message_type == MessageType.VIDEO:
            return "[视频]"
        if message.message_type == MessageType.VOICE:
            transcript = dict((message.extra or {}).get(VOICE_TRANSCRIPT_EXTRA_KEY) or {})
            if str(transcript.get("status") or "").strip() == "ready":
                text = cls._normalize_scalar(transcript.get("text"), max_chars=max_chars)
                if text:
                    return f"[语音转文字: {text}]"
            return "[语音]"
        if message.message_type == MessageType.SYSTEM:
            return "[系统消息]"
        return ""

    @staticmethod
    def _attachment_name(message: ChatMessage) -> str:
        extra = message.extra if isinstance(message.extra, dict) else {}
        media = extra.get("media") if isinstance(extra.get("media"), dict) else {}
        for key in ("name", "original_name", "file_name"):
            value = str(extra.get(key) or media.get(key) or "").strip()
            if value:
                return value
        return ""

    @classmethod
    def _normalize_list(cls, raw_value: str, *, limit: int, item_max_chars: int) -> tuple[str, ...]:
        value = str(raw_value or "").strip()
        if value in cls.EMPTY_MARKERS:
            return ()
        items: list[str] = []
        for raw_item in re.split(r"\s*\|\s*", value):
            normalized = cls._normalize_scalar(raw_item, max_chars=item_max_chars)
            if not normalized or normalized in cls.EMPTY_MARKERS or normalized in items:
                continue
            items.append(normalized)
            if len(items) >= max(1, int(limit or 1)):
                break
        return tuple(items)

    @staticmethod
    def _normalize_scalar(value: Any, *, max_chars: int) -> str:
        text = re.sub(r"\s+", " ", str(value or "").strip())
        if max_chars > 0 and len(text) > max_chars:
            text = text[:max_chars].rstrip()
        return text

    @staticmethod
    def _join_or_default(values: Sequence[str], *, default: str) -> str:
        cleaned = [str(value or "").strip() for value in list(values or []) if str(value or "").strip()]
        return "；".join(cleaned) if cleaned else default

    @staticmethod
    def _format_time_range(bucket_start_ts: int, bucket_end_ts: int) -> str:
        try:
            start_label = datetime.fromtimestamp(int(bucket_start_ts or 0)).strftime("%Y-%m-%d %H:%M")
            end_label = datetime.fromtimestamp(int(bucket_end_ts or bucket_start_ts or 0)).strftime("%H:%M")
            return f"{start_label}-{end_label}"
        except (OSError, ValueError):
            return f"{int(bucket_start_ts or 0)}-{int(bucket_end_ts or bucket_start_ts or 0)}"
