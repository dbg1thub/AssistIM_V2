from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import timedelta, timezone
from pathlib import Path
import shutil

import pytest

from client.models.message import sanitize_outbound_message_extra
from client.services import e2ee_service as e2ee_service_module


pytest.importorskip("cryptography")


class FakeDatabase:
    def __init__(self) -> None:
        self.state: dict[str, str] = {}
        self.replace_calls: list[tuple[dict[str, str], list[str]]] = []

    async def get_app_state(self, key: str):
        return self.state.get(key)

    async def replace_app_state(self, values: dict[str, str] | None = None, *, delete_keys=()) -> None:
        self.replace_calls.append((dict(values or {}), [str(key) for key in list(delete_keys or [])]))
        for key in list(delete_keys or []):
            self.state.pop(str(key), None)
        for key, value in dict(values or {}).items():
            self.state[str(key)] = value

    async def set_app_state(self, key: str, value: str) -> None:
        await self.replace_app_state({key: value})

    async def delete_app_state(self, key: str) -> None:
        await self.replace_app_state(delete_keys=[key])

    async def delete_app_states(self, keys) -> None:
        await self.replace_app_state(delete_keys=keys)


class FakeHttpClient:
    async def get(self, *args, **kwargs):
        return []

    async def post(self, *args, **kwargs):
        return {}


class RecordingHttpClient:
    def __init__(self) -> None:
        self.get_calls: list[tuple[str, dict]] = []
        self.post_calls: list[tuple[str, dict]] = []
        self.delete_calls: list[tuple[str, dict]] = []
        self.get_responses: dict[str, object] = {}
        self.post_responses: dict[str, object] = {}

    async def get(self, path: str, **kwargs):
        self.get_calls.append((path, dict(kwargs)))
        return deepcopy(self.get_responses.get(path, []))

    async def post(self, path: str, **kwargs):
        payload = deepcopy(dict(kwargs.get('json') or {}))
        self.post_calls.append((path, payload))
        return deepcopy(self.post_responses.get(path, {}))

    async def delete(self, path: str, **kwargs):
        self.delete_calls.append((path, dict(kwargs)))
        return None


def build_remote_bundle(bundle: dict[str, object], *, user_id: str) -> dict[str, object]:
    signed_prekey = dict(bundle["signed_prekey"])
    one_time_prekey = dict(bundle["one_time_prekeys"][0])
    return {
        "device_id": bundle["device_id"],
        "user_id": user_id,
        "device_name": bundle["device_name"],
        "identity_key_public": bundle["identity_key_public"],
        "signing_key_public": bundle["signing_key_public"],
        "signed_prekey": {
            "key_id": signed_prekey["key_id"],
            "public_key": signed_prekey["public_key"],
            "signature": signed_prekey["signature"],
        },
        "one_time_prekey": {
            "prekey_id": one_time_prekey["prekey_id"],
            "public_key": one_time_prekey["public_key"],
        },
        "available_prekey_count": len(bundle["one_time_prekeys"]),
    }


def test_e2ee_service_encrypts_for_recipient_and_recipient_can_decrypt(monkeypatch) -> None:
    alice_db = FakeDatabase()
    bob_db = FakeDatabase()

    monkeypatch.setattr(e2ee_service_module, "get_http_client", lambda: FakeHttpClient())

    async def scenario() -> None:
        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: alice_db)
        alice_service = e2ee_service_module.E2EEService()
        alice_bundle = await alice_service.get_or_create_local_bundle()

        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: bob_db)
        bob_service = e2ee_service_module.E2EEService()
        bob_bundle = await bob_service.get_or_create_local_bundle()

        remote_bundle = {
            "device_id": bob_bundle["device_id"],
            "user_id": "bob",
            "device_name": bob_bundle["device_name"],
            "identity_key_public": bob_bundle["identity_key_public"],
            "signing_key_public": bob_bundle["signing_key_public"],
            "signed_prekey": {
                "key_id": bob_bundle["signed_prekey"]["key_id"],
                "public_key": bob_bundle["signed_prekey"]["public_key"],
                "signature": bob_bundle["signed_prekey"]["signature"],
            },
            "one_time_prekey": {
                "prekey_id": bob_bundle["one_time_prekeys"][0]["prekey_id"],
                "public_key": bob_bundle["one_time_prekeys"][0]["public_key"],
            },
            "available_prekey_count": len(bob_bundle["one_time_prekeys"]),
        }

        async def fake_fetch_prekey_bundle(user_id: str) -> list[dict]:
            assert user_id == "bob"
            return [dict(remote_bundle)]

        async def fake_claim_prekeys(device_ids: list[str]) -> list[dict]:
            assert device_ids == [bob_bundle["device_id"]]
            return [dict(remote_bundle)]

        alice_service.fetch_prekey_bundle = fake_fetch_prekey_bundle  # type: ignore[method-assign]
        alice_service.claim_prekeys = fake_claim_prekeys  # type: ignore[method-assign]

        ciphertext, encryption = await alice_service.encrypt_text_for_user("bob", "secret hello")
        encryption["decryption_state"] = "missing_private_key"
        encryption["recovery_action"] = "reprovision_device"
        encryption["local_device_id"] = "device-alice"
        encryption["target_device_id"] = "device-bob"
        encryption["can_decrypt"] = False
        remote_extra = sanitize_outbound_message_extra({"encryption": encryption})
        plaintext = await bob_service.decrypt_text_content(ciphertext, remote_extra)

        assert alice_bundle["device_id"] != bob_bundle["device_id"]
        assert ciphertext != "secret hello"
        assert remote_extra["encryption"]["content_ciphertext"] == ciphertext
        assert "local_plaintext" not in remote_extra["encryption"]
        assert "decryption_state" not in remote_extra["encryption"]
        assert "recovery_action" not in remote_extra["encryption"]
        assert "local_device_id" not in remote_extra["encryption"]
        assert "target_device_id" not in remote_extra["encryption"]
        assert "can_decrypt" not in remote_extra["encryption"]
        assert plaintext == "secret hello"

    asyncio.run(scenario())


