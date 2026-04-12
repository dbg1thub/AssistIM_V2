"""Message service."""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.session import SessionEvent
from app.models.user import User
from app.repositories.group_repo import GroupRepository
from app.repositories.message_repo import MessageIdConflictError, MessageRepository
from app.repositories.session_repo import SessionRepository
from app.repositories.user_repo import UserRepository
from app.services.avatar_service import AvatarService
from app.utils.time import ensure_utc, isoformat_utc, utcnow


class MessageService:
    RECALLED_MESSAGE_PLACEHOLDER = "[message recalled]"
    RECALL_LIMIT = timedelta(minutes=2)
    EDIT_LIMIT = timedelta(minutes=2)
    DIRECT_TEXT_SCHEMES = {"x25519-aesgcm-v1"}
    GROUP_TEXT_SCHEMES = {"group-sender-key-v1"}
    DIRECT_ATTACHMENT_SCHEMES = {"aesgcm-file+x25519-v1"}
    GROUP_ATTACHMENT_SCHEMES = {"aesgcm-file+group-sender-key-v1"}
    MAX_MESSAGE_CONTENT_LENGTH = 20_000
    ENCRYPTION_MODE_PLAIN = "plain"
    ENCRYPTION_MODE_E2EE_PRIVATE = "e2ee_private"
    ENCRYPTION_MODE_E2EE_GROUP = "e2ee_group"
    ENCRYPTION_MODE_SERVER_VISIBLE_AI = "server_visible_ai"
    SUPPORTED_ENCRYPTION_MODES = {
        ENCRYPTION_MODE_PLAIN,
        ENCRYPTION_MODE_E2EE_PRIVATE,
        ENCRYPTION_MODE_E2EE_GROUP,
        ENCRYPTION_MODE_SERVER_VISIBLE_AI,
    }
    ATTACHMENT_MESSAGE_TYPES = {"file", "image", "video", "voice"}
    CLIENT_MESSAGE_TYPES = {"text", *ATTACHMENT_MESSAGE_TYPES}
    INTERNAL_ATTACHMENT_METADATA_KEYS = {
        "checksum_sha256",
        "storage_key",
        "storage_provider",
    }
    LOCAL_ONLY_MESSAGE_EXTRA_KEYS = {
        "content",
        "local_path",
        "uploading",
        "client_flags",
        *INTERNAL_ATTACHMENT_METADATA_KEYS,
    }
    LOCAL_ONLY_ENCRYPTION_KEYS = {
        "local_plaintext",
        "local_plaintext_version",
        "decryption_error",
        "decryption_state",
        "recovery_action",
        "local_device_id",
        "target_device_id",
        "can_decrypt",
    }
    MUTABLE_MESSAGE_STATUSES = {"sent", "edited"}
    EDITABLE_MESSAGE_TYPES = {"text"}
    RECALLABLE_MESSAGE_TYPES = CLIENT_MESSAGE_TYPES
    LOCAL_ONLY_ATTACHMENT_ENCRYPTION_KEYS = {
        "local_metadata",
        "local_plaintext_version",
        "decryption_error",
        "decryption_state",
        "recovery_action",
        "local_device_id",
        "target_device_id",
        "can_decrypt",
    }

    def __init__(self, db: Session) -> None:
        self.db = db
        self.messages = MessageRepository(db)
        self.sessions = SessionRepository(db)
        self.groups = GroupRepository(db)
        self.users = UserRepository(db)
        self.avatars = AvatarService(db)

    def list_messages(
        self,
        current_user: User,
        session_id: str,
        limit: int = 50,
        before_seq: int | None = None,
    ) -> list[dict]:
        self._ensure_visible_session_membership(current_user.id, session_id)
        items = self.messages.list_session_messages(session_id, limit=limit, before_seq=before_seq)
        return self._serialize_messages(items, current_user.id)

    def send_message(
        self,
        current_user: User,
        session_id: str,
        content: str,
        message_type: str = "text",
        message_id: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> tuple[dict, bool]:
        self._ensure_visible_session_membership(current_user.id, session_id)
        normalized_message_type = self._normalize_client_message_type(message_type)
        self._ensure_message_content(content)
        normalized_extra = self._normalize_message_extra(
            sender_id=current_user.id,
            session_id=session_id,
            content=content,
            message_type=normalized_message_type,
            extra=extra,
        )
        try:
            message, created = self.messages.create(
                session_id=session_id,
                sender_id=current_user.id,
                content=content,
                message_type=normalized_message_type,
                message_id=message_id,
                extra=normalized_extra,
            )
        except MessageIdConflictError as exc:
            raise AppError(ErrorCode.INVALID_REQUEST, str(exc), 409) from exc
        return self.serialize_message(message, current_user.id), created

    def send_ws_message(
        self,
        sender_id: str,
        session_id: str,
        content: str,
        message_type: str = "text",
        message_id: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> tuple[dict, bool]:
        self._ensure_visible_session_membership(sender_id, session_id)
        normalized_message_type = self._normalize_client_message_type(message_type)
        self._ensure_message_content(content)
        normalized_extra = self._normalize_message_extra(
            sender_id=sender_id,
            session_id=session_id,
            content=content,
            message_type=normalized_message_type,
            extra=extra,
        )
        try:
            message, created = self.messages.create(
                session_id=session_id,
                sender_id=sender_id,
                content=content,
                message_type=normalized_message_type,
                message_id=message_id,
                extra=normalized_extra,
            )
        except MessageIdConflictError as exc:
            raise AppError(ErrorCode.INVALID_REQUEST, str(exc), 409) from exc
        return self.serialize_message(message, sender_id), created

    @classmethod
    def _normalize_client_message_type(cls, message_type: str) -> str:
        normalized = str(message_type or "text").strip().lower()
        if normalized not in cls.CLIENT_MESSAGE_TYPES:
            raise AppError(ErrorCode.INVALID_REQUEST, "unsupported message type", 422)
        return normalized

    def mark_read(self, current_user: User, message_id: str) -> dict:
        message = self.messages.get_by_id(message_id)
        if message is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "message not found", 404)
        self._ensure_visible_session_membership(current_user.id, message.session_id)
        payload = self.messages.mark_read(message_id, current_user.id, commit=False)
        if payload is None:
            raise AppError(ErrorCode.INVALID_REQUEST, "invalid read target", 422)

        event_payload = None
        if payload.get("advanced"):
            event_payload = self._record_session_event(
                message.session_id,
                "read",
                self._read_event_data(payload),
                message_id=message.id,
                actor_user_id=current_user.id,
            )

        self.db.commit()
        return self._read_result(payload, event_payload)

    def batch_read(self, current_user: User, session_id: str, message_id: str) -> dict:
        self._ensure_visible_session_membership(current_user.id, session_id)
        last_message = self.messages.get_by_id(message_id)
        if last_message is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "message not found", 404)
        if last_message.session_id != session_id:
            raise AppError(ErrorCode.INVALID_REQUEST, "message does not belong to the session", 422)

        payload = self.messages.mark_read_batch(session_id, current_user.id, message_id, commit=False)
        if payload is None:
            raise AppError(ErrorCode.INVALID_REQUEST, "invalid read target", 422)

        event_payload = None
        if payload.get("advanced"):
            event_payload = self._record_session_event(
                session_id,
                "read",
                self._read_event_data(payload),
                message_id=last_message.id,
                actor_user_id=current_user.id,
            )

        self.db.commit()
        return self._read_result(payload, event_payload)

    def recall(self, current_user: User, message_id: str) -> dict:
        message = self.messages.get_by_id(message_id)
        if message is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "message not found", 404)
        self._ensure_visible_session_membership(current_user.id, message.session_id)
        if message.sender_id != current_user.id:
            raise AppError(ErrorCode.FORBIDDEN, "cannot recall this message", 403)
        self._ensure_message_status_allows(message, "recall")
        self._ensure_message_type_allows_recall(message)
        if message.created_at and utcnow() - ensure_utc(message.created_at) > self.RECALL_LIMIT:
            raise AppError(ErrorCode.FORBIDDEN, "recall time limit exceeded", 403)

        self.messages.update_status(message, "recalled", commit=False)
        payload = {
            "session_id": message.session_id,
            "message_id": message.id,
            "user_id": current_user.id,
            "status": "recalled",
            "updated_at": isoformat_utc(message.updated_at),
            "session_seq": int(message.session_seq or 0),
        }
        payload = self._record_session_event(
            message.session_id,
            "message_recall",
            payload,
            message_id=message.id,
            actor_user_id=current_user.id,
        )
        self.db.commit()
        return payload

    def edit(
        self,
        current_user: User,
        message_id: str,
        content: str,
        *,
        extra: dict[str, Any] | None = None,
    ) -> dict:
        message = self.messages.get_by_id(message_id)
        if message is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "message not found", 404)
        self._ensure_visible_session_membership(current_user.id, message.session_id)
        if message.sender_id != current_user.id:
            raise AppError(ErrorCode.FORBIDDEN, "cannot edit this message", 403)
        self._ensure_message_status_allows(message, "edit")
        self._ensure_message_type_allows_edit(message)
        self._ensure_message_content(content)
        if message.created_at and utcnow() - ensure_utc(message.created_at) > self.EDIT_LIMIT:
            raise AppError(ErrorCode.FORBIDDEN, "edit time limit exceeded", 403)

        normalized_extra = self._normalize_message_extra(
            sender_id=current_user.id,
            session_id=message.session_id,
            content=content,
            message_type=str(message.type or "text"),
            extra=extra if extra is not None else self.messages.load_extra(message),
        )
        self.messages.update_content(message, content, extra=normalized_extra, commit=False)
        self.messages.update_status(message, "edited", commit=False)
        serialized = self.serialize_message(message, current_user.id)
        payload = {
            "session_id": serialized["session_id"],
            "message_id": serialized["message_id"],
            "user_id": current_user.id,
            "content": serialized["content"],
            "status": serialized["status"],
            "updated_at": serialized["updated_at"],
            "session_seq": serialized.get("session_seq", 0),
            "read_count": serialized.get("read_count", 0),
            "read_target_count": serialized.get("read_target_count", 0),
            "read_by_user_ids": serialized.get("read_by_user_ids", []),
            "extra": dict(serialized.get("extra") or {}),
        }
        payload = self._record_session_event(
            serialized["session_id"],
            "message_edit",
            payload,
            message_id=serialized["message_id"],
            actor_user_id=current_user.id,
        )
        self.db.commit()
        return payload

    def delete(self, current_user: User, message_id: str) -> dict:
        message = self.messages.get_by_id(message_id)
        if message is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "message not found", 404)
        self._ensure_visible_session_membership(current_user.id, message.session_id)
        if message.sender_id != current_user.id:
            raise AppError(ErrorCode.FORBIDDEN, "cannot delete this message", 403)
        self._ensure_message_status_allows(message, "delete")

        payload = {
            "session_id": message.session_id,
            "message_id": message.id,
            "user_id": current_user.id,
            "status": "deleted",
        }
        self.messages.delete(message, commit=False)
        payload = self._record_session_event(
            payload["session_id"],
            "message_delete",
            payload,
            message_id=payload["message_id"],
            actor_user_id=current_user.id,
        )
        self.db.commit()
        return payload

    def unread_summary(self, current_user: User) -> dict:
        counts = self.session_unread_counts(current_user)
        return {"total": sum(int(item.get("unread", 0) or 0) for item in counts)}

    def session_unread_counts(self, current_user: User) -> list[dict]:
        unread_by_session = {
            str(item.get("session_id") or ""): int(item.get("unread", 0) or 0)
            for item in self.messages.unread_by_session_for_user(current_user.id)
            if str(item.get("session_id") or "")
        }
        if not unread_by_session:
            return []

        visible_counts: list[dict] = []
        for session in self.sessions.list_user_sessions(current_user.id):
            session_id = str(getattr(session, "id", "") or "")
            if not session_id or session_id not in unread_by_session:
                continue
            member_ids = self.sessions.list_member_ids(session_id)
            if not self._is_visible_private_session(session, member_ids):
                continue
            visible_counts.append({"session_id": session_id, "unread": unread_by_session[session_id]})
        return visible_counts

    def sync_missing_messages(self, session_cursors: dict | None, current_user_id: str) -> list[dict]:
        items = self.messages.list_missing_messages_for_user(
            self._normalize_session_cursors(session_cursors),
            current_user_id,
        )
        items = self._filter_visible_session_items(current_user_id, items)
        return self._serialize_messages(items, current_user_id)

    def sync_missing_events(self, event_cursors: dict | None, current_user_id: str) -> list[dict]:
        items = self.messages.list_missing_events_for_user(
            self._normalize_event_cursors(event_cursors),
            current_user_id,
        )
        items = self._filter_visible_session_items(current_user_id, items)
        return [self.serialize_session_event(item) for item in items]

    def get_session_member_ids(self, session_id: str, user_id: str | None = None) -> list[str]:
        session = self._ensure_session_exists(session_id)
        member_ids = self.sessions.list_member_ids(session_id)
        if user_id is not None and user_id not in member_ids:
            raise AppError(ErrorCode.FORBIDDEN, "not a session member", 403)
        if not self._is_visible_private_session(session, member_ids):
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "session not found", 404)
        return member_ids

    def _ensure_session_exists(self, session_id: str):
        session = self.sessions.get_by_id(session_id)
        if session is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "session not found", 404)
        return session

    def _ensure_membership(self, user_id: str, session_id: str) -> None:
        self._ensure_visible_session_membership(user_id, session_id)

    def _ensure_visible_session_membership(self, user_id: str, session_id: str):
        session = self._ensure_session_exists(session_id)
        member_ids = self.sessions.list_member_ids(session_id)
        if user_id not in member_ids:
            raise AppError(ErrorCode.FORBIDDEN, "not a session member", 403)

        if not self._is_visible_private_session(session, member_ids):
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "session not found", 404)
        return session, member_ids

    def _is_visible_session_for_user(self, user_id: str, session_id: str) -> bool:
        try:
            self._ensure_visible_session_membership(user_id, session_id)
        except AppError:
            return False
        return True

    def _filter_visible_session_items(self, user_id: str, items: list) -> list:
        visibility_cache: dict[str, bool] = {}
        visible_items = []
        for item in items:
            session_id = str(getattr(item, "session_id", "") or "")
            if not session_id:
                continue
            if session_id not in visibility_cache:
                visibility_cache[session_id] = self._is_visible_session_for_user(user_id, session_id)
            if visibility_cache[session_id]:
                visible_items.append(item)

        return visible_items

    @staticmethod
    def _is_visible_private_session(session, member_ids: list[str]) -> bool:
        if getattr(session, "type", "") != "private" or bool(getattr(session, "is_ai_session", False)):
            return True
        return len(set(str(member_id or "") for member_id in member_ids if str(member_id or ""))) >= 2

    def _ensure_message_status_allows(self, message, action: str) -> None:
        status = str(getattr(message, "status", "") or "").strip().lower()
        if status not in self.MUTABLE_MESSAGE_STATUSES:
            raise AppError(
                ErrorCode.INVALID_REQUEST,
                f"cannot {action} {status or 'unknown'} message",
                409,
            )

    def _ensure_message_type_allows_edit(self, message) -> None:
        message_type = str(getattr(message, "type", "") or "").strip().lower()
        if message_type not in self.EDITABLE_MESSAGE_TYPES:
            raise AppError(ErrorCode.INVALID_REQUEST, "message type does not support edit", 422)

    def _ensure_message_type_allows_recall(self, message) -> None:
        message_type = str(getattr(message, "type", "") or "").strip().lower()
        if message_type not in self.RECALLABLE_MESSAGE_TYPES:
            raise AppError(ErrorCode.INVALID_REQUEST, "message type does not support recall", 422)

    def _ensure_message_content(self, content: str) -> None:
        if not isinstance(content, str):
            raise AppError(ErrorCode.INVALID_REQUEST, "content must be a string", 422)
        if not content.strip():
            raise AppError(ErrorCode.INVALID_REQUEST, "content cannot be blank", 422)
        if len(content) > self.MAX_MESSAGE_CONTENT_LENGTH:
            raise AppError(ErrorCode.INVALID_REQUEST, "content is too long", 422)

    def _normalize_message_extra(
        self,
        *,
        sender_id: str,
        session_id: str,
        content: str,
        message_type: str,
        extra: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        session = self.sessions.get_by_id(session_id)
        if session is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "session not found", 404)

        normalized_extra = self._sanitize_transport_extra(extra)
        normalized_message_type = str(message_type or "text").strip().lower()
        raw_session_type = str(getattr(session, "type", "") or "").strip().lower()
        normalized_session_type = "direct" if raw_session_type == "private" else raw_session_type
        self._validate_message_encryption(
            session_type=normalized_session_type,
            is_ai_session=bool(getattr(session, "is_ai_session", False)),
            encryption_mode=getattr(session, "encryption_mode", ""),
            message_type=normalized_message_type,
            extra=normalized_extra,
        )
        self._validate_attachment_payload(normalized_message_type, normalized_extra)

        mentions = []
        raw_mentions = normalized_extra.get("mentions")
        if normalized_message_type == "text" and isinstance(raw_mentions, list):
            session_member_ids = {
                str(member_id or "").strip()
                for member_id in self.sessions.list_member_ids(session_id)
                if str(member_id or "").strip()
            }
            mentions = self._normalize_mentions(raw_mentions, content=content, member_ids=session_member_ids)

        if any(str(item.get("mention_type", "") or "") == "all" for item in mentions):
            self._ensure_can_mention_everyone(sender_id, session_id)

        if mentions:
            normalized_extra["mentions"] = mentions
        else:
            normalized_extra.pop("mentions", None)
        return normalized_extra or None

    @classmethod
    def _validate_attachment_payload(cls, message_type: str, extra: dict[str, Any]) -> None:
        normalized_message_type = str(message_type or "").strip().lower()
        if normalized_message_type not in cls.ATTACHMENT_MESSAGE_TYPES:
            return

        attachment_encryption = dict(extra.get("attachment_encryption") or {})
        if attachment_encryption.get("enabled"):
            return

        media = dict(extra.get("media") or {})
        url = str(extra.get("url") or media.get("url") or "").strip()
        name = str(extra.get("name") or media.get("original_name") or media.get("file_name") or media.get("name") or "").strip()
        mime_type = str(extra.get("file_type") or media.get("mime_type") or media.get("file_type") or "").strip()
        try:
            size = int(extra.get("size") or media.get("size_bytes") or media.get("size") or 0)
        except (TypeError, ValueError):
            size = 0

        if not url or not name or not mime_type or size <= 0:
            raise AppError(
                ErrorCode.INVALID_REQUEST,
                "attachment messages require url, name, file_type, and size metadata",
                422,
            )

    @classmethod
    def _sanitize_transport_extra(cls, extra: dict[str, Any] | None) -> dict[str, Any]:
        normalized = dict(extra or {})
        for key in cls.LOCAL_ONLY_MESSAGE_EXTRA_KEYS:
            normalized.pop(key, None)

        encryption = cls._sanitize_encryption_envelope(
            normalized.get("encryption"),
            local_only_keys=cls.LOCAL_ONLY_ENCRYPTION_KEYS,
        )
        if encryption:
            normalized["encryption"] = encryption
        else:
            normalized.pop("encryption", None)

        attachment_encryption = cls._sanitize_encryption_envelope(
            normalized.get("attachment_encryption"),
            local_only_keys=cls.LOCAL_ONLY_ATTACHMENT_ENCRYPTION_KEYS,
        )
        if attachment_encryption:
            normalized["attachment_encryption"] = attachment_encryption
            if attachment_encryption.get("enabled"):
                normalized.pop("url", None)
                normalized.pop("name", None)
                normalized.pop("file_type", None)
                normalized.pop("size", None)
                normalized.pop("media", None)
        else:
            normalized.pop("attachment_encryption", None)

        media = normalized.get("media")
        if isinstance(media, dict):
            sanitized_media = dict(media)
            for key in cls.INTERNAL_ATTACHMENT_METADATA_KEYS:
                sanitized_media.pop(key, None)
            if sanitized_media:
                normalized["media"] = sanitized_media
            else:
                normalized.pop("media", None)
        else:
            normalized.pop("media", None)

        return normalized

    @staticmethod
    def _sanitize_encryption_envelope(
        envelope: Any,
        *,
        local_only_keys: set[str],
    ) -> dict[str, Any]:
        if not isinstance(envelope, dict):
            return {}
        normalized = dict(envelope)
        for key in local_only_keys:
            normalized.pop(key, None)
        return normalized

    @classmethod
    def _validate_message_encryption(
        cls,
        *,
        session_type: str,
        is_ai_session: bool,
        encryption_mode: str | None,
        message_type: str,
        extra: dict[str, Any],
    ) -> None:
        encryption = dict(extra.get("encryption") or {})
        attachment_encryption = dict(extra.get("attachment_encryption") or {})
        has_text_encryption = bool(encryption.get("enabled"))
        has_attachment_encryption = bool(attachment_encryption.get("enabled"))

        normalized_session_type = str(session_type or "").strip().lower()
        session_encryption_mode = cls._resolve_session_encryption_mode(
            encryption_mode=encryption_mode,
            session_type=normalized_session_type,
            is_ai_session=is_ai_session,
        )
        if is_ai_session:
            if has_text_encryption or has_attachment_encryption:
                raise AppError(ErrorCode.INVALID_REQUEST, "AI sessions do not support end-to-end encryption", 422)
            return
        if session_encryption_mode in {cls.ENCRYPTION_MODE_PLAIN, cls.ENCRYPTION_MODE_SERVER_VISIBLE_AI}:
            if has_text_encryption or has_attachment_encryption:
                raise AppError(ErrorCode.INVALID_REQUEST, "session encryption is not enabled", 422)
            return
        normalized_message_type = str(message_type or "text").strip().lower()
        if normalized_session_type not in {"direct", "group"}:
            raise AppError(ErrorCode.INVALID_REQUEST, "unsupported encrypted session type", 422)
        if session_encryption_mode == cls.ENCRYPTION_MODE_E2EE_PRIVATE and normalized_session_type != "direct":
            raise AppError(ErrorCode.INVALID_REQUEST, "session encryption mode does not match session type", 422)
        if session_encryption_mode == cls.ENCRYPTION_MODE_E2EE_GROUP and normalized_session_type != "group":
            raise AppError(ErrorCode.INVALID_REQUEST, "session encryption mode does not match session type", 422)

        is_text_message = normalized_message_type == "text"
        is_attachment_message = normalized_message_type in cls.ATTACHMENT_MESSAGE_TYPES
        if not is_text_message and not is_attachment_message:
            raise AppError(
                ErrorCode.INVALID_REQUEST,
                "end-to-end encrypted sessions only support encrypted text and attachment messages",
                422,
            )
        if is_text_message and not has_text_encryption:
            raise AppError(ErrorCode.INVALID_REQUEST, "end-to-end encrypted text messages require text encryption", 422)
        if is_attachment_message and not has_attachment_encryption:
            raise AppError(
                ErrorCode.INVALID_REQUEST,
                "end-to-end encrypted attachment messages require attachment encryption",
                422,
            )

        if has_text_encryption:
            if normalized_message_type != "text":
                raise AppError(ErrorCode.INVALID_REQUEST, "text encryption is only valid for text messages", 422)
            scheme = str(encryption.get("scheme") or "").strip()
            allowed_text_schemes = cls.DIRECT_TEXT_SCHEMES if normalized_session_type == "direct" else cls.GROUP_TEXT_SCHEMES
            if scheme not in allowed_text_schemes:
                raise AppError(ErrorCode.INVALID_REQUEST, "invalid text encryption scheme for session type", 422)
            if normalized_session_type == "direct":
                cls._validate_direct_text_envelope(encryption)
            else:
                cls._validate_group_text_envelope(encryption)

        if has_attachment_encryption:
            if normalized_message_type not in cls.ATTACHMENT_MESSAGE_TYPES:
                raise AppError(ErrorCode.INVALID_REQUEST, "attachment encryption requires an attachment message type", 422)
            scheme = str(attachment_encryption.get("scheme") or "").strip()
            allowed_attachment_schemes = (
                cls.DIRECT_ATTACHMENT_SCHEMES
                if normalized_session_type == "direct"
                else cls.GROUP_ATTACHMENT_SCHEMES
            )
            if scheme not in allowed_attachment_schemes:
                raise AppError(ErrorCode.INVALID_REQUEST, "invalid attachment encryption scheme for session type", 422)
            if normalized_session_type == "direct":
                cls._validate_direct_attachment_envelope(attachment_encryption)
            else:
                cls._validate_group_attachment_envelope(attachment_encryption)

    @classmethod
    def _resolve_session_encryption_mode(
        cls,
        *,
        encryption_mode: str | None,
        session_type: str,
        is_ai_session: bool,
    ) -> str:
        normalized_session_type = str(session_type or "").strip().lower()
        if is_ai_session or normalized_session_type == "ai":
            return cls.ENCRYPTION_MODE_SERVER_VISIBLE_AI
        normalized_mode = str(encryption_mode or "").strip().lower()
        if normalized_mode in cls.SUPPORTED_ENCRYPTION_MODES:
            return normalized_mode
        return cls.ENCRYPTION_MODE_PLAIN

    @classmethod
    def _validate_direct_text_envelope(cls, envelope: dict[str, Any]) -> None:
        cls._require_envelope_fields(
            envelope,
            "direct text",
            ("sender_device_id", "sender_identity_key_public", "recipient_user_id", "recipient_device_id", "content_ciphertext", "nonce"),
        )
        cls._require_int_field(envelope, "recipient_prekey_id", "direct text")
        cls._require_allowed_value(
            envelope,
            "recipient_prekey_type",
            {"signed", "one_time"},
            "direct text",
        )

    @classmethod
    def _validate_group_text_envelope(cls, envelope: dict[str, Any]) -> None:
        cls._require_envelope_fields(
            envelope,
            "group text",
            ("session_id", "sender_device_id", "sender_key_id", "content_ciphertext", "nonce"),
        )
        cls._require_group_fanout(envelope.get("fanout"), "group text")

    @classmethod
    def _validate_direct_attachment_envelope(cls, envelope: dict[str, Any]) -> None:
        cls._require_envelope_fields(
            envelope,
            "direct attachment",
            ("sender_device_id", "sender_identity_key_public", "recipient_user_id", "recipient_device_id", "metadata_ciphertext", "nonce"),
        )
        cls._require_int_field(envelope, "recipient_prekey_id", "direct attachment")
        cls._require_allowed_value(
            envelope,
            "recipient_prekey_type",
            {"signed", "one_time"},
            "direct attachment",
        )

    @classmethod
    def _validate_group_attachment_envelope(cls, envelope: dict[str, Any]) -> None:
        cls._require_envelope_fields(
            envelope,
            "group attachment",
            ("session_id", "sender_device_id", "sender_key_id", "metadata_ciphertext", "nonce"),
        )
        cls._require_group_fanout(envelope.get("fanout"), "group attachment")

    @staticmethod
    def _require_envelope_fields(envelope: dict[str, Any], envelope_label: str, fields: tuple[str, ...]) -> None:
        missing_fields = []
        for field_name in fields:
            value = envelope.get(field_name)
            if not isinstance(value, str) or not value.strip():
                missing_fields.append(field_name)
        if missing_fields:
            raise AppError(
                ErrorCode.INVALID_REQUEST,
                f"{envelope_label} encryption envelope is missing required fields: {', '.join(missing_fields)}",
                422,
            )

    @staticmethod
    def _require_int_field(envelope: dict[str, Any], field_name: str, envelope_label: str) -> None:
        try:
            value = int(envelope.get(field_name))
        except (TypeError, ValueError):
            value = 0
        if value <= 0:
            raise AppError(
                ErrorCode.INVALID_REQUEST,
                f"{envelope_label} encryption envelope has invalid field: {field_name}",
                422,
            )

    @staticmethod
    def _require_allowed_value(
        envelope: dict[str, Any],
        field_name: str,
        allowed_values: set[str],
        envelope_label: str,
    ) -> None:
        value = str(envelope.get(field_name) or "").strip()
        if value not in allowed_values:
            raise AppError(
                ErrorCode.INVALID_REQUEST,
                f"{envelope_label} encryption envelope has invalid field: {field_name}",
                422,
            )

    @classmethod
    def _require_group_fanout(cls, fanout: Any, envelope_label: str) -> None:
        if not isinstance(fanout, list) or not fanout:
            raise AppError(
                ErrorCode.INVALID_REQUEST,
                f"{envelope_label} encryption envelope requires a non-empty fanout list",
                422,
            )
        for item in fanout:
            if not isinstance(item, dict):
                raise AppError(
                    ErrorCode.INVALID_REQUEST,
                    f"{envelope_label} encryption envelope contains an invalid fanout item",
                    422,
                )
            cls._require_envelope_fields(
                item,
                f"{envelope_label} fanout",
                ("recipient_user_id", "recipient_device_id", "sender_device_id", "sender_key_id", "ciphertext", "nonce"),
            )
            cls._require_allowed_value(
                item,
                "scheme",
                {"group-sender-key-fanout-v1"},
                f"{envelope_label} fanout",
            )

    def _ensure_can_mention_everyone(self, sender_id: str, session_id: str) -> None:
        session = self.sessions.get_by_id(session_id)
        if session is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "session not found", 404)
        if str(session.type or "") != "group":
            raise AppError(ErrorCode.INVALID_REQUEST, "@all is only available in group chats", 422)

        group = self.groups.get_by_session_id(session_id)
        if group is None:
            raise AppError(ErrorCode.INVALID_REQUEST, "group metadata not found", 422)
        if str(group.owner_id or "") == sender_id:
            return

        membership = self.groups.get_member(group.id, sender_id)
        role = str(getattr(membership, "role", "") or "").strip().lower()
        if role not in {"owner", "admin"}:
            raise AppError(ErrorCode.FORBIDDEN, "@all requires owner or admin privileges", 403)

    @staticmethod
    def _normalize_mentions(
        raw_mentions: Any,
        *,
        content: str,
        member_ids: set[str],
    ) -> list[dict[str, Any]]:
        if not isinstance(raw_mentions, list):
            return []

        text = str(content or "")
        text_length = len(text)
        normalized: list[dict[str, Any]] = []
        for item in raw_mentions:
            if not isinstance(item, dict):
                continue
            try:
                start = int(item.get("start", -1))
                end = int(item.get("end", -1))
            except (TypeError, ValueError):
                continue

            if start < 0 or end <= start or start >= text_length:
                continue
            end = min(end, text_length)
            if end <= start:
                continue

            display_name = str(item.get("display_name", "") or "").strip()
            if not display_name or text[start:end] != f"@{display_name}":
                continue

            mention_type = str(item.get("mention_type", "member") or "member").strip().lower()
            if mention_type not in {"member", "all"}:
                mention_type = "member"

            payload: dict[str, Any] = {
                "start": start,
                "end": end,
                "display_name": display_name,
                "mention_type": mention_type,
            }
            if mention_type == "member":
                member_id = str(item.get("member_id", "") or "").strip()
                if not member_id:
                    continue
                if member_id not in member_ids:
                    raise AppError(ErrorCode.INVALID_REQUEST, "mention member is not in session", 422)
                payload["member_id"] = member_id
            normalized.append(payload)

        normalized.sort(key=lambda item: (int(item["start"]), int(item["end"])))
        previous_end = -1
        for item in normalized:
            start = int(item["start"])
            end = int(item["end"])
            if start < previous_end:
                raise AppError(ErrorCode.INVALID_REQUEST, "mention spans must not overlap", 422)
            previous_end = end
        return normalized

    @staticmethod
    def _normalize_session_cursors(raw_cursors: dict | None) -> dict[str, int]:
        if not isinstance(raw_cursors, dict):
            return {}

        normalized: dict[str, int] = {}
        for session_id, raw_value in raw_cursors.items():
            normalized_session_id = str(session_id or "").strip()
            if not normalized_session_id:
                continue
            try:
                session_seq = max(0, int(raw_value or 0))
            except (TypeError, ValueError):
                continue
            normalized[normalized_session_id] = session_seq
        return normalized

    @staticmethod
    def _normalize_event_cursors(raw_cursors: dict | None) -> dict[str, int]:
        if not isinstance(raw_cursors, dict):
            return {}

        normalized: dict[str, int] = {}
        for session_id, raw_value in raw_cursors.items():
            normalized_session_id = str(session_id or "").strip()
            if not normalized_session_id:
                continue
            try:
                event_seq = max(0, int(raw_value or 0))
            except (TypeError, ValueError):
                continue
            normalized[normalized_session_id] = event_seq
        return normalized

    def _load_session_members(self, session_id: str):
        return self.sessions.list_members(session_id)

    def _message_read_metadata(self, message, current_user_id: str, session_members: list) -> dict:
        read_by_user_ids = sorted(
            member.user_id
            for member in session_members
            if member.user_id != message.sender_id and int(member.last_read_seq or 0) >= int(message.session_seq or 0)
        )
        viewer_member = next((member for member in session_members if member.user_id == current_user_id), None)
        viewer_last_read_seq = int(viewer_member.last_read_seq or 0) if viewer_member is not None else 0
        read_target_count = max(0, len(session_members) - 1)
        return {
            "session_seq": int(message.session_seq or 0),
            "read_count": len(read_by_user_ids),
            "read_target_count": read_target_count,
            "read_by_user_ids": read_by_user_ids,
            "is_read_by_me": message.sender_id == current_user_id or viewer_last_read_seq >= int(message.session_seq or 0),
        }

    def _serialize_message_content(self, message, current_user_id: str) -> str:
        if message.status == "recalled":
            return self.RECALLED_MESSAGE_PLACEHOLDER
        return message.content

    def _serialize_messages(self, messages: list, current_user_id: str) -> list[dict]:
        session_ids = {message.session_id for message in messages}
        session_members_by_session = {
            session_id: self._load_session_members(session_id)
            for session_id in session_ids
        }
        session_metadata_by_session = {
            session_id: self._load_session_metadata(
                session_id,
                session_members=session_members_by_session.get(session_id, []),
            )
            for session_id in session_ids
        }
        sender_ids = sorted(
            {
                str(message.sender_id or "")
                for message in messages
                if str(message.sender_id or "")
            }
        )
        sender_users_by_id = self.users.list_users_by_ids(sender_ids) if sender_ids else {}
        return [
            self.serialize_message(
                message,
                current_user_id,
                session_members=session_members_by_session.get(message.session_id, []),
                session_metadata=session_metadata_by_session.get(message.session_id),
                sender_users_by_id=sender_users_by_id,
            )
            for message in messages
        ]

    def serialize_message(
        self,
        message,
        current_user_id: str,
        session_members: list | None = None,
        session_metadata: dict[str, Any] | None = None,
        sender_users_by_id: dict[str, User] | None = None,
    ) -> dict:
        if session_members is None:
            session_members = self._load_session_members(message.session_id)
        if session_metadata is None:
            session_metadata = self._load_session_metadata(
                message.session_id,
                session_members=session_members,
            )
        read_metadata = self._message_read_metadata(message, current_user_id, session_members)
        extra = self._message_extra(message)
        sender_profile = self._serialize_sender_profile(
            str(message.sender_id or ""),
            users_by_id=sender_users_by_id,
        )
        return {
            "message_id": message.id,
            "session_id": message.session_id,
            "sender_id": message.sender_id,
            "content": self._serialize_message_content(message, current_user_id),
            "message_type": message.type,
            "status": message.status,
            "created_at": isoformat_utc(message.created_at),
            "updated_at": isoformat_utc(message.updated_at),
            "is_self": message.sender_id == current_user_id,
            "session_type": session_metadata.get("session_type", ""),
            "session_name": session_metadata.get("session_name", ""),
            "session_avatar": session_metadata.get("session_avatar"),
            "participant_ids": session_metadata.get("participant_ids", []),
            "is_ai_session": session_metadata.get("is_ai_session", False),
            "sender_profile": sender_profile,
            "session_seq": read_metadata["session_seq"],
            "read_count": read_metadata["read_count"],
            "read_target_count": read_metadata["read_target_count"],
            "read_by_user_ids": read_metadata["read_by_user_ids"],
            "is_read_by_me": read_metadata["is_read_by_me"],
            "extra": extra,
        }

    def _load_session_metadata(
        self,
        session_id: str,
        *,
        session_members: list | None = None,
    ) -> dict[str, Any]:
        session = self.sessions.get_by_id(session_id)
        if session is None:
            return {
                "session_type": "",
                "session_name": "",
                "session_avatar": None,
                "participant_ids": [],
                "is_ai_session": False,
            }

        members = session_members if session_members is not None else self._load_session_members(session_id)
        normalized_session_type = "direct" if session.type == "private" else str(session.type or "")
        participant_ids = list(dict.fromkeys(str(member.user_id or "") for member in members if str(member.user_id or "")))
        return {
            "session_type": normalized_session_type,
            "session_name": str(session.name or ""),
            "session_avatar": session.avatar,
            "participant_ids": participant_ids,
            "is_ai_session": bool(session.is_ai_session),
        }

    def _serialize_sender_profile(
        self,
        user_id: str,
        *,
        users_by_id: dict[str, User] | None = None,
    ) -> dict[str, Any] | None:
        normalized_user_id = str(user_id or "").strip()
        if not normalized_user_id:
            return None

        user = (users_by_id or {}).get(normalized_user_id)
        if user is None:
            user = self.users.get_by_id(normalized_user_id)
        if user is None:
            return None

        user = self.avatars.backfill_user_avatar_state(user)
        nickname = str(user.nickname or "")
        username = str(user.username or "")
        return {
            "id": user.id,
            "username": username,
            "nickname": nickname,
            "display_name": nickname or username or user.id,
            "avatar": self.avatars.resolve_user_avatar_url(user),
            "avatar_kind": str(getattr(user, "avatar_kind", "") or ""),
            "gender": str(user.gender or ""),
        }

    def _message_extra(self, message) -> dict[str, Any]:
        return self._sanitize_transport_extra(self.messages.load_extra(message))

    def serialize_session_event(self, event: SessionEvent) -> dict:
        try:
            data = json.loads(event.payload or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        if isinstance(data.get("extra"), dict):
            data["extra"] = self._sanitize_transport_extra(data.get("extra"))

        event_seq = int(event.event_seq or 0)
        data.setdefault("event_seq", event_seq)
        timestamp = int(event.created_at.timestamp()) if event.created_at else int(time.time())
        return {
            "type": event.type,
            "seq": event_seq,
            "msg_id": self._event_message_id(event.type, data),
            "timestamp": timestamp,
            "data": data,
        }

    def _record_session_event(
        self,
        session_id: str,
        event_type: str,
        data: dict[str, Any],
        *,
        message_id: str | None = None,
        actor_user_id: str | None = None,
    ) -> dict:
        payload = dict(data or {})
        if isinstance(payload.get("extra"), dict):
            payload["extra"] = self._sanitize_transport_extra(payload.get("extra"))
        event = self.messages.append_session_event(
            session_id,
            event_type,
            payload,
            message_id=message_id,
            actor_user_id=actor_user_id,
            commit=False,
        )
        payload["event_seq"] = int(event.event_seq or 0)
        return payload

    @staticmethod
    def _read_event_data(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "session_id": payload.get("session_id", ""),
            "message_id": payload.get("message_id", ""),
            "last_read_seq": int(payload.get("last_read_seq", 0) or 0),
            "user_id": payload.get("user_id", ""),
            "read_at": MessageService._read_timestamp(payload.get("read_at")),
        }

    @staticmethod
    def _read_timestamp(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return ensure_utc(value).isoformat()
        if isinstance(value, str):
            normalized = value.strip()
            if not normalized:
                return None
            try:
                return ensure_utc(datetime.fromisoformat(normalized.replace("Z", "+00:00"))).isoformat()
            except ValueError:
                return normalized
        return str(value)

    @staticmethod
    def _read_result(payload: dict[str, Any], event_payload: dict[str, Any] | None = None) -> dict[str, Any]:
        advanced = bool(payload.get("advanced"))
        event_payload = event_payload or {}
        return {
            "status": "read",
            "session_id": str(payload.get("session_id") or ""),
            "message_id": str(payload.get("message_id") or ""),
            "last_read_seq": int(payload.get("last_read_seq", 0) or 0),
            "user_id": str(payload.get("user_id") or ""),
            "read_at": MessageService._read_timestamp(payload.get("read_at")),
            "advanced": advanced,
            "noop": not advanced,
            "event_seq": int(event_payload.get("event_seq", 0) or 0),
        }

    @staticmethod
    def _event_message_id(event_type: str, data: dict[str, Any]) -> str:
        return str(data.get("message_id") or "")









