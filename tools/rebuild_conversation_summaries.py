from __future__ import annotations

import argparse
import asyncio
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from client.managers.ai_task_manager import AITaskManager
from client.managers.conversation_summary_manager import ConversationSummaryManager
from client.storage.database import Database


@dataclass
class RebuildStats:
    scanned: int = 0
    rebuilt: int = 0
    reindexed: int = 0
    skipped: int = 0
    failed: int = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rebuild conversation summaries and refresh memory/embedding indexes.",
    )
    parser.add_argument("--db-path", default="", help="SQLite database path. Defaults to app config storage.db_path.")
    parser.add_argument("--session-id", default="", help="Only rebuild one session.")
    parser.add_argument("--batch-size", type=int, default=50, help="Number of buckets to read per page.")
    parser.add_argument("--limit", type=int, default=0, help="Maximum buckets to scan. 0 means no limit.")
    parser.add_argument("--include-open", action="store_true", help="Also rebuild the currently open buckets.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--force", action="store_true", help="Regenerate every scanned bucket with the model.")
    mode.add_argument(
        "--reindex-only",
        action="store_true",
        help="Do not call the model; only rebuild memory/embedding indexes for current-schema ready buckets.",
    )
    return parser.parse_args()


def _needs_model_refresh(
    manager: ConversationSummaryManager,
    bucket: dict[str, Any],
    *,
    force: bool,
    reindex_only: bool,
) -> bool:
    if reindex_only:
        return False
    if force:
        return True
    status = str(bucket.get("summary_status") or "").strip().lower()
    if status in {"pending", "stale", "failed"}:
        return True
    return manager._summary_bucket_needs_regeneration(bucket)


async def _mark_bucket_stale(
    database: Database,
    manager: ConversationSummaryManager,
    session_id: str,
    bucket: dict[str, Any],
    stats: dict[str, Any],
) -> None:
    bucket_start_ts = int(bucket.get("bucket_start_ts") or 0)
    updated = dict(bucket)
    updated["summary_status"] = "stale"
    updated["error_code"] = ""
    updated["updated_at"] = int(time.time())
    updated["message_count"] = int(stats.get("message_count") or updated.get("message_count") or 0)
    last_message_id = str(stats.get("last_message_id") or "").strip()
    last_message_ts = int(stats.get("last_message_ts") or 0)
    if last_message_id:
        updated["last_message_id"] = last_message_id
    if last_message_ts > 0:
        updated["last_message_ts"] = last_message_ts
        updated["bucket_end_ts"] = max(int(updated.get("bucket_end_ts") or bucket_start_ts), last_message_ts)
    await database.upsert_conversation_summary_bucket(updated)
    await manager._delete_memory_item_for_bucket(session_id, bucket_start_ts)


async def _process_bucket(
    database: Database,
    manager: ConversationSummaryManager,
    bucket: dict[str, Any],
    *,
    force: bool,
    reindex_only: bool,
) -> str:
    session_id = str(bucket.get("session_id") or "").strip()
    bucket_start_ts = int(bucket.get("bucket_start_ts") or 0)
    if not session_id or bucket_start_ts <= 0:
        return "failed"

    session = await database.get_session(session_id)
    if session is None or session.is_ai_session or session.session_type == "ai":
        return "skipped"

    stats = await manager._bucket_message_stats(session_id, bucket)
    if _needs_model_refresh(manager, bucket, force=force, reindex_only=reindex_only):
        await _mark_bucket_stale(database, manager, session_id, bucket, stats)
        await manager._refresh_bucket_summary(session_id, bucket_start_ts)
        refreshed = await database.get_conversation_summary_bucket(
            session_id,
            bucket_start_ts,
            bucket_rule_version=int(bucket.get("bucket_rule_version") or 1),
        )
        if refreshed is None:
            return "failed"
        status = str(refreshed.get("summary_status") or "").strip().lower()
        if status == "ready" and not manager._summary_bucket_needs_regeneration(refreshed):
            return "rebuilt"
        return "failed"

    if await manager._memory_index_needs_rebuild(session_id, bucket):
        rebuilt = await manager._rebuild_memory_item_for_ready_bucket(session, bucket, stats=stats)
        return "reindexed" if rebuilt else "failed"

    return "skipped"


async def run(args: argparse.Namespace) -> RebuildStats:
    database = Database(db_path=args.db_path or None)
    task_manager = AITaskManager()
    manager = ConversationSummaryManager(db=database, task_manager=task_manager)
    stats = RebuildStats()
    await database.connect()
    try:
        batch_size = min(1000, max(1, int(args.batch_size or 1)))
        max_scan = max(0, int(args.limit or 0))
        last_seen_id = 0
        while True:
            if max_scan and stats.scanned >= max_scan:
                break
            page_limit = batch_size
            if max_scan:
                page_limit = min(page_limit, max_scan - stats.scanned)
            rows = await database.list_conversation_summary_buckets_for_rebuild(
                session_id=str(args.session_id or "").strip(),
                limit=page_limit,
                after_id=last_seen_id,
                include_open=bool(args.include_open),
            )
            if not rows:
                break
            last_seen_id = max(last_seen_id, *(int(row.get("id") or 0) for row in rows))
            for bucket in rows:
                stats.scanned += 1
                session_id = str(bucket.get("session_id") or "")
                bucket_start_ts = int(bucket.get("bucket_start_ts") or 0)
                try:
                    result = await _process_bucket(
                        database,
                        manager,
                        bucket,
                        force=bool(args.force),
                        reindex_only=bool(args.reindex_only),
                    )
                except Exception as exc:
                    stats.failed += 1
                    print(
                        f"failed session_id={session_id} bucket_start_ts={bucket_start_ts} error={type(exc).__name__}: {exc}",
                        flush=True,
                    )
                    continue

                if result == "rebuilt":
                    stats.rebuilt += 1
                elif result == "reindexed":
                    stats.reindexed += 1
                elif result == "skipped":
                    stats.skipped += 1
                else:
                    stats.failed += 1
                print(f"{result} session_id={session_id} bucket_start_ts={bucket_start_ts}", flush=True)
    finally:
        await manager.close()
        await task_manager.close()
        await database.close()
    return stats


async def main() -> None:
    args = parse_args()
    stats = await run(args)
    print(
        "done "
        f"scanned={stats.scanned} rebuilt={stats.rebuilt} reindexed={stats.reindexed} "
        f"skipped={stats.skipped} failed={stats.failed} "
        f"summary_schema_version={ConversationSummaryManager.SUMMARY_SCHEMA_VERSION} "
        f"memory_index_version={ConversationSummaryManager.MEMORY_INDEX_VERSION}",
        flush=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