def test_e2ee_service_decrypts_with_retired_signed_prekey_after_rotation(monkeypatch) -> None:
    alice_db = FakeDatabase()
    bob_db = FakeDatabase()

    monkeypatch.setattr(e2ee_service_module, "get_http_client", lambda: FakeHttpClient())

    async def scenario() -> None:
        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: alice_db)
        alice_service = e2ee_service_module.E2EEService()
        await alice_service.get_or_create_local_bundle()

        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: bob_db)
        bob_service = e2ee_service_module.E2EEService()
        bob_bundle = await bob_service.get_or_create_local_bundle()

        remote_bundle = {
            "device_id": bob_bundle["device_id"],
            "user_id": "bob",
            "device_name": bob_bundle["device_name"],
            "identity_key_public": bob_bundle["identity_key_public"],
            "signing_key_public": bob_bundle["signing_key_public"],
            "signed_prekey": {
                "key_id": bob_bundle["signed_prekey"]["key_id"],
                "public_key": bob_bundle["signed_prekey"]["public_key"],
                "signature": bob_bundle["signed_prekey"]["signature"],
            },
            "one_time_prekey": None,
            "available_prekey_count": 0,
        }

        async def fake_fetch_prekey_bundle(user_id: str) -> list[dict]:
            assert user_id == "bob"
            return [dict(remote_bundle)]

        async def fake_claim_prekeys(device_ids: list[str]) -> list[dict]:
            assert device_ids == [bob_bundle["device_id"]]
            return []

        alice_service.fetch_prekey_bundle = fake_fetch_prekey_bundle  # type: ignore[method-assign]
        alice_service.claim_prekeys = fake_claim_prekeys  # type: ignore[method-assign]

        ciphertext, encryption = await alice_service.encrypt_text_for_user("bob", "rotated secret")
        remote_extra = sanitize_outbound_message_extra({"encryption": encryption})

        bob_bundle = await bob_service.get_or_create_local_bundle()
        bob_service._rotate_signed_prekey_in_bundle(bob_bundle)
        await bob_service._save_local_bundle(bob_bundle)

        plaintext = await bob_service.decrypt_text_content(ciphertext, remote_extra)
        saved_bundle = await bob_service.get_or_create_local_bundle()

        assert plaintext == "rotated secret"
        assert saved_bundle["signed_prekey"]["key_id"] == 2
        assert [item["key_id"] for item in saved_bundle["retired_signed_prekeys"]] == [1]

    asyncio.run(scenario())


def test_e2ee_service_ensure_registered_device_refreshes_low_prekey_inventory(monkeypatch) -> None:
    fake_db = FakeDatabase()
    fake_http = RecordingHttpClient()

    monkeypatch.setattr(e2ee_service_module, "get_http_client", lambda: fake_http)

    async def scenario() -> None:
        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: fake_db)
        service = e2ee_service_module.E2EEService()
        bundle = await service.get_or_create_local_bundle()
        bundle["signed_prekey_created_at"] = (
            e2ee_service_module._utcnow() - timedelta(days=30)
        ).astimezone(timezone.utc).isoformat()
        await service._save_local_bundle(bundle)

        fake_http.get_responses["/devices"] = [
            {
                "device_id": bundle["device_id"],
                "user_id": "alice",
                "device_name": bundle["device_name"],
                "identity_key_public": bundle["identity_key_public"],
                "signing_key_public": bundle["signing_key_public"],
                "is_active": True,
                "available_prekey_count": 1,
            }
        ]
        fake_http.post_responses[f"/devices/{bundle['device_id']}/keys/refresh"] = {
            "device_id": bundle["device_id"],
            "user_id": "alice",
            "device_name": bundle["device_name"],
            "identity_key_public": bundle["identity_key_public"],
            "signing_key_public": bundle["signing_key_public"],
            "is_active": True,
            "available_prekey_count": 32,
        }

        response = await service.ensure_registered_device()
        saved_bundle = await service.get_or_create_local_bundle()

        assert response["device_id"] == bundle["device_id"]
        assert fake_http.get_calls == [("/devices", {})]
        assert len(fake_http.post_calls) == 1
        path, payload = fake_http.post_calls[0]
        assert path == f"/devices/{bundle['device_id']}/keys/refresh"
        assert payload["signed_prekey"]["key_id"] == 2
        assert len(payload["prekeys"]) == 31
        assert payload["prekeys"][0]["prekey_id"] == 33
        assert payload["prekeys"][-1]["prekey_id"] == 63
        assert saved_bundle["signed_prekey"]["key_id"] == 2
        assert saved_bundle["next_signed_prekey_id"] == 3
        assert [item["key_id"] for item in saved_bundle["retired_signed_prekeys"]] == [1]
        assert saved_bundle["next_prekey_id"] == 64
        assert len(saved_bundle["one_time_prekeys"]) == 63

    asyncio.run(scenario())


def test_e2ee_service_reprovisions_local_device_and_deletes_previous_remote_device(monkeypatch) -> None:
    fake_db = FakeDatabase()
    fake_http = RecordingHttpClient()

    monkeypatch.setattr(e2ee_service_module, "get_http_client", lambda: fake_http)

    async def scenario() -> None:
        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: fake_db)
        service = e2ee_service_module.E2EEService()
        previous_bundle = await service.get_or_create_local_bundle()
        fake_http.post_responses["/devices/register"] = {
            "device_id": "replacement-device",
            "user_id": "alice",
            "device_name": previous_bundle["device_name"],
            "identity_key_public": "replacement-identity",
            "signing_key_public": "replacement-signing",
            "is_active": True,
            "available_prekey_count": 32,
        }

        response = await service.reprovision_local_device()
        current_bundle = await service.get_or_create_local_bundle()

        assert response["device_id"] == "replacement-device"
        assert fake_http.delete_calls == [(f"/devices/{previous_bundle['device_id']}", {})]
        assert fake_http.post_calls[0][0] == "/devices/register"
        assert fake_http.post_calls[0][1]["device_id"] != previous_bundle["device_id"]
        assert current_bundle["device_id"] != previous_bundle["device_id"]
        assert current_bundle["next_signed_prekey_id"] == 2
        assert current_bundle["next_prekey_id"] == 33
        bundle_replace_calls = [
            (values, delete_keys)
            for values, delete_keys in fake_db.replace_calls
            if set(values) == {service.DEVICE_STATE_KEY}
            and set(delete_keys) == {
                service.GROUP_SESSION_STATE_KEY,
                service.HISTORY_RECOVERY_STATE_KEY,
                service.IDENTITY_TRUST_STATE_KEY,
            }
        ]
        assert bundle_replace_calls

    asyncio.run(scenario())


def test_e2ee_service_reprovision_tolerates_remote_delete_failure(monkeypatch) -> None:
    fake_db = FakeDatabase()

    class FailingDeleteHttpClient(RecordingHttpClient):
        async def delete(self, path: str, **kwargs):
            raise RuntimeError(f"delete failed for {path}")

    fake_http = FailingDeleteHttpClient()
    monkeypatch.setattr(e2ee_service_module, "get_http_client", lambda: fake_http)

    async def scenario() -> None:
        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: fake_db)
        service = e2ee_service_module.E2EEService()
        previous_bundle = await service.get_or_create_local_bundle()
        fake_http.post_responses["/devices/register"] = {
            "device_id": "replacement-device-2",
            "user_id": "alice",
            "device_name": previous_bundle["device_name"],
            "identity_key_public": "replacement-identity-2",
            "signing_key_public": "replacement-signing-2",
            "is_active": True,
            "available_prekey_count": 32,
        }

        response = await service.reprovision_local_device()
        current_bundle = await service.get_or_create_local_bundle()

        assert response["device_id"] == "replacement-device-2"
        assert current_bundle["device_id"] != previous_bundle["device_id"]

    asyncio.run(scenario())


