"""E2EE device bootstrap API tests."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _device_payload(device_id: str, *, offset: int = 0) -> dict:
    return {
        "device_id": device_id,
        "device_name": f"Desktop {device_id}",
        "identity_key_public": f"identity-key-{device_id}-{'a' * 24}",
        "signing_key_public": f"signing-key-{device_id}-{'b' * 24}",
        "signed_prekey": {
            "key_id": 1 + offset,
            "public_key": f"signed-prekey-{device_id}-{'c' * 24}",
            "signature": f"signature-{device_id}-{'d' * 24}",
        },
        "prekeys": [
            {
                "prekey_id": 1 + offset,
                "public_key": f"prekey-one-{device_id}-{'e' * 24}",
            },
            {
                "prekey_id": 2 + offset,
                "public_key": f"prekey-two-{device_id}-{'f' * 24}",
            },
        ],
    }


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
            "signed_prekey": {
                "key_id": 99,
                "public_key": "signed-prekey-rotated-" + ("x" * 24),
                "signature": "signature-rotated-" + ("y" * 24),
            },
            "prekeys": [
                {
                    "prekey_id": 100,
                    "public_key": "refresh-prekey-one-" + ("z" * 24),
                },
                {
                    "prekey_id": 101,
                    "public_key": "refresh-prekey-two-" + ("w" * 24),
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
