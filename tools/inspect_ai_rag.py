from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from client.managers.ai_task_manager import AITaskManager
from client.managers.conversation_memory_manager import ConversationMemoryManager
from client.managers.conversation_rag_planner import ConversationRagPlanner
from client.managers.conversation_summary_manager import ConversationSummaryManager
from client.storage.database import Database


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect AI-assistant RAG planning, contact resolution, ANN retrieval, and memory context.",
    )
    parser.add_argument("query", nargs="*", help="User question to inspect.")
    parser.add_argument("--db-path", default="", help="SQLite database path. Defaults to app config storage.db_path.")
    parser.add_argument("--session-id", default="", help="Only scope index health counters to one session.")
    parser.add_argument("--top-k", type=int, default=8, help="Number of ranked candidates to show.")
    parser.add_argument(
        "--history",
        action="append",
        default=[],
        help="Optional previous assistant-thread message, format role:content. Can be repeated.",
    )
    return parser.parse_args()


def _history_messages(raw_values: list[str]) -> list[Any]:
    messages: list[Any] = []
    for raw in list(raw_values or []):
        text = str(raw or "").strip()
        if not text:
            continue
        if ":" in text:
            role, content = text.split(":", 1)
        elif "：" in text:
            role, content = text.split("：", 1)
        else:
            role, content = "user", text
        normalized_role = str(role or "").strip().lower()
        if normalized_role not in {"user", "assistant"}:
            normalized_role = "user"
        content = str(content or "").strip()
        if content:
            messages.append(SimpleNamespace(role=normalized_role, content=content))
    return messages


def _query_text(parts: list[str]) -> str:
    return " ".join(str(part or "").strip() for part in list(parts or []) if str(part or "").strip()).strip()


async def run(args: argparse.Namespace) -> dict[str, Any]:
    query = _query_text(args.query)
    if not query:
        raise SystemExit("query is required")

    database = Database(db_path=args.db_path or None)
    task_manager = AITaskManager()
    planner = ConversationRagPlanner(task_manager=task_manager)
    manager = ConversationMemoryManager(db=database, semantic_planner=planner)
    await database.connect()
    try:
        stats = await database.get_conversation_rag_index_stats(
            session_id=str(args.session_id or "").strip(),
            summary_schema_version=ConversationSummaryManager.SUMMARY_SCHEMA_VERSION,
            memory_index_version=ConversationSummaryManager.MEMORY_INDEX_VERSION,
        )
        debug: dict[str, Any]
        try:
            debug = await manager.inspect_rag_retrieval_for_ai_chat(
                query,
                previous_messages=_history_messages(args.history),
                top_k=max(1, int(args.top_k or 8)),
            )
        except Exception as exc:
            debug = {
                "query_text": query,
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        return {
            "query": query,
            "index_stats": stats,
            "rag": debug,
        }
    finally:
        await task_manager.close()
        await database.close()


async def main() -> None:
    payload = await run(parse_args())
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
