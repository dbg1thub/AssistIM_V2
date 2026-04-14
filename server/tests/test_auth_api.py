"""Authentication API tests."""

from __future__ import annotations

from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.core.errors import ErrorCode
from app.websocket.manager import connection_manager


def test_auth_register_login_refresh_and_me(client: TestClient, auth_header) -> None:
    register_response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "alice",
            "password": "secret123",
            "nickname": "Alice",
        },
    )
    assert register_response.status_code == 200
    register_payload = register_response.json()
    assert register_payload["code"] == 0
    register_user = register_payload["data"]["user"]
    assert register_user["username"] == "alice"
    assert register_payload["data"]["token_type"] == "Bearer"
    assert register_user["email"] is None
    assert register_user["birthday"] is None
    assert register_user["gender"] is None
    assert register_user["avatar"].startswith("/uploads/default_avatars/avatar_default_")

    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "username": "alice",
            "password": "secret123",
        },
    )
    assert login_response.status_code == 200
    login_payload = login_response.json()["data"]
    assert login_payload["user"]["nickname"] == "Alice"
    assert login_payload["user"]["phone"] is None
    assert login_payload["user"]["avatar"] == register_user["avatar"]

    # A new login should revoke the older register-issued session.
    stale_me_response = client.get(
        "/api/v1/auth/me",
        headers=auth_header(register_payload["data"]["access_token"]),
    )
    assert stale_me_response.status_code == 401

    stale_refresh_response = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": register_payload["data"]["refresh_token"]},
    )
    assert stale_refresh_response.status_code == 401

    refresh_response = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": login_payload["refresh_token"]},
    )
    assert refresh_response.status_code == 200
    assert refresh_response.json()["data"]["access_token"]

    me_response = client.get(
        "/api/v1/auth/me",
        headers=auth_header(login_payload["access_token"]),
    )
    assert me_response.status_code == 200
    me_payload = me_response.json()["data"]
    assert me_payload["username"] == "alice"
    assert me_payload["nickname"] == "Alice"
    assert me_payload["region"] is None
    assert me_payload["signature"] is None
    assert me_payload["gender"] is None
    assert me_payload["avatar"] == register_user["avatar"]

    logout_response = client.delete(
        "/api/v1/auth/session",
        headers=auth_header(login_payload["access_token"]),
    )
    assert logout_response.status_code == 204

    post_logout_me = client.get(
        "/api/v1/auth/me",
        headers=auth_header(login_payload["access_token"]),
    )
    assert post_logout_me.status_code == 401


def test_update_me_extended_profile_fields(client: TestClient, auth_header) -> None:
    register_response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "carla",
            "password": "secret123",
            "nickname": "Carla",
        },
    )
    assert register_response.status_code == 200
    access_token = register_response.json()["data"]["access_token"]

    update_response = client.put(
        "/api/v1/users/me",
        headers=auth_header(access_token),
        json={
            "nickname": "Carla QA",
            "email": "carla@example.com",
            "phone": "+82-10-1111-2222",
            "birthday": "1996-02-21",
            "region": "Seoul",
            "signature": "Testing profile updates.",
            "gender": "female",
            "status": "online",
        },
    )
    assert update_response.status_code == 200
    payload = update_response.json()["data"]
    assert payload["nickname"] == "Carla QA"
    assert payload["email"] == "carla@example.com"
    assert payload["phone"] == "+82-10-1111-2222"
    assert payload["birthday"] == "1996-02-21"
    assert payload["region"] == "Seoul"
    assert payload["signature"] == "Testing profile updates."
    assert payload["gender"] == "female"
    assert payload["status"] == "online"

    clear_response = client.put(
        "/api/v1/users/me",
        headers=auth_header(access_token),
        json={
            "email": "",
            "phone": "",
            "birthday": "",
            "region": "",
            "signature": "",
            "gender": "",
        },
    )
    assert clear_response.status_code == 200
    cleared_payload = clear_response.json()["data"]
    assert cleared_payload["email"] is None
    assert cleared_payload["phone"] is None
    assert cleared_payload["birthday"] is None
    assert cleared_payload["region"] is None
    assert cleared_payload["signature"] is None
    assert cleared_payload["gender"] is None

    me_response = client.get(
        "/api/v1/auth/me",
        headers=auth_header(access_token),
    )
    assert me_response.status_code == 200
    me_payload = me_response.json()["data"]
    assert me_payload["email"] is None
    assert me_payload["birthday"] is None
    assert me_payload["status"] == "online"


