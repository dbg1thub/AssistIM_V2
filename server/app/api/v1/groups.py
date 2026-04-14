"""Group routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies.auth_dependency import get_current_user
from app.models.user import User
from app.schemas.group import (
    GroupCreate,
    GroupMemberAdd,
    GroupMemberRoleUpdate,
    GroupProfileUpdate,
    GroupSelfProfileUpdate,
    GroupTransferOwner,
)
from app.services.group_service import GroupService
from app.services.message_service import MessageService
from app.utils.response import success_response
from app.websocket.manager import connection_manager
from app.websocket.payloads import ws_message


router = APIRouter()
logger = logging.getLogger(__name__)


async def _broadcast_group_announcement_message(
    db: Session,
    announcement_message_id: str,
    participant_ids: list[str],
) -> None:
    normalized_message_id = str(announcement_message_id or "").strip()
    normalized_participant_ids = [
        value
        for value in dict.fromkeys(str(raw_id or "").strip() for raw_id in participant_ids)
        if value
    ]
    if not normalized_message_id or not normalized_participant_ids:
        return

    service = MessageService(db)
    message = service.messages.get_by_id(normalized_message_id)
    if message is None:
        return

    for viewer_id in normalized_participant_ids:
        payload = service.serialize_message(message, viewer_id)
        try:
            await connection_manager.send_json_to_users(
                [viewer_id],
                ws_message("chat_message", payload, msg_id=str(payload.get("message_id", "") or "")),
            )
        except Exception:
            logger.exception("Group announcement fanout failed after committed group profile mutation")


async def _broadcast_group_profile_update(db: Session, group_id: str, *, actor_user_id: str) -> None:
    service = GroupService(db)
    event_item = service.record_group_profile_update_event(group_id, actor_user_id=actor_user_id)
    if not event_item:
        return

    payload = dict(event_item.get("payload") or {})
    participant_ids = [
        value
        for value in dict.fromkeys(str(raw_id or "").strip() for raw_id in event_item.get("participant_ids", []))
        if value
    ]
    if not participant_ids:
        return

    session_id = str(payload.get("session_id", "") or "")
    event_seq = int(payload.get("event_seq", 0) or 0)
    try:
        await connection_manager.send_json_to_users(
            participant_ids,
            ws_message(
                "group_profile_update",
                payload,
                msg_id=f"group-profile:{session_id}:{event_seq}",
                seq=event_seq,
            ),
        )
    except Exception:
        logger.exception("Group profile fanout failed after committed group profile mutation")


async def _broadcast_group_self_profile_update(db: Session, current_user: User, group_id: str) -> None:
    service = GroupService(db)
    payload = service.record_group_self_profile_update_event(current_user, group_id)
    session_id = str(payload.get("session_id", "") or "")
    event_seq = int(payload.get("event_seq", 0) or 0)
    try:
        await connection_manager.send_json_to_users(
            [current_user.id],
            ws_message(
                "group_self_profile_update",
                payload,
                msg_id=f"group-self-profile:{session_id}:{event_seq}",
                seq=event_seq,
            ),
        )
    except Exception:
        logger.exception("Group self-profile fanout failed after committed group self-profile mutation")


@router.get("")
def list_groups(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return success_response(GroupService(db).list_groups(current_user))


@router.post("", status_code=status.HTTP_201_CREATED)
def create_group(payload: GroupCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    member_ids = payload.requested_member_ids
    return success_response(GroupService(db).create_group(current_user, payload.name, member_ids, payload.encryption_mode))


@router.get("/{group_id}")
def get_group(group_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return success_response(GroupService(db).get_group(current_user, group_id))


@router.patch("/{group_id}")
async def update_group_profile(
    group_id: str,
    payload: GroupProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    result = GroupService(db).update_group_profile(current_user, group_id, payload.name, payload.announcement)
    if result.announcement_message_id:
        await _broadcast_group_announcement_message(db, result.announcement_message_id, result.participant_ids)
    await _broadcast_group_profile_update(db, group_id, actor_user_id=current_user.id)
    return success_response(
        GroupService.group_mutation_result(
            "profile_updated",
            result.group,
            announcement={
                "message_id": result.announcement_message_id or None,
                "created": bool(result.announcement_message_id),
                "participant_count": len(result.participant_ids),
            },
        )
    )


@router.patch("/{group_id}/me")
async def update_my_group_profile(
    group_id: str,
    payload: GroupSelfProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    result = GroupService(db).update_my_group_profile(current_user, group_id, payload.note, payload.my_group_nickname)
    if result.changed:
        await _broadcast_group_self_profile_update(db, current_user, group_id)
    return success_response({**result.profile, "changed": result.changed})


@router.delete("/{group_id}")
def delete_group(group_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return success_response(GroupService(db).delete_group(current_user, group_id))


@router.post("/{group_id}/members")
def add_member(
    group_id: str,
    payload: GroupMemberAdd,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return success_response(GroupService(db).add_member(current_user, group_id, payload.user_id, payload.role))


@router.delete("/{group_id}/members/{user_id}")
def remove_member(group_id: str, user_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return success_response(GroupService(db).remove_member(current_user, group_id, user_id))


@router.patch("/{group_id}/members/{user_id}/role")
def update_member_role(
    group_id: str,
    user_id: str,
    payload: GroupMemberRoleUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return success_response(GroupService(db).update_member_role(current_user, group_id, user_id, payload.role))


@router.post("/{group_id}/leave")
def leave_group(group_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return success_response(GroupService(db).leave_group(current_user, group_id))


@router.post("/{group_id}/transfer")
def transfer_group(
    group_id: str,
    payload: GroupTransferOwner,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return success_response(GroupService(db).transfer_ownership(current_user, group_id, payload.new_owner_id))
