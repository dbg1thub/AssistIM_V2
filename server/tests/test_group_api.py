"""Group API tests."""

from __future__ import annotations

from unittest.mock import AsyncMock

from fastapi.testclient import TestClient


def test_group_permissions_and_transfer_flow(client: TestClient, user_factory, auth_header) -> None:
    owner = user_factory("owner", "Owner")
    member = user_factory("member", "Member")
    outsider = user_factory("outsider", "Outsider")

    create_group_response = client.post(
        "/api/v1/groups",
        json={"name": "Core Team", "member_ids": [member["user"]["id"]]},
        headers=auth_header(owner["access_token"]),
    )
    assert create_group_response.status_code == 201
    group_payload = create_group_response.json()["data"]
    group_id = group_payload["id"]

    forbidden_group_response = client.get(
        f"/api/v1/groups/{group_id}",
        headers=auth_header(outsider["access_token"]),
    )
    assert forbidden_group_response.status_code == 403

    add_member_response = client.post(
        f"/api/v1/groups/{group_id}/members",
        json={"user_id": outsider["user"]["id"], "role": "member"},
        headers=auth_header(owner["access_token"]),
    )
    assert add_member_response.status_code == 200
    assert add_member_response.json()["data"]["status"] == "added"

    outsider_group_response = client.get(
        f"/api/v1/groups/{group_id}",
        headers=auth_header(outsider["access_token"]),
    )
    assert outsider_group_response.status_code == 200
    member_ids = {item["user_id"] for item in outsider_group_response.json()["data"]["members"]}
    assert outsider["user"]["id"] in member_ids

    transfer_response = client.post(
        f"/api/v1/groups/{group_id}/transfer",
        json={"new_owner_id": outsider["user"]["id"]},
        headers=auth_header(owner["access_token"]),
    )
    assert transfer_response.status_code == 200
    assert transfer_response.json()["data"]["owner_id"] == outsider["user"]["id"]

    delete_as_old_owner_response = client.delete(
        f"/api/v1/groups/{group_id}",
        headers=auth_header(owner["access_token"]),
    )
    assert delete_as_old_owner_response.status_code == 403


def test_group_owner_cannot_remove_self_without_transfer(client: TestClient, user_factory, auth_header) -> None:
    owner = user_factory("owner", "Owner")
    member = user_factory("member", "Member")

    create_group_response = client.post(
        "/api/v1/groups",
        json={"name": "Core Team", "member_ids": [member["user"]["id"]]},
        headers=auth_header(owner["access_token"]),
    )
    assert create_group_response.status_code == 201
    group_id = create_group_response.json()["data"]["id"]

    remove_owner_response = client.delete(
        f"/api/v1/groups/{group_id}/members/{owner['user']['id']}",
        headers=auth_header(owner["access_token"]),
    )
    assert remove_owner_response.status_code == 403


def test_create_group_generates_server_managed_group_avatar(client: TestClient, user_factory, auth_header) -> None:
    owner = user_factory("group-avatar-owner", "Owner")
    member = user_factory("group-avatar-member", "Member")

    response = client.post(
        "/api/v1/groups",
        json={"name": "Avatar Group", "member_ids": [member["user"]["id"]]},
        headers=auth_header(owner["access_token"]),
    )
    assert response.status_code == 201
    payload = response.json()["data"]
    assert payload["avatar_kind"] == "generated"
    assert payload["avatar"].startswith("/uploads/group_avatars/")


def test_create_group_accepts_blank_name_for_default_naming(client: TestClient, user_factory, auth_header) -> None:
    owner = user_factory("blank-group-owner", "Owner")
    member = user_factory("blank-group-member", "Member")

    response = client.post(
        "/api/v1/groups",
        json={"name": "", "member_ids": [member["user"]["id"]]},
        headers=auth_header(owner["access_token"]),
    )

    assert response.status_code == 201
    payload = response.json()["data"]
    assert payload["name"] == ""
    assert payload["member_count"] == 2


def test_group_owner_can_promote_and_demote_admin(client: TestClient, user_factory, auth_header) -> None:
    owner = user_factory("role-owner", "Owner")
    member = user_factory("role-member", "Member")

    create_group_response = client.post(
        "/api/v1/groups",
        json={"name": "Ops Team", "member_ids": [member["user"]["id"]]},
        headers=auth_header(owner["access_token"]),
    )
    assert create_group_response.status_code == 201
    group_id = create_group_response.json()["data"]["id"]

    promote_response = client.patch(
        f"/api/v1/groups/{group_id}/members/{member['user']['id']}/role",
        json={"role": "admin"},
        headers=auth_header(owner["access_token"]),
    )
    assert promote_response.status_code == 200
    promoted_group = promote_response.json()["data"]["group"]
    promoted_member = next(item for item in promoted_group["members"] if item["id"] == member["user"]["id"])
    assert promote_response.json()["data"]["status"] == "role_updated"
    assert promoted_member["role"] == "admin"

    demote_response = client.patch(
        f"/api/v1/groups/{group_id}/members/{member['user']['id']}/role",
        json={"role": "member"},
        headers=auth_header(owner["access_token"]),
    )
    assert demote_response.status_code == 200
    demoted_group = demote_response.json()["data"]["group"]
    demoted_member = next(item for item in demoted_group["members"] if item["id"] == member["user"]["id"])
    assert demoted_member["role"] == "member"


