from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from app.services.friend_service import FriendService
from app.services.user_service import UserService


class _FakeFriendRepo:
    def __init__(self) -> None:
        self.friendships = [SimpleNamespace(friend_id="user-2"), SimpleNamespace(friend_id="user-3")]
        self.requests = [
            SimpleNamespace(
                id="req-1",
                sender_id="user-2",
                receiver_id="user-1",
                status="pending",
                message="hello",
                created_at=datetime(2026, 4, 14, 10, 0, 0),
            )
        ]

    def list_friends(self, user_id: str):
        assert user_id == "user-1"
        return list(self.friendships)

    def list_requests_for_user(self, user_id: str):
        assert user_id == "user-1"
        return list(self.requests)


class _FakeUserRepo:
    def __init__(self) -> None:
        self.list_users_by_ids_calls: list[list[str]] = []
        self.users = {
            "user-2": SimpleNamespace(id="user-2", username="bob", nickname="Bob", avatar="/avatars/bob.png", avatar_kind="custom", gender="male"),
            "user-3": SimpleNamespace(id="user-3", username="charlie", nickname="Charlie", avatar="/avatars/charlie.png", avatar_kind="custom", gender="male"),
        }

    def list_users_by_ids(self, user_ids: list[str]):
        self.list_users_by_ids_calls.append(list(user_ids))
        return {user_id: self.users[user_id] for user_id in user_ids if user_id in self.users}

    def get_by_id(self, user_id: str):
        raise AssertionError("bulk loaders should be used instead of get_by_id")


class _FakeAvatarService:
    def resolve_user_avatar_url(self, user) -> str | None:
        return getattr(user, "avatar", None)


class _FakeSessionRepo:
    def __init__(self) -> None:
        self.sessions = [
            SimpleNamespace(id="session-1", type="direct", is_ai_session=False),
            SimpleNamespace(id="session-2", type="group", is_ai_session=False),
        ]
        self.members_by_session = {
            "session-1": [SimpleNamespace(user_id="user-1"), SimpleNamespace(user_id="user-2")],
            "session-2": [SimpleNamespace(user_id="user-1"), SimpleNamespace(user_id="user-3")],
        }
        self.list_members_for_sessions_calls: list[list[str]] = []

    def list_user_sessions(self, user_id: str):
        assert user_id == "user-1"
        return list(self.sessions)

    def list_members_for_sessions(self, session_ids: list[str]):
        self.list_members_for_sessions_calls.append(list(session_ids))
        return {session_id: list(self.members_by_session.get(session_id, [])) for session_id in session_ids}

    def list_member_ids(self, session_id: str):
        raise AssertionError("record_profile_update_events should use list_members_for_sessions")


class _FakeMessageRepo:
    def __init__(self) -> None:
        self.append_calls: list[tuple[str, str, dict, str]] = []

    def append_session_event(self, session_id: str, event_type: str, payload: dict, *, actor_user_id: str, commit: bool):
        self.append_calls.append((session_id, event_type, dict(payload), actor_user_id))
        return SimpleNamespace(event_seq=len(self.append_calls))


class _FakeDB:
    def __init__(self) -> None:
        self.commit_calls = 0

    def commit(self) -> None:
        self.commit_calls += 1


def test_friend_service_uses_bulk_user_loaders_for_friend_and_request_lists() -> None:
    service = FriendService(db=_FakeDB())
    fake_users = _FakeUserRepo()
    service.friends = _FakeFriendRepo()
    service.users = fake_users
    service.user_payloads = UserService(db=None)
    service.user_payloads.users = fake_users
    service.user_payloads.avatars = _FakeAvatarService()

    friends_payload = service.list_friends(SimpleNamespace(id="user-1"))
    requests_payload = service.list_requests(SimpleNamespace(id="user-1"))

    assert [item["id"] for item in friends_payload] == ["user-2", "user-3"]
    assert requests_payload[0]["sender"]["id"] == "user-2"
    assert requests_payload[0]["receiver"] == {}
    assert fake_users.list_users_by_ids_calls == [["user-2", "user-3"], ["user-2", "user-1"]]


def test_user_service_record_profile_update_events_uses_bulk_member_lookup_and_noop_update_short_circuits() -> None:
    fake_db = _FakeDB()
    service = UserService(db=fake_db)
    service.sessions = _FakeSessionRepo()
    service.messages = _FakeMessageRepo()
    service.avatars = _FakeAvatarService()
    service.users = SimpleNamespace(
        update=lambda user, **fields: SimpleNamespace(**{**user.__dict__, **fields}),
    )
    current_user = SimpleNamespace(
        id="user-1",
        username="alice",
        nickname="Alice",
        avatar="/avatars/alice.png",
        avatar_kind="custom",
        gender="female",
        email=None,
        phone=None,
        birthday=None,
        region=None,
        signature=None,
        status="online",
        created_at=None,
        updated_at=None,
    )

    payload, changed = service.update_me(current_user, nickname="Alice")
    assert changed is False
    assert payload["nickname"] == "Alice"

    event_result = service.record_profile_update_events(current_user)

    assert fake_db.commit_calls == 1
    assert service.sessions.list_members_for_sessions_calls == [["session-1", "session-2"]]
    assert [item[0] for item in service.messages.append_calls] == ["session-1", "session-2"]
    assert event_result["participant_ids"] == ["user-1", "user-2", "user-3"]
