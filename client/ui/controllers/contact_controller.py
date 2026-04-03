"""Controller for loading and normalizing contact-related data."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Optional

from client.core import logging
from client.core.i18n import tr
from client.core.logging import setup_logging
from client.services.contact_service import get_contact_service
from client.services.user_service import get_user_service
from client.storage.database import get_database
from client.ui.controllers.auth_controller import get_auth_controller


setup_logging()
logger = logging.get_logger(__name__)


def _looks_like_generated_user_id(value: str) -> bool:
    """Return whether a raw identifier looks like an internal UUID-style id."""
    candidate = str(value or "").strip()
    return len(candidate) >= 24 and candidate.count("-") >= 2


def _preferred_request_name(name: str, user_id: str, *, fallback_key: str, fallback_default: str) -> str:
    """Resolve a human-friendly request party name without exposing noisy generated ids."""
    display = str(name or "").strip()
    if display:
        return display

    candidate = str(user_id or "").strip()
    if candidate and not _looks_like_generated_user_id(candidate):
        return candidate
    return tr(fallback_key, fallback_default)


try:
    from pypinyin import Style, lazy_pinyin
except Exception:  # pragma: no cover - optional dependency
    Style = None
    lazy_pinyin = None


@dataclass
class ContactRecord:
    """Normalized contact data used by the contact interface."""

    id: str
    name: str
    username: str = ""
    nickname: str = ""
    avatar: str = ""
    remark: str = ""
    assistim_id: str = ""
    region: str = ""
    signature: str = ""
    email: str = ""
    phone: str = ""
    birthday: str = ""
    gender: str = ""
    status: str = ""
    category: str = "friend"
    extra: dict = field(default_factory=dict)

    @property
    def display_name(self) -> str:
        """Return the best visible name for UI rendering."""
        return self.remark or self.nickname or self.name or self.username or tr("contact.record.unnamed", "Unnamed Contact")


@dataclass
class GroupRecord:
    """Normalized group data."""

    id: str
    name: str
    avatar: str = ""
    owner_id: str = ""
    session_id: str = ""
    member_count: int = 0
    created_at: str = ""
    extra: dict = field(default_factory=dict)


@dataclass
class FriendRequestRecord:
    """Normalized pending friend request data."""

    id: str
    sender_id: str
    receiver_id: str
    message: str = ""
    status: str = "pending"
    created_at: str = ""
    sender_name: str = ""
    receiver_name: str = ""
    sender_avatar: str = ""
    receiver_avatar: str = ""
    sender_gender: str = ""
    receiver_gender: str = ""

    @property
    def display_name(self) -> str:
        """Return the best visible name for the sender."""
        return _preferred_request_name(
            self.sender_name,
            self.sender_id,
            fallback_key="contact.request.new_friend",
            fallback_default="New Friend",
        )

    def is_incoming(self, current_user_id: str) -> bool:
        """Return whether the request was received by the current user."""
        return bool(current_user_id) and self.receiver_id == current_user_id

    def is_outgoing(self, current_user_id: str) -> bool:
        """Return whether the request was sent by the current user."""
        return bool(current_user_id) and self.sender_id == current_user_id

    def counterpart_id(self, current_user_id: str) -> str:
        """Return the other party ID for this request."""
        if self.is_outgoing(current_user_id):
            return self.receiver_id
        return self.sender_id

    def counterpart_name(self, current_user_id: str) -> str:
        """Return the best display name for the other party."""
        if self.is_outgoing(current_user_id):
            return _preferred_request_name(
                self.receiver_name,
                self.receiver_id,
                fallback_key="contact.request.target_user",
                fallback_default="Target User",
            )
        return self.display_name

    def counterpart_avatar(self, current_user_id: str) -> str:
        """Return the authoritative avatar for the other party when present."""
        if self.is_outgoing(current_user_id):
            return self.receiver_avatar
        return self.sender_avatar

    def counterpart_gender(self, current_user_id: str) -> str:
        """Return the other party gender for avatar fallback rendering."""
        if self.is_outgoing(current_user_id):
            return self.receiver_gender
        return self.sender_gender

    def direction_label(self, current_user_id: str) -> str:
        """Return a UI label describing request direction."""
        if self.is_outgoing(current_user_id):
            return tr("contact.request.direction.sent", "Sent")
        if self.is_incoming(current_user_id):
            return tr("contact.request.direction.received", "Received")
        return tr("contact.request.direction.requested", "Request")

    def status_label(self) -> str:
        """Return a localized status label."""
        return {
            "pending": tr("contact.request.status.pending", "Pending"),
            "accepted": tr("contact.request.status.accepted", "Accepted"),
            "rejected": tr("contact.request.status.rejected", "Rejected"),
            "expired": tr("contact.request.status.expired", "Expired"),
        }.get(self.status, self.status or tr("contact.request.status.processed", "Processed"))

    def can_review(self, current_user_id: str) -> bool:
        """Return whether the current user can accept or reject this request."""
        return self.is_incoming(current_user_id) and self.status == "pending"


@dataclass
class UserSearchRecord:
    """Normalized searchable user data."""

    id: str
    username: str = ""
    nickname: str = ""
    avatar: str = ""
    gender: str = ""
    status: str = ""

    @property
    def display_name(self) -> str:
        """Return the best visible name."""
        return self.nickname or self.username or tr("contact.user.unknown", "Unknown User")


class ContactController:
    """Provide contact, group, and friend-request data to the UI."""

    def __init__(self) -> None:
        self._contact_service = get_contact_service()
        self._user_service = get_user_service()
        self._auth = get_auth_controller()
        self._db = get_database()

    def get_current_user_id(self) -> str:
        """Return the authenticated user id for UI flows that need directionality."""
        current_user = self._auth.current_user or {}
        return str(current_user.get("id", "") or "")

    async def load_contacts(self) -> list[ContactRecord]:
        """Load and normalize the friend list."""
        payload = await self._contact_service.fetch_friends()
        contacts: list[ContactRecord] = []

        for item in payload or []:
            username = str(item.get("username", "") or "")
            nickname = str(item.get("nickname", "") or "")
            contacts.append(
                ContactRecord(
                    id=str(item.get("id", "") or ""),
                    name=username or nickname,
                    username=username,
                    nickname=nickname,
                    avatar=str(item.get("avatar", "") or ""),
                    remark=str(item.get("remark", "") or ""),
                    assistim_id=username,
                    region=str(item.get("region", "") or ""),
                    signature=str(item.get("signature", "") or ""),
                    email=str(item.get("email", "") or ""),
                    phone=str(item.get("phone", "") or ""),
                    birthday=str(item.get("birthday", "") or ""),
                    gender=str(item.get("gender", "") or ""),
                    status=str(item.get("status", "") or ""),
                    category="friend",
                    extra=dict(item or {}),
                )
            )

        contacts.sort(key=lambda item: (self.sort_letter(item.display_name), item.display_name.lower()))
        await self._persist_contacts_cache(contacts)
        return contacts

    async def load_groups(self) -> list[GroupRecord]:
        """Load and normalize the group list."""
        payload = await self._contact_service.fetch_groups()
        groups = [
            GroupRecord(
                id=str(item.get("id", "") or ""),
                name=str(item.get("name", "") or "Untitled Group"),
                avatar=str(item.get("avatar", "") or ""),
                owner_id=str(item.get("owner_id", "") or ""),
                session_id=str(item.get("session_id", "") or ""),
                member_count=int(item.get("member_count", 0) or 0),
                created_at=str(item.get("created_at", "") or ""),
                extra=dict(item or {}),
            )
            for item in (payload or [])
        ]
        groups.sort(key=lambda item: item.name.lower())
        await self._persist_groups_cache(groups)
        return groups

    async def _persist_contacts_cache(self, contacts: list[ContactRecord]) -> None:
        """Persist one lightweight contact snapshot for local search."""
        if not getattr(self._db, "is_connected", False):
            return

        payload = [
            {
                "id": item.id,
                "name": item.name,
                "display_name": item.display_name,
                "username": item.username,
                "nickname": item.nickname,
                "remark": item.remark,
                "assistim_id": item.assistim_id,
                "region": item.region,
                "avatar": item.avatar,
                "signature": item.signature,
                "category": item.category,
                "status": item.status,
                "extra": dict(item.extra),
            }
            for item in contacts
        ]
        try:
            await self._db.replace_contacts_cache(payload)
        except Exception:
            logger.debug("Failed to persist contacts cache", exc_info=True)

    async def _persist_groups_cache(self, groups: list[GroupRecord]) -> None:
        """Persist one lightweight group snapshot for local search."""
        if not getattr(self._db, "is_connected", False):
            return

        payload = [
            {
                "id": item.id,
                "name": item.name,
                "avatar": item.avatar,
                "owner_id": item.owner_id,
                "session_id": item.session_id,
                "member_count": item.member_count,
                "member_search_text": self._group_member_search_text(item.extra),
                "extra": self._group_search_extra(item.extra),
            }
            for item in groups
        ]
        try:
            await self._db.replace_groups_cache(payload)
        except Exception:
            logger.debug("Failed to persist groups cache", exc_info=True)

    @staticmethod
    def _group_member_search_text(extra: dict) -> str:
        """Build one flattened member-search index for future group-member search."""
        previews = ContactController._group_member_previews(extra)
        return " ".join(previews)

    @staticmethod
    def _group_search_extra(extra: dict) -> dict:
        """Persist only lightweight member-preview data needed by local search UI."""
        payload = dict(extra or {})
        payload["member_previews"] = ContactController._group_member_previews(extra)
        return payload

    @staticmethod
    def _group_member_previews(extra: dict) -> list[str]:
        """Extract the first-level member display previews from one raw group payload."""
        previews: list[str] = []
        for item in list((extra or {}).get("members") or []):
            if not isinstance(item, dict):
                continue
            name = str(
                item.get("display_name", "")
                or item.get("nickname", "")
                or item.get("remark", "")
                or item.get("username", "")
                or item.get("user_id", "")
                or ""
            ).strip()
            region = str(item.get("region", "") or "").strip()
            if not name:
                continue
            previews.append(f"{name}(地区: {region})" if region else name)
        return previews

    async def load_requests(self) -> list[FriendRequestRecord]:
        """Load pending friend requests."""
        payload = await self._contact_service.fetch_friend_requests()
        requests: list[FriendRequestRecord] = []
        pending_records: list[dict[str, str]] = []
        user_ids_to_resolve: set[str] = set()
        current_user_id = self.get_current_user_id()

        for item in payload or []:
            from_user = item.get("from_user") or item.get("sender") or {}
            to_user = item.get("to_user") or item.get("receiver") or {}
            sender_id = str(item.get("sender_id", "") or from_user.get("id", "") or "")
            receiver_id = str(item.get("receiver_id", "") or to_user.get("id", "") or "")
            sender_name = (
                str(from_user.get("nickname", "") or "")
                or str(from_user.get("username", "") or "")
                or str(item.get("sender_name", "") or "")
            )
            receiver_name = (
                str(to_user.get("nickname", "") or "")
                or str(to_user.get("username", "") or "")
                or str(item.get("receiver_name", "") or "")
            )
            if sender_id and sender_id != current_user_id and not sender_name:
                user_ids_to_resolve.add(sender_id)
            if receiver_id and receiver_id != current_user_id and not receiver_name:
                user_ids_to_resolve.add(receiver_id)

            pending_records.append(
                {
                    "id": str(item.get("request_id", "") or ""),
                    "sender_id": sender_id,
                    "receiver_id": receiver_id,
                    "message": str(item.get("message", "") or ""),
                    "status": str(item.get("status", "pending") or "pending"),
                    "created_at": str(item.get("created_at", "") or ""),
                    "sender_name": sender_name,
                    "receiver_name": receiver_name,
                    "sender_avatar": str(from_user.get("avatar", "") or item.get("sender_avatar", "") or ""),
                    "receiver_avatar": str(to_user.get("avatar", "") or item.get("receiver_avatar", "") or ""),
                    "sender_gender": str(from_user.get("gender", "") or item.get("sender_gender", "") or ""),
                    "receiver_gender": str(to_user.get("gender", "") or item.get("receiver_gender", "") or ""),
                }
            )

        resolved_names = await self._load_request_user_names(user_ids_to_resolve)
        for item in pending_records:
            requests.append(
                FriendRequestRecord(
                    id=item["id"],
                    sender_id=item["sender_id"],
                    receiver_id=item["receiver_id"],
                    message=item["message"],
                    status=item["status"],
                    created_at=item["created_at"],
                    sender_name=item["sender_name"] or resolved_names.get(item["sender_id"], ""),
                    receiver_name=item["receiver_name"] or resolved_names.get(item["receiver_id"], ""),
                    sender_avatar=item["sender_avatar"],
                    receiver_avatar=item["receiver_avatar"],
                    sender_gender=item["sender_gender"],
                    receiver_gender=item["receiver_gender"],
                )
            )

        requests.sort(key=lambda item: item.created_at, reverse=True)
        return requests

    async def _load_request_user_names(self, user_ids: set[str]) -> dict[str, str]:
        """Fetch missing user names for request rows in one concurrent pass."""
        if not user_ids:
            return {}

        async def _fetch_name(user_id: str) -> tuple[str, str]:
            try:
                payload = await self._user_service.fetch_user(user_id)
            except Exception:
                logger.debug("Failed to resolve request user name for %s", user_id, exc_info=True)
                return user_id, ""
            return user_id, self._extract_user_display_name(payload)

        results = await asyncio.gather(*(_fetch_name(user_id) for user_id in user_ids))
        return {user_id: name for user_id, name in results if name}

    @staticmethod
    def _extract_user_display_name(payload: object) -> str:
        """Extract a visible display name from a user payload."""
        if not isinstance(payload, dict):
            return ""
        return str(payload.get("nickname", "") or "") or str(payload.get("username", "") or "")

    async def search_users(self, keyword: str, limit: int = 20) -> list[UserSearchRecord]:
        """Search users for the add-friend flow."""
        payload = await self._user_service.search_users(keyword, page=1, size=limit)
        items = payload.get("items", []) if isinstance(payload, dict) else []
        return [
            UserSearchRecord(
                id=str(item.get("id", "") or ""),
                username=str(item.get("username", "") or ""),
                nickname=str(item.get("nickname", "") or ""),
                avatar=str(item.get("avatar", "") or ""),
                gender=str(item.get("gender", "") or ""),
                status=str(item.get("status", "") or ""),
            )
            for item in items
        ]

    async def send_friend_request(self, user_id: str, message: str = "") -> dict:
        """Create a new friend request."""
        return await self._contact_service.send_friend_request(user_id, message)

    async def create_group(self, name: str, member_ids: list[str]) -> GroupRecord:
        """Create a new group from selected members."""
        payload = await self._contact_service.create_group(name, member_ids)
        data = dict(payload or {})
        return GroupRecord(
            id=str(data.get("id", "") or ""),
            name=str(data.get("name", "") or name),
            avatar=str(data.get("avatar", "") or ""),
            owner_id=str(data.get("owner_id", "") or ""),
            session_id=str(data.get("session_id", "") or ""),
            member_count=len(data.get("members", []) or []) or int(data.get("member_count", 0) or 0),
            created_at=str(data.get("created_at", "") or ""),
            extra=data,
        )

    async def accept_request(self, request_id: str) -> dict:
        """Accept a pending friend request."""
        return await self._contact_service.accept_friend_request(request_id)

    async def reject_request(self, request_id: str) -> dict:
        """Reject a pending friend request."""
        return await self._contact_service.reject_friend_request(request_id)

    async def remove_friend(self, friend_id: str) -> None:
        """Remove an existing friend."""
        await self._contact_service.remove_friend(friend_id)

    def group_contacts(self, contacts: list[ContactRecord]) -> dict[str, list[ContactRecord]]:
        """Group contacts by sort letter."""
        grouped: dict[str, list[ContactRecord]] = {}
        for contact in contacts:
            grouped.setdefault(self.sort_letter(contact.display_name), []).append(contact)
        return dict(sorted(grouped.items(), key=lambda item: item[0]))

    def sort_letter(self, value: str) -> str:
        """Return alphabet group key for a display name."""
        if not value:
            return "#"

        if lazy_pinyin and Style:
            try:
                letters = lazy_pinyin(value, style=Style.FIRST_LETTER)
                if letters:
                    first = (letters[0] or "#").upper()
                    if first.isascii() and first.isalpha():
                        return first
            except Exception:
                logger.debug("Falling back to non-pinyin contact sort", exc_info=True)

        first = value[0].upper()
        if first.isascii() and first.isalpha():
            return first
        return "#"


_contact_controller: Optional[ContactController] = None


def get_contact_controller() -> ContactController:
    """Return the global contact controller instance."""
    global _contact_controller
    if _contact_controller is None:
        _contact_controller = ContactController()
    return _contact_controller






