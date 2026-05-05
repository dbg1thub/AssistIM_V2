"""Block routes."""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies.auth_dependency import get_current_user
from app.models.user import User
from app.schemas.block import BlockTargetCreate
from app.services.block_service import BlockService
from app.utils.response import success_response
from app.websocket.manager import connection_manager


router = APIRouter()
logger = logging.getLogger(__name__)


def _block_refresh_message(reason: str, payload: dict | None = None) -> dict:
    """Build one lightweight realtime block-refresh event."""
    data = dict(payload or {})
    data.setdefault("reason", reason)
    block_payload = dict(data.get("block") or {}) if isinstance(data.get("block"), dict) else {}
    user_payload = dict(data.get("user") or {}) if isinstance(data.get("user"), dict) else {}
    message_id = str(user_payload.get("id", "") or block_payload.get("blocked_user_id", "") or "")
    return {
        "type": "contact_refresh",
        "seq": 0,
        "msg_id": message_id,
        "timestamp": int(time.time()),
        "data": data,
    }


async def _broadcast_block_refresh(user_ids: list[str], payload: dict | None = None) -> None:
    """Broadcast one block-refresh event to the affected users."""
    deduped_user_ids = [user_id for index, user_id in enumerate(user_ids) if user_id and user_id not in user_ids[:index]]
    if not deduped_user_ids:
        return
    try:
        await connection_manager.send_json_to_users(
            deduped_user_ids,
            _block_refresh_message("session_lifecycle_changed", payload),
        )
    except Exception:
        logger.exception("Block refresh fanout failed after committed block mutation")


@router.get("")
def list_blocks(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return success_response(BlockService(db).list_blocks(current_user))


@router.get("/check/{user_id}")
def check_block(user_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return success_response(BlockService(db).check_blocking(current_user, user_id))


@router.post("")
async def block_user(
    payload: BlockTargetCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    result = BlockService(db).block_user(current_user, payload.target_user_id)
    await _broadcast_block_refresh([current_user.id, payload.target_user_id], result)
    return success_response(result)


@router.delete("/{user_id}")
async def unblock_user(user_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    result = BlockService(db).unblock_user(current_user, user_id)
    await _broadcast_block_refresh([current_user.id, user_id], result)
    return success_response(result)