def test_e2ee_service_encrypts_attachment_metadata_for_recipient(monkeypatch) -> None:
    alice_db = FakeDatabase()
    bob_db = FakeDatabase()

    monkeypatch.setattr(e2ee_service_module, "get_http_client", lambda: FakeHttpClient())
    workspace_tmp = (Path.cwd() / "client/tests/.pytest_tmp/e2ee-service").resolve()
    workspace_tmp.mkdir(parents=True, exist_ok=True)

    async def scenario() -> None:
        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: alice_db)
        alice_service = e2ee_service_module.E2EEService()
        await alice_service.get_or_create_local_bundle()

        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: bob_db)
        bob_service = e2ee_service_module.E2EEService()
        bob_bundle = await bob_service.get_or_create_local_bundle()

        remote_bundle = {
            "device_id": bob_bundle["device_id"],
            "user_id": "bob",
            "device_name": bob_bundle["device_name"],
            "identity_key_public": bob_bundle["identity_key_public"],
            "signing_key_public": bob_bundle["signing_key_public"],
            "signed_prekey": {
                "key_id": bob_bundle["signed_prekey"]["key_id"],
                "public_key": bob_bundle["signed_prekey"]["public_key"],
                "signature": bob_bundle["signed_prekey"]["signature"],
            },
            "one_time_prekey": {
                "prekey_id": bob_bundle["one_time_prekeys"][0]["prekey_id"],
                "public_key": bob_bundle["one_time_prekeys"][0]["public_key"],
            },
            "available_prekey_count": len(bob_bundle["one_time_prekeys"]),
        }

        async def fake_fetch_prekey_bundle(user_id: str) -> list[dict]:
            assert user_id == "bob"
            return [dict(remote_bundle)]

        async def fake_claim_prekeys(device_ids: list[str]) -> list[dict]:
            assert device_ids == [bob_bundle["device_id"]]
            return [dict(remote_bundle)]

        alice_service.fetch_prekey_bundle = fake_fetch_prekey_bundle  # type: ignore[method-assign]
        alice_service.claim_prekeys = fake_claim_prekeys  # type: ignore[method-assign]

        source_path = workspace_tmp / "secret.bin"
        source_path.write_bytes(b"binary-secret")
        encrypted = await alice_service.encrypt_attachment_for_user(
            "bob",
            str(source_path),
            fallback_name="secret.bin",
            size_bytes=13,
            mime_type="application/octet-stream",
        )
        remote_metadata = dict(encrypted.attachment_encryption)
        remote_metadata.pop("local_metadata", None)
        payload = await bob_service.decrypt_attachment_metadata(remote_metadata)

        assert encrypted.upload_file_path != str(source_path)
        assert source_path.read_bytes() != Path(encrypted.upload_file_path).read_bytes()
        assert payload == {
            "file_key": payload["file_key"],
            "file_nonce": payload["file_nonce"],
            "original_name": "secret.bin",
            "size_bytes": 13,
            "mime_type": "application/octet-stream",
        }

    try:
        asyncio.run(scenario())
    finally:
        shutil.rmtree(workspace_tmp, ignore_errors=True)


def test_e2ee_service_decrypts_attachment_bytes_for_recipient(monkeypatch) -> None:
    alice_db = FakeDatabase()
    bob_db = FakeDatabase()

    monkeypatch.setattr(e2ee_service_module, "get_http_client", lambda: FakeHttpClient())
    workspace_tmp = (Path.cwd() / "client/tests/.pytest_tmp/e2ee-service-bytes").resolve()
    workspace_tmp.mkdir(parents=True, exist_ok=True)

    async def scenario() -> None:
        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: alice_db)
        alice_service = e2ee_service_module.E2EEService()
        await alice_service.get_or_create_local_bundle()

        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: bob_db)
        bob_service = e2ee_service_module.E2EEService()
        bob_bundle = await bob_service.get_or_create_local_bundle()

        remote_bundle = {
            "device_id": bob_bundle["device_id"],
            "user_id": "bob",
            "device_name": bob_bundle["device_name"],
            "identity_key_public": bob_bundle["identity_key_public"],
            "signing_key_public": bob_bundle["signing_key_public"],
            "signed_prekey": {
                "key_id": bob_bundle["signed_prekey"]["key_id"],
                "public_key": bob_bundle["signed_prekey"]["public_key"],
                "signature": bob_bundle["signed_prekey"]["signature"],
            },
            "one_time_prekey": {
                "prekey_id": bob_bundle["one_time_prekeys"][0]["prekey_id"],
                "public_key": bob_bundle["one_time_prekeys"][0]["public_key"],
            },
            "available_prekey_count": len(bob_bundle["one_time_prekeys"]),
        }

        async def fake_fetch_prekey_bundle(user_id: str) -> list[dict]:
            assert user_id == "bob"
            return [dict(remote_bundle)]

        async def fake_claim_prekeys(device_ids: list[str]) -> list[dict]:
            assert device_ids == [bob_bundle["device_id"]]
            return [dict(remote_bundle)]

        alice_service.fetch_prekey_bundle = fake_fetch_prekey_bundle  # type: ignore[method-assign]
        alice_service.claim_prekeys = fake_claim_prekeys  # type: ignore[method-assign]

        source_path = workspace_tmp / "secret-photo.png"
        plaintext_bytes = b"binary-image-payload"
        source_path.write_bytes(plaintext_bytes)
        encrypted = await alice_service.encrypt_attachment_for_user(
            "bob",
            str(source_path),
            fallback_name="secret-photo.png",
            size_bytes=len(plaintext_bytes),
            mime_type="image/png",
        )
        ciphertext_bytes = Path(encrypted.upload_file_path).read_bytes()
        remote_metadata = dict(encrypted.attachment_encryption)
        remote_metadata.pop("local_metadata", None)

        decrypted_bytes, metadata = await bob_service.decrypt_attachment_bytes(ciphertext_bytes, remote_metadata)

        assert decrypted_bytes == plaintext_bytes
        assert metadata["original_name"] == "secret-photo.png"
        assert metadata["mime_type"] == "image/png"
        assert metadata["size_bytes"] == len(plaintext_bytes)

    try:
        asyncio.run(scenario())
    finally:
        shutil.rmtree(workspace_tmp, ignore_errors=True)


def test_e2ee_service_prepares_group_session_fanout_and_reuses_sender_key(monkeypatch) -> None:
    alice_db = FakeDatabase()
    bob_db = FakeDatabase()

    monkeypatch.setattr(e2ee_service_module, "get_http_client", lambda: FakeHttpClient())

    def build_remote_bundle(bundle: dict[str, object], *, user_id: str) -> dict[str, object]:
        signed_prekey = dict(bundle["signed_prekey"])
        one_time_prekey = dict(bundle["one_time_prekeys"][0])
        return {
            "device_id": bundle["device_id"],
            "user_id": user_id,
            "device_name": bundle["device_name"],
            "identity_key_public": bundle["identity_key_public"],
            "signing_key_public": bundle["signing_key_public"],
            "signed_prekey": {
                "key_id": signed_prekey["key_id"],
                "public_key": signed_prekey["public_key"],
                "signature": signed_prekey["signature"],
            },
            "one_time_prekey": {
                "prekey_id": one_time_prekey["prekey_id"],
                "public_key": one_time_prekey["public_key"],
            },
        }

    async def scenario() -> None:
        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: alice_db)
        alice_service = e2ee_service_module.E2EEService()
        alice_bundle = await alice_service.get_or_create_local_bundle()

        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: bob_db)
        bob_service = e2ee_service_module.E2EEService()
        bob_bundle = await bob_service.get_or_create_local_bundle()
        bob_remote_bundle = build_remote_bundle(bob_bundle, user_id="bob")

        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: alice_db)
        first = await alice_service.prepare_group_session_fanout(
            "session-group-1",
            [bob_remote_bundle],
            member_version=3,
            owner_user_id="alice",
        )
        second = await alice_service.prepare_group_session_fanout(
            "session-group-1",
            [bob_remote_bundle],
            member_version=3,
            owner_user_id="alice",
        )
        summary = await alice_service.get_group_session_summary("session-group-1")
        sender_key_record = await alice_service.get_group_sender_key_record("session-group-1")

        assert first["reused"] is False
        assert second["reused"] is True
        assert first["sender_key_id"] == second["sender_key_id"]
        assert len(first["fanout"]) == 1
        assert first["fanout"][0]["scheme"] == alice_service.GROUP_FANOUT_SCHEME
        assert first["fanout"][0]["recipient_device_id"] == bob_bundle["device_id"]
        assert summary == {
            "session_id": "session-group-1",
            "local_device_id": alice_bundle["device_id"],
            "has_local_sender_key": True,
            "local_sender_key_id": first["sender_key_id"],
            "member_version": 3,
            "retired_local_sender_key_ids": [],
            "inbound_sender_devices": [],
            "total_sender_keys": 1,
            "updated_at": summary["updated_at"],
        }
        assert sender_key_record is not None
        assert sender_key_record["key_id"] == first["sender_key_id"]
        assert sender_key_record["owner_user_id"] == "alice"
        assert sender_key_record["owner_device_id"] == alice_bundle["device_id"]

    asyncio.run(scenario())


