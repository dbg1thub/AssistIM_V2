"""Admin chat inspection API tests."""

from __future__ import annotations

from sqlalchemy import text
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.core.errors import ErrorCode
from app.models.admin import AdminAuditLog
from app.models.message import Message
from app.models.session import ChatSession, SessionMember
from app.models.user import User
from app.utils.time import utcnow


def _register(client: TestClient, username: str, nickname: str) -> dict:
    response = client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": "secret123", "nickname": nickname},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _set_role(user_id: str, role: str) -> None:
    with SessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        user.role = role
        db.add(user)
        db.commit()


def _seed_session(
    *,
    name: str,
    session_type: str = "private",
    member_ids: list[str],
    is_ai_session: bool = False,
    encryption_mode: str = "plain",
    messages: list[dict] | None = None,
    last_message_seq: int | None = None,
) -> str:
    with SessionLocal() as db:
        session = ChatSession(
            name=name,
            type=session_type,
            is_ai_session=is_ai_session,
            encryption_mode=encryption_mode,
        )
        db.add(session)
        db.flush()
        for member_id in member_ids:
            db.add(SessionMember(session_id=session.id, user_id=member_id))
        max_seq = 0
        for payload in messages or []:
            message = Message(
                session_id=session.id,
                sender_id=payload["sender_id"],
                session_seq=payload["session_seq"],
                type=payload.get("type", "text"),
                content=payload.get("content", ""),
                status=payload.get("status", "sent"),
                extra_json=payload.get("extra_json", "{}"),
            )
            db.add(message)
            max_seq = max(max_seq, int(payload["session_seq"]))
        session.last_message_seq = max_seq if last_message_seq is None else last_message_seq
        db.commit()
        return str(session.id)


def test_admin_chat_inspection_forbids_non_admin(client: TestClient) -> None:
    auth_payload = _register(client, "chat-normal", "Chat Normal")

    list_response = client.get(
        "/api/v1/admin/chat/sessions",
        headers=_auth_header(auth_payload["access_token"]),
    )
    health_response = client.get(
        "/api/v1/admin/chat/health",
        headers=_auth_header(auth_payload["access_token"]),
    )

    assert list_response.status_code == 403
    assert list_response.json()["code"] == ErrorCode.FORBIDDEN
    assert health_response.status_code == 403
    assert health_response.json()["code"] == ErrorCode.FORBIDDEN


