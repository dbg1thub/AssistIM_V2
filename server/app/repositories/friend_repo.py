"""Friend repository."""

from __future__ import annotations

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models.user import FriendRequest, Friendship


class FriendRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create_request(
        self,
        sender_id: str,
        receiver_id: str,
        message: str | None = None,
        *,
        commit: bool = True,
    ) -> FriendRequest:
        request = FriendRequest(sender_id=sender_id, receiver_id=receiver_id, message=message)
        self.db.add(request)
        self.db.flush()
        if commit:
            self.db.commit()
            self.db.refresh(request)
        return request

    def get_request(self, request_id: str) -> FriendRequest | None:
        return self.db.get(FriendRequest, request_id)

    def list_requests_between(self, user_id: str, other_user_id: str) -> list[FriendRequest]:
        stmt = (
            select(FriendRequest)
            .where(
                or_(
                    and_(FriendRequest.sender_id == user_id, FriendRequest.receiver_id == other_user_id),
                    and_(FriendRequest.sender_id == other_user_id, FriendRequest.receiver_id == user_id),
                )
            )
            .order_by(FriendRequest.created_at.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def list_requests_for_user(self, user_id: str) -> list[FriendRequest]:
        stmt = select(FriendRequest).where(
            or_(FriendRequest.sender_id == user_id, FriendRequest.receiver_id == user_id)
        ).order_by(FriendRequest.created_at.desc())
        return list(self.db.execute(stmt).scalars().all())

    def create_friendship_pair(self, user_id: str, friend_id: str, *, commit: bool = True) -> None:
        for src, dst in ((user_id, friend_id), (friend_id, user_id)):
            exists_stmt = select(Friendship).where(
                and_(Friendship.user_id == src, Friendship.friend_id == dst)
            )
            if self.db.execute(exists_stmt).scalar_one_or_none() is None:
                self.db.add(Friendship(user_id=src, friend_id=dst))
        self.db.flush()
        if commit:
            self.db.commit()

    def list_friends(self, user_id: str) -> list[Friendship]:
        stmt = select(Friendship).where(Friendship.user_id == user_id)
        return list(self.db.execute(stmt).scalars().all())

    def update_request_status(self, request: FriendRequest, status: str, *, commit: bool = True) -> FriendRequest:
        request.status = status
        self.db.add(request)
        self.db.flush()
        if commit:
            self.db.commit()
            self.db.refresh(request)
        return request

    def is_friend(self, user_id: str, friend_id: str) -> bool:
        stmt = select(Friendship).where(
            and_(Friendship.user_id == user_id, Friendship.friend_id == friend_id)
        )
        return self.db.execute(stmt).scalar_one_or_none() is not None

    def remove_friendship(self, user_id: str, friend_id: str, *, commit: bool = True) -> bool:
        stmt = select(Friendship).where(
            or_(
                and_(Friendship.user_id == user_id, Friendship.friend_id == friend_id),
                and_(Friendship.user_id == friend_id, Friendship.friend_id == user_id),
            )
        )
        removed = False
        for friendship in self.db.execute(stmt).scalars().all():
            self.db.delete(friendship)
            removed = True
        self.db.flush()
        if commit:
            self.db.commit()
        return removed
