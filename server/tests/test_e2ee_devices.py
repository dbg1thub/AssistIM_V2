"""E2EE device bootstrap API tests."""

from __future__ import annotations

from base64 import b64encode
from sqlalchemy import String

from fastapi.testclient import TestClient
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, x25519

from app.models.device import UserPreKey, UserSignedPreKey


_SIGNING_PRIVATE_BY_DEVICE_ID: dict[str, ed25519.Ed25519PrivateKey] = {}


def test_prekey_models_keep_string_primary_keys_for_existing_schema() -> None:
    signed_prekey_id_type = UserSignedPreKey.__table__.c.id.type
    one_time_prekey_id_type = UserPreKey.__table__.c.id.type

    assert isinstance(signed_prekey_id_type, String)
    assert isinstance(one_time_prekey_id_type, String)
    assert signed_prekey_id_type.length == 36
    assert one_time_prekey_id_type.length == 36


def _b64(raw: bytes) -> str:
    return b64encode(raw).decode("ascii")


def _x25519_public() -> str:
    private_key = x25519.X25519PrivateKey.generate()
    return _b64(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    )


def _device_payload(device_id: str, *, offset: int = 0) -> dict:
    signing_private = ed25519.Ed25519PrivateKey.generate()
    _SIGNING_PRIVATE_BY_DEVICE_ID[device_id] = signing_private
    signing_public = signing_private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    signed_prekey_public = x25519.X25519PrivateKey.generate().public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return {
        "device_id": device_id,
        "device_name": f"Desktop {device_id}",
        "identity_key_public": _x25519_public(),
        "signing_key_public": _b64(signing_public),
        "signed_prekey": {
            "key_id": 1 + offset,
            "public_key": _b64(signed_prekey_public),
            "signature": _b64(signing_private.sign(signed_prekey_public)),
        },
        "prekeys": [
            {
                "prekey_id": 1 + offset,
                "public_key": _x25519_public(),
            },
            {
                "prekey_id": 2 + offset,
                "public_key": _x25519_public(),
            },
        ],
    }


def _signed_prekey_for_device(device_id: str, key_id: int) -> dict:
    signing_private = _SIGNING_PRIVATE_BY_DEVICE_ID[device_id]
    signed_prekey_public = x25519.X25519PrivateKey.generate().public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return {
        "key_id": key_id,
        "public_key": _b64(signed_prekey_public),
        "signature": _b64(signing_private.sign(signed_prekey_public)),
    }