def test_group_role_update_requires_owner_and_disallows_owner_role_change(client: TestClient, user_factory, auth_header) -> None:
    owner = user_factory("role-guard-owner", "Owner")
    member = user_factory("role-guard-member", "Member")

    create_group_response = client.post(
        "/api/v1/groups",
        json={"name": "Ops Team", "member_ids": [member["user"]["id"]]},
        headers=auth_header(owner["access_token"]),
    )
    assert create_group_response.status_code == 201
    group_id = create_group_response.json()["data"]["id"]

    forbidden_response = client.patch(
        f"/api/v1/groups/{group_id}/members/{member['user']['id']}/role",
        json={"role": "admin"},
        headers=auth_header(member["access_token"]),
    )
    assert forbidden_response.status_code == 403

    invalid_role_response = client.patch(
        f"/api/v1/groups/{group_id}/members/{member['user']['id']}/role",
        json={"role": "owner"},
        headers=auth_header(owner["access_token"]),
    )
    assert invalid_role_response.status_code == 422

    non_string_role_response = client.patch(
        f"/api/v1/groups/{group_id}/members/{member['user']['id']}/role",
        json={"role": 123},
        headers=auth_header(owner["access_token"]),
    )
    assert non_string_role_response.status_code == 422

    missing_role_response = client.patch(
        f"/api/v1/groups/{group_id}/members/{member['user']['id']}/role",
        json={},
        headers=auth_header(owner["access_token"]),
    )
    assert missing_role_response.status_code == 422

    owner_change_response = client.patch(
        f"/api/v1/groups/{group_id}/members/{owner['user']['id']}/role",
        json={"role": "member"},
        headers=auth_header(owner["access_token"]),
    )
    assert owner_change_response.status_code == 403


def test_group_profile_update_requires_owner_or_admin_and_persists_metadata(client: TestClient, user_factory, auth_header) -> None:
    owner = user_factory("profile-owner", "Owner")
    admin = user_factory("profile-admin", "Admin")
    member = user_factory("profile-member", "Member")

    create_group_response = client.post(
        "/api/v1/groups",
        json={"name": "", "member_ids": [admin["user"]["id"], member["user"]["id"]]},
        headers=auth_header(owner["access_token"]),
    )
    group_id = create_group_response.json()["data"]["id"]

    promote_response = client.patch(
        f"/api/v1/groups/{group_id}/members/{admin['user']['id']}/role",
        json={"role": "admin"},
        headers=auth_header(owner["access_token"]),
    )
    assert promote_response.status_code == 200

    forbidden_response = client.patch(
        f"/api/v1/groups/{group_id}",
        json={"name": "New Name", "announcement": "Notice"},
        headers=auth_header(member["access_token"]),
    )
    assert forbidden_response.status_code == 403

    update_response = client.patch(
        f"/api/v1/groups/{group_id}",
        json={"name": "Ops", "announcement": "Deploy at 6"},
        headers=auth_header(admin["access_token"]),
    )
    assert update_response.status_code == 200
    payload = update_response.json()["data"]
    assert payload["name"] == "Ops"
    assert payload["announcement"] == "Deploy at 6"


def test_group_self_profile_update_persists_note_and_group_nickname(client: TestClient, user_factory, auth_header) -> None:
    owner = user_factory("self-profile-owner", "Owner")
    member = user_factory("self-profile-member", "Member")

    create_group_response = client.post(
        "/api/v1/groups",
        json={"name": "Ops", "member_ids": [member["user"]["id"]]},
        headers=auth_header(owner["access_token"]),
    )
    group_id = create_group_response.json()["data"]["id"]

    update_response = client.patch(
        f"/api/v1/groups/{group_id}/me",
        json={"note": "private note", "my_group_nickname": "oncall"},
        headers=auth_header(member["access_token"]),
    )
    assert update_response.status_code == 200
    payload = update_response.json()["data"]
    assert payload["group_note"] == "private note"
    assert payload["my_group_nickname"] == "oncall"
    updated_member = next(item for item in payload["members"] if item["id"] == member["user"]["id"])
    assert updated_member["group_nickname"] == "oncall"