def test_e2ee_service_exports_and_imports_direct_history_recovery_package(monkeypatch) -> None:
    alice_db = FakeDatabase()
    bob_old_db = FakeDatabase()
    bob_new_db = FakeDatabase()

    monkeypatch.setattr(e2ee_service_module, "get_http_client", lambda: FakeHttpClient())

    async def scenario() -> None:
        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: alice_db)
        alice_service = e2ee_service_module.E2EEService()
        await alice_service.get_or_create_local_bundle()

        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: bob_old_db)
        bob_old_service = e2ee_service_module.E2EEService()
        bob_old_bundle = await bob_old_service.get_or_create_local_bundle()

        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: bob_new_db)
        bob_new_service = e2ee_service_module.E2EEService()
        bob_new_bundle = await bob_new_service.get_or_create_local_bundle()

        old_remote_bundle = build_remote_bundle(bob_old_bundle, user_id="bob")
        new_remote_bundle = build_remote_bundle(bob_new_bundle, user_id="bob")

        async def alice_fetch_prekey_bundle(user_id: str) -> list[dict]:
            assert user_id == "bob"
            return [dict(old_remote_bundle)]

        async def alice_claim_prekeys(device_ids: list[str]) -> list[dict]:
            assert device_ids == [bob_old_bundle["device_id"]]
            return [dict(old_remote_bundle)]

        alice_service.fetch_prekey_bundle = alice_fetch_prekey_bundle  # type: ignore[method-assign]
        alice_service.claim_prekeys = alice_claim_prekeys  # type: ignore[method-assign]

        ciphertext, encryption = await alice_service.encrypt_text_for_user("bob", "recoverable secret")
        remote_extra = sanitize_outbound_message_extra({"encryption": encryption})

        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: bob_old_db)

        async def old_fetch_prekey_bundle(user_id: str) -> list[dict]:
            assert user_id == "bob"
            return [dict(new_remote_bundle)]

        async def old_claim_prekeys(device_ids: list[str]) -> list[dict]:
            assert device_ids == [bob_new_bundle["device_id"]]
            return [dict(new_remote_bundle)]

        bob_old_service.fetch_prekey_bundle = old_fetch_prekey_bundle  # type: ignore[method-assign]
        bob_old_service.claim_prekeys = old_claim_prekeys  # type: ignore[method-assign]
        package = await bob_old_service.export_history_recovery_package(
            "bob",
            str(bob_new_bundle["device_id"]),
            source_user_id="bob",
        )

        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: bob_new_db)
        import_result = await bob_new_service.import_history_recovery_package(package)
        plaintext = await bob_new_service.decrypt_text_content(ciphertext, remote_extra)
        summary = await bob_new_service.get_history_recovery_summary()
        diagnostics = await bob_new_service.get_history_recovery_diagnostics()

        assert package["scheme"] == bob_old_service.DEVICE_HISTORY_RECOVERY_SCHEME
        assert package["recipient_device_id"] == bob_new_bundle["device_id"]
        assert package["package_summary"]["signed_prekey_count"] >= 1
        assert package["package_summary"]["one_time_prekey_count"] >= 1
        assert import_result["source_device_id"] == bob_old_bundle["device_id"]
        assert import_result["source_user_id"] == "bob"
        assert import_result["imported_signed_prekeys"] >= 1
        assert import_result["imported_one_time_prekeys"] >= 1
        assert plaintext == "recoverable secret"
        assert summary["source_device_count"] == 1
        assert summary["signed_prekey_count"] >= 1
        assert summary["one_time_prekey_count"] >= 1
        assert diagnostics == {
            "local_device_id": bob_new_bundle["device_id"],
            "available": True,
            "source_device_count": 1,
            "signed_prekey_count": diagnostics["signed_prekey_count"],
            "one_time_prekey_count": diagnostics["one_time_prekey_count"],
            "group_session_count": 0,
            "group_sender_key_count": 0,
            "primary_source_device_id": bob_old_bundle["device_id"],
            "primary_source_user_id": "bob",
            "last_imported_at": diagnostics["last_imported_at"],
            "source_devices": [
                {
                    "source_device_id": bob_old_bundle["device_id"],
                    "source_user_id": "bob",
                    "sender_identity_key_public": bob_old_bundle["identity_key_public"],
                    "imported_at": diagnostics["source_devices"][0]["imported_at"],
                    "exported_at": package["exported_at"],
                    "signed_prekey_count": diagnostics["source_devices"][0]["signed_prekey_count"],
                    "one_time_prekey_count": diagnostics["source_devices"][0]["one_time_prekey_count"],
                    "group_session_count": 0,
                    "group_sender_key_count": 0,
                    "session_ids": [],
                }
            ],
        }

    asyncio.run(scenario())


