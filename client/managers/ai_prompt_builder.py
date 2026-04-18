"""Prompt construction for chat AI assist features."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence

from client.models.message import ChatMessage, MessageType, Session
from client.services.ai_service import AIPrivacyScope, AIRequest, AITaskType


class AIAssistAction(Enum):
    """Supported chat-composer AI assist actions."""

    POLISH = "polish"
    SHORTEN = "shorten"
    TRANSLATE = "translate"
    REWRITE = "rewrite"
    REPLY_SUGGESTION = "reply_suggestion"


@dataclass(frozen=True, slots=True)
class ReplySuggestionRequest:
    """AI request plus the latest peer message it is anchored to."""

    request: AIRequest
    anchor_message: ChatMessage


@dataclass(frozen=True, slots=True)
class ReplySummaryContext:
    """Optional summary context prepended to reply-suggestion prompts."""

    open_bucket_summary: str = ""
    recent_bucket_summaries: tuple[str, ...] = field(default_factory=tuple)


class AIPromptBuilder:
    """Build bounded prompts and parse model output for AI assist managers."""

    MAX_DRAFT_INPUT_CHARS = 2000
    MAX_MESSAGE_CHARS = 700
    MAX_CONTEXT_MESSAGES = 8
    DRAFT_OUTPUT_CHARS = 2200
    REPLY_OUTPUT_CHARS = 900
    REPLY_SUGGESTION_COUNT = 4
    REPLY_POSITIVE_COUNT = 2
    REPLY_RESERVED_COUNT = 2

    _DRAFT_TASK_TYPES = {
        AIAssistAction.POLISH: AITaskType.INPUT_POLISH,
        AIAssistAction.SHORTEN: AITaskType.INPUT_SHORTEN,
        AIAssistAction.TRANSLATE: AITaskType.TRANSLATE,
        AIAssistAction.REWRITE: AITaskType.INPUT_REWRITE,
    }

    def build_draft_request(
        self,
        action: AIAssistAction | str,
        text: str,
        *,
        session: Session | None = None,
        task_id: str = "",
        target_language: str = "中文",
    ) -> AIRequest:
        """Build an AI request for editing a draft that has not been sent."""
        normalized_action = coerce_assist_action(action)
        if normalized_action == AIAssistAction.REPLY_SUGGESTION:
            raise ValueError("reply suggestion is not a draft assist action")

        draft = _normalize_text(text, max_chars=self.MAX_DRAFT_INPUT_CHARS)
        if not draft:
            raise ValueError("draft text is required")

        task_type = self._DRAFT_TASK_TYPES[normalized_action]
        privacy_scope = privacy_scope_for_session(session)
        must_be_local = bool(session and session.uses_e2ee())
        instruction = self._draft_instruction(normalized_action, target_language=target_language)
        prompt = (
            f"{instruction}\n\n"
            "约束：只输出改写后的正文，不要解释，不要添加引号。\n\n"
            f"原文：\n{draft}"
        )

        return AIRequest(
            task_id=task_id,
            session_id=str(getattr(session, "session_id", "") or ""),
            task_type=task_type,
            privacy_scope=privacy_scope,
            must_be_local=must_be_local,
            stream=False,
            temperature=0.3,
            max_tokens=768,
            max_output_chars=self.DRAFT_OUTPUT_CHARS,
            messages=[{"role": "user", "content": prompt}],
            metadata={
                "assist_action": normalized_action.value,
                "session_type": str(getattr(session, "session_type", "") or ""),
            },
        )

    def build_reply_suggestion_request(
        self,
        session: Session,
        messages: Sequence[ChatMessage],
        *,
        task_id: str = "",
        current_user_id: str = "",
        max_context_messages: int | None = None,
        summary_context: ReplySummaryContext | None = None,
    ) -> ReplySuggestionRequest:
        """Build an AI request for private reply suggestions."""
        anchor = latest_peer_text_message(messages, current_user_id=current_user_id)
        if anchor is None:
            raise ValueError("reply suggestions require a latest peer text message")

        context_limit = max(1, int(max_context_messages or self.MAX_CONTEXT_MESSAGES))
        context = self._format_context(messages[-context_limit:])
        normalized_summary_context = summary_context or ReplySummaryContext()
        prompt_sections = [f"聊天上下文：\n{context}"]
        open_bucket_summary = _normalize_text(
            normalized_summary_context.open_bucket_summary,
            max_chars=self.MAX_MESSAGE_CHARS,
        )
        if open_bucket_summary:
            prompt_sections.append(f"当前时间段摘要：\n- {open_bucket_summary}")
        history_lines = [
            _normalize_text(item, max_chars=self.MAX_MESSAGE_CHARS)
            for item in normalized_summary_context.recent_bucket_summaries
        ]
        history_lines = [item for item in history_lines if item]
        if history_lines:
            prompt_sections.append("最近历史摘要：\n" + "\n".join(f"- {item}" for item in history_lines))
        privacy_scope = privacy_scope_for_session(session)
        must_be_local = session.uses_e2ee()
        prompt = (
            f"基于下面的私聊上下文，生成 {self.REPLY_SUGGESTION_COUNT} 条我可以直接发送的简短回复。\n"
            f"风格要求：前 {self.REPLY_POSITIVE_COUNT} 条为积极推进型；"
            f"后 {self.REPLY_RESERVED_COUNT} 条为保守婉拒型（偏消极，但保持礼貌、克制，不要攻击或辱骂）。\n"
            "约束：每行一条；不要编号；不要解释；不要替我发送。\n\n"
            + "\n\n".join(prompt_sections)
        )

        request = AIRequest(
            task_id=task_id,
            session_id=session.session_id,
            task_type=AITaskType.REPLY_SUGGESTION,
            privacy_scope=privacy_scope,
            must_be_local=must_be_local,
            stream=False,
            temperature=0.5,
            max_tokens=320,
            max_output_chars=self.REPLY_OUTPUT_CHARS,
            messages=[{"role": "user", "content": prompt}],
            metadata={
                "assist_action": AIAssistAction.REPLY_SUGGESTION.value,
                "anchor_message_id": anchor.message_id,
                "session_type": session.session_type,
                "has_open_bucket_summary": bool(open_bucket_summary),
                "history_summary_count": len(history_lines),
            },
        )
        return ReplySuggestionRequest(request=request, anchor_message=anchor)

    def parse_reply_suggestions(self, output: str, *, limit: int = REPLY_SUGGESTION_COUNT) -> list[str]:
        """Parse one model response into short reply candidates."""
        suggestions: list[str] = []
        seen: set[str] = set()
        for raw_line in str(output or "").splitlines():
            line = _strip_list_marker(raw_line)
            if not line:
                continue
            if len(line) > 180:
                line = line[:180].rstrip()
            key = line.casefold()
            if key in seen:
                continue
            seen.add(key)
            suggestions.append(line)
            if len(suggestions) >= max(1, int(limit or 1)):
                break
        return suggestions

    def _draft_instruction(self, action: AIAssistAction, *, target_language: str) -> str:
        if action == AIAssistAction.POLISH:
            return "润色下面这段聊天草稿，让语气自然、清晰、礼貌，并保留原意。"
        if action == AIAssistAction.SHORTEN:
            return "压缩下面这段聊天草稿，让它更简短直接，并保留关键信息。"
        if action == AIAssistAction.TRANSLATE:
            language = str(target_language or "中文").strip() or "中文"
            return f"把下面这段聊天草稿翻译成{language}，保留自然聊天语气。"
        return "改写下面这段聊天草稿，让表达更自然，并保留原意。"

    def _format_context(self, messages: Sequence[ChatMessage]) -> str:
        lines: list[str] = []
        for message in messages:
            if message.message_type != MessageType.TEXT:
                continue
            content = _normalize_text(message.content, max_chars=self.MAX_MESSAGE_CHARS)
            if not content:
                continue
            role = "我" if message.is_self else "对方"
            lines.append(f"{role}: {content}")
        return "\n".join(lines)


def coerce_assist_action(action: AIAssistAction | str) -> AIAssistAction:
    """Return a supported AI assist action."""
    if isinstance(action, AIAssistAction):
        return action
    normalized = str(action or "").strip()
    for candidate in AIAssistAction:
        if normalized in {candidate.value, candidate.name}:
            return candidate
    raise ValueError(f"unsupported AI assist action: {normalized}")


def privacy_scope_for_session(session: Session | None) -> AIPrivacyScope:
    """Map session privacy into AI request scope."""
    if session is None:
        return AIPrivacyScope.GENERAL
    if session.uses_e2ee():
        return AIPrivacyScope.E2EE_PLAINTEXT
    if session.is_ai_session or session.session_type == "ai":
        return AIPrivacyScope.SERVER_VISIBLE_AI
    if session.session_type in {"direct", "private"}:
        return AIPrivacyScope.DIRECT_CONTEXT
    return AIPrivacyScope.GENERAL


def latest_peer_text_message(
    messages: Sequence[ChatMessage],
    *,
    current_user_id: str = "",
) -> ChatMessage | None:
    """Return the latest text message from the peer that can anchor suggestions."""
    normalized_current_user_id = str(current_user_id or "").strip()
    for message in reversed(list(messages or [])):
        if message.message_type != MessageType.TEXT:
            continue
        if message.is_ai or message.is_self:
            continue
        if normalized_current_user_id and str(message.sender_id or "").strip() == normalized_current_user_id:
            continue
        if str(getattr(message.status, "value", message.status)) in {"failed", "recalled"}:
            continue
        if not str(message.content or "").strip():
            continue
        return message
    return None


def _normalize_text(value: str, *, max_chars: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if max_chars > 0 and len(text) > max_chars:
        return text[:max_chars].rstrip()
    return text


def _strip_list_marker(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^\s*(?:[-*•]+|\d+[.)、：:]|[（(]?\d+[）)])\s*", "", text)
    return text.strip().strip('"').strip("'").strip()