def test_update_me_rejects_invalid_profile_fields(client: TestClient, auth_header) -> None:
    register_response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "dylan",
            "password": "secret123",
            "nickname": "Dylan",
        },
    )
    assert register_response.status_code == 200
    access_token = register_response.json()["data"]["access_token"]

    invalid_email_response = client.put(
        "/api/v1/users/me",
        headers=auth_header(access_token),
        json={"email": "not-an-email"},
    )
    assert invalid_email_response.status_code == 422

    invalid_phone_response = client.put(
        "/api/v1/users/me",
        headers=auth_header(access_token),
        json={"phone": "abc"},
    )
    assert invalid_phone_response.status_code == 422

    invalid_status_response = client.put(
        "/api/v1/users/me",
        headers=auth_header(access_token),
        json={"status": "sleeping"},
    )
    assert invalid_status_response.status_code == 422

def test_auth_login_requires_confirmation_before_replacing_online_session(client: TestClient, auth_header) -> None:
    register_response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "online-alice",
            "password": "secret123",
            "nickname": "Alice",
        },
    )
    assert register_response.status_code == 200
    register_payload = register_response.json()["data"]
    register_user = register_payload["user"]
    connection_manager.bind_user("conn-1", register_user["id"])

    conflict_response = client.post(
        "/api/v1/auth/login",
        json={
            "username": "online-alice",
            "password": "secret123",
        },
    )
    assert conflict_response.status_code == 409
    assert conflict_response.json()["code"] == ErrorCode.SESSION_CONFLICT

    still_valid_me = client.get(
        "/api/v1/auth/me",
        headers=auth_header(register_payload["access_token"]),
    )
    assert still_valid_me.status_code == 200

    forced_login_response = client.post(
        "/api/v1/auth/login",
        json={
            "username": "online-alice",
            "password": "secret123",
            "force": True,
        },
    )
    assert forced_login_response.status_code == 200
    forced_payload = forced_login_response.json()["data"]
    assert forced_payload["user"]["id"] == register_user["id"]
    assert connection_manager.has_user_connections(register_user["id"]) is False

    stale_me_response = client.get(
        "/api/v1/auth/me",
        headers=auth_header(register_payload["access_token"]),
    )
    assert stale_me_response.status_code == 401

    fresh_me_response = client.get(
        "/api/v1/auth/me",
        headers=auth_header(forced_payload["access_token"]),
    )
    assert fresh_me_response.status_code == 200


def test_users_me_avatar_endpoints_replace_and_reset_avatar(client: TestClient, auth_header) -> None:
    register_response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "avatar-user",
            "password": "secret123",
            "nickname": "Avatar User",
        },
    )
    assert register_response.status_code == 200
    payload = register_response.json()["data"]
    access_token = payload["access_token"]
    default_avatar = payload["user"]["avatar"]

    upload_response = client.post(
        "/api/v1/users/me/avatar",
        headers=auth_header(access_token),
        files={"file": ("avatar.png", b"not-a-real-png-but-valid-for-boundary-test", "image/png")},
    )
    assert upload_response.status_code == 200
    upload_payload = upload_response.json()["data"]
    assert upload_payload["avatar_kind"] == "custom"
    assert upload_payload["avatar"] != default_avatar
    assert upload_payload["avatar"].startswith("/uploads/")

    reset_response = client.delete(
        "/api/v1/users/me/avatar",
        headers=auth_header(access_token),
    )
    assert reset_response.status_code == 200
    reset_payload = reset_response.json()["data"]
    assert reset_payload["avatar_kind"] == "default"
    assert reset_payload["avatar"] == default_avatar