def test_device_key_refresh_requires_signed_prekey_or_prekeys(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice_e2ee_refresh_schema", "Alice E2EE Refresh Schema")

    register_response = client.post(
        "/api/v1/devices/register",
        json=_device_payload("alice-refresh-schema-device"),
        headers=auth_header(alice["access_token"]),
    )
    assert register_response.status_code == 200

    empty_refresh = client.post(
        "/api/v1/devices/alice-refresh-schema-device/keys/refresh",
        json={},
        headers=auth_header(alice["access_token"]),
    )
    assert empty_refresh.status_code == 422
    assert "signed_prekey or prekeys is required" in empty_refresh.json()["message"]

    empty_prekeys = client.post(
        "/api/v1/devices/alice-refresh-schema-device/keys/refresh",
        json={"prekeys": []},
        headers=auth_header(alice["access_token"]),
    )
    assert empty_prekeys.status_code == 422
    assert "signed_prekey or prekeys is required" in empty_prekeys.json()["message"]

    signed_prekey_only = client.post(
        "/api/v1/devices/alice-refresh-schema-device/keys/refresh",
        json={"signed_prekey": _signed_prekey_for_device("alice-refresh-schema-device", 50)},
        headers=auth_header(alice["access_token"]),
    )
    assert signed_prekey_only.status_code == 200
    assert signed_prekey_only.json()["data"]["available_prekey_count"] == 2

    prekeys_only = client.post(
        "/api/v1/devices/alice-refresh-schema-device/keys/refresh",
        json={
            "prekeys": [
                {
                    "prekey_id": 200,
                    "public_key": _x25519_public(),
                }
            ]
        },
        headers=auth_header(alice["access_token"]),
    )
    assert prekeys_only.status_code == 200
    assert prekeys_only.json()["data"]["available_prekey_count"] == 3


def test_device_registration_and_prekey_claim_flow(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice_e2ee_devices", "Alice E2EE Devices")
    bob = user_factory("bob_e2ee_devices", "Bob E2EE Devices")

    register_response = client.post(
        "/api/v1/devices/register",
        json=_device_payload("alice-device-1"),
        headers=auth_header(alice["access_token"]),
    )
    assert register_response.status_code == 200
    registered_device = register_response.json()["data"]
    assert registered_device["device_id"] == "alice-device-1"
    assert registered_device["user_id"] == alice["user"]["id"]
    assert registered_device["available_prekey_count"] == 2

    list_response = client.get(
        "/api/v1/devices",
        headers=auth_header(alice["access_token"]),
    )
    assert list_response.status_code == 200
    devices = list_response.json()["data"]
    assert len(devices) == 1
    assert devices[0]["device_id"] == "alice-device-1"

    bundle_response = client.get(
        f"/api/v1/keys/prekey-bundle/{alice['user']['id']}",
        headers=auth_header(bob["access_token"]),
    )
    assert bundle_response.status_code == 200
    bundles = bundle_response.json()["data"]
    assert len(bundles) == 1
    assert bundles[0]["device_id"] == "alice-device-1"
    assert bundles[0]["signed_prekey"]["key_id"] == 1
    assert bundles[0]["one_time_prekey"] is None
    assert bundles[0]["available_prekey_count"] == 2

    claim_response = client.post(
        "/api/v1/keys/prekeys/claim",
        json={"device_ids": ["alice-device-1"]},
        headers=auth_header(bob["access_token"]),
    )
    assert claim_response.status_code == 200
    claimed = claim_response.json()["data"]
    assert len(claimed) == 1
    assert claimed[0]["device_id"] == "alice-device-1"
    assert claimed[0]["one_time_prekey"]["prekey_id"] == 1
    assert claimed[0]["available_prekey_count"] == 1

    refresh_response = client.post(
        "/api/v1/devices/alice-device-1/keys/refresh",
        json={
            "signed_prekey": _signed_prekey_for_device("alice-device-1", 99),
            "prekeys": [
                {
                    "prekey_id": 100,
                    "public_key": _x25519_public(),
                },
                {
                    "prekey_id": 101,
                    "public_key": _x25519_public(),
                },
            ],
        },
        headers=auth_header(alice["access_token"]),
    )
    assert refresh_response.status_code == 200
    refreshed_device = refresh_response.json()["data"]
    assert refreshed_device["device_id"] == "alice-device-1"
    assert refreshed_device["available_prekey_count"] == 3

    refreshed_bundle_response = client.get(
        f"/api/v1/keys/prekey-bundle/{alice['user']['id']}",
        headers=auth_header(bob["access_token"]),
    )
    assert refreshed_bundle_response.status_code == 200
    refreshed_bundles = refreshed_bundle_response.json()["data"]
    assert len(refreshed_bundles) == 1
    assert refreshed_bundles[0]["signed_prekey"]["key_id"] == 99
    assert refreshed_bundles[0]["available_prekey_count"] == 3

    second_claim_response = client.post(
        "/api/v1/keys/prekeys/claim",
        json={"device_ids": ["alice-device-1"]},
        headers=auth_header(bob["access_token"]),
    )
    assert second_claim_response.status_code == 200
    second_claim = second_claim_response.json()["data"]
    assert len(second_claim) == 1
    assert second_claim[0]["one_time_prekey"]["prekey_id"] == 2
    assert second_claim[0]["available_prekey_count"] == 2

    duplicated_claim = client.post(
        "/api/v1/keys/prekeys/claim",
        json={"device_ids": [" alice-device-1 ", "alice-device-1", ""]},
        headers=auth_header(bob["access_token"]),
    )
    assert duplicated_claim.status_code == 200
    assert len(duplicated_claim.json()["data"]) == 1
    assert duplicated_claim.json()["data"][0]["one_time_prekey"]["prekey_id"] == 100

    exhausted_one_time_prekeys = client.post(
        "/api/v1/keys/prekeys/claim",
        json={"device_ids": ["alice-device-1"]},
        headers=auth_header(bob["access_token"]),
    )
    assert exhausted_one_time_prekeys.status_code == 200
    assert exhausted_one_time_prekeys.json()["data"][0]["one_time_prekey"]["prekey_id"] == 101

    no_prekeys_left = client.post(
        "/api/v1/keys/prekeys/claim",
        json={"device_ids": ["alice-device-1"]},
        headers=auth_header(bob["access_token"]),
    )
    assert no_prekeys_left.status_code == 409
    assert "no available one-time prekey" in no_prekeys_left.json()["message"]

    delete_response = client.delete(
        "/api/v1/devices/alice-device-1",
        headers=auth_header(alice["access_token"]),
    )
    assert delete_response.status_code == 204

    list_after_delete = client.get(
        "/api/v1/devices",
        headers=auth_header(alice["access_token"]),
    )
    assert list_after_delete.status_code == 200
    assert list_after_delete.json()["data"] == []


def test_device_registration_rejects_invalid_signed_prekey_signature(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice_e2ee_invalid_signature", "Alice E2EE Invalid Signature")
    payload = _device_payload("alice-invalid-signature-device")
    payload["signed_prekey"]["signature"] = _b64(b"x" * 64)

    response = client.post(
        "/api/v1/devices/register",
        json=payload,
        headers=auth_header(alice["access_token"]),
    )

    assert response.status_code == 422
    assert "signed_prekey signature is invalid" in response.json()["message"]
