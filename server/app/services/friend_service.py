"""Friend service."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.user import User
from app.repositories.friend_repo import FriendRepository
from app.repositories.user_repo import UserRepository


class FriendService:
    def __init__(self, db: Session) -> None:
        self.friends = FriendRepository(db)
        self.users = UserRepository(db)

    def create_request(self, current_user: User, receiver_id: str | None, message: str | None = None) -> dict:
        if not receiver_id:
            raise AppError(ErrorCode.INVALID_REQUEST, "receiver_id is required", 422)
        receiver = self.users.get_by_id(receiver_id)
        if receiver is None:
            raise AppError(ErrorCode.USER_NOT_FOUND, "receiver not found", 404)
        request = self.friends.create_request(current_user.id, receiver_id, message)
        return self.serialize_request(request)

    def list_requests(self, current_user: User) -> list[dict]:
        return [self.serialize_request(item) for item in self.friends.list_requests_for_user(current_user.id)]

    def accept_request(self, current_user: User, request_id: str) -> dict:
        request = self.friends.get_request(request_id)
        if request is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "friend request not found", 404)
        if request.receiver_id != current_user.id:
            raise AppError(ErrorCode.FORBIDDEN, "cannot accept this request", 403)
        self.friends.update_request_status(request, "accepted")
        self.friends.create_friendship_pair(request.sender_id, request.receiver_id)
        return {"status": "accepted"}

    def reject_request(self, current_user: User, request_id: str) -> dict:
        request = self.friends.get_request(request_id)
        if request is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "friend request not found", 404)
        if request.receiver_id != current_user.id:
            raise AppError(ErrorCode.FORBIDDEN, "cannot reject this request", 403)
        self.friends.update_request_status(request, "rejected")
        return {"status": "rejected"}

    def list_friends(self, current_user: User) -> list[dict]:
        items = []
        for friendship in self.friends.list_friends(current_user.id):
            friend = self.users.get_by_id(friendship.friend_id)
            if friend is not None:
                items.append(
                    {
                        "id": friend.id,
                        "username": friend.username,
                        "nickname": friend.nickname,
                        "avatar": friend.avatar,
                    }
                )
        return items

    def remove_friend(self, current_user: User, friend_id: str) -> None:
        self.friends.remove_friendship(current_user.id, friend_id)

    def check_relationship(self, current_user: User, user_id: str) -> dict:
        return {"is_friend": self.friends.is_friend(current_user.id, user_id)}

    @staticmethod
    def serialize_request(request) -> dict:
        return {
            "id": request.id,
            "sender_id": request.sender_id,
            "receiver_id": request.receiver_id,
            "status": request.status,
            "message": request.message,
            "created_at": request.created_at.isoformat() if request.created_at else None,
        }
