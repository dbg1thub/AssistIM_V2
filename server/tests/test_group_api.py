"""Group API tests."""

from __future__ import annotations

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
