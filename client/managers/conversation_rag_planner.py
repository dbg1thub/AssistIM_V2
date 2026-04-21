from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence

from client.core import logging
from client.managers.ai_task_manager import AITaskManager, get_ai_task_manager


logger = logging.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ConversationRagParticipant:
    """One participant mention extracted by the semantic planner."""

    mention: str
    role: str = "contact"


@dataclass(frozen=True, slots=True)
class ConversationRagTimeRange:
    """One normalized memory-query time range."""

    type: str
    start_ts: int | None
    end_ts: int | None
    label: str = ""


@dataclass(frozen=True, slots=True)
class ConversationRagSemanticPlan:
    """Structured retrieval plan produced by the local model."""

    needs_memory: bool
    user_goal: str
    memory_query: str
    participants: tuple[ConversationRagParticipant, ...]
    participant_relation: str
    time_range: ConversationRagTimeRange
    answer_style: str = "summary"
    query_kind: str = "rag"

    @property
    def use_rag(self) -> bool:
        return self.needs_memory

    @property
    def rewritten_query(self) -> str:
        return self.memory_query or self.user_goal

    @property
    def start_ts(self) -> int | None:
        return self.time_range.start_ts

    @property
    def end_ts(self) -> int | None:
        return self.time_range.end_ts


