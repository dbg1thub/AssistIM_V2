"""Group routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies.auth_dependency import get_current_user
from app.models.user import User
from app.schemas.group import GroupCreate, GroupMemberAdd, GroupTransferOwner
from app.services.group_service import GroupService
from app.utils.response import success_response


router = APIRouter()


@router.get("")
def list_groups(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return success_response(GroupService(db).list_groups(current_user))


@router.post("", status_code=status.HTTP_201_CREATED)
def create_group(payload: GroupCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    member_ids = payload.member_ids or payload.members
    return success_response(GroupService(db).create_group(current_user, payload.name, member_ids))


@router.get("/{group_id}")
def get_group(group_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return success_response(GroupService(db).get_group(current_user, group_id))


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_group(group_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Response:
    GroupService(db).delete_group(current_user, group_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{group_id}/members")
def add_member(
    group_id: str,
    payload: GroupMemberAdd,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return success_response(GroupService(db).add_member(current_user, group_id, payload.user_id, payload.role))


@router.delete("/{group_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(group_id: str, user_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Response:
    GroupService(db).remove_member(current_user, group_id, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