def test_e2ee_service_history_recovery_restores_group_sender_keys(monkeypatch) -> None:
    alice_old_db = FakeDatabase()
    alice_new_db = FakeDatabase()
    bob_db = FakeDatabase()

    monkeypatch.setattr(e2ee_service_module, "get_http_client", lambda: FakeHttpClient())

    async def scenario() -> None:
        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: alice_old_db)
        alice_old_service = e2ee_service_module.E2EEService()
        alice_old_bundle = await alice_old_service.get_or_create_local_bundle()

        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: alice_new_db)
        alice_new_service = e2ee_service_module.E2EEService()
        alice_new_bundle = await alice_new_service.get_or_create_local_bundle()

        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: bob_db)
        bob_service = e2ee_service_module.E2EEService()
        bob_bundle = await bob_service.get_or_create_local_bundle()

        alice_old_remote_bundle = build_remote_bundle(alice_old_bundle, user_id="alice")
        alice_new_remote_bundle = build_remote_bundle(alice_new_bundle, user_id="alice")

        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: bob_db)
        ciphertext, encryption = await bob_service.encrypt_text_for_group_session(
            "session-group-history-1",
            "historic group secret",
            [alice_old_remote_bundle],
            member_version=9,
            owner_user_id="bob",
        )
        remote_extra = sanitize_outbound_message_extra({"encryption": encryption})

        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: alice_old_db)
        initial_plaintext = await alice_old_service.decrypt_text_content(
            ciphertext,
            {
                "session_id": "session-group-history-1",
                "encryption": remote_extra["encryption"],
            },
        )

        async def old_fetch_prekey_bundle(user_id: str) -> list[dict]:
            assert user_id == "alice"
            return [dict(alice_new_remote_bundle)]

        async def old_claim_prekeys(device_ids: list[str]) -> list[dict]:
            assert device_ids == [alice_new_bundle["device_id"]]
            return [dict(alice_new_remote_bundle)]

        alice_old_service.fetch_prekey_bundle = old_fetch_prekey_bundle  # type: ignore[method-assign]
        alice_old_service.claim_prekeys = old_claim_prekeys  # type: ignore[method-assign]
        package = await alice_old_service.export_history_recovery_package(
            "alice",
            str(alice_new_bundle["device_id"]),
            source_user_id="alice",
        )

        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: alice_new_db)
        import_result = await alice_new_service.import_history_recovery_package(package)
        recovered_plaintext = await alice_new_service.decrypt_text_content(
            ciphertext,
            {
                "session_id": "session-group-history-1",
                "encryption": remote_extra["encryption"],
            },
        )
        summary = await alice_new_service.get_history_recovery_summary()
        diagnostics = await alice_new_service.get_history_recovery_diagnostics()

        assert initial_plaintext == "historic group secret"
        assert import_result["source_device_id"] == alice_old_bundle["device_id"]
        assert import_result["imported_group_sessions"] == 1
        assert import_result["imported_group_sender_keys"] >= 1
        assert package["package_summary"]["group_session_count"] == 1
        assert package["package_summary"]["group_sender_key_count"] >= 1
        assert recovered_plaintext == "historic group secret"
        assert summary["group_session_count"] == 1
        assert summary["group_sender_key_count"] >= 1
        assert diagnostics["available"] is True
        assert diagnostics["primary_source_device_id"] == alice_old_bundle["device_id"]
        assert diagnostics["source_devices"][0]["session_ids"] == ["session-group-history-1"]
        recovered_key = await alice_new_service.get_group_sender_key_record(
            "session-group-history-1",
            owner_device_id=bob_bundle["device_id"],
            sender_key_id=remote_extra["encryption"]["sender_key_id"],
        )
        assert recovered_key is not None
        assert recovered_key["owner_device_id"] == bob_bundle["device_id"]

    asyncio.run(scenario())


def test_e2ee_service_history_recovery_diagnostics_use_explicit_primary_source(monkeypatch) -> None:
    fake_db = FakeDatabase()
    monkeypatch.setattr(e2ee_service_module, "get_http_client", lambda: FakeHttpClient())

    async def scenario() -> None:
        fake_db.state[e2ee_service_module.E2EEService.HISTORY_RECOVERY_STATE_KEY] = (
            e2ee_service_module.SecureStorage.encrypt_text(
                e2ee_service_module.json.dumps(
                    {
                        "primary_source_device_id": "device-primary",
                        "devices": {
                            "device-primary": {
                                "source_user_id": "alice",
                                "sender_identity_key_public": "identity-primary",
                                "imported_at": "2026-04-14T10:00:00+00:00",
                                "exported_at": "2026-04-14T09:00:00+00:00",
                                "signed_prekeys": {"1": {"key_id": 1, "private_key": "pk-primary"}},
                                "one_time_prekeys": {},
                                "group_sessions": {},
                            },
                            "device-newer": {
                                "source_user_id": "alice",
                                "sender_identity_key_public": "identity-newer",
                                "imported_at": "2026-04-15T10:00:00+00:00",
                                "exported_at": "2026-04-15T09:00:00+00:00",
                                "signed_prekeys": {"2": {"key_id": 2, "private_key": "pk-newer"}},
                                "one_time_prekeys": {},
                                "group_sessions": {},
                            },
                        },
                    }
                )
            )
        )
        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: fake_db)
        service = e2ee_service_module.E2EEService()

        diagnostics = await service.get_history_recovery_diagnostics()

        assert diagnostics["primary_source_device_id"] == "device-primary"
        assert diagnostics["primary_source_user_id"] == "alice"
        assert diagnostics["last_imported_at"] == "2026-04-14T10:00:00+00:00"
        assert diagnostics["source_devices"][0]["source_device_id"] == "device-newer"

    asyncio.run(scenario())


def test_e2ee_service_history_recovery_rejects_cross_account_export(monkeypatch) -> None:
    fake_db = FakeDatabase()
    monkeypatch.setattr(e2ee_service_module, "get_http_client", lambda: FakeHttpClient())

    async def scenario() -> None:
        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: fake_db)
        service = e2ee_service_module.E2EEService()
        await service.get_or_create_local_bundle()

        with pytest.raises(RuntimeError, match="same-account"):
            await service.export_history_recovery_package(
                "bob",
                "device-bob-new",
                source_user_id="alice",
            )

    asyncio.run(scenario())


def test_e2ee_service_history_recovery_rejects_cross_account_import(monkeypatch) -> None:
    alice_old_db = FakeDatabase()
    alice_new_db = FakeDatabase()
    monkeypatch.setattr(e2ee_service_module, "get_http_client", lambda: FakeHttpClient())

    async def scenario() -> None:
        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: alice_old_db)
        old_service = e2ee_service_module.E2EEService()
        old_bundle = await old_service.get_or_create_local_bundle()

        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: alice_new_db)
        new_service = e2ee_service_module.E2EEService()
        new_bundle = await new_service.get_or_create_local_bundle()
        new_remote_bundle = build_remote_bundle(new_bundle, user_id="alice")

        async def old_fetch_prekey_bundle(user_id: str) -> list[dict]:
            assert user_id == "alice"
            return [dict(new_remote_bundle)]

        async def old_claim_prekeys(device_ids: list[str]) -> list[dict]:
            assert device_ids == [new_bundle["device_id"]]
            return [dict(new_remote_bundle)]

        old_service.fetch_prekey_bundle = old_fetch_prekey_bundle  # type: ignore[method-assign]
        old_service.claim_prekeys = old_claim_prekeys  # type: ignore[method-assign]
        package = await old_service.export_history_recovery_package(
            "alice",
            str(new_bundle["device_id"]),
            source_user_id="alice",
        )

        package["recipient_user_id"] = "mallory"
        with pytest.raises(RuntimeError, match="same-account"):
            await new_service.import_history_recovery_package(package, expected_source_user_id="alice")

        package["recipient_user_id"] = "alice"
        package["source_user_id"] = "mallory"
        with pytest.raises(RuntimeError, match="source user mismatch"):
            await new_service.import_history_recovery_package(package, expected_source_user_id="alice")

        assert old_bundle["device_id"]

    asyncio.run(scenario())