def test_user_avatar_change_regenerates_generated_group_avatar(client: TestClient, auth_header) -> None:
    owner_response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "group-owner-avatar-refresh",
            "password": "secret123",
            "nickname": "Owner",
        },
    )
    member_response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "group-member-avatar-refresh",
            "password": "secret123",
            "nickname": "Member",
        },
    )
    assert owner_response.status_code == 200
    assert member_response.status_code == 200

    owner_payload = owner_response.json()["data"]
    member_payload = member_response.json()["data"]
    owner_token = owner_payload["access_token"]
    member_id = member_payload["user"]["id"]

    create_group_response = client.post(
        "/api/v1/groups",
        json={"name": "Avatar Refresh Group", "member_ids": [member_id]},
        headers=auth_header(owner_token),
    )
    assert create_group_response.status_code == 201
    initial_group = create_group_response.json()["data"]["group"]
    initial_avatar = initial_group["avatar"]
    assert initial_avatar.startswith("/uploads/group_avatars/")

    upload_response = client.post(
        "/api/v1/users/me/avatar",
        headers=auth_header(owner_token),
        files={"file": ("avatar.png", b"owner-avatar-refresh", "image/png")},
    )
    assert upload_response.status_code == 200

    refreshed_group_response = client.get(
        f"/api/v1/groups/{initial_group['id']}",
        headers=auth_header(owner_token),
    )
    assert refreshed_group_response.status_code == 200
    refreshed_group = refreshed_group_response.json()["data"]
    assert refreshed_group["avatar_kind"] == "generated"
    assert refreshed_group["avatar"].startswith("/uploads/group_avatars/")
    assert refreshed_group["avatar"] != initial_avatar


def test_update_me_rejects_avatar_field_after_avatar_api_split(client: TestClient, auth_header) -> None:
    register_response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "strict-avatar-user",
            "password": "secret123",
            "nickname": "Strict Avatar",
        },
    )
    assert register_response.status_code == 200
    access_token = register_response.json()["data"]["access_token"]

    response = client.put(
        "/api/v1/users/me",
        headers=auth_header(access_token),
        json={"avatar": "https://example.com/avatar.png"},
    )
    assert response.status_code == 422



def test_update_me_succeeds_when_profile_fanout_fails(client: TestClient, auth_header, monkeypatch) -> None:
    from app.api.v1 import users as user_routes

    register_response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "fanout-profile-user",
            "password": "secret123",
            "nickname": "Profile User",
        },
    )
    access_token = register_response.json()["data"]["access_token"]

    monkeypatch.setattr(
        user_routes.connection_manager,
        "send_json_to_users",
        AsyncMock(side_effect=RuntimeError("fanout failed")),
    )

    response = client.put(
        "/api/v1/users/me",
        headers=auth_header(access_token),
        json={"nickname": "Profile User Updated"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["nickname"] == "Profile User Updated"


def test_auth_request_models_reject_unknown_fields(client: TestClient) -> None:
    register_response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "strict-register-user",
            "password": "secret123",
            "nickname": "Strict Register",
            "unexpected": True,
        },
    )
    assert register_response.status_code == 422

    seed_response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "strict-login-user",
            "password": "secret123",
            "nickname": "Strict Login",
        },
    )
    assert seed_response.status_code == 200
    refresh_token = seed_response.json()["data"]["refresh_token"]

    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "username": "strict-login-user",
            "password": "secret123",
            "unexpected": True,
        },
    )
    assert login_response.status_code == 422

    refresh_response = client.post(
        "/api/v1/auth/refresh",
        json={
            "refresh_token": refresh_token,
            "unexpected": True,
        },
    )
    assert refresh_response.status_code == 422


