"""Controller for loading and normalizing contact-related data."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from client.core import logging
from client.core.i18n import tr
from client.core.logging import setup_logging
from client.network.http_client import get_http_client
from client.ui.controllers.auth_controller import get_auth_controller


setup_logging()
logger = logging.get_logger(__name__)


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

    @property
    def display_name(self) -> str:
        """Return the best visible name for the sender."""
        return self.sender_name or self.sender_id or tr("contact.request.new_friend", "New Friend")

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
            return self.receiver_id or tr("contact.request.target_user", "Target User")
        return self.display_name

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
    status: str = ""

    @property
    def display_name(self) -> str:
        """Return the best visible name."""
        return self.nickname or self.username or tr("contact.user.unknown", "Unknown User")


class ContactController:
    """Provide contact, group, and friend-request data to the UI."""

    def __init__(self) -> None:
        self._http = get_http_client()
        self._auth = get_auth_controller()

    def get_current_user_id(self) -> str:
        """Return the authenticated user id for UI flows that need directionality."""
        current_user = self._auth.current_user or {}
        return str(current_user.get("id", "") or "")

    async def load_contacts(self) -> list[ContactRecord]:
        """Load and normalize the friend list."""
        payload = await self._http.get("/friends")
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
        return contacts

    async def load_groups(self) -> list[GroupRecord]:
        """Load and normalize the group list."""
        payload = await self._http.get("/groups")
        groups = [
            GroupRecord(
                id=str(item.get("id", "") or ""),
                name=str(item.get("name", "") or "Untitled Group"),
                owner_id=str(item.get("owner_id", "") or ""),
                session_id=str(item.get("session_id", "") or ""),
                member_count=int(item.get("member_count", 0) or 0),
                created_at=str(item.get("created_at", "") or ""),
                extra=dict(item or {}),
            )
            for item in (payload or [])
        ]
        groups.sort(key=lambda item: item.name.lower())
        return groups

    async def load_requests(self) -> list[FriendRequestRecord]:
        """Load pending friend requests."""
        payload = await self._http.get("/friends/requests")
        requests: list[FriendRequestRecord] = []

        for item in payload or []:
            from_user = item.get("from_user") or item.get("sender") or {}
            sender_name = (
                str(from_user.get("nickname", "") or "")
                or str(from_user.get("username", "") or "")
                or str(item.get("sender_name", "") or "")
            )
            requests.append(
                FriendRequestRecord(
                    id=str(item.get("id", "") or ""),
                    sender_id=str(item.get("sender_id", "") or ""),
                    receiver_id=str(item.get("receiver_id", "") or ""),
                    message=str(item.get("message", "") or ""),
                    status=str(item.get("status", "pending") or "pending"),
                    created_at=str(item.get("created_at", "") or ""),
                    sender_name=sender_name,
                )
            )

        requests.sort(key=lambda item: item.created_at, reverse=True)
        return requests

    async def search_users(self, keyword: str, limit: int = 20) -> list[UserSearchRecord]:
        """Search users for the add-friend flow."""
        payload = await self._http.get(
            "/users/search",
            params={
                "keyword": keyword,
                "page": 1,
                "size": limit,
            },
        )
        items = payload.get("items", []) if isinstance(payload, dict) else []
        return [
            UserSearchRecord(
                id=str(item.get("id", "") or ""),
                username=str(item.get("username", "") or ""),
                nickname=str(item.get("nickname", "") or ""),
                avatar=str(item.get("avatar", "") or ""),
                status=str(item.get("status", "") or ""),
            )
            for item in items
        ]

    async def send_friend_request(self, user_id: str, message: str = "") -> dict:
        """Create a new friend request."""
        return await self._http.post(
            "/friends/requests",
            json={
                "receiver_id": user_id,
                "message": message,
            },
        )

    async def create_group(self, name: str, member_ids: list[str]) -> GroupRecord:
        """Create a new group from selected members."""
        payload = await self._http.post(
            "/groups",
            json={
                "name": name,
                "member_ids": member_ids,
            },
        )
        data = dict(payload or {})
        return GroupRecord(
            id=str(data.get("id", "") or ""),
            name=str(data.get("name", "") or name),
            owner_id=str(data.get("owner_id", "") or ""),
            session_id=str(data.get("session_id", "") or ""),
            member_count=len(data.get("members", []) or []) or int(data.get("member_count", 0) or 0),
            created_at=str(data.get("created_at", "") or ""),
            extra=data,
        )

    async def accept_request(self, request_id: str) -> dict:
        """Accept a pending friend request."""
        return await self._http.post(f"/friends/requests/{request_id}/accept", json={})

    async def reject_request(self, request_id: str) -> dict:
        """Reject a pending friend request."""
        return await self._http.post(f"/friends/requests/{request_id}/reject", json={})

    async def remove_friend(self, friend_id: str) -> None:
        """Remove an existing friend."""
        await self._http.delete(f"/friends/{friend_id}")

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
