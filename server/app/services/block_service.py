"""User block service."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.user import User
from app.repositories.block_repo import BlockRepository
from app.repositories.friend_repo import FriendRepository
from app.repositories.user_repo import UserRepository
from app.services.user_service import UserService


class BlockService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.blocks = BlockRepository(db)
        self.friends = FriendRepository(db)
        self.users = UserRepository(db)
        self.user_payloads = UserService(db)

    def list_blocks(self, current_user: User) -> list[dict]:
        blocks = self.blocks.list_blocks(current_user.id)
        users_by_id = self.users.list_users_by_ids([item.blocked_user_id for item in blocks])
        return [self._serialize_block(item, users_by_id.get(str(item.blocked_user_id or ""))) for item in blocks]

    def check_blocking(self, current_user: User, user_id: str) -> dict:
        normalized_user_id = self._normalize_target_user_id(user_id)
        target = self._require_user(normalized_user_id)
        return {
            "user": self.user_payloads.serialize_public_user(target),
            "block": self._serialize_block_state(current_user, target),
        }

    def block_user(self, current_user: User, target_user_id: str) -> dict:
        normalized_target_user_id = self._normalize_target_user_id(target_user_id)
        self._ensure_not_self(current_user, normalized_target_user_id)
        target = self._require_user(normalized_target_user_id)

        existing_block = self.blocks.get_block(current_user.id, normalized_target_user_id)
        created = existing_block is None
        changed = False
        if created:
            self.blocks.create_block(current_user.id, normalized_target_user_id, commit=False)
            changed = True

        if self.friends.remove_friendship(current_user.id, normalized_target_user_id, commit=False):
            changed = True
        if self.friends.delete_requests_between(current_user.id, normalized_target_user_id, status="pending", commit=False):
            changed = True

        self.db.commit()
        return {
            "mutation": {
                "action": "block_created" if created else "block_reused",
                "changed": bool(changed),
                "created": bool(created),
            },
            "user": self.user_payloads.serialize_public_user(target),
            "block": self._serialize_block_state(current_user, target),
        }

    def unblock_user(self, current_user: User, target_user_id: str) -> dict:
        normalized_target_user_id = self._normalize_target_user_id(target_user_id)
        self._ensure_not_self(current_user, normalized_target_user_id)
        target = self._require_user(normalized_target_user_id)
        changed = self.blocks.remove_block(current_user.id, normalized_target_user_id)
        return {
            "mutation": {
                "action": "block_removed" if changed else "block_missing",
                "changed": bool(changed),
                "created": False,
            },
            "user": self.user_payloads.serialize_public_user(target),
            "block": self._serialize_block_state(current_user, target),
        }

    def _serialize_block(self, block, user: User | None) -> dict:
        target_id = str(block.blocked_user_id or "")
        return {
            "user": self.user_payloads.serialize_public_user(user) if user is not None else {"id": target_id},
            "block": {
                "is_blocked": True,
                "is_blocked_by": False,
                "blocked_user_id": target_id,
                "blocked_by_user_id": None,
                "created_at": block.created_at.isoformat() if block.created_at else None,
                "updated_at": block.updated_at.isoformat() if block.updated_at else None,
            },
        }

    def _serialize_block_state(self, current_user: User, target: User) -> dict:
        blocked = self.blocks.get_block(current_user.id, target.id)
        blocked_by = self.blocks.get_block(target.id, current_user.id)
        return {
            "is_blocked": bool(blocked is not None),
            "is_blocked_by": bool(blocked_by is not None),
            "blocked_user_id": str(target.id or "") if blocked is not None else None,
            "blocked_by_user_id": str(target.id or "") if blocked_by is not None else None,
            "created_at": blocked.created_at.isoformat() if blocked and blocked.created_at else None,
            "updated_at": blocked.updated_at.isoformat() if blocked and blocked.updated_at else None,
        }

    def _require_user(self, user_id: str) -> User:
        user = self.users.get_by_id(user_id)
        if user is None:
            raise AppError(ErrorCode.USER_NOT_FOUND, "user not found", 404)
        return user

    @staticmethod
    def _normalize_target_user_id(user_id: str) -> str:
        normalized = str(user_id or "").strip()
        if not normalized:
            raise AppError(ErrorCode.INVALID_REQUEST, "target_user_id is required", 422)
        return normalized

    @staticmethod
    def _ensure_not_self(current_user: User, target_user_id: str) -> None:
        if str(current_user.id or "") == target_user_id:
            raise AppError(ErrorCode.INVALID_REQUEST, "cannot block yourself", 422)
