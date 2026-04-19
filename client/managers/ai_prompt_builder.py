"""Prompt construction for chat AI assist features."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence

from client.core.message_translation import AI_TRANSLATION_NOOP_MARKER, language_name_for_code
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
class ReplySuggestionParseDiagnostics:
    """Lightweight parse diagnostics for one reply-suggestion model output."""

    raw_segment_count: int = 0
    cleaned_candidate_count: int = 0
    empty_count: int = 0
    duplicate_count: int = 0
    trimmed_count: int = 0
    anchor_repeat_count: int = 0
    stale_topic_count: int = 0
    output_preview: str = ""


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
    TRANSLATION_OUTPUT_CHARS = 1200
    REPLY_SUGGESTION_COUNT = 4
    REPLY_POSITIVE_COUNT = 2
    REPLY_RESERVED_COUNT = 2
    REPLY_HISTORY_SUMMARY_LIMIT = 1
    REPLY_SUGGESTION_TEMPERATURE = 1.0
    REPLY_SINGLE_TEMPERATURE = 0.35

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

    def build_message_translation_request(
        self,
        text: str,
        *,
        session: Session | None = None,
        message_id: str = "",
        target_language_code: str = "zh-CN",
        mode: str = "manual",
        task_id: str = "",
    ) -> AIRequest:
        """Build a local-only AI request for translating one chat message."""
        source = _normalize_text(text, max_chars=self.MAX_DRAFT_INPUT_CHARS)
        if not source:
            raise ValueError("message text is required")

        normalized_mode = str(mode or "manual").strip().lower() or "manual"
        target_language = language_name_for_code(target_language_code)
        auto_noop_instruction = (
            f"如果原文已经是{target_language}或无需翻译，只输出 {AI_TRANSLATION_NOOP_MARKER}。"
            if normalized_mode == "auto"
            else ""
        )
        system_prompt = (
            "你是 AssistIM 的消息翻译助手。\n"
            "使用标准聊天角色，不要输出思考过程，不要解释，只输出最终译文。\n"
            "保留原文的聊天语气、称呼和礼貌程度。"
        )
        prompt = (
            f"请把下面这条聊天消息翻译成{target_language}。\n"
            "只输出译文，不要添加引号。"
            f"{auto_noop_instruction}\n\n"
            f"原文：\n{source}"
        )

        return AIRequest(
            task_id=task_id,
            session_id=str(getattr(session, "session_id", "") or ""),
            task_type=AITaskType.TRANSLATE,
            privacy_scope=privacy_scope_for_session(session),
            must_be_local=True,
            stream=False,
            temperature=0.2,
            max_tokens=256,
            max_output_chars=self.TRANSLATION_OUTPUT_CHARS,
            system_prompt=system_prompt,
            messages=[{"role": "user", "content": prompt}],
            metadata={
                "mode": normalized_mode,
                "message_id": str(message_id or ""),
                "target_language": str(target_language_code or "").strip(),
                "source_chars": len(source),
                "prompt_chars": len(prompt),
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
        fallback_mode: bool = False,
    ) -> ReplySuggestionRequest:
        """Build an AI request for private reply suggestions."""
        anchor_group = latest_peer_text_message_group(messages, current_user_id=current_user_id)
        if not anchor_group:
            raise ValueError("reply suggestions require a latest peer text message")
        anchor = anchor_group[-1]

        context_limit = max(1, int(max_context_messages or self.MAX_CONTEXT_MESSAGES))
        direct_context_messages = list(messages[-context_limit:])
        direct_context = self._format_context(direct_context_messages)
        recent_context_count = sum(1 for message in direct_context_messages if message.message_type == MessageType.TEXT)
        grouped_anchor_lines = [
            _normalize_text(message.content, max_chars=self.MAX_MESSAGE_CHARS)
            for message in anchor_group
        ]
        grouped_anchor_lines = [line for line in grouped_anchor_lines if line]
        normalized_summary_context = summary_context or ReplySummaryContext()
        prompt_sections = ["当前待回复消息组："]
        prompt_sections[-1] += "\n" + "\n".join(
            f"{index + 1}. {line}" for index, line in enumerate(grouped_anchor_lines)
        )
        prompt_sections[-1] += f"\n最新一句：{_normalize_text(anchor.content, max_chars=self.MAX_MESSAGE_CHARS)}"
        if direct_context:
            prompt_sections.append(f"最近直接上下文：\n{direct_context}")
        open_bucket_summary = _normalize_text(
            normalized_summary_context.open_bucket_summary,
            max_chars=self.MAX_MESSAGE_CHARS,
        )
        background_lines: list[str] = []
        if open_bucket_summary:
            background_lines.append(f"- 当前时间段摘要：{open_bucket_summary}")
        history_lines = [
            _normalize_text(item, max_chars=self.MAX_MESSAGE_CHARS)
            for item in normalized_summary_context.recent_bucket_summaries
        ]
        history_lines = [item for item in history_lines if item]
        if history_lines:
            background_lines.extend(f"- 最近历史摘要：{item}" for item in history_lines)
        if background_lines:
            prompt_sections.append(
                "背景摘要（仅供参考，用来避免前后矛盾；不要优先复述已经确认过的话题）：\n"
                + "\n".join(background_lines)
            )
        privacy_scope = privacy_scope_for_session(session)
        must_be_local = session.uses_e2ee()
        if fallback_mode:
            system_prompt = (
                "你是 AssistIM 的私聊回复建议助手。\n"
                "使用标准聊天角色，不要输出思考过程，不要输出解释。\n"
                f"请生成 {self.REPLY_SUGGESTION_COUNT} 条我可以直接发送的简短回复。\n"
                "只输出最终答案，每行一条，不要编号，不要项目符号，不要引号，不要额外说明。\n"
                f"前 {self.REPLY_POSITIVE_COUNT} 条为积极推进型；"
                f"后 {self.REPLY_RESERVED_COUNT} 条为保守婉拒型，但要礼貌、自然。\n"
                "禁止直接复述或轻微改写对方最后一句。"
            )
            prompt = (
                "请根据下面的私聊场景生成回复：\n\n"
                + "\n\n".join(prompt_sections)
            )
        else:
            system_prompt = (
                "你是 AssistIM 的私聊回复建议助手。\n"
                "使用标准聊天角色，不要输出思考过程，不要输出解释，只输出最终答案。\n"
                f"请生成 {self.REPLY_SUGGESTION_COUNT} 条我可以直接发送的简短回复。\n"
                "每行一条，不要编号，不要项目符号，不要引号，不要空行。\n"
                f"前 {self.REPLY_POSITIVE_COUNT} 条为积极推进型；"
                f"后 {self.REPLY_RESERVED_COUNT} 条为保守婉拒型，但要礼貌、克制、自然。\n"
                "回复必须优先回应当前待回复消息，沿着最新话题往下推进；"
                "如果最新消息是问句，优先直接回答或补充新信息；"
                "不要回到已经确认过的旧问题；"
                "禁止直接复述或轻微改写对方最后一句。"
            )
            prompt = (
                "请根据下面的私聊场景生成回复：\n\n"
                + "\n\n".join(prompt_sections)
            )

        request = AIRequest(
            task_id=task_id,
            session_id=session.session_id,
            task_type=AITaskType.REPLY_SUGGESTION,
            privacy_scope=privacy_scope,
            must_be_local=must_be_local,
            stream=False,
            temperature=self.REPLY_SUGGESTION_TEMPERATURE,
            max_tokens=160,
            max_output_chars=self.REPLY_OUTPUT_CHARS,
            system_prompt=system_prompt,
            messages=[{"role": "user", "content": prompt}],
            metadata={
                "assist_action": AIAssistAction.REPLY_SUGGESTION.value,
                "reply_prompt_mode": "fallback" if fallback_mode else "standard",
                "anchor_message_id": anchor.message_id,
                "anchor_group_size": len(anchor_group),
                "session_type": session.session_type,
                "has_open_bucket_summary": bool(open_bucket_summary),
                "history_summary_count": len(history_lines),
                "has_summary": bool(background_lines),
                "recent_context_count": recent_context_count,
                "prompt_chars": len(prompt),
                "reply_template_family": "gemma4_standard_roles",
            },
        )
        return ReplySuggestionRequest(request=request, anchor_message=anchor)

    def build_single_reply_suggestion_request(
        self,
        session: Session,
        messages: Sequence[ChatMessage],
        *,
        task_id: str = "",
        current_user_id: str = "",
        max_context_messages: int | None = None,
        summary_context: ReplySummaryContext | None = None,
        target_style: str = "positive",
        existing_candidates: Sequence[str] | None = None,
        round_index: int = 0,
        fallback_mode: bool = False,
    ) -> ReplySuggestionRequest:
        """Build one single-candidate reply request for iterative suggestion generation."""
        anchor_group = latest_peer_text_message_group(messages, current_user_id=current_user_id)
        if not anchor_group:
            raise ValueError("reply suggestions require a latest peer text message")
        anchor = anchor_group[-1]

        context_limit = max(1, int(max_context_messages or self.MAX_CONTEXT_MESSAGES))
        direct_context_messages = list(messages[-context_limit:])
        direct_context = self._format_context(direct_context_messages)
        recent_context_count = sum(1 for message in direct_context_messages if message.message_type == MessageType.TEXT)
        grouped_anchor_lines = [
            _normalize_text(message.content, max_chars=self.MAX_MESSAGE_CHARS)
            for message in anchor_group
        ]
        grouped_anchor_lines = [line for line in grouped_anchor_lines if line]
        normalized_summary_context = summary_context or ReplySummaryContext()
        prompt_sections = ["当前待回复消息组："]
        prompt_sections[-1] += "\n" + "\n".join(
            f"{index + 1}. {line}" for index, line in enumerate(grouped_anchor_lines)
        )
        prompt_sections[-1] += f"\n最新一句：{_normalize_text(anchor.content, max_chars=self.MAX_MESSAGE_CHARS)}"
        if direct_context:
            prompt_sections.append(f"最近直接上下文：\n{direct_context}")
        open_bucket_summary = _normalize_text(
            normalized_summary_context.open_bucket_summary,
            max_chars=self.MAX_MESSAGE_CHARS,
        )
        background_lines: list[str] = []
        if open_bucket_summary:
            background_lines.append(f"- 当前时间段摘要：{open_bucket_summary}")
        history_lines = [
            _normalize_text(item, max_chars=self.MAX_MESSAGE_CHARS)
            for item in normalized_summary_context.recent_bucket_summaries
        ]
        history_lines = [item for item in history_lines if item]
        if history_lines:
            background_lines.extend(f"- 最近历史摘要：{item}" for item in history_lines)
        if background_lines:
            prompt_sections.append(
                "背景摘要（仅供参考，用来避免前后矛盾；不要优先复述已经确认过的话题）：\n"
                + "\n".join(background_lines)
            )

        normalized_existing = [
            _normalize_text(item, max_chars=self.MAX_MESSAGE_CHARS)
            for item in list(existing_candidates or [])
        ]
        normalized_existing = [item for item in normalized_existing if item]
        if normalized_existing:
            prompt_sections.append(
                "以下回复已经生成，禁止重复、近似改写或只换几个词：\n"
                + "\n".join(f"- {item}" for item in normalized_existing)
            )

        style_instruction = (
            "积极推进型：语气自然，直接回应并推进安排。"
            if str(target_style or "").strip().lower() == "positive"
            else "保守婉拒型：语气礼貌、克制，可以保留余地，但不要攻击或阴阳怪气。"
        )
        if fallback_mode:
            prompt = (
                "基于下面的私聊场景，只生成 1 条我可以直接发送的简短回复。\n"
                "只输出这一条回复正文；不要编号；不要解释；不要加引号；不要换行。\n"
                f"目标风格：{style_instruction}\n"
                "必须继续回应最新话题；如果最新消息是问句，优先直接回答或补充新信息；"
                "不要复述或轻微改写对方原话；如果拿不准，也要给出礼貌、简短、能推进对话的信息。\n\n"
                + "\n\n".join(prompt_sections)
            )
        else:
            prompt = (
                "基于下面的私聊场景，只生成 1 条我可以直接发送的简短回复。\n"
                "只输出这一条回复正文；不要编号；不要解释；不要加引号；不要换行。\n"
                f"目标风格：{style_instruction}\n"
                "回复目标：必须优先回应“当前待回复消息”，沿着最新话题往下推进；"
                "如果更早的大话题已经确认，不要回到那个问题上重复确认或原地兜圈；"
                "如果最新消息是在追问细节，回复也要继续细化，不要退回上一步；"
                "如果最新消息是问句，优先直接回答或补充新信息，不要重复对方的问句。\n"
                "约束：不要替我发送；不要直接复述或轻微改写对方刚说过的话；"
                "尽量给出能继续推进对话的信息。\n\n"
                + "\n\n".join(prompt_sections)
            )

        request = AIRequest(
            task_id=task_id,
            session_id=session.session_id,
            task_type=AITaskType.REPLY_SUGGESTION,
            privacy_scope=privacy_scope_for_session(session),
            must_be_local=session.uses_e2ee(),
            stream=False,
            temperature=self.REPLY_SINGLE_TEMPERATURE,
            max_tokens=96,
            max_output_chars=self.REPLY_OUTPUT_CHARS,
            messages=[{"role": "user", "content": prompt}],
            metadata={
                "assist_action": AIAssistAction.REPLY_SUGGESTION.value,
                "reply_prompt_mode": "single_fallback" if fallback_mode else "single",
                "reply_target_style": str(target_style or "").strip().lower() or "positive",
                "reply_round": max(0, int(round_index or 0)),
                "reply_existing_count": len(normalized_existing),
                "anchor_message_id": anchor.message_id,
                "anchor_group_size": len(anchor_group),
                "session_type": session.session_type,
                "has_open_bucket_summary": bool(open_bucket_summary),
                "history_summary_count": len(history_lines),
                "has_summary": bool(background_lines),
                "recent_context_count": recent_context_count,
                "prompt_chars": len(prompt),
            },
        )
        return ReplySuggestionRequest(request=request, anchor_message=anchor)

    def parse_reply_suggestions(
        self,
        output: str,
        *,
        limit: int = REPLY_SUGGESTION_COUNT,
        anchor_message: ChatMessage | None = None,
        recent_messages: Sequence[ChatMessage] | None = None,
    ) -> list[str]:
        """Parse one model response into short reply candidates."""
        suggestions, _diagnostics = self.parse_reply_suggestions_with_diagnostics(
            output,
            limit=limit,
            anchor_message=anchor_message,
            recent_messages=recent_messages,
        )
        return suggestions

    def parse_reply_suggestions_with_diagnostics(
        self,
        output: str,
        *,
        limit: int = REPLY_SUGGESTION_COUNT,
        anchor_message: ChatMessage | None = None,
        recent_messages: Sequence[ChatMessage] | None = None,
    ) -> tuple[list[str], ReplySuggestionParseDiagnostics]:
        """Parse reply candidates and return diagnostics for filter decisions."""
        json_candidates = _extract_reply_candidates_from_json(output)
        if json_candidates is not None:
            raw_lines = list(json_candidates)
        else:
            raw_lines = list(_split_reply_output_segments(output))

        suggestions: list[str] = []
        seen: set[str] = set()
        raw_segment_count = 0
        cleaned_candidate_count = 0
        empty_count = 0
        duplicate_count = 0
        trimmed_count = 0
        anchor_repeat_count = 0
        stale_topic_count = 0
        for raw_line in raw_lines:
            raw_segment_count += 1
            line = _strip_list_marker(raw_line)
            if not line:
                empty_count += 1
                continue
            if len(line) > 180:
                line = line[:180].rstrip()
                trimmed_count += 1
            key = line.casefold()
            if key in seen:
                duplicate_count += 1
                continue
            skip_reason = self._reply_skip_reason(
                line,
                anchor_message=anchor_message,
                recent_messages=recent_messages,
            )
            if skip_reason == "anchor_repeat":
                anchor_repeat_count += 1
                continue
            if skip_reason == "stale_topic":
                stale_topic_count += 1
                continue
            seen.add(key)
            suggestions.append(line)
            cleaned_candidate_count += 1
            if len(suggestions) >= max(1, int(limit or 1)):
                break
        diagnostics = ReplySuggestionParseDiagnostics(
            raw_segment_count=raw_segment_count,
            cleaned_candidate_count=cleaned_candidate_count,
            empty_count=empty_count,
            duplicate_count=duplicate_count,
            trimmed_count=trimmed_count,
            anchor_repeat_count=anchor_repeat_count,
            stale_topic_count=stale_topic_count,
            output_preview=_reply_output_preview(output),
        )
        return suggestions, diagnostics

    def parse_message_translation(self, output: str, *, mode: str = "manual") -> str:
        """Normalize one translation model output and apply the auto no-op marker."""
        text = _strip_code_fence(str(output or "").strip())
        text = text.strip().strip('"').strip("'").strip()
        if not text:
            return ""
        if str(mode or "").strip().lower() == "auto" and AI_TRANSLATION_NOOP_MARKER in text:
            return ""
        if text == AI_TRANSLATION_NOOP_MARKER:
            return ""
        return text

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

    def _reply_skip_reason(
        self,
        candidate: str,
        *,
        anchor_message: ChatMessage | None,
        recent_messages: Sequence[ChatMessage] | None,
    ) -> str:
        normalized_candidate = _normalize_compare_text(candidate)
        if not normalized_candidate:
            return "empty"

        anchor_text = _normalize_compare_text(getattr(anchor_message, "content", ""))
        if anchor_text:
            if normalized_candidate == anchor_text:
                return "anchor_repeat"
            anchor_similarity = _char_ngram_similarity(normalized_candidate, anchor_text)
            if anchor_similarity >= 0.88:
                return "anchor_repeat"
        else:
            anchor_similarity = 0.0

        if not recent_messages:
            return ""

        stale_similarity = 0.0
        for message in recent_messages:
            if message.message_type != MessageType.TEXT:
                continue
            if message.is_self or message.is_ai:
                continue
            if anchor_message is not None and message.message_id == anchor_message.message_id:
                continue
            message_text = _normalize_compare_text(message.content)
            if len(message_text) < 4:
                continue
            if normalized_candidate == message_text:
                return "stale_topic"
            shorter = min(len(normalized_candidate), len(message_text))
            if shorter >= 10 and (
                normalized_candidate in message_text or message_text in normalized_candidate
            ):
                return "stale_topic"
            stale_similarity = max(stale_similarity, _char_ngram_similarity(normalized_candidate, message_text))

        if stale_similarity >= 0.82 and stale_similarity > anchor_similarity + 0.12:
            return "stale_topic"
        return ""


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


def latest_peer_text_message_group(
    messages: Sequence[ChatMessage],
    *,
    current_user_id: str = "",
    max_group_messages: int = 4,
) -> tuple[ChatMessage, ...]:
    """Return the latest consecutive peer-text message burst used for one reply round."""
    normalized_current_user_id = str(current_user_id or "").strip()
    collected: list[ChatMessage] = []
    for message in reversed(list(messages or [])):
        if len(collected) >= max(1, int(max_group_messages or 1)):
            break
        if message.message_type != MessageType.TEXT:
            if collected:
                break
            continue
        if message.is_ai or message.is_self:
            if collected:
                break
            continue
        if normalized_current_user_id and str(message.sender_id or "").strip() == normalized_current_user_id:
            if collected:
                break
            continue
        if str(getattr(message.status, "value", message.status)) in {"failed", "recalled"}:
            if collected:
                break
            continue
        if not str(message.content or "").strip():
            if collected:
                break
            continue
        collected.append(message)
    return tuple(reversed(collected))


def _normalize_text(value: str, *, max_chars: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if max_chars > 0 and len(text) > max_chars:
        return text[:max_chars].rstrip()
    return text


def _extract_reply_candidates_from_json(output: str) -> list[str] | None:
    text = _strip_code_fence(str(output or "").strip())
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    replies = data.get("replies")
    if not isinstance(replies, list):
        return None
    candidates: list[str] = []
    for item in replies:
        if isinstance(item, str):
            candidates.append(item)
    return candidates


def _strip_list_marker(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^\s*(?:[-*•]+|\d+[.)、：:]|[（(]?\d+[）)])\s*", "", text)
    return text.strip().strip('"').strip("'").strip()


def _strip_code_fence(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^```(?:\w+)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _split_reply_output_segments(output: str) -> list[str]:
    text = _strip_code_fence(str(output or "").strip())
    if not text:
        return []
    lines: list[str] = []
    for raw_line in text.replace("\r\n", "\n").splitlines():
        line = str(raw_line or "").strip()
        if not line:
            continue
        numbered_parts = _split_inline_numbered_candidates(line)
        source_parts = numbered_parts if len(numbered_parts) > 1 else [line]
        for part in source_parts:
            delimiter_parts = [item.strip() for item in re.split(r"[;；|｜]+", part) if item.strip()]
            if len(delimiter_parts) > 1:
                lines.extend(delimiter_parts)
            else:
                lines.append(part)
    return lines


def _split_inline_numbered_candidates(line: str) -> list[str]:
    pattern = re.compile(r"(?:^|(?<=\s)|(?<=[。！？!?]))(?P<marker>\d+[.)、：:]|[（(]?\d+[）)])\s*")
    matches = list(pattern.finditer(str(line or "")))
    if len(matches) <= 1:
        return []
    parts: list[str] = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(line)
        part = str(line[start:end] or "").strip()
        if part:
            parts.append(part)
    return parts


def _reply_output_preview(output: str, *, max_chars: int = 120) -> str:
    text = re.sub(r"\s+", " ", _strip_code_fence(str(output or "")).strip())
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."


def _normalize_compare_text(value: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[^\w\u4e00-\u9fff]", "", text)
    return text


def _char_ngram_similarity(left: str, right: str, *, n: int = 2) -> float:
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    if len(left) < n or len(right) < n:
        return 1.0 if left == right else 0.0
    left_ngrams = {left[index : index + n] for index in range(len(left) - n + 1)}
    right_ngrams = {right[index : index + n] for index in range(len(right) - n + 1)}
    if not left_ngrams or not right_ngrams:
        return 0.0
    overlap = len(left_ngrams & right_ngrams)
    base = min(len(left_ngrams), len(right_ngrams))
    return overlap / base if base > 0 else 0.0
