"""Admin contacts inspection API tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from auth_test_helpers import register_user
from app.core.database import SessionLocal
from app.core.errors import ErrorCode
from app.models.admin import AdminAuditLog
from app.models.user import FriendRequest, Friendship, User, UserBlock
from app.utils.time import utcnow


MISSING_USER_ID = "00000000-0000-0000-0000-000000000001"
MISSING_FRIEND_ID = "00000000-0000-0000-0000-000000000002"


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


def _seed_friend_request(
    *,
    sender_id: str,
    receiver_id: str,
    status: str = "pending",
    message: str | None = None,
) -> str:
    with SessionLocal() as db:
        request = FriendRequest(
            sender_id=sender_id,
            receiver_id=receiver_id,
            status=status,
            message=message,
        )
        db.add(request)
        db.commit()
        return str(request.id)


def _seed_friendship(*, user_id: str, friend_id: str) -> str:
    with SessionLocal() as db:
        friendship = Friendship(user_id=user_id, friend_id=friend_id)
        db.add(friendship)
        db.commit()
        return str(friendship.id)


def _seed_block(*, user_id: str, blocked_user_id: str) -> str:
    with SessionLocal() as db:
        block = UserBlock(user_id=user_id, blocked_user_id=blocked_user_id)
        db.add(block)
        db.commit()
        return str(block.id)


def test_admin_contacts_forbids_non_admin(client: TestClient) -> None:
    auth_payload = _register(client, "contacts-normal", "Contacts Normal")

    requests_response = client.get(
        "/api/v1/admin/contacts/friend-requests",
        headers=_auth_header(auth_payload["access_token"]),
    )
    friendships_response = client.get(
        "/api/v1/admin/contacts/friendships",
        headers=_auth_header(auth_payload["access_token"]),
    )
    blocks_response = client.get(
        "/api/v1/admin/contacts/blocks",
        headers=_auth_header(auth_payload["access_token"]),
    )
    health_response = client.get(
        "/api/v1/admin/contacts/health",
        headers=_auth_header(auth_payload["access_token"]),
    )

    assert requests_response.status_code == 403
    assert requests_response.json()["code"] == ErrorCode.FORBIDDEN
    assert friendships_response.status_code == 403
    assert friendships_response.json()["code"] == ErrorCode.FORBIDDEN
    assert blocks_response.status_code == 403
    assert blocks_response.json()["code"] == ErrorCode.FORBIDDEN
    assert health_response.status_code == 403
    assert health_response.json()["code"] == ErrorCode.FORBIDDEN


def test_admin_friend_requests_support_filters_pagination_and_audit(client: TestClient) -> None:
    admin_auth = _register(client, "contacts-requests-admin", "Contacts Requests Admin")
    alice = _register(client, "contacts-requests-alice", "Contacts Requests Alice")
    bob = _register(client, "contacts-requests-bob", "Contacts Requests Bob")
    charlie = _register(client, "contacts-requests-charlie", "Contacts Requests Charlie")
    _set_role(admin_auth["user"]["id"], "admin")
    target_request_id = _seed_friend_request(
        sender_id=alice["user"]["id"],
        receiver_id=bob["user"]["id"],
        status="pending",
        message="hello bob",
    )
    _seed_friend_request(
        sender_id=charlie["user"]["id"],
        receiver_id=alice["user"]["id"],
        status="rejected",
        message="ignored",
    )

    response = client.get(
        "/api/v1/admin/contacts/friend-requests",
        headers=_auth_header(admin_auth["access_token"]),
        params={
            "status": "pending",
            "sender_id": alice["user"]["id"],
            "receiver_id": bob["user"]["id"],
            "page": 1,
            "size": 10,
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["total"] == 1
    assert payload["page"] == 1
    assert payload["size"] == 10
    item = payload["items"][0]
    assert item["id"] == target_request_id
    assert item["sender_id"] == alice["user"]["id"]
    assert item["receiver_id"] == bob["user"]["id"]
    assert item["status"] == "pending"
    assert item["message"] == "hello bob"
    assert item["sender"]["username"] == "contacts-requests-alice"
    assert item["receiver"]["nickname"] == "Contacts Requests Bob"

    with SessionLocal() as db:
        audit = db.query(AdminAuditLog).filter(AdminAuditLog.action == "admin.contacts.friend_requests.read").one()
        assert audit.actor_user_id == admin_auth["user"]["id"]
        assert audit.success is True


def test_admin_friendships_support_filters_profiles_and_audit(client: TestClient) -> None:
    admin_auth = _register(client, "contacts-friends-admin", "Contacts Friends Admin")
    alice = _register(client, "contacts-friends-alice", "Contacts Friends Alice")
    bob = _register(client, "contacts-friends-bob", "Contacts Friends Bob")
    charlie = _register(client, "contacts-friends-charlie", "Contacts Friends Charlie")
    _set_role(admin_auth["user"]["id"], "admin")
    bob_friendship_id = _seed_friendship(user_id=alice["user"]["id"], friend_id=bob["user"]["id"])
    _seed_friendship(user_id=alice["user"]["id"], friend_id=charlie["user"]["id"])
    _seed_friendship(user_id=bob["user"]["id"], friend_id=alice["user"]["id"])

    response = client.get(
        "/api/v1/admin/contacts/friendships",
        headers=_auth_header(admin_auth["access_token"]),
        params={"user_id": alice["user"]["id"], "friend_id": bob["user"]["id"], "page": 1, "size": 10},
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["total"] == 1
    item = payload["items"][0]
    assert item["id"] == bob_friendship_id
    assert item["user_id"] == alice["user"]["id"]
    assert item["friend_id"] == bob["user"]["id"]
    assert item["user"]["username"] == "contacts-friends-alice"
    assert item["friend"]["nickname"] == "Contacts Friends Bob"

    with SessionLocal() as db:
        audit = db.query(AdminAuditLog).filter(AdminAuditLog.action == "admin.contacts.friendships.read").one()
        assert audit.actor_user_id == admin_auth["user"]["id"]
        assert audit.success is True


def test_admin_blocks_support_filters_profiles_and_audit(client: TestClient) -> None:
    admin_auth = _register(client, "contacts-blocks-admin", "Contacts Blocks Admin")
    alice = _register(client, "contacts-blocks-alice", "Contacts Blocks Alice")
    bob = _register(client, "contacts-blocks-bob", "Contacts Blocks Bob")
    charlie = _register(client, "contacts-blocks-charlie", "Contacts Blocks Charlie")
    _set_role(admin_auth["user"]["id"], "admin")
    bob_block_id = _seed_block(user_id=alice["user"]["id"], blocked_user_id=bob["user"]["id"])
    _seed_block(user_id=alice["user"]["id"], blocked_user_id=charlie["user"]["id"])
    _seed_block(user_id=bob["user"]["id"], blocked_user_id=alice["user"]["id"])

    response = client.get(
        "/api/v1/admin/contacts/blocks",
        headers=_auth_header(admin_auth["access_token"]),
        params={"user_id": alice["user"]["id"], "blocked_user_id": bob["user"]["id"], "page": 1, "size": 10},
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["total"] == 1
    item = payload["items"][0]
    assert item["id"] == bob_block_id
    assert item["user_id"] == alice["user"]["id"]
    assert item["blocked_user_id"] == bob["user"]["id"]
    assert item["user"]["username"] == "contacts-blocks-alice"
    assert item["blocked_user"]["nickname"] == "Contacts Blocks Bob"

    with SessionLocal() as db:
        audit = db.query(AdminAuditLog).filter(AdminAuditLog.action == "admin.contacts.blocks.read").one()
        assert audit.actor_user_id == admin_auth["user"]["id"]
        assert audit.success is True


def test_admin_contacts_health_reports_relationship_request_integrity_issues(client: TestClient) -> None:
    admin_auth = _register(client, "contacts-health-admin", "Contacts Health Admin")
    alice = _register(client, "contacts-health-alice", "Contacts Health Alice")
    bob = _register(client, "contacts-health-bob", "Contacts Health Bob")
    charlie = _register(client, "contacts-health-charlie", "Contacts Health Charlie")
    _set_role(admin_auth["user"]["id"], "admin")
    _seed_friendship(user_id=alice["user"]["id"], friend_id=bob["user"]["id"])
    _seed_friendship(user_id=charlie["user"]["id"], friend_id=charlie["user"]["id"])
    _seed_friendship(user_id=MISSING_USER_ID, friend_id=alice["user"]["id"])
    _seed_friendship(user_id=alice["user"]["id"], friend_id=MISSING_FRIEND_ID)
    _seed_friend_request(sender_id=alice["user"]["id"], receiver_id=bob["user"]["id"], status="pending")
    _seed_friend_request(sender_id=alice["user"]["id"], receiver_id=bob["user"]["id"], status="pending")
    _seed_friend_request(sender_id=bob["user"]["id"], receiver_id=alice["user"]["id"], status="unknown")
    _seed_friend_request(sender_id=charlie["user"]["id"], receiver_id=charlie["user"]["id"], status="pending")
    _seed_friend_request(sender_id=MISSING_USER_ID, receiver_id=alice["user"]["id"], status="pending")
    _seed_friend_request(sender_id=alice["user"]["id"], receiver_id=MISSING_FRIEND_ID, status="pending")
    _seed_block(user_id=alice["user"]["id"], blocked_user_id=bob["user"]["id"])
    _seed_block(user_id=charlie["user"]["id"], blocked_user_id=charlie["user"]["id"])
    _seed_block(user_id=MISSING_USER_ID, blocked_user_id=alice["user"]["id"])
    _seed_block(user_id=alice["user"]["id"], blocked_user_id=MISSING_FRIEND_ID)
    _seed_friend_request(sender_id=bob["user"]["id"], receiver_id=alice["user"]["id"], status="pending")

    response = client.get(
        "/api/v1/admin/contacts/health",
        headers=_auth_header(admin_auth["access_token"]),
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["status"] == "warning"
    issue_types = {item["issue_type"] for item in payload["issues"]}
    assert "friendship_missing_reverse" in issue_types
    assert "self_friendship" in issue_types
    assert "friendship_user_missing" in issue_types
    assert "friendship_friend_missing" in issue_types
    assert "duplicate_friend_request" in issue_types
    assert "invalid_friend_request_status" in issue_types
    assert "self_friend_request" in issue_types
    assert "friend_request_sender_missing" in issue_types
    assert "friend_request_receiver_missing" in issue_types
    assert "block_user_missing" in issue_types
    assert "block_blocked_user_missing" in issue_types
    assert "self_block" in issue_types
    assert "blocked_friendship_conflict" in issue_types
    assert "blocked_friend_request_conflict" in issue_types
    assert any(
        item["issue_type"] == "friendship_missing_reverse"
        and item["user_id"] == alice["user"]["id"]
        and item["friend_id"] == bob["user"]["id"]
        for item in payload["issues"]
    )
    assert any(
        item["issue_type"] == "duplicate_friend_request"
        and item["sender_id"] == alice["user"]["id"]
        and item["receiver_id"] == bob["user"]["id"]
        and item["status"] == "pending"
        and item["count"] == 2
        for item in payload["issues"]
    )
    assert any(
        item["issue_type"] == "blocked_friendship_conflict"
        and item["user_id"] == alice["user"]["id"]
        and item["friend_id"] == bob["user"]["id"]
        for item in payload["issues"]
    )
    assert any(
        item["issue_type"] == "blocked_friend_request_conflict"
        and item["sender_id"] == bob["user"]["id"]
        and item["receiver_id"] == alice["user"]["id"]
        and item["status"] == "pending"
        for item in payload["issues"]
    )

    with SessionLocal() as db:
        audit = db.query(AdminAuditLog).filter(AdminAuditLog.action == "admin.contacts.health.read").one()
        assert audit.actor_user_id == admin_auth["user"]["id"]
        assert audit.success is True
        assert '"issue_count"' in audit.detail_json
