"""Friend service."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.user import FriendRequest, User
from app.repositories.friend_repo import FriendRepository
from app.repositories.user_repo import UserRepository
from app.services.user_service import UserService


class FriendService:
    REQUEST_EXPIRE_AFTER = timedelta(days=7)

    def __init__(self, db: Session) -> None:
        self.db = db
        self.friends = FriendRepository(db)
        self.users = UserRepository(db)
        self.user_payloads = UserService(db)

    def create_request(self, current_user: User, target_user_id: str | None, message: str | None = None) -> dict:
        receiver_id = str(target_user_id or "").strip()
        if not receiver_id:
            raise AppError(ErrorCode.INVALID_REQUEST, "target_user_id is required", 422)
        if receiver_id == current_user.id:
            raise AppError(ErrorCode.INVALID_REQUEST, "cannot add yourself as a friend", 422)

        receiver = self.users.get_by_id(receiver_id)
        if receiver is None:
            raise AppError(ErrorCode.USER_NOT_FOUND, "receiver not found", 404)
        if self.friends.is_friend(current_user.id, receiver_id):
            raise AppError(ErrorCode.INVALID_REQUEST, "users are already friends", 409)

        pair_requests = self.friends.list_requests_between(current_user.id, receiver_id)
        self._persist_expired_requests(pair_requests)
        users_by_id = self.users.list_users_by_ids([current_user.id, receiver_id])

        outgoing_pending = self._find_pending_request(pair_requests, current_user.id, receiver_id)
        if outgoing_pending is not None:
            request_payload = self._serialize_request(outgoing_pending, users_by_id)
            return self._serialize_relationship_mutation(
                action="request_reused",
                changed=False,
                created=False,
                user=receiver,
                friendship_user_id=receiver_id,
                is_friend=False,
                request=request_payload,
            )

        incoming_pending = self._find_pending_request(pair_requests, receiver_id, current_user.id)
        if incoming_pending is not None:
            accepted_request = self.friends.update_request_status(incoming_pending, "accepted", commit=False)
            self.friends.create_friendship_pair(accepted_request.sender_id, accepted_request.receiver_id, commit=False)
            self.db.commit()
            self.db.refresh(accepted_request)
            request_payload = self._serialize_request(accepted_request, users_by_id)
            return self._serialize_relationship_mutation(
                action="friendship_created",
                changed=True,
                created=False,
                user=receiver,
                friendship_user_id=receiver_id,
                is_friend=True,
                request=request_payload,
            )

        request = self.friends.create_request(current_user.id, receiver_id, message, commit=False)
        self.db.commit()
        self.db.refresh(request)
        request_payload = self._serialize_request(request, users_by_id)
        return self._serialize_relationship_mutation(
            action="request_created",
            changed=True,
            created=True,
            user=receiver,
            friendship_user_id=receiver_id,
            is_friend=False,
            request=request_payload,
        )

    def list_requests(self, current_user: User) -> list[dict]:
        requests = self.friends.list_requests_for_user(current_user.id)
        users_by_id = self.users.list_users_by_ids(
            [
                user_id
                for request in requests
                for user_id in (request.sender_id, request.receiver_id)
                if str(user_id or "").strip()
            ]
        )
        return [self._serialize_request(item, users_by_id) for item in requests]

    def accept_request(self, current_user: User, request_id: str) -> dict:
        request = self.friends.get_request(request_id)
        if request is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "friend request not found", 404)
        if request.receiver_id != current_user.id:
            raise AppError(ErrorCode.FORBIDDEN, "cannot accept this request", 403)
        self._raise_if_request_not_pending(request)
        request = self.friends.update_request_status(request, "accepted", commit=False)
        self.friends.create_friendship_pair(request.sender_id, request.receiver_id, commit=False)
        self.db.commit()
        self.db.refresh(request)
        users_by_id = self.users.list_users_by_ids([request.sender_id, request.receiver_id])
        request_payload = self._serialize_request(request, users_by_id)
        sender = users_by_id.get(str(request.sender_id or ""))
        return self._serialize_relationship_mutation(
            action="friendship_created",
            changed=True,
            created=False,
            user=sender,
            friendship_user_id=str(request.sender_id or ""),
            is_friend=True,
            request=request_payload,
        )

    def reject_request(self, current_user: User, request_id: str) -> dict:
        request = self.friends.get_request(request_id)
        if request is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "friend request not found", 404)
        if request.receiver_id != current_user.id:
            raise AppError(ErrorCode.FORBIDDEN, "cannot reject this request", 403)
        self._raise_if_request_not_pending(request)
        request = self.friends.update_request_status(request, "rejected", commit=False)
        self.db.commit()
        self.db.refresh(request)
        users_by_id = self.users.list_users_by_ids([request.sender_id, request.receiver_id])
        request_payload = self._serialize_request(request, users_by_id)
        sender = users_by_id.get(str(request.sender_id or ""))
        return self._serialize_relationship_mutation(
            action="request_rejected",
            changed=True,
            created=False,
            user=sender,
            friendship_user_id=str(request.sender_id or ""),
            is_friend=False,
            request=request_payload,
        )

    def list_friends(self, current_user: User) -> list[dict]:
        friendships = self.friends.list_friends(current_user.id)
        users_by_id = self.users.list_users_by_ids([friendship.friend_id for friendship in friendships])
        items: list[dict] = []
        for friendship in friendships:
            friend = users_by_id.get(str(friendship.friend_id or ""))
            if friend is not None:
                items.append(
                    self._serialize_relationship(
                        user=friend,
                        friendship_user_id=str(friend.id or ""),
                        is_friend=True,
                    )
                )
        return items

    def remove_friend(self, current_user: User, friend_id: str) -> dict:
        changed = self.friends.remove_friendship(current_user.id, friend_id)
        normalized_friend_id = str(friend_id or "").strip()
        friend = self.users.get_by_id(normalized_friend_id)
        return self._serialize_relationship_mutation(
            action="friendship_removed" if changed else "friendship_missing",
            changed=bool(changed),
            created=False,
            user=friend,
            friendship_user_id=normalized_friend_id,
            is_friend=False,
            request=None,
        )

    def check_relationship(self, current_user: User, user_id: str) -> dict:
        normalized_user_id = str(user_id or "").strip()
        user = self.users.get_by_id(normalized_user_id)
        if user is None:
            raise AppError(ErrorCode.USER_NOT_FOUND, "user not found", 404)
        is_friend = self.friends.is_friend(current_user.id, normalized_user_id)
        return self._serialize_relationship(
            user=user,
            friendship_user_id=normalized_user_id,
            is_friend=is_friend,
        )

    def _persist_expired_requests(self, requests: list[FriendRequest]) -> None:
        touched = False
        for request in requests:
            if self._is_request_expired(request) and request.status == "pending":
                self.friends.update_request_status(request, "expired", commit=False)
                touched = True
        if touched:
            self.db.commit()
            for request in requests:
                if request.status == "expired":
                    self.db.refresh(request)

    @staticmethod
    def _find_pending_request(requests: list[FriendRequest], sender_id: str, receiver_id: str) -> FriendRequest | None:
        for request in requests:
            if (
                request.sender_id == sender_id
                and request.receiver_id == receiver_id
                and request.status == "pending"
                and not FriendService._is_request_expired(request)
            ):
                return request
        return None

    def _raise_if_request_not_pending(self, request: FriendRequest) -> None:
        if self._is_request_expired(request):
            if request.status == "pending":
                self.friends.update_request_status(request, "expired", commit=False)
                self.db.commit()
                self.db.refresh(request)
            raise AppError(ErrorCode.INVALID_REQUEST, "friend request expired", 409)
        if request.status != "pending":
            raise AppError(ErrorCode.INVALID_REQUEST, f"friend request {request.status}", 409)

    @classmethod
    def _is_request_expired(cls, request: FriendRequest) -> bool:
        if request.status != "pending" or request.created_at is None:
            return False
        created_at = request.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - created_at >= cls.REQUEST_EXPIRE_AFTER

    def _serialize_request(self, request: FriendRequest, users_by_id: dict[str, User]) -> dict:
        sender = users_by_id.get(str(request.sender_id or ""))
        receiver = users_by_id.get(str(request.receiver_id or ""))
        status = "expired" if self._is_request_expired(request) else str(request.status or "")
        return {
            "request_id": request.id,
            "status": status,
            "message": request.message,
            "created_at": request.created_at.isoformat() if request.created_at else None,
            "sender": self._serialize_request_party(sender),
            "receiver": self._serialize_request_party(receiver),
        }

    def _serialize_request_party(self, user: User | None) -> dict:
        if user is None:
            return {}
        return self.user_payloads.serialize_public_user(user)

    def _serialize_relationship(self, *, user: User | None, friendship_user_id: str, is_friend: bool) -> dict:
        normalized_friendship_user_id = str(friendship_user_id or "").strip()
        payload = self.user_payloads.serialize_public_user(user) if user is not None else {"id": normalized_friendship_user_id}
        return {
            "user": payload,
            "friendship": {
                "is_friend": bool(is_friend),
                "friend_id": normalized_friendship_user_id if is_friend else None,
            },
        }

    def _serialize_relationship_mutation(
        self,
        *,
        action: str,
        changed: bool,
        created: bool,
        user: User | None,
        friendship_user_id: str,
        is_friend: bool,
        request: dict | None,
    ) -> dict:
        return {
            "mutation": {
                "action": str(action or ""),
                "changed": bool(changed),
                "created": bool(created),
            },
            "relationship": self._serialize_relationship(
                user=user,
                friendship_user_id=friendship_user_id,
                is_friend=is_friend,
            ),
            "request": dict(request or {}) if request is not None else None,
        }