def test_auth_identity_inputs_are_canonicalized_and_validated(client: TestClient) -> None:
    register_response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "  trim.user-1  ",
            "password": "secret123",
            "nickname": "  Trim User  ",
        },
    )
    assert register_response.status_code == 200
    payload = register_response.json()["data"]
    assert payload["user"]["username"] == "trim.user-1"
    assert payload["user"]["nickname"] == "Trim User"

    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "username": "  trim.user-1  ",
            "password": "secret123",
        },
    )
    assert login_response.status_code == 200
    login_payload = login_response.json()["data"]

    refresh_response = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": f"  {login_payload['refresh_token']}  "},
    )
    assert refresh_response.status_code == 200

    invalid_username_response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "bad user",
            "password": "secret123",
            "nickname": "Bad User",
        },
    )
    assert invalid_username_response.status_code == 422

    invalid_nickname_response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "blank-nickname-user",
            "password": "secret123",
            "nickname": "   ",
        },
    )
    assert invalid_nickname_response.status_code == 422

    short_password_response = client.post(
        "/api/v1/auth/login",
        json={
            "username": "trim.user-1",
            "password": "123",
        },
    )
    assert short_password_response.status_code == 422


def test_deleted_auth_subjects_return_unauthorized(client: TestClient, auth_header) -> None:
    import pytest

    from app.core.database import SessionLocal
    from app.models.user import User
    from app.services.auth_service import AuthService

    register_response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "deleted-subject-user",
            "password": "secret123",
            "nickname": "Deleted Subject",
        },
    )
    assert register_response.status_code == 200
    payload = register_response.json()["data"]
    user_id = payload["user"]["id"]

    with SessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        db.delete(user)
        db.commit()

    me_response = client.get(
        "/api/v1/auth/me",
        headers=auth_header(payload["access_token"]),
    )
    assert me_response.status_code == 401
    assert me_response.json()["code"] == ErrorCode.UNAUTHORIZED

    refresh_response = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": payload["refresh_token"]},
    )
    assert refresh_response.status_code == 401
    assert refresh_response.json()["code"] == ErrorCode.UNAUTHORIZED

    with SessionLocal() as db:
        service = AuthService(db)
        with pytest.raises(Exception) as exc_info:
            service.refresh_access_token(payload["refresh_token"])
    assert exc_info.value.code == ErrorCode.UNAUTHORIZED


def test_logout_success_does_not_depend_on_realtime_disconnect(client: TestClient, auth_header, monkeypatch) -> None:
    from app.api.v1 import auth as auth_routes

    register_response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "logout-fanout-user",
            "password": "secret123",
            "nickname": "Logout Fanout",
        },
    )
    assert register_response.status_code == 200
    payload = register_response.json()["data"]

    monkeypatch.setattr(
        auth_routes.connection_manager,
        "disconnect_user_connections",
        AsyncMock(side_effect=RuntimeError("disconnect failed")),
    )

    logout_response = client.delete(
        "/api/v1/auth/session",
        headers=auth_header(payload["access_token"]),
    )
    assert logout_response.status_code == 204

    me_response = client.get(
        "/api/v1/auth/me",
        headers=auth_header(payload["access_token"]),
    )
    assert me_response.status_code == 401


def test_force_login_disconnects_existing_runtime_before_rotating_session(client: TestClient, auth_header, monkeypatch) -> None:
    from app.api.v1 import auth as auth_routes

    register_response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "force-disconnect-user",
            "password": "secret123",
            "nickname": "Force Disconnect",
        },
    )
    assert register_response.status_code == 200
    payload = register_response.json()["data"]
    user_id = payload["user"]["id"]
    connection_manager.bind_user("force-conn", user_id)

    monkeypatch.setattr(
        auth_routes.connection_manager,
        "disconnect_user_connections",
        AsyncMock(side_effect=RuntimeError("disconnect failed")),
    )

    failed_login_response = client.post(
        "/api/v1/auth/login",
        json={
            "username": "force-disconnect-user",
            "password": "secret123",
            "force": True,
        },
    )
    assert failed_login_response.status_code == 500

    still_valid_me = client.get(
        "/api/v1/auth/me",
        headers=auth_header(payload["access_token"]),
    )
    assert still_valid_me.status_code == 200


