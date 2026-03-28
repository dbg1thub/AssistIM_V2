"""Friend service."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.user import FriendRequest, User
from app.repositories.friend_repo import FriendRepository
from app.repositories.user_repo import UserRepository


class FriendService:
    REQUEST_EXPIRE_AFTER = timedelta(days=7)

    def __init__(self, db: Session) -> None:
        self.friends = FriendRepository(db)
        self.users = UserRepository(db)

    def create_request(self, current_user: User, receiver_id: str | None, message: str | None = None) -> dict:
        if not receiver_id:
            raise AppError(ErrorCode.INVALID_REQUEST, "receiver_id is required", 422)
        if receiver_id == current_user.id:
            raise AppError(ErrorCode.INVALID_REQUEST, "cannot add yourself as a friend", 422)

        receiver = self.users.get_by_id(receiver_id)
        if receiver is None:
            raise AppError(ErrorCode.USER_NOT_FOUND, "receiver not found", 404)
        if self.friends.is_friend(current_user.id, receiver_id):
            raise AppError(ErrorCode.INVALID_REQUEST, "users are already friends", 409)

        pair_requests = self._list_pair_requests(current_user.id, receiver_id)
        outgoing_pending = self._find_pending_request(pair_requests, current_user.id, receiver_id)
        if outgoing_pending is not None:
            return self.serialize_request(outgoing_pending)

        incoming_pending = self._find_pending_request(pair_requests, receiver_id, current_user.id)
        if incoming_pending is not None:
            accepted_request = self.friends.update_request_status(incoming_pending, "accepted")
            self.friends.create_friendship_pair(accepted_request.sender_id, accepted_request.receiver_id)
            return self.serialize_request(accepted_request)

        request = self.friends.create_request(current_user.id, receiver_id, message)
        return self.serialize_request(request)

    def list_requests(self, current_user: User) -> list[dict]:
        requests = self.friends.list_requests_for_user(current_user.id)
        return [self.serialize_request(self._expire_if_needed(item)) for item in requests]

    def accept_request(self, current_user: User, request_id: str) -> dict:
        request = self.friends.get_request(request_id)
        if request is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "friend request not found", 404)
        if request.receiver_id != current_user.id:
            raise AppError(ErrorCode.FORBIDDEN, "cannot accept this request", 403)
        request = self._expire_if_needed(request)
        if request.status != "pending":
            raise AppError(ErrorCode.INVALID_REQUEST, f"friend request {request.status}", 409)
        request = self.friends.update_request_status(request, "accepted")
        self.friends.create_friendship_pair(request.sender_id, request.receiver_id)
        return self.serialize_request(request)

    def reject_request(self, current_user: User, request_id: str) -> dict:
        request = self.friends.get_request(request_id)
        if request is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "friend request not found", 404)
        if request.receiver_id != current_user.id:
            raise AppError(ErrorCode.FORBIDDEN, "cannot reject this request", 403)
        request = self._expire_if_needed(request)
        if request.status != "pending":
            raise AppError(ErrorCode.INVALID_REQUEST, f"friend request {request.status}", 409)
        request = self.friends.update_request_status(request, "rejected")
        return self.serialize_request(request)

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
                        "email": friend.email,
                        "phone": friend.phone,
                        "birthday": friend.birthday.isoformat() if friend.birthday else None,
                        "region": friend.region,
                        "signature": friend.signature,
                        "gender": friend.gender,
                        "status": friend.status,
                    }
                )
        return items

    def remove_friend(self, current_user: User, friend_id: str) -> None:
        self.friends.remove_friendship(current_user.id, friend_id)

    def check_relationship(self, current_user: User, user_id: str) -> dict:
        return {"is_friend": self.friends.is_friend(current_user.id, user_id)}

    def _list_pair_requests(self, user_id: str, other_user_id: str) -> list[FriendRequest]:
        return [self._expire_if_needed(item) for item in self.friends.list_requests_between(user_id, other_user_id)]

    @staticmethod
    def _find_pending_request(requests: list[FriendRequest], sender_id: str, receiver_id: str) -> FriendRequest | None:
        for request in requests:
            if request.sender_id == sender_id and request.receiver_id == receiver_id and request.status == "pending":
                return request
        return None

    def _expire_if_needed(self, request: FriendRequest) -> FriendRequest:
        if request.status != "pending" or request.created_at is None:
            return request

        created_at = request.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        if datetime.now(timezone.utc) - created_at >= self.REQUEST_EXPIRE_AFTER:
            return self.friends.update_request_status(request, "expired")
        return request

    @staticmethod
    def serialize_request(request: FriendRequest) -> dict:
        return {
            "request_id": request.id,
            "sender_id": request.sender_id,
            "receiver_id": request.receiver_id,
            "status": request.status,
            "message": request.message,
            "created_at": request.created_at.isoformat() if request.created_at else None,
        }