def test_group_profile_update_succeeds_when_realtime_fanout_fails(
    client: TestClient,
    user_factory,
    auth_header,
    monkeypatch,
) -> None:
    from app.api.v1 import groups as group_routes

    owner = user_factory("group-fanout-owner", "Owner")
    member = user_factory("group-fanout-member", "Member")

    create_group_response = client.post(
        "/api/v1/groups",
        json={"name": "Ops", "member_ids": [member["user"]["id"]]},
        headers=auth_header(owner["access_token"]),
    )
    group_id = create_group_response.json()["data"]["id"]

    monkeypatch.setattr(
        group_routes.connection_manager,
        "send_json_to_users",
        AsyncMock(side_effect=RuntimeError("fanout failed")),
    )

    response = client.patch(
        f"/api/v1/groups/{group_id}",
        json={"name": "Ops 2"},
        headers=auth_header(owner["access_token"]),
    )

    assert response.status_code == 200
    assert response.json()["data"]["name"] == "Ops 2"


def test_group_schema_rejects_conflicting_member_sources_and_extra_fields(client: TestClient, user_factory, auth_header) -> None:
    owner = user_factory("group-schema-owner", "Owner")
    member = user_factory("group-schema-member", "Member")
    outsider = user_factory("group-schema-outsider", "Outsider")

    conflicting_members = client.post(
        "/api/v1/groups",
        json={
            "name": "Ops",
            "member_ids": [member["user"]["id"]],
            "members": [outsider["user"]["id"]],
        },
        headers=auth_header(owner["access_token"]),
    )
    assert conflicting_members.status_code == 422

    extra_field = client.post(
        "/api/v1/groups",
        json={"name": "Ops", "member_ids": [member["user"]["id"]], "extra": True},
        headers=auth_header(owner["access_token"]),
    )
    assert extra_field.status_code == 422

    blank_member = client.post(
        "/api/v1/groups",
        json={"name": "Ops", "member_ids": ["   "]},
        headers=auth_header(owner["access_token"]),
    )
    assert blank_member.status_code == 422

    oversized_member = client.post(
        "/api/v1/groups",
        json={"name": "Ops", "member_ids": ["u" * 129]},
        headers=auth_header(owner["access_token"]),
    )
    assert oversized_member.status_code == 422

    non_string_member = client.post(
        "/api/v1/groups",
        json={"name": "Ops", "member_ids": [123]},
        headers=auth_header(owner["access_token"]),
    )
    assert non_string_member.status_code == 422

    normalized_duplicate = client.post(
        "/api/v1/groups",
        json={"name": "Ops", "member_ids": [f"  {member['user']['id']}  ", member["user"]["id"]]},
        headers=auth_header(owner["access_token"]),
    )
    assert normalized_duplicate.status_code == 201
    normalized_members = normalized_duplicate.json()["data"]["members"]
    normalized_member_ids = [item["id"] for item in normalized_members]
    assert normalized_member_ids.count(member["user"]["id"]) == 1


def test_group_member_and_profile_schemas_reject_extra_fields(client: TestClient, user_factory, auth_header) -> None:
    owner = user_factory("group-schema-owner-2", "Owner")
    member = user_factory("group-schema-member-2", "Member")

    create_group_response = client.post(
        "/api/v1/groups",
        json={"name": "Ops", "member_ids": [member["user"]["id"]]},
        headers=auth_header(owner["access_token"]),
    )
    group_id = create_group_response.json()["data"]["id"]

    extra_add = client.post(
        f"/api/v1/groups/{group_id}/members",
        json={"user_id": member["user"]["id"], "role": "member", "extra": True},
        headers=auth_header(owner["access_token"]),
    )
    assert extra_add.status_code == 422

    blank_add = client.post(
        f"/api/v1/groups/{group_id}/members",
        json={"user_id": "   ", "role": "member"},
        headers=auth_header(owner["access_token"]),
    )
    assert blank_add.status_code == 422

    oversized_add = client.post(
        f"/api/v1/groups/{group_id}/members",
        json={"user_id": "u" * 129, "role": "member"},
        headers=auth_header(owner["access_token"]),
    )
    assert oversized_add.status_code == 422

    non_string_add = client.post(
        f"/api/v1/groups/{group_id}/members",
        json={"user_id": 123, "role": "member"},
        headers=auth_header(owner["access_token"]),
    )
    assert non_string_add.status_code == 422

    blank_transfer = client.post(
        f"/api/v1/groups/{group_id}/transfer",
        json={"new_owner_id": "   "},
        headers=auth_header(owner["access_token"]),
    )
    assert blank_transfer.status_code == 422

    oversized_transfer = client.post(
        f"/api/v1/groups/{group_id}/transfer",
        json={"new_owner_id": "u" * 129},
        headers=auth_header(owner["access_token"]),
    )
    assert oversized_transfer.status_code == 422

    extra_profile = client.patch(
        f"/api/v1/groups/{group_id}",
        json={"name": "Ops 2", "extra": True},
        headers=auth_header(owner["access_token"]),
    )
    assert extra_profile.status_code == 422