def test_e2ee_service_peer_identity_summary_tracks_verification_and_changes(monkeypatch) -> None:
    fake_db = FakeDatabase()

    monkeypatch.setattr(e2ee_service_module, "get_http_client", lambda: FakeHttpClient())

    async def scenario() -> None:
        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: fake_db)
        service = e2ee_service_module.E2EEService()
        await service.get_or_create_local_bundle()

        remote_bundle = {
            "device_id": "device-bob-1",
            "user_id": "bob",
            "device_name": "Bob Desktop",
            "identity_key_public": "identity-bob-1",
            "signing_key_public": "signing-bob-1",
        }

        async def fetch_prekey_bundle(user_id: str) -> list[dict]:
            assert user_id == "bob"
            return [dict(remote_bundle)]

        service.fetch_prekey_bundle = fetch_prekey_bundle  # type: ignore[method-assign]

        first_summary = await service.get_peer_identity_summary("bob")
        trusted_summary = await service.trust_peer_identities("bob")
        verified_summary = await service.get_peer_identity_summary("bob")

        changed_bundle = dict(remote_bundle)
        changed_bundle["identity_key_public"] = "identity-bob-1-rotated"

        async def fetch_changed_prekey_bundle(user_id: str) -> list[dict]:
            assert user_id == "bob"
            return [dict(changed_bundle)]

        service.fetch_prekey_bundle = fetch_changed_prekey_bundle  # type: ignore[method-assign]
        changed_summary = await service.get_peer_identity_summary("bob")
        repeated_changed_summary = await service.get_peer_identity_summary("bob")

        assert first_summary["status"] == service.IDENTITY_STATUS_UNVERIFIED
        assert first_summary["device_count"] == 1
        assert first_summary["unverified_device_ids"] == ["device-bob-1"]
        assert first_summary["verification_available"] is True
        assert first_summary["primary_verification_device_id"] == "device-bob-1"
        assert first_summary["primary_verification_code"]
        assert first_summary["primary_verification_code_short"]
        assert first_summary["devices"][0]["first_seen_at"]
        assert first_summary["devices"][0]["last_seen_at"]
        assert first_summary["devices"][0]["change_count"] == 0
        assert first_summary["devices"][0]["verification_code"] == first_summary["primary_verification_code"]
        assert first_summary["devices"][0]["verification_code_short"] == first_summary["primary_verification_code_short"]
        assert trusted_summary["status"] == service.IDENTITY_STATUS_VERIFIED
        assert trusted_summary["trusted_now_device_ids"] == ["device-bob-1"]
        assert trusted_summary["last_trusted_at"]
        assert trusted_summary["devices"][0]["last_trusted_at"] == trusted_summary["last_trusted_at"]
        assert trusted_summary["devices"][0]["trust_source"] == "local_manual"
        assert verified_summary["status"] == service.IDENTITY_STATUS_VERIFIED
        assert verified_summary["trusted_device_count"] == 1
        assert changed_summary["status"] == service.IDENTITY_STATUS_CHANGED
        assert changed_summary["changed_device_count"] == 1
        assert changed_summary["changed_device_ids"] == ["device-bob-1"]
        assert changed_summary["change_count"] == 1
        assert changed_summary["last_changed_at"]
        assert changed_summary["devices"][0]["last_changed_at"] == changed_summary["last_changed_at"]
        assert changed_summary["devices"][0]["fingerprint"] != verified_summary["devices"][0]["fingerprint"]
        assert changed_summary["primary_verification_code"] != verified_summary["primary_verification_code"]
        assert repeated_changed_summary["change_count"] == 1

    asyncio.run(scenario())


def test_e2ee_service_rotates_group_sender_key_when_member_version_changes(monkeypatch) -> None:
    alice_db = FakeDatabase()
    bob_db = FakeDatabase()

    monkeypatch.setattr(e2ee_service_module, "get_http_client", lambda: FakeHttpClient())

    def build_remote_bundle(bundle: dict[str, object], *, user_id: str) -> dict[str, object]:
        signed_prekey = dict(bundle["signed_prekey"])
        one_time_prekey = dict(bundle["one_time_prekeys"][0])
        return {
            "device_id": bundle["device_id"],
            "user_id": user_id,
            "device_name": bundle["device_name"],
            "identity_key_public": bundle["identity_key_public"],
            "signing_key_public": bundle["signing_key_public"],
            "signed_prekey": {
                "key_id": signed_prekey["key_id"],
                "public_key": signed_prekey["public_key"],
                "signature": signed_prekey["signature"],
            },
            "one_time_prekey": {
                "prekey_id": one_time_prekey["prekey_id"],
                "public_key": one_time_prekey["public_key"],
            },
        }

    async def scenario() -> None:
        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: alice_db)
        alice_service = e2ee_service_module.E2EEService()
        alice_bundle = await alice_service.get_or_create_local_bundle()

        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: bob_db)
        bob_service = e2ee_service_module.E2EEService()
        bob_bundle = await bob_service.get_or_create_local_bundle()
        bob_remote_bundle = build_remote_bundle(bob_bundle, user_id="bob")

        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: alice_db)
        first = await alice_service.prepare_group_session_fanout(
            "session-group-2",
            [bob_remote_bundle],
            member_version=1,
            owner_user_id="alice",
        )
        second = await alice_service.prepare_group_session_fanout(
            "session-group-2",
            [bob_remote_bundle],
            member_version=2,
            owner_user_id="alice",
        )
        summary = await alice_service.get_group_session_summary("session-group-2")

        assert first["sender_key_id"] != second["sender_key_id"]
        assert second["reused"] is False
        assert summary["local_sender_key_id"] == second["sender_key_id"]
        assert summary["member_version"] == 2
        assert summary["retired_local_sender_key_ids"] == [first["sender_key_id"]]
        retired_key = await alice_service.get_group_sender_key_record(
            "session-group-2",
            owner_device_id=alice_bundle["device_id"],
            sender_key_id=first["sender_key_id"],
        )
        assert retired_key is not None
        assert retired_key["key_id"] == first["sender_key_id"]

    asyncio.run(scenario())


def test_e2ee_service_reconcile_group_session_state_retires_previous_local_key(monkeypatch) -> None:
    alice_db = FakeDatabase()
    bob_db = FakeDatabase()

    monkeypatch.setattr(e2ee_service_module, "get_http_client", lambda: FakeHttpClient())

    def build_remote_bundle(bundle: dict[str, object], *, user_id: str) -> dict[str, object]:
        signed_prekey = dict(bundle["signed_prekey"])
        one_time_prekey = dict(bundle["one_time_prekeys"][0])
        return {
            "device_id": bundle["device_id"],
            "user_id": user_id,
            "device_name": bundle["device_name"],
            "identity_key_public": bundle["identity_key_public"],
            "signing_key_public": bundle["signing_key_public"],
            "signed_prekey": {
                "key_id": signed_prekey["key_id"],
                "public_key": signed_prekey["public_key"],
                "signature": signed_prekey["signature"],
            },
            "one_time_prekey": {
                "prekey_id": one_time_prekey["prekey_id"],
                "public_key": one_time_prekey["public_key"],
            },
        }

    async def scenario() -> None:
        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: alice_db)
        alice_service = e2ee_service_module.E2EEService()
        alice_bundle = await alice_service.get_or_create_local_bundle()

        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: bob_db)
        bob_service = e2ee_service_module.E2EEService()
        bob_bundle = await bob_service.get_or_create_local_bundle()
        bob_remote_bundle = build_remote_bundle(bob_bundle, user_id="bob")

        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: alice_db)
        first = await alice_service.prepare_group_session_fanout(
            "session-group-4",
            [bob_remote_bundle],
            member_version=1,
            owner_user_id="alice",
        )
        reconcile = await alice_service.reconcile_group_session_state(
            "session-group-4",
            member_version=2,
            member_user_ids=["alice", "bob"],
        )
        summary = await alice_service.get_group_session_summary("session-group-4")
        retired_key = await alice_service.get_group_sender_key_record(
            "session-group-4",
            owner_device_id=alice_bundle["device_id"],
            sender_key_id=first["sender_key_id"],
        )

        assert reconcile["changed"] is True
        assert reconcile["local_sender_key_cleared"] is True
        assert reconcile["pruned_inbound_sender_devices"] == []
        assert summary["has_local_sender_key"] is False
        assert summary["local_sender_key_id"] == ""
        assert summary["retired_local_sender_key_ids"] == [first["sender_key_id"]]
        assert summary["total_sender_keys"] == 1
        assert retired_key is not None
        assert retired_key["key_id"] == first["sender_key_id"]
        assert retired_key["owner_device_id"] == alice_bundle["device_id"]
        assert retired_key["member_version"] == 1

    asyncio.run(scenario())


