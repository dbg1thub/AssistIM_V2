"""Admin moments inspection API tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from auth_test_helpers import register_user
from app.core.database import SessionLocal
from app.core.errors import ErrorCode
from app.models.admin import AdminAuditLog
from app.models.moment import Moment, MomentComment, MomentLike
from app.models.user import User


MISSING_MOMENT_AUTHOR_ID = "00000000-0000-0000-0000-000000000021"
MISSING_COMMENT_MOMENT_ID = "00000000-0000-0000-0000-000000000022"
MISSING_COMMENT_USER_ID = "00000000-0000-0000-0000-000000000023"
MISSING_LIKE_MOMENT_ID = "00000000-0000-0000-0000-000000000024"
MISSING_LIKE_USER_ID = "00000000-0000-0000-0000-000000000025"


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


def _seed_moment(user_id: str, content: str) -> str:
    with SessionLocal() as db:
        moment = Moment(user_id=user_id, content=content)
        db.add(moment)
        db.commit()
        return str(moment.id)


def _seed_comment(moment_id: str, user_id: str, content: str) -> str:
    with SessionLocal() as db:
        comment = MomentComment(moment_id=moment_id, user_id=user_id, content=content)
        db.add(comment)
        db.commit()
        return str(comment.id)


def _seed_like(moment_id: str, user_id: str) -> None:
    with SessionLocal() as db:
        db.add(MomentLike(moment_id=moment_id, user_id=user_id))
        db.commit()


def test_admin_moments_forbids_non_admin(client: TestClient) -> None:
    auth_payload = _register(client, "moments-normal", "Moments Normal")

    list_response = client.get(
        "/api/v1/admin/moments",
        headers=_auth_header(auth_payload["access_token"]),
    )
    health_response = client.get(
        "/api/v1/admin/moments/health",
        headers=_auth_header(auth_payload["access_token"]),
    )

    assert list_response.status_code == 403
    assert list_response.json()["code"] == ErrorCode.FORBIDDEN
    assert health_response.status_code == 403
    assert health_response.json()["code"] == ErrorCode.FORBIDDEN


def test_admin_moments_list_supports_filters_counts_and_audit(client: TestClient) -> None:
    admin_auth = _register(client, "moments-list-admin", "Moments List Admin")
    alice = _register(client, "moments-list-alice", "Moments List Alice")
    bob = _register(client, "moments-list-bob", "Moments List Bob")
    _set_role(admin_auth["user"]["id"], "admin")
    target_moment_id = _seed_moment(alice["user"]["id"], "Alpha launch note")
    _seed_moment(bob["user"]["id"], "Beta hidden note")
    _seed_comment(target_moment_id, bob["user"]["id"], "looks good")
    _seed_like(target_moment_id, bob["user"]["id"])

    response = client.get(
        "/api/v1/admin/moments",
        headers=_auth_header(admin_auth["access_token"]),
        params={"keyword": "Alpha", "user_id": alice["user"]["id"], "page": 1, "size": 10},
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["total"] == 1
    assert payload["page"] == 1
    assert payload["size"] == 10
    item = payload["items"][0]
    assert item["id"] == target_moment_id
    assert item["user_id"] == alice["user"]["id"]
    assert item["content"] == "Alpha launch note"
    assert item["author"]["username"] == "moments-list-alice"
    assert item["comment_count"] == 1
    assert item["like_count"] == 1
    assert item["created_at"]

    with SessionLocal() as db:
        audit = db.query(AdminAuditLog).filter(AdminAuditLog.action == "admin.moments.read").one()
        assert audit.actor_user_id == admin_auth["user"]["id"]
        assert audit.success is True


def test_admin_moment_detail_comments_and_likes(client: TestClient) -> None:
    admin_auth = _register(client, "moments-detail-admin", "Moments Detail Admin")
    alice = _register(client, "moments-detail-alice", "Moments Detail Alice")
    bob = _register(client, "moments-detail-bob", "Moments Detail Bob")
    _set_role(admin_auth["user"]["id"], "admin")
    moment_id = _seed_moment(alice["user"]["id"], "Detail target")
    _seed_comment(moment_id, alice["user"]["id"], "owner comment")
    bob_comment_id = _seed_comment(moment_id, bob["user"]["id"], "bob comment")
    _seed_like(moment_id, alice["user"]["id"])
    _seed_like(moment_id, bob["user"]["id"])

    detail_response = client.get(
        f"/api/v1/admin/moments/{moment_id}",
        headers=_auth_header(admin_auth["access_token"]),
    )
    comments_response = client.get(
        f"/api/v1/admin/moments/{moment_id}/comments",
        headers=_auth_header(admin_auth["access_token"]),
        params={"user_id": bob["user"]["id"], "page": 1, "size": 10},
    )
    likes_response = client.get(
        f"/api/v1/admin/moments/{moment_id}/likes",
        headers=_auth_header(admin_auth["access_token"]),
        params={"user_id": bob["user"]["id"], "page": 1, "size": 10},
    )

    assert detail_response.status_code == 200, detail_response.text
    detail = detail_response.json()["data"]
    assert detail["id"] == moment_id
    assert detail["content"] == "Detail target"
    assert detail["author"]["username"] == "moments-detail-alice"
    assert detail["comment_count"] == 2
    assert detail["like_count"] == 2

    assert comments_response.status_code == 200, comments_response.text
    comments = comments_response.json()["data"]
    assert comments["total"] == 1
    assert comments["moment"]["id"] == moment_id
    assert comments["items"][0]["id"] == bob_comment_id
    assert comments["items"][0]["user"]["username"] == "moments-detail-bob"

    assert likes_response.status_code == 200, likes_response.text
    likes = likes_response.json()["data"]
    assert likes["total"] == 1
    assert likes["moment"]["id"] == moment_id
    assert likes["items"][0]["user_id"] == bob["user"]["id"]
    assert likes["items"][0]["user"]["nickname"] == "Moments Detail Bob"

    with SessionLocal() as db:
        assert db.query(AdminAuditLog).filter(AdminAuditLog.action == "admin.moment.read").one().success is True
        assert db.query(AdminAuditLog).filter(AdminAuditLog.action == "admin.moment.comments.read").one().success is True
        assert db.query(AdminAuditLog).filter(AdminAuditLog.action == "admin.moment.likes.read").one().success is True


def test_admin_moments_health_reports_relationship_integrity_issues(client: TestClient) -> None:
    admin_auth = _register(client, "moments-health-admin", "Moments Health Admin")
    alice = _register(client, "moments-health-alice", "Moments Health Alice")
    _set_role(admin_auth["user"]["id"], "admin")
    valid_moment_id = _seed_moment(alice["user"]["id"], "Valid moment")
    _seed_moment(MISSING_MOMENT_AUTHOR_ID, "Missing author")
    _seed_comment(MISSING_COMMENT_MOMENT_ID, alice["user"]["id"], "missing moment")
    _seed_comment(valid_moment_id, MISSING_COMMENT_USER_ID, "missing comment user")
    _seed_like(MISSING_LIKE_MOMENT_ID, alice["user"]["id"])
    _seed_like(valid_moment_id, MISSING_LIKE_USER_ID)

    response = client.get(
        "/api/v1/admin/moments/health",
        headers=_auth_header(admin_auth["access_token"]),
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["status"] == "warning"
    issue_types = {item["issue_type"] for item in payload["issues"]}
    assert "moment_author_missing" in issue_types
    assert "moment_comment_moment_missing" in issue_types
    assert "moment_comment_user_missing" in issue_types
    assert "moment_like_moment_missing" in issue_types
    assert "moment_like_user_missing" in issue_types
    assert any(
        item["issue_type"] == "moment_author_missing" and item["user_id"] == MISSING_MOMENT_AUTHOR_ID
        for item in payload["issues"]
    )
    assert any(
        item["issue_type"] == "moment_like_user_missing" and item["user_id"] == MISSING_LIKE_USER_ID
        for item in payload["issues"]
    )

    with SessionLocal() as db:
        audit = db.query(AdminAuditLog).filter(AdminAuditLog.action == "admin.moments.health.read").one()
        assert audit.actor_user_id == admin_auth["user"]["id"]
        assert audit.success is True