class ConversationRagPlanner:
    """Use the local model to decide whether one AI chat turn needs local retrieval."""

    CONTEXT_MESSAGES = 4
    MAX_CONTEXT_CHARS = 600

    def __init__(self, task_manager: AITaskManager | None = None) -> None:
        self._task_manager = task_manager

    async def plan(
        self,
        query_text: str,
        *,
        previous_messages: Sequence[Any] | None = None,
    ) -> ConversationRagSemanticPlan | None:
        task_manager = self._task_manager or get_ai_task_manager()
        try:
            from client.services.ai_service import AIPrivacyScope, AIRequest, AITaskType
        except Exception:
            logger.exception("RAG planner request contracts are unavailable")
            return None

        now = datetime.now()
        history_lines: list[str] = []
        total_chars = 0
        for message in reversed(list(previous_messages or [])[-self.CONTEXT_MESSAGES :]):
            role = self._message_role(message)
            if role not in {"user", "assistant"}:
                continue
            content = " ".join(str(getattr(message, "content", "") or "").split())
            if not content:
                continue
            line = f"{role}: {content}"
            if total_chars + len(line) > self.MAX_CONTEXT_CHARS and history_lines:
                break
            history_lines.append(line)
            total_chars += len(line)
        history_lines.reverse()
        history_block = "\n".join(history_lines) if history_lines else "无"

        system_prompt = (
            "你是 AssistIM 的本地聊天检索规划器，只输出 JSON，不要解释，不要代码块。\n"
            "你的职责是判断当前用户问题是否需要检索本机聊天历史来帮助回答。\n"
            "如果不需要检索，输出 needs_memory=false。\n"
            "如果需要检索，输出一个结构化检索计划。\n"
            "不要规划执行动作，不要调用任何 action workflow。\n"
            "语义理解由你完成，系统只执行你给出的结构化检索信息。"
        )
        prompt = (
            f"当前本地时间：{now.strftime('%Y-%m-%d %H:%M:%S')}\n"
            "请输出一个 JSON 对象，字段为：\n"
            "needs_memory: boolean\n"
            "user_goal: string\n"
            "memory_query: string\n"
            "participants: [{mention:string, role:\"contact\"|\"group\"|\"unknown\"}]\n"
            "participant_relation: \"separate\"|\"together\"|\"compare\"|\"unknown\"\n"
            "time_range: {type:\"all_history\"|\"absolute\"|\"relative\"|\"unknown\", start_ts:number|null, end_ts:number|null, label:string}\n"
            "answer_style: \"summary\"|\"answer\"|\"compare\"\n"
            "query_kind: string\n\n"
            "规则：\n"
            "1. 如果当前问题是普通创作、闲聊、翻译、代码或常识问答，不需要本机聊天历史，则 needs_memory=false。\n"
            "2. 如果当前问题需要依赖本机历史聊天来回答，则 needs_memory=true。\n"
            "3. memory_query 是补全指代后的完整检索问题；如果当前句是追问，可结合历史消息理解。\n"
            "4. participants 只填写用户提到的联系人、群或明确对话对象；不要把时间、动作、问题词写进去。\n"
            "5. 多个联系人默认不是歧义；分别查询用 separate，一起出现的会话用 together，需要比较用 compare。\n"
            "6. 用户没说时间时，time_range.type=all_history，start_ts/end_ts 为 null；不要追问日期。\n"
            "7. 若用户说了明确时间范围，请输出绝对 Unix 秒级时间戳。\n"
            "8. 只有参与人关系会显著改变查询结果且你无法判断时，participant_relation 才输出 unknown。\n"
            "9. 不要编造不存在的联系人或时间范围，不要输出多余字段。\n\n"
            f"最近对话：\n{history_block}\n\n"
            f"当前用户问题：\n{query_text}"
        )
        request = AIRequest(
            task_id=f"ai-rag-plan-{int(time.time() * 1000)}",
            session_id="",
            task_type=AITaskType.CHAT,
            privacy_scope=AIPrivacyScope.GENERAL,
            must_be_local=True,
            stream=False,
            temperature=0.0,
            max_tokens=256,
            response_format={"type": "json_object"},
            system_prompt=system_prompt,
            messages=[{"role": "user", "content": prompt}],
            metadata={
                "source": "conversation_memory_rag_planner",
                "strict_json": True,
            },
        )
        try:
            snapshot = await task_manager.run_once(request)
        except Exception:
            logger.exception("RAG planner request failed")
            return None
        return self.coerce_plan(str(getattr(snapshot, "content", "") or ""), fallback_query=query_text)

    @staticmethod
    def coerce_plan(raw_result: Any, *, fallback_query: str) -> ConversationRagSemanticPlan | None:
        payload: dict[str, Any] | None = None
        if isinstance(raw_result, dict):
            payload = dict(raw_result)
        else:
            text = " ".join(str(raw_result or "").split())
            if not text:
                return None
            try:
                payload = json.loads(text)
            except Exception:
                return None
        if not isinstance(payload, dict):
            return None
        needs_memory = bool(payload.get("needs_memory"))
        user_goal = " ".join(str(payload.get("user_goal") or fallback_query).split())
        memory_query = " ".join(str(payload.get("memory_query") or user_goal or fallback_query).split())
        participants = ConversationRagPlanner._coerce_participants(payload.get("participants"))
        relation = ConversationRagPlanner._coerce_relation(payload.get("participant_relation"))
        time_range = ConversationRagPlanner._coerce_time_range(payload.get("time_range"))
        answer_style = str(payload.get("answer_style") or "summary").strip() or "summary"
        query_kind = str(payload.get("query_kind") or "rag").strip() or "rag"
        return ConversationRagSemanticPlan(
            needs_memory=needs_memory,
            user_goal=user_goal,
            memory_query=memory_query,
            participants=participants,
            participant_relation=relation,
            time_range=time_range,
            answer_style=answer_style,
            query_kind=query_kind,
        )

    @staticmethod
    def _coerce_participants(value: Any) -> tuple[ConversationRagParticipant, ...]:
        participants: list[ConversationRagParticipant] = []
        seen: set[str] = set()
        if not isinstance(value, list):
            return ()
        for item in value:
            if isinstance(item, dict):
                mention = " ".join(str(item.get("mention") or "").split())
                role = str(item.get("role") or "contact").strip().lower() or "contact"
            else:
                mention = " ".join(str(item or "").split())
                role = "contact"
            if not mention:
                continue
            key = mention.casefold()
            if key in seen:
                continue
            seen.add(key)
            if role not in {"contact", "group", "unknown"}:
                role = "unknown"
            participants.append(ConversationRagParticipant(mention=mention, role=role))
        return tuple(participants)

    @staticmethod
    def _coerce_relation(value: Any) -> str:
        relation = str(value or "separate").strip().lower() or "separate"
        return relation if relation in {"separate", "together", "compare", "unknown"} else "unknown"

    @staticmethod
    def _coerce_time_range(value: Any) -> ConversationRagTimeRange:
        if not isinstance(value, dict):
            return ConversationRagTimeRange(type="all_history", start_ts=None, end_ts=None, label="全部历史")
        range_type = str(value.get("type") or "all_history").strip().lower() or "all_history"
        if range_type not in {"all_history", "absolute", "relative", "unknown"}:
            range_type = "unknown"
        return ConversationRagTimeRange(
            type=range_type,
            start_ts=ConversationRagPlanner._coerce_optional_int(value.get("start_ts")),
            end_ts=ConversationRagPlanner._coerce_optional_int(value.get("end_ts")),
            label=" ".join(str(value.get("label") or "").split()),
        )

    @staticmethod
    def _coerce_optional_int(value: Any) -> int | None:
        if value in (None, "", "null"):
            return None
        try:
            normalized = int(float(value))
        except (TypeError, ValueError):
            return None
        return normalized if normalized > 0 else None

    @staticmethod
    def _message_role(message: Any) -> str:
        role = getattr(message, "role", "")
        value = getattr(role, "value", role)
        return str(value or "").strip().lower()
