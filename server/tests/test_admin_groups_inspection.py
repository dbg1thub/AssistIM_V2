"""Admin group inspection API tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from auth_test_helpers import register_user
from app.core.database import SessionLocal
from app.core.errors import ErrorCode
from app.models.admin import AdminAuditLog
from app.models.file import StoredFile
from app.models.group import Group, GroupMember
from app.models.message import Message
from app.models.session import ChatSession, SessionMember
from app.models.user import User


MISSING_SESSION_ID = "00000000-0000-0000-0000-000000000010"
MISSING_OWNER_ID = "00000000-0000-0000-0000-000000000011"
MISSING_MEMBER_ID = "00000000-0000-0000-0000-000000000012"
MISSING_MESSAGE_ID = "00000000-0000-0000-0000-000000000013"
MISSING_FILE_ID = "00000000-0000-0000-0000-000000000014"


def _register(client: TestClient, username: str, nickname: str) -> dict:
    return register_user(client, username, nickname=nickname)


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _set_role(user_id: str, role: str) -> None:
    with SessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        user.role = role
        db.add(user)
        db.commit()


def _seed_group(
    *,
    name: str,
    owner_id: str,
    session_type: str = "group",
    session_id: str | None = None,
    group_member_ids: list[str] | None = None,
    session_member_ids: list[str] | None = None,
    member_roles: dict[str, str] | None = None,
    announcement: str = "",
    announcement_message_id: str | None = None,
    avatar_file_id: str | None = None,
) -> tuple[str, str]:
    with SessionLocal() as db:
        resolved_session_id = session_id
        if resolved_session_id is None:
            session = ChatSession(type=session_type, name=name, encryption_mode="plain")
            db.add(session)
            db.flush()
            resolved_session_id = str(session.id)

        group = Group(
            name=name,
            owner_id=owner_id,
            session_id=resolved_session_id,
            announcement=announcement,
            announcement_message_id=announcement_message_id,
            avatar_file_id=avatar_file_id,
            avatar_kind="custom" if avatar_file_id else "generated",
        )
        db.add(group)
        db.flush()

        roles = member_roles or {}
        for user_id in group_member_ids or []:
            db.add(GroupMember(group_id=group.id, user_id=user_id, role=roles.get(user_id, "member")))
        for user_id in session_member_ids or []:
            db.add(SessionMember(session_id=resolved_session_id, user_id=user_id))
        db.commit()
        return str(group.id), resolved_session_id


def test_admin_groups_forbids_non_admin(client: TestClient) -> None:
    auth_payload = _register(client, "groups-normal", "Groups Normal")

    list_response = client.get(
        "/api/v1/admin/groups",
        headers=_auth_header(auth_payload["access_token"]),
    )
    health_response = client.get(
        "/api/v1/admin/groups/health",
        headers=_auth_header(auth_payload["access_token"]),
    )

    assert list_response.status_code == 403
    assert list_response.json()["code"] == ErrorCode.FORBIDDEN
    assert health_response.status_code == 403
    assert health_response.json()["code"] == ErrorCode.FORBIDDEN


def test_admin_groups_list_supports_filters_counts_and_audit(client: TestClient) -> None:
    admin_auth = _register(client, "groups-list-admin", "Groups List Admin")
    owner = _register(client, "groups-list-owner", "Groups List Owner")
    bob = _register(client, "groups-list-bob", "Groups List Bob")
    _set_role(admin_auth["user"]["id"], "admin")
    target_group_id, target_session_id = _seed_group(
        name="Alpha Ops",
        owner_id=owner["user"]["id"],
        group_member_ids=[owner["user"]["id"], bob["user"]["id"]],
        session_member_ids=[owner["user"]["id"], bob["user"]["id"]],
        member_roles={owner["user"]["id"]: "owner"},
    )
    _seed_group(
        name="Beta Ops",
        owner_id=bob["user"]["id"],
        group_member_ids=[bob["user"]["id"]],
        session_member_ids=[bob["user"]["id"]],
        member_roles={bob["user"]["id"]: "owner"},
    )

    response = client.get(
        "/api/v1/admin/groups",
        headers=_auth_header(admin_auth["access_token"]),
        params={"keyword": "Alpha", "owner_id": owner["user"]["id"], "page": 1, "size": 10},
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["total"] == 1
    assert payload["page"] == 1
    assert payload["size"] == 10
    item = payload["items"][0]
    assert item["id"] == target_group_id
    assert item["name"] == "Alpha Ops"
    assert item["owner_id"] == owner["user"]["id"]
    assert item["owner"]["username"] == "groups-list-owner"
    assert item["session"]["id"] == target_session_id
    assert item["session"]["type"] == "group"
    assert item["member_count"] == 2
    assert item["session_member_count"] == 2

    with SessionLocal() as db:
        audit = db.query(AdminAuditLog).filter(AdminAuditLog.action == "admin.groups.read").one()
        assert audit.actor_user_id == admin_auth["user"]["id"]
        assert audit.success is True


def test_admin_group_detail_and_members_support_filters(client: TestClient) -> None:
    admin_auth = _register(client, "groups-detail-admin", "Groups Detail Admin")
    owner = _register(client, "groups-detail-owner", "Groups Detail Owner")
    bob = _register(client, "groups-detail-bob", "Groups Detail Bob")
    charlie = _register(client, "groups-detail-charlie", "Groups Detail Charlie")
    _set_role(admin_auth["user"]["id"], "admin")
    group_id, session_id = _seed_group(
        name="Detail Group",
        owner_id=owner["user"]["id"],
        group_member_ids=[owner["user"]["id"], bob["user"]["id"], charlie["user"]["id"]],
        session_member_ids=[owner["user"]["id"], bob["user"]["id"], charlie["user"]["id"]],
        member_roles={owner["user"]["id"]: "owner", bob["user"]["id"]: "admin"},
        announcement="Deploy at 6",
    )

    detail_response = client.get(
        f"/api/v1/admin/groups/{group_id}",
        headers=_auth_header(admin_auth["access_token"]),
    )
    members_response = client.get(
        f"/api/v1/admin/groups/{group_id}/members",
        headers=_auth_header(admin_auth["access_token"]),
        params={"role": "admin", "user_id": bob["user"]["id"], "page": 1, "size": 10},
    )

    assert detail_response.status_code == 200, detail_response.text
    detail = detail_response.json()["data"]
    assert detail["id"] == group_id
    assert detail["session"]["id"] == session_id
    assert detail["announcement"] == "Deploy at 6"
    assert detail["owner"]["nickname"] == "Groups Detail Owner"
    assert detail["member_count"] == 3
    assert detail["session_member_count"] == 3

    assert members_response.status_code == 200, members_response.text
    members = members_response.json()["data"]
    assert members["total"] == 1
    assert members["items"][0]["user_id"] == bob["user"]["id"]
    assert members["items"][0]["role"] == "admin"
    assert members["items"][0]["user"]["username"] == "groups-detail-bob"

    with SessionLocal() as db:
        assert db.query(AdminAuditLog).filter(AdminAuditLog.action == "admin.group.read").one().success is True
        assert db.query(AdminAuditLog).filter(AdminAuditLog.action == "admin.group.members.read").one().success is True


def test_admin_groups_health_reports_group_relationship_integrity_issues(client: TestClient) -> None:
    admin_auth = _register(client, "groups-health-admin", "Groups Health Admin")
    owner = _register(client, "groups-health-owner", "Groups Health Owner")
    bob = _register(client, "groups-health-bob", "Groups Health Bob")
    charlie = _register(client, "groups-health-charlie", "Groups Health Charlie")
    _set_role(admin_auth["user"]["id"], "admin")

    _seed_group(
        name="Missing Session",
        owner_id=owner["user"]["id"],
        session_id=MISSING_SESSION_ID,
        group_member_ids=[owner["user"]["id"]],
        session_member_ids=[],
    )
    _seed_group(
        name="Private Session",
        owner_id=owner["user"]["id"],
        session_type="private",
        group_member_ids=[owner["user"]["id"]],
        session_member_ids=[owner["user"]["id"]],
    )
    _seed_group(
        name="Missing Owner",
        owner_id=MISSING_OWNER_ID,
        group_member_ids=[owner["user"]["id"]],
        session_member_ids=[owner["user"]["id"]],
    )
    _seed_group(
        name="Owner Not Member",
        owner_id=owner["user"]["id"],
        group_member_ids=[bob["user"]["id"]],
        session_member_ids=[bob["user"]["id"]],
    )
    _seed_group(name="No Members", owner_id=owner["user"]["id"], group_member_ids=[], session_member_ids=[])
    _seed_group(
        name="Missing Group Member User",
        owner_id=owner["user"]["id"],
        group_member_ids=[owner["user"]["id"], MISSING_MEMBER_ID],
        session_member_ids=[owner["user"]["id"], MISSING_MEMBER_ID],
    )
    _seed_group(
        name="Group Member Missing Session Member",
        owner_id=owner["user"]["id"],
        group_member_ids=[owner["user"]["id"], bob["user"]["id"]],
        session_member_ids=[owner["user"]["id"]],
    )
    _seed_group(
        name="Session Member Missing Group Member",
        owner_id=owner["user"]["id"],
        group_member_ids=[owner["user"]["id"]],
        session_member_ids=[owner["user"]["id"], bob["user"]["id"]],
    )
    _seed_group(
        name="Missing Announcement",
        owner_id=owner["user"]["id"],
        group_member_ids=[owner["user"]["id"]],
        session_member_ids=[owner["user"]["id"]],
        announcement="Missing message",
        announcement_message_id=MISSING_MESSAGE_ID,
    )
    with SessionLocal() as db:
        other_session = ChatSession(type="group", name="Other Session")
        db.add(other_session)
        db.flush()
        other_message = Message(
            session_id=other_session.id,
            sender_id=charlie["user"]["id"],
            session_seq=1,
            content="wrong session",
        )
        db.add(other_message)
        db.commit()
        wrong_message_id = str(other_message.id)
    _seed_group(
        name="Announcement Mismatch",
        owner_id=owner["user"]["id"],
        group_member_ids=[owner["user"]["id"]],
        session_member_ids=[owner["user"]["id"]],
        announcement="Wrong message",
        announcement_message_id=wrong_message_id,
    )
    _seed_group(
        name="Missing Avatar File",
        owner_id=owner["user"]["id"],
        group_member_ids=[owner["user"]["id"]],
        session_member_ids=[owner["user"]["id"]],
        avatar_file_id=MISSING_FILE_ID,
    )

    response = client.get(
        "/api/v1/admin/groups/health",
        headers=_auth_header(admin_auth["access_token"]),
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["status"] == "warning"
    issue_types = {item["issue_type"] for item in payload["issues"]}
    assert "group_session_missing" in issue_types
    assert "group_session_type_invalid" in issue_types
    assert "group_owner_missing" in issue_types
    assert "group_owner_not_member" in issue_types
    assert "group_without_members" in issue_types
    assert "group_member_user_missing" in issue_types
    assert "group_member_missing_session_member" in issue_types
    assert "session_member_missing_group_member" in issue_types
    assert "group_announcement_message_missing" in issue_types
    assert "group_announcement_message_session_mismatch" in issue_types
    assert "group_avatar_file_missing" in issue_types
    assert any(
        item["issue_type"] == "group_member_user_missing" and item["user_id"] == MISSING_MEMBER_ID
        for item in payload["issues"]
    )
    assert any(
        item["issue_type"] == "group_announcement_message_session_mismatch"
        and item["announcement_message_id"] == wrong_message_id
        for item in payload["issues"]
    )

    with SessionLocal() as db:
        audit = db.query(AdminAuditLog).filter(AdminAuditLog.action == "admin.groups.health.read").one()
        assert audit.actor_user_id == admin_auth["user"]["id"]
        assert audit.success is True
