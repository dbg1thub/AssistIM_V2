"""Group API tests."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient


def _group_mutation(response, action: str) -> tuple[dict, dict]:
    payload = response.json()["data"]
    assert set(payload) == {"group", "mutation"}
    assert payload["mutation"]["action"] == action
    return payload["group"], payload["mutation"]


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
    group_payload, create_mutation = _group_mutation(create_group_response, "created")
    assert create_mutation["changed"] is True
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
    added_group, add_mutation = _group_mutation(add_member_response, "member_added")
    assert add_mutation["target_user_id"] == outsider["user"]["id"]
    assert any(item["id"] == outsider["user"]["id"] for item in added_group["members"])

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
    transferred_group, transfer_mutation = _group_mutation(transfer_response, "ownership_transferred")
    assert transfer_mutation["new_owner_id"] == outsider["user"]["id"]
    assert transferred_group["owner_id"] == outsider["user"]["id"]

    delete_as_old_owner_response = client.delete(
        f"/api/v1/groups/{group_id}",
        headers=auth_header(owner["access_token"]),
    )
    assert delete_as_old_owner_response.status_code == 403


def test_group_member_mutations_emit_authoritative_group_events(
    client: TestClient,
    user_factory,
    auth_header,
    monkeypatch,
) -> None:
    from app.api.v1 import groups as group_routes

    owner = user_factory("event-owner", "Owner")
    member = user_factory("event-member", "Member")
    outsider = user_factory("event-outsider", "Outsider")
    send_mock = AsyncMock(return_value={"delivered"})
    monkeypatch.setattr(group_routes.connection_manager, "send_json_to_users", send_mock)

    create_group_response = client.post(
        "/api/v1/groups",
        json={"name": "Core Team", "member_ids": [member["user"]["id"]]},
        headers=auth_header(owner["access_token"]),
    )
    assert create_group_response.status_code == 201
    group_payload, _ = _group_mutation(create_group_response, "created")
    group_id = group_payload["id"]
    send_mock.reset_mock()

    add_member_response = client.post(
        f"/api/v1/groups/{group_id}/members",
        json={"user_id": outsider["user"]["id"], "role": "member"},
        headers=auth_header(owner["access_token"]),
    )

    assert add_member_response.status_code == 200
    send_mock.assert_awaited()
    recipients, message = send_mock.await_args.args[:2]
    assert set(recipients) == {owner["user"]["id"], member["user"]["id"], outsider["user"]["id"]}
    assert message["type"] == "group_profile_update"
    assert message["data"]["group_id"] == group_id
    assert message["data"]["mutation"]["action"] == "member_added"
    assert message["data"]["mutation"]["target_user_id"] == outsider["user"]["id"]


def test_group_delete_emits_contact_refresh_tombstone(
    client: TestClient,
    user_factory,
    auth_header,
    monkeypatch,
) -> None:
    from app.api.v1 import groups as group_routes

    owner = user_factory("delete-event-owner", "Owner")
    member = user_factory("delete-event-member", "Member")
    send_mock = AsyncMock(return_value={"delivered"})
    monkeypatch.setattr(group_routes.connection_manager, "send_json_to_users", send_mock)

    create_group_response = client.post(
        "/api/v1/groups",
        json={"name": "Core Team", "member_ids": [member["user"]["id"]]},
        headers=auth_header(owner["access_token"]),
    )
    assert create_group_response.status_code == 201
    group_payload, _ = _group_mutation(create_group_response, "created")
    send_mock.reset_mock()

    delete_response = client.delete(
        f"/api/v1/groups/{group_payload['id']}",
        headers=auth_header(owner["access_token"]),
    )

    assert delete_response.status_code == 200
    recipients, message = send_mock.await_args.args[:2]
    assert set(recipients) == {owner["user"]["id"], member["user"]["id"]}
    assert message["type"] == "contact_refresh"
    assert message["data"]["reason"] == "group_deleted"
    assert message["data"]["group_id"] == group_payload["id"]


def test_group_owner_cannot_remove_self_without_transfer(client: TestClient, user_factory, auth_header) -> None:
    owner = user_factory("owner", "Owner")
    member = user_factory("member", "Member")

    create_group_response = client.post(
        "/api/v1/groups",
        json={"name": "Core Team", "member_ids": [member["user"]["id"]]},
        headers=auth_header(owner["access_token"]),
    )
    assert create_group_response.status_code == 201
    group_payload, _ = _group_mutation(create_group_response, "created")
    group_id = group_payload["id"]

    remove_owner_response = client.delete(
        f"/api/v1/groups/{group_id}/members/{owner['user']['id']}",
        headers=auth_header(owner["access_token"]),
    )
    assert remove_owner_response.status_code == 403


def test_group_remove_member_returns_canonical_mutation_result(client: TestClient, user_factory, auth_header) -> None:
    owner = user_factory("remove-member-owner", "Owner")
    member = user_factory("remove-member-member", "Member")

    create_group_response = client.post(
        "/api/v1/groups",
        json={"name": "Core Team", "member_ids": [member["user"]["id"]]},
        headers=auth_header(owner["access_token"]),
    )
    assert create_group_response.status_code == 201
    group_payload, _ = _group_mutation(create_group_response, "created")
    group_id = group_payload["id"]

    remove_response = client.delete(
        f"/api/v1/groups/{group_id}/members/{member['user']['id']}",
        headers=auth_header(owner["access_token"]),
    )
    assert remove_response.status_code == 200
    updated_group, mutation = _group_mutation(remove_response, "member_removed")
    assert mutation["target_user_id"] == member["user"]["id"]
    assert all(item["id"] != member["user"]["id"] for item in updated_group["members"])


def test_create_group_generates_server_managed_group_avatar(client: TestClient, user_factory, auth_header) -> None:
    owner = user_factory("group-avatar-owner", "Owner")
    member = user_factory("group-avatar-member", "Member")

    response = client.post(
        "/api/v1/groups",
        json={"name": "Avatar Group", "member_ids": [member["user"]["id"]]},
        headers=auth_header(owner["access_token"]),
    )
    assert response.status_code == 201
    payload, mutation = _group_mutation(response, "created")
    assert mutation["changed"] is True
    assert payload["avatar_kind"] == "generated"
    assert payload["avatar"].startswith("/uploads/group_avatars/")


def test_create_group_rejects_blank_name(client: TestClient, user_factory, auth_header) -> None:
    owner = user_factory("blank-group-owner", "Owner")
    member = user_factory("blank-group-member", "Member")

    response = client.post(
        "/api/v1/groups",
        json={"name": "", "member_ids": [member["user"]["id"]]},
        headers=auth_header(owner["access_token"]),
    )

    assert response.status_code == 422


def test_group_owner_can_promote_and_demote_admin(client: TestClient, user_factory, auth_header) -> None:
    owner = user_factory("role-owner", "Owner")
    member = user_factory("role-member", "Member")

    create_group_response = client.post(
        "/api/v1/groups",
        json={"name": "Ops Team", "member_ids": [member["user"]["id"]]},
        headers=auth_header(owner["access_token"]),
    )
    assert create_group_response.status_code == 201
    group_payload, _ = _group_mutation(create_group_response, "created")
    group_id = group_payload["id"]

    promote_response = client.patch(
        f"/api/v1/groups/{group_id}/members/{member['user']['id']}/role",
        json={"role": "admin"},
        headers=auth_header(owner["access_token"]),
    )
    assert promote_response.status_code == 200
    promoted_group, promote_mutation = _group_mutation(promote_response, "member_role_updated")
    promoted_member = next(item for item in promoted_group["members"] if item["id"] == member["user"]["id"])
    assert promote_mutation["target_user_id"] == member["user"]["id"]
    assert promote_mutation["role"] == "admin"
    assert promoted_member["role"] == "admin"

    demote_response = client.patch(
        f"/api/v1/groups/{group_id}/members/{member['user']['id']}/role",
        json={"role": "member"},
        headers=auth_header(owner["access_token"]),
    )
    assert demote_response.status_code == 200
    demoted_group, demote_mutation = _group_mutation(demote_response, "member_role_updated")
    demoted_member = next(item for item in demoted_group["members"] if item["id"] == member["user"]["id"])
    assert demote_mutation["role"] == "member"
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
    group_payload, _ = _group_mutation(create_group_response, "created")
    group_id = group_payload["id"]

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


def test_group_membership_noop_mutations_are_rejected(client: TestClient, user_factory, auth_header) -> None:
    owner = user_factory("noop-owner", "Owner")
    member = user_factory("noop-member", "Member")

    create_group_response = client.post(
        "/api/v1/groups",
        json={"name": "Ops Team", "member_ids": [member["user"]["id"]]},
        headers=auth_header(owner["access_token"]),
    )
    assert create_group_response.status_code == 201
    group_payload, _ = _group_mutation(create_group_response, "created")
    group_id = group_payload["id"]

    duplicate_add = client.post(
        f"/api/v1/groups/{group_id}/members",
        json={"user_id": member["user"]["id"], "role": "member"},
        headers=auth_header(owner["access_token"]),
    )
    assert duplicate_add.status_code == 409

    remove_missing = client.delete(
        f"/api/v1/groups/{group_id}/members/{owner['user']['id'].replace(owner['user']['id'][-1], '0')}",
        headers=auth_header(owner["access_token"]),
    )
    assert remove_missing.status_code in {404, 422}

    self_transfer = client.post(
        f"/api/v1/groups/{group_id}/transfer",
        json={"new_owner_id": owner["user"]["id"]},
        headers=auth_header(owner["access_token"]),
    )
    assert self_transfer.status_code == 409


def test_group_profile_update_requires_owner_or_admin_and_persists_metadata(client: TestClient, user_factory, auth_header) -> None:
    owner = user_factory("profile-owner", "Owner")
    admin = user_factory("profile-admin", "Admin")
    member = user_factory("profile-member", "Member")

    create_group_response = client.post(
        "/api/v1/groups",
        json={"name": "Ops Team", "member_ids": [admin["user"]["id"], member["user"]["id"]]},
        headers=auth_header(owner["access_token"]),
    )
    group_payload, _ = _group_mutation(create_group_response, "created")
    group_id = group_payload["id"]

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
    group_payload, mutation = _group_mutation(update_response, "profile_updated")
    assert group_payload["name"] == "Ops"
    assert group_payload["announcement"] == "Deploy at 6"
    assert mutation["announcement"]["created"] is True
    assert mutation["announcement"]["message_id"] == group_payload["announcement_message_id"]
    assert mutation["announcement"]["participant_count"] == 3


def test_group_self_profile_update_persists_note_and_group_nickname(client: TestClient, user_factory, auth_header) -> None:
    owner = user_factory("self-profile-owner", "Owner")
    member = user_factory("self-profile-member", "Member")

    create_group_response = client.post(
        "/api/v1/groups",
        json={"name": "Ops", "member_ids": [member["user"]["id"]]},
        headers=auth_header(owner["access_token"]),
    )
    group_payload, _ = _group_mutation(create_group_response, "created")
    group_id = group_payload["id"]

    update_response = client.patch(
        f"/api/v1/groups/{group_id}/me",
        json={"note": "private note", "my_group_nickname": "oncall"},
        headers=auth_header(member["access_token"]),
    )
    assert update_response.status_code == 200
    payload = update_response.json()["data"]
    assert payload == {
        "group_id": group_id,
        "session_id": group_payload["session_id"],
        "group_note": "private note",
        "my_group_nickname": "oncall",
        "changed": True,
    }

    unchanged_response = client.patch(
        f"/api/v1/groups/{group_id}/me",
        json={},
        headers=auth_header(member["access_token"]),
    )
    assert unchanged_response.status_code == 200
    unchanged_payload = unchanged_response.json()["data"]
    assert unchanged_payload == {**payload, "changed": False}

    group_response = client.get(
        f"/api/v1/groups/{group_id}",
        headers=auth_header(member["access_token"]),
    )
    assert group_response.status_code == 200
    updated_member = next(item for item in group_response.json()["data"]["members"] if item["id"] == member["user"]["id"])
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
    group_payload, _ = _group_mutation(create_group_response, "created")
    group_id = group_payload["id"]

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
    group_payload, mutation = _group_mutation(response, "profile_updated")
    assert group_payload["name"] == "Ops 2"
    assert mutation["changed"] is True


def test_group_announcement_message_fanout_serializes_each_viewer(monkeypatch) -> None:
    from app.api.v1 import groups as group_routes

    serialize_calls: list[str] = []
    message = SimpleNamespace(id='message-1', sender_id='alice')

    class _FakeMessageRepo:
        def get_by_id(self, message_id: str):
            assert message_id == 'message-1'
            return message

    class _FakeMessageService:
        def __init__(self, db) -> None:
            self.messages = _FakeMessageRepo()

        def serialize_message(self, message_item, current_user_id: str) -> dict:
            assert message_item is message
            serialize_calls.append(current_user_id)
            return {
                'message_id': 'message-1',
                'viewer_id': current_user_id,
                'is_self': current_user_id == 'alice',
            }

    send_mock = AsyncMock(return_value={'delivered'})
    monkeypatch.setattr(group_routes, 'MessageService', _FakeMessageService)
    monkeypatch.setattr(group_routes.connection_manager, 'send_json_to_users', send_mock)

    async def scenario() -> None:
        await group_routes._broadcast_group_announcement_message(
            db=None,
            announcement_message_id=' message-1 ',
            participant_ids=['alice', 'bob', 'carol', 'bob'],
        )

    asyncio.run(scenario())

    assert serialize_calls == ['alice', 'bob', 'carol']
    assert send_mock.await_count == 3
    for await_call, expected_user_id in zip(send_mock.await_args_list, ['alice', 'bob', 'carol'], strict=True):
        user_ids, payload = await_call.args[:2]
        assert user_ids == [expected_user_id]
        assert payload['type'] == 'chat_message'
        assert payload['data']['viewer_id'] == expected_user_id
        assert payload['data']['is_self'] is (expected_user_id == 'alice')


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
    normalized_group, _ = _group_mutation(normalized_duplicate, "created")
    normalized_members = normalized_group["members"]
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
    group_payload, _ = _group_mutation(create_group_response, "created")
    group_id = group_payload["id"]

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

    extra_transfer = client.post(
        f"/api/v1/groups/{group_id}/transfer",
        json={"new_owner_id": member["user"]["id"], "extra": True},
        headers=auth_header(owner["access_token"]),
    )
    assert extra_transfer.status_code == 422

    extra_role = client.patch(
        f"/api/v1/groups/{group_id}/members/{member['user']['id']}/role",
        json={"role": "member", "extra": True},
        headers=auth_header(owner["access_token"]),
    )
    assert extra_role.status_code == 422

    extra_self_profile = client.patch(
        f"/api/v1/groups/{group_id}/me",
        json={"note": "ops", "extra": True},
        headers=auth_header(member["access_token"]),
    )
    assert extra_self_profile.status_code == 422

    extra_profile = client.patch(
        f"/api/v1/groups/{group_id}",
        json={"name": "Ops 2", "extra": True},
        headers=auth_header(owner["access_token"]),
    )
    assert extra_profile.status_code == 422