def test_e2ee_service_reconcile_group_session_state_prunes_removed_members(monkeypatch) -> None:
    alice_db = FakeDatabase()
    bob_db = FakeDatabase()
    charlie_db = FakeDatabase()

    monkeypatch.setattr(e2ee_service_module, "get_http_client", lambda: FakeHttpClient())

    def build_remote_bundle(bundle: dict[str, object], *, user_id: str) -> dict[str, object]:
        signed_prekey = dict(bundle["signed_prekey"])
        one_time_prekey = dict(bundle["one_time_prekeys"][0])
        return {
            "device_id": bundle["device_id"],
            "user_id": user_id,
            "device_name": bundle["device_name"],
            "identity_key_public": bundle["identity_key_public"],
            "signing_key_public": bundle["signing_key_public"],
            "signed_prekey": {
                "key_id": signed_prekey["key_id"],
                "public_key": signed_prekey["public_key"],
                "signature": signed_prekey["signature"],
            },
            "one_time_prekey": {
                "prekey_id": one_time_prekey["prekey_id"],
                "public_key": one_time_prekey["public_key"],
            },
        }

    async def scenario() -> None:
        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: alice_db)
        alice_service = e2ee_service_module.E2EEService()
        alice_bundle = await alice_service.get_or_create_local_bundle()

        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: bob_db)
        bob_service = e2ee_service_module.E2EEService()
        bob_bundle = await bob_service.get_or_create_local_bundle()

        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: charlie_db)
        charlie_service = e2ee_service_module.E2EEService()
        charlie_bundle = await charlie_service.get_or_create_local_bundle()

        alice_remote_bundle = build_remote_bundle(alice_bundle, user_id="alice")

        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: bob_db)
        bob_fanout = await bob_service.prepare_group_session_fanout(
            "session-group-5",
            [alice_remote_bundle],
            member_version=3,
            owner_user_id="bob",
        )
        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: charlie_db)
        charlie_fanout = await charlie_service.prepare_group_session_fanout(
            "session-group-5",
            [alice_remote_bundle],
            member_version=3,
            owner_user_id="charlie",
        )
        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: alice_db)
        await alice_service.apply_group_session_fanout(bob_fanout["fanout"][0])
        await alice_service.apply_group_session_fanout(charlie_fanout["fanout"][0])

        reconcile = await alice_service.reconcile_group_session_state(
            "session-group-5",
            member_version=3,
            member_user_ids=["alice", "bob"],
        )
        summary = await alice_service.get_group_session_summary("session-group-5")
        removed_sender_key = await alice_service.get_group_sender_key_record(
            "session-group-5",
            owner_device_id=charlie_bundle["device_id"],
            sender_key_id=charlie_fanout["sender_key_id"],
        )

        assert reconcile["changed"] is True
        assert reconcile["local_sender_key_cleared"] is False
        assert reconcile["pruned_inbound_sender_devices"] == [charlie_bundle["device_id"]]
        assert summary["inbound_sender_devices"] == [bob_bundle["device_id"]]
        assert removed_sender_key is None

    asyncio.run(scenario())


def test_e2ee_service_applies_group_session_fanout_for_recipient_device(monkeypatch) -> None:
    alice_db = FakeDatabase()
    bob_db = FakeDatabase()

    monkeypatch.setattr(e2ee_service_module, "get_http_client", lambda: FakeHttpClient())

    def build_remote_bundle(bundle: dict[str, object], *, user_id: str) -> dict[str, object]:
        signed_prekey = dict(bundle["signed_prekey"])
        one_time_prekey = dict(bundle["one_time_prekeys"][0])
        return {
            "device_id": bundle["device_id"],
            "user_id": user_id,
            "device_name": bundle["device_name"],
            "identity_key_public": bundle["identity_key_public"],
            "signing_key_public": bundle["signing_key_public"],
            "signed_prekey": {
                "key_id": signed_prekey["key_id"],
                "public_key": signed_prekey["public_key"],
                "signature": signed_prekey["signature"],
            },
            "one_time_prekey": {
                "prekey_id": one_time_prekey["prekey_id"],
                "public_key": one_time_prekey["public_key"],
            },
        }

    async def scenario() -> None:
        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: alice_db)
        alice_service = e2ee_service_module.E2EEService()
        alice_bundle = await alice_service.get_or_create_local_bundle()

        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: bob_db)
        bob_service = e2ee_service_module.E2EEService()
        bob_bundle = await bob_service.get_or_create_local_bundle()
        bob_remote_bundle = build_remote_bundle(bob_bundle, user_id="bob")

        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: alice_db)
        fanout = await alice_service.prepare_group_session_fanout(
            "session-group-3",
            [bob_remote_bundle],
            member_version=5,
            owner_user_id="alice",
        )

        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: bob_db)
        install_result = await bob_service.apply_group_session_fanout(fanout["fanout"][0])
        summary = await bob_service.get_group_session_summary("session-group-3")
        installed_key = await bob_service.get_group_sender_key_record(
            "session-group-3",
            owner_device_id=alice_bundle["device_id"],
        )

        assert install_result == {
            "session_id": "session-group-3",
            "sender_key_id": fanout["sender_key_id"],
            "member_version": 5,
            "owner_device_id": alice_bundle["device_id"],
            "installed": True,
        }
        assert summary == {
            "session_id": "session-group-3",
            "local_device_id": bob_bundle["device_id"],
            "has_local_sender_key": False,
            "local_sender_key_id": "",
            "member_version": 0,
            "retired_local_sender_key_ids": [],
            "inbound_sender_devices": [alice_bundle["device_id"]],
            "total_sender_keys": 1,
            "updated_at": summary["updated_at"],
        }
        assert installed_key is not None
        assert installed_key["key_id"] == fanout["sender_key_id"]
        assert installed_key["member_version"] == 5
        assert installed_key["owner_user_id"] == "alice"
        assert installed_key["owner_device_id"] == alice_bundle["device_id"]
        assert installed_key["sender_key_scheme"] == bob_service.GROUP_SENDER_KEY_SCHEME

    asyncio.run(scenario())