def test_admin_chat_sessions_support_filters_pagination_and_audit(client: TestClient) -> None:
    admin_auth = _register(client, "chat-list-admin", "Chat List Admin")
    alice = _register(client, "chat-list-alice", "Chat List Alice")
    bob = _register(client, "chat-list-bob", "Chat List Bob")
    _set_role(admin_auth["user"]["id"], "admin")
    target_session_id = _seed_session(
        name="Alpha private",
        session_type="private",
        member_ids=[alice["user"]["id"], bob["user"]["id"]],
        encryption_mode="e2ee_private",
        messages=[
            {"sender_id": alice["user"]["id"], "session_seq": 1, "content": "hello"},
            {"sender_id": bob["user"]["id"], "session_seq": 2, "content": "reply"},
        ],
    )
    _seed_session(
        name="Beta group",
        session_type="group",
        member_ids=[bob["user"]["id"]],
        messages=[{"sender_id": bob["user"]["id"], "session_seq": 1, "content": "group"}],
    )

    response = client.get(
        "/api/v1/admin/chat/sessions",
        headers=_auth_header(admin_auth["access_token"]),
        params={"type": "private", "keyword": "Alpha", "user_id": alice["user"]["id"], "page": 1, "size": 10},
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["total"] == 1
    assert payload["page"] == 1
    assert payload["size"] == 10
    item = payload["items"][0]
    assert item["id"] == target_session_id
    assert item["type"] == "private"
    assert item["name"] == "Alpha private"
    assert item["member_count"] == 2
    assert item["message_count"] == 2
    assert item["last_message"]["content"] == "reply"
    assert item["last_message"]["session_seq"] == 2
    assert item["encryption_mode"] == "e2ee_private"

    with SessionLocal() as db:
        audit = db.query(AdminAuditLog).filter(AdminAuditLog.action == "admin.chat.sessions.read").one()
        assert audit.actor_user_id == admin_auth["user"]["id"]
        assert audit.success is True


def test_admin_chat_session_detail_reports_members_and_counts(client: TestClient) -> None:
    admin_auth = _register(client, "chat-detail-admin", "Chat Detail Admin")
    alice = _register(client, "chat-detail-alice", "Chat Detail Alice")
    bob = _register(client, "chat-detail-bob", "Chat Detail Bob")
    _set_role(admin_auth["user"]["id"], "admin")
    session_id = _seed_session(
        name="Detail session",
        member_ids=[alice["user"]["id"], bob["user"]["id"]],
        messages=[
            {"sender_id": alice["user"]["id"], "session_seq": 1, "content": "first"},
            {"sender_id": bob["user"]["id"], "session_seq": 2, "content": "second"},
        ],
    )

    response = client.get(
        f"/api/v1/admin/chat/sessions/{session_id}",
        headers=_auth_header(admin_auth["access_token"]),
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["id"] == session_id
    assert payload["member_count"] == 2
    assert payload["message_count"] == 2
    assert payload["last_message"]["content"] == "second"
    members = {item["user_id"]: item for item in payload["members"]}
    assert members[alice["user"]["id"]]["username"] == "chat-detail-alice"
    assert members[bob["user"]["id"]]["nickname"] == "Chat Detail Bob"


def test_admin_chat_messages_are_paginated_and_ordered_by_session_seq(client: TestClient) -> None:
    admin_auth = _register(client, "chat-msg-admin", "Chat Msg Admin")
    alice = _register(client, "chat-msg-alice", "Chat Msg Alice")
    _set_role(admin_auth["user"]["id"], "admin")
    session_id = _seed_session(
        name="Messages session",
        member_ids=[alice["user"]["id"]],
        messages=[
            {"sender_id": alice["user"]["id"], "session_seq": 3, "content": "third"},
            {"sender_id": alice["user"]["id"], "session_seq": 1, "content": "first"},
            {"sender_id": alice["user"]["id"], "session_seq": 2, "type": "image", "content": "image"},
        ],
    )

    response = client.get(
        f"/api/v1/admin/chat/sessions/{session_id}/messages",
        headers=_auth_header(admin_auth["access_token"]),
        params={"page": 1, "size": 2},
    )
    image_response = client.get(
        f"/api/v1/admin/chat/sessions/{session_id}/messages",
        headers=_auth_header(admin_auth["access_token"]),
        params={"type": "image", "page": 1, "size": 10},
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["total"] == 3
    assert [item["session_seq"] for item in payload["items"]] == [1, 2]
    assert [item["content"] for item in payload["items"]] == ["first", "image"]
    assert image_response.status_code == 200, image_response.text
    image_payload = image_response.json()["data"]
    assert image_payload["total"] == 1
    assert image_payload["items"][0]["type"] == "image"


def test_admin_chat_health_reports_orphans_gaps_duplicates_and_seq_mismatches(client: TestClient) -> None:
    admin_auth = _register(client, "chat-health-admin", "Chat Health Admin")
    alice = _register(client, "chat-health-alice", "Chat Health Alice")
    bob = _register(client, "chat-health-bob", "Chat Health Bob")
    _set_role(admin_auth["user"]["id"], "admin")
    gap_session_id = _seed_session(
        name="Gap session",
        member_ids=[alice["user"]["id"]],
        messages=[
            {"sender_id": alice["user"]["id"], "session_seq": 1, "content": "first"},
            {"sender_id": alice["user"]["id"], "session_seq": 3, "content": "third"},
        ],
        last_message_seq=9,
    )
    memberless_session_id = _seed_session(name="Memberless session", member_ids=[])

    with SessionLocal() as db:
        db.execute(text("DROP INDEX IF EXISTS idx_messages_session_seq"))
        duplicate_session = ChatSession(name="Duplicate session", type="private", last_message_seq=2)
        db.add(duplicate_session)
        db.flush()
        db.add(SessionMember(session_id=duplicate_session.id, user_id=alice["user"]["id"]))
        db.add_all(
            [
                Message(session_id=duplicate_session.id, sender_id=alice["user"]["id"], session_seq=1, content="one"),
                Message(session_id=duplicate_session.id, sender_id=alice["user"]["id"], session_seq=1, content="duplicate"),
                Message(session_id=gap_session_id, sender_id=bob["user"]["id"], session_seq=4, content="not member"),
                Message(
                    session_id="00000000-0000-0000-0000-000000000000",
                    sender_id=alice["user"]["id"],
                    session_seq=1,
                    content="orphan",
                    created_at=utcnow(),
                    updated_at=utcnow(),
                ),
            ]
        )
        db.commit()
        duplicate_session_id = str(duplicate_session.id)

    response = client.get(
        "/api/v1/admin/chat/health",
        headers=_auth_header(admin_auth["access_token"]),
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["status"] == "warning"
    issue_types = {item["issue_type"] for item in payload["issues"]}
    assert "orphan_message" in issue_types
    assert "session_without_members" in issue_types
    assert "message_sender_not_member" in issue_types
    assert "duplicate_session_seq" in issue_types
    assert "session_seq_gap" in issue_types
    assert "last_message_seq_mismatch" in issue_types
    assert any(
        item["issue_type"] == "session_without_members" and item["session_id"] == memberless_session_id
        for item in payload["issues"]
    )
    assert any(
        item["issue_type"] == "duplicate_session_seq" and item["session_id"] == duplicate_session_id
        for item in payload["issues"]
    )
    assert any(
        item["issue_type"] == "session_seq_gap"
        and item["session_id"] == gap_session_id
        and item["missing_session_seq"] == [2]
        for item in payload["issues"]
    )
    assert any(
        item["issue_type"] == "last_message_seq_mismatch"
        and item["session_id"] == gap_session_id
        and item["expected_last_message_seq"] == 4
        and item["recorded_last_message_seq"] == 9
        for item in payload["issues"]
    )

    with SessionLocal() as db:
        audit = db.query(AdminAuditLog).filter(AdminAuditLog.action == "admin.chat.health.read").one()
        assert audit.actor_user_id == admin_auth["user"]["id"]
        assert audit.success is True