def test_register_rolls_back_user_when_default_avatar_assignment_fails(client: TestClient, monkeypatch) -> None:
    import pytest

    from app.core.database import SessionLocal
    from app.models.user import User
    from app.services import auth_service as auth_service_module
    from app.services.avatar_service import AvatarService

    def fail_default_avatar(self, user, *, seed="", gender="", commit=True):
        raise RuntimeError("default avatar failed")

    monkeypatch.setattr(AvatarService, "assign_default_user_avatar", fail_default_avatar)

    with SessionLocal() as db:
        service = auth_service_module.AuthService(db)
        with pytest.raises(RuntimeError):
            service.register("rollback-register-user", "secret123", "Rollback Register")

    with SessionLocal() as db:
        user = db.query(User).filter(User.username == "rollback-register-user").one_or_none()
    assert user is None


def test_username_identity_is_case_canonical_across_register_login_and_search(client: TestClient, auth_header) -> None:
    register_response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "Case.User",
            "password": "secret123",
            "nickname": "Case User",
        },
    )
    assert register_response.status_code == 200
    payload = register_response.json()["data"]
    assert payload["user"]["username"] == "case.user"

    duplicate_response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "case.user",
            "password": "secret123",
            "nickname": "Duplicate Case User",
        },
    )
    assert duplicate_response.status_code == 409

    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "username": "CASE.USER",
            "password": "secret123",
        },
    )
    assert login_response.status_code == 200
    login_payload = login_response.json()["data"]
    assert login_payload["user"]["id"] == payload["user"]["id"]

    search_response = client.get(
        "/api/v1/users/search",
        headers=auth_header(login_payload["access_token"]),
        params={"keyword": "CASE.USER"},
    )
    assert search_response.status_code == 200
    search_payload = search_response.json()["data"]
    assert [item["username"] for item in search_payload["items"]] == ["case.user"]


def test_user_routes_use_collection_and_public_detail_contracts(client: TestClient, user_factory, auth_header) -> None:
    alice = user_factory("user_contract_alice", "User Contract Alice")
    bob = user_factory("user_contract_bob", "User Contract Bob")
    headers = auth_header(alice["access_token"])

    list_response = client.get(
        "/api/v1/users",
        headers=headers,
        params={"page": 1, "size": 1},
    )
    assert list_response.status_code == 200
    list_payload = list_response.json()["data"]
    assert set(list_payload) == {"total", "page", "size", "items"}
    assert list_payload["total"] == 2
    assert list_payload["page"] == 1
    assert list_payload["size"] == 1
    assert len(list_payload["items"]) == 1
    assert "email" not in list_payload["items"][0]
    assert "created_at" not in list_payload["items"][0]
    assert "display_name" in list_payload["items"][0]

    detail_response = client.get(
        f"/api/v1/users/{bob['user']['id']}",
        headers=headers,
    )
    assert detail_response.status_code == 200
    public_detail = detail_response.json()["data"]
    assert public_detail["id"] == bob["user"]["id"]
    assert public_detail["display_name"] == "User Contract Bob"
    assert "email" not in public_detail
    assert "phone" not in public_detail
    assert "created_at" not in public_detail

    me_response = client.get("/api/v1/auth/me", headers=headers)
    assert me_response.status_code == 200
    self_detail = me_response.json()["data"]
    assert self_detail["id"] == alice["user"]["id"]
    assert "email" in self_detail
    assert "created_at" in self_detail