def test_e2ee_service_encrypts_group_text_with_sender_key_fanout(monkeypatch) -> None:
    alice_db = FakeDatabase()
    bob_db = FakeDatabase()

    monkeypatch.setattr(e2ee_service_module, "get_http_client", lambda: FakeHttpClient())

    def build_remote_bundle(bundle: dict[str, object], *, user_id: str) -> dict[str, object]:
        signed_prekey = dict(bundle["signed_prekey"])
        one_time_prekey = dict(bundle["one_time_prekeys"][0])
        return {
            "device_id": bundle["device_id"],
            "user_id": user_id,
            "device_name": bundle["device_name"],
            "identity_key_public": bundle["identity_key_public"],
            "signing_key_public": bundle["signing_key_public"],
            "signed_prekey": {
                "key_id": signed_prekey["key_id"],
                "public_key": signed_prekey["public_key"],
                "signature": signed_prekey["signature"],
            },
            "one_time_prekey": {
                "prekey_id": one_time_prekey["prekey_id"],
                "public_key": one_time_prekey["public_key"],
            },
            "available_prekey_count": len(bundle["one_time_prekeys"]),
        }

    async def scenario() -> None:
        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: alice_db)
        alice_service = e2ee_service_module.E2EEService()
        alice_bundle = await alice_service.get_or_create_local_bundle()

        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: bob_db)
        bob_service = e2ee_service_module.E2EEService()
        bob_bundle = await bob_service.get_or_create_local_bundle()
        bob_remote_bundle = build_remote_bundle(bob_bundle, user_id="bob")

        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: alice_db)
        ciphertext, encryption = await alice_service.encrypt_text_for_group_session(
            "session-group-text-1",
            "hello encrypted group",
            [bob_remote_bundle],
            member_version=7,
            owner_user_id="alice",
        )
        remote_extra = sanitize_outbound_message_extra({"encryption": encryption})

        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: bob_db)
        plaintext = await bob_service.decrypt_text_content(
            ciphertext,
            {
                "session_id": "session-group-text-1",
                "encryption": remote_extra["encryption"],
            },
        )
        summary = await bob_service.get_group_session_summary("session-group-text-1")
        installed_key = await bob_service.get_group_sender_key_record(
            "session-group-text-1",
            owner_device_id=alice_bundle["device_id"],
        )

        assert plaintext == "hello encrypted group"
        assert remote_extra["encryption"]["scheme"] == alice_service.GROUP_SENDER_KEY_SCHEME
        assert remote_extra["encryption"]["content_ciphertext"] == ciphertext
        assert "local_plaintext" not in remote_extra["encryption"]
        assert len(remote_extra["encryption"]["fanout"]) == 1
        assert remote_extra["encryption"]["fanout"][0]["recipient_device_id"] == bob_bundle["device_id"]
        assert summary["inbound_sender_devices"] == [alice_bundle["device_id"]]
        assert summary["total_sender_keys"] == 1
        assert installed_key is not None
        assert installed_key["key_id"] == remote_extra["encryption"]["sender_key_id"]
        assert installed_key["member_version"] == 7

    asyncio.run(scenario())


def test_e2ee_service_encrypts_group_attachment_with_sender_key_fanout(monkeypatch) -> None:
    alice_db = FakeDatabase()
    bob_db = FakeDatabase()

    monkeypatch.setattr(e2ee_service_module, "get_http_client", lambda: FakeHttpClient())
    workspace_tmp = (Path.cwd() / "client/tests/.pytest_tmp/e2ee-service-group-attachment").resolve()
    workspace_tmp.mkdir(parents=True, exist_ok=True)

    def build_remote_bundle(bundle: dict[str, object], *, user_id: str) -> dict[str, object]:
        signed_prekey = dict(bundle["signed_prekey"])
        one_time_prekey = dict(bundle["one_time_prekeys"][0])
        return {
            "device_id": bundle["device_id"],
            "user_id": user_id,
            "device_name": bundle["device_name"],
            "identity_key_public": bundle["identity_key_public"],
            "signing_key_public": bundle["signing_key_public"],
            "signed_prekey": {
                "key_id": signed_prekey["key_id"],
                "public_key": signed_prekey["public_key"],
                "signature": signed_prekey["signature"],
            },
            "one_time_prekey": {
                "prekey_id": one_time_prekey["prekey_id"],
                "public_key": one_time_prekey["public_key"],
            },
            "available_prekey_count": len(bundle["one_time_prekeys"]),
        }

    async def scenario() -> None:
        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: alice_db)
        alice_service = e2ee_service_module.E2EEService()
        alice_bundle = await alice_service.get_or_create_local_bundle()

        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: bob_db)
        bob_service = e2ee_service_module.E2EEService()
        bob_bundle = await bob_service.get_or_create_local_bundle()
        bob_remote_bundle = build_remote_bundle(bob_bundle, user_id="bob")

        source_path = workspace_tmp / "group-secret.png"
        plaintext_bytes = b"group-image-payload"
        source_path.write_bytes(plaintext_bytes)

        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: alice_db)
        encrypted = await alice_service.encrypt_attachment_for_group_session(
            "session-group-attachment-1",
            str(source_path),
            [bob_remote_bundle],
            fallback_name="group-secret.png",
            size_bytes=len(plaintext_bytes),
            mime_type="image/png",
            member_version=11,
            owner_user_id="alice",
        )
        remote_metadata = sanitize_outbound_message_extra(
            {"attachment_encryption": dict(encrypted.attachment_encryption)}
        )["attachment_encryption"]
        ciphertext_bytes = Path(encrypted.upload_file_path).read_bytes()

        monkeypatch.setattr(e2ee_service_module, "get_database", lambda: bob_db)
        metadata = await bob_service.decrypt_attachment_metadata(remote_metadata)
        decrypted_bytes, decrypted_metadata = await bob_service.decrypt_attachment_bytes(ciphertext_bytes, remote_metadata)
        summary = await bob_service.get_group_session_summary("session-group-attachment-1")
        installed_key = await bob_service.get_group_sender_key_record(
            "session-group-attachment-1",
            owner_device_id=alice_bundle["device_id"],
        )

        assert remote_metadata["scheme"] == alice_service.GROUP_ATTACHMENT_SCHEME
        assert remote_metadata["sender_device_id"] == alice_bundle["device_id"]
        assert remote_metadata["sender_key_id"]
        assert len(remote_metadata["fanout"]) == 1
        assert remote_metadata["fanout"][0]["recipient_device_id"] == bob_bundle["device_id"]
        assert "local_metadata" not in remote_metadata
        assert metadata is not None
        assert metadata["original_name"] == "group-secret.png"
        assert metadata["mime_type"] == "image/png"
        assert decrypted_bytes == plaintext_bytes
        assert decrypted_metadata["size_bytes"] == len(plaintext_bytes)
        assert summary["inbound_sender_devices"] == [alice_bundle["device_id"]]
        assert installed_key is not None
        assert installed_key["key_id"] == remote_metadata["sender_key_id"]
        assert installed_key["member_version"] == 11

    try:
        asyncio.run(scenario())
    finally:
        shutil.rmtree(workspace_tmp, ignore_errors=True)
