"""Admin E2EE device and key inventory inspection API tests."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.core.errors import ErrorCode
from app.models.admin import AdminAuditLog
from app.models.device import UserDevice, UserPreKey, UserSignedPreKey
from app.models.user import User


MISSING_DEVICE_USER_ID = "00000000-0000-0000-0000-000000000041"
MISSING_PREKEY_DEVICE_ID = "missing-prekey-device"
MISSING_SIGNED_PREKEY_DEVICE_ID = "missing-signed-prekey-device"


def _register(client: TestClient, username: str, nickname: str) -> dict:
    response = client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": "secret123", "nickname": nickname},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _set_role(user_id: str, role: str) -> None:
    with SessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        user.role = role
        db.add(user)
        db.commit()


def _seed_device(
    *,
    device_id: str,
    user_id: str,
    active: bool = True,
    signed_prekey_count: int = 1,
    active_signed_prekey_count: int = 1,
    available_prekeys: int = 3,
    consumed_prekeys: int = 1,
) -> None:
    with SessionLocal() as db:
        db.add(
            UserDevice(
                device_id=device_id,
                user_id=user_id,
                identity_key_public=f"identity-secret-{device_id}",
                signing_key_public=f"signing-secret-{device_id}",
                device_name=f"Device {device_id}",
                is_active=active,
            )
        )
        for index in range(signed_prekey_count):
            db.add(
                UserSignedPreKey(
                    device_id=device_id,
                    key_id=index + 1,
                    public_key=f"signed-public-secret-{device_id}-{index}",
                    signature=f"signed-signature-secret-{device_id}-{index}",
                    is_active=index < active_signed_prekey_count,
                )
            )
        for index in range(available_prekeys):
            db.add(
                UserPreKey(
                    device_id=device_id,
                    prekey_id=index + 1,
                    public_key=f"available-prekey-secret-{device_id}-{index}",
                    is_consumed=False,
                )
            )
        for index in range(consumed_prekeys):
            db.add(
                UserPreKey(
                    device_id=device_id,
                    prekey_id=100 + index,
                    public_key=f"consumed-prekey-secret-{device_id}-{index}",
                    is_consumed=True,
                )
            )
        db.commit()


def _seed_orphan_prekey(*, device_id: str = MISSING_PREKEY_DEVICE_ID) -> None:
    with SessionLocal() as db:
        db.add(
            UserPreKey(
                device_id=device_id,
                prekey_id=1,
                public_key="orphan-prekey-secret",
                is_consumed=False,
            )
        )
        db.commit()


def _seed_orphan_signed_prekey(*, device_id: str = MISSING_SIGNED_PREKEY_DEVICE_ID) -> None:
    with SessionLocal() as db:
        db.add(
            UserSignedPreKey(
                device_id=device_id,
                key_id=1,
                public_key="orphan-signed-prekey-secret",
                signature="orphan-signed-signature-secret",
                is_active=True,
            )
        )
        db.commit()


def test_admin_e2ee_forbids_non_admin(client: TestClient) -> None:
    auth_payload = _register(client, "e2ee-normal", "E2EE Normal")
    headers = _auth_header(auth_payload["access_token"])

    responses = [
        client.get("/api/v1/admin/e2ee/devices", headers=headers),
        client.get("/api/v1/admin/e2ee/prekeys", headers=headers),
        client.get("/api/v1/admin/e2ee/health", headers=headers),
    ]

    assert [response.status_code for response in responses] == [403, 403, 403]
    assert all(response.json()["code"] == ErrorCode.FORBIDDEN for response in responses)


def test_admin_e2ee_devices_list_filters_counts_and_hides_key_material(client: TestClient) -> None:
    admin_auth = _register(client, "e2ee-list-admin", "E2EE List Admin")
    alice = _register(client, "e2ee-list-alice", "E2EE List Alice")
    bob = _register(client, "e2ee-list-bob", "E2EE List Bob")
    _set_role(admin_auth["user"]["id"], "admin")
    _seed_device(device_id="alice-active-device", user_id=alice["user"]["id"], active=True, available_prekeys=6)
    _seed_device(device_id="bob-inactive-device", user_id=bob["user"]["id"], active=False, available_prekeys=2)

    response = client.get(
        "/api/v1/admin/e2ee/devices",
        headers=_auth_header(admin_auth["access_token"]),
        params={"user_id": alice["user"]["id"], "active": "true", "page": 1, "size": 10},
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["total"] == 1
    assert payload["page"] == 1
    assert payload["size"] == 10
    item = payload["items"][0]
    assert item["device_id"] == "alice-active-device"
    assert item["user_id"] == alice["user"]["id"]
    assert item["user"]["username"] == "e2ee-list-alice"
    assert item["is_active"] is True
    assert item["key_material"] == {
        "identity_key_public_present": True,
        "signing_key_public_present": True,
    }
    assert item["signed_prekeys"] == {"total": 1, "active": 1}
    assert item["one_time_prekeys"] == {"total": 7, "available": 6, "consumed": 1}
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "identity-secret" not in serialized
    assert "signing-secret" not in serialized
    assert "signed-public-secret" not in serialized
    assert "signed-signature-secret" not in serialized
    assert "available-prekey-secret" not in serialized

    with SessionLocal() as db:
        audit = db.query(AdminAuditLog).filter(AdminAuditLog.action == "admin.e2ee.devices.read").one()
        assert audit.actor_user_id == admin_auth["user"]["id"]
        assert audit.success is True


def test_admin_e2ee_device_detail_and_prekey_list_are_redacted(client: TestClient) -> None:
    admin_auth = _register(client, "e2ee-detail-admin", "E2EE Detail Admin")
    alice = _register(client, "e2ee-detail-alice", "E2EE Detail Alice")
    _set_role(admin_auth["user"]["id"], "admin")
    _seed_device(
        device_id="alice-detail-device",
        user_id=alice["user"]["id"],
        active=True,
        signed_prekey_count=2,
        active_signed_prekey_count=1,
        available_prekeys=2,
        consumed_prekeys=2,
    )

    detail_response = client.get(
        "/api/v1/admin/e2ee/devices/alice-detail-device",
        headers=_auth_header(admin_auth["access_token"]),
    )
    prekeys_response = client.get(
        "/api/v1/admin/e2ee/prekeys",
        headers=_auth_header(admin_auth["access_token"]),
        params={"device_id": "alice-detail-device", "consumed": "false", "page": 1, "size": 10},
    )

    assert detail_response.status_code == 200, detail_response.text
    detail = detail_response.json()["data"]
    assert detail["device_id"] == "alice-detail-device"
    assert detail["signed_prekeys"] == {"total": 2, "active": 1}
    assert detail["one_time_prekeys"] == {"total": 4, "available": 2, "consumed": 2}
    assert detail["key_material"] == {
        "identity_key_public_present": True,
        "signing_key_public_present": True,
    }

    assert prekeys_response.status_code == 200, prekeys_response.text
    prekeys = prekeys_response.json()["data"]
    assert prekeys["total"] == 2
    assert prekeys["items"][0]["device_id"] == "alice-detail-device"
    assert prekeys["items"][0]["is_consumed"] is False
    assert prekeys["items"][0]["device"]["exists"] is True
    serialized = json.dumps({"detail": detail, "prekeys": prekeys}, ensure_ascii=False)
    assert "identity-secret" not in serialized
    assert "signing-secret" not in serialized
    assert "signed-public-secret" not in serialized
    assert "signed-signature-secret" not in serialized
    assert "available-prekey-secret" not in serialized
    assert "consumed-prekey-secret" not in serialized
    assert "public_key" not in serialized
    assert "signature" not in serialized

    with SessionLocal() as db:
        assert db.query(AdminAuditLog).filter(AdminAuditLog.action == "admin.e2ee.device.read").one().success is True
        assert db.query(AdminAuditLog).filter(AdminAuditLog.action == "admin.e2ee.prekeys.read").one().success is True


def test_admin_e2ee_health_reports_inventory_integrity_issues(client: TestClient) -> None:
    admin_auth = _register(client, "e2ee-health-admin", "E2EE Health Admin")
    alice = _register(client, "e2ee-health-alice", "E2EE Health Alice")
    no_device_user = _register(client, "e2ee-health-no-device", "E2EE Health No Device")
    _set_role(admin_auth["user"]["id"], "admin")
    _seed_device(
        device_id="missing-user-device",
        user_id=MISSING_DEVICE_USER_ID,
        active=True,
        available_prekeys=3,
    )
    _seed_device(
        device_id="missing-signed-device",
        user_id=alice["user"]["id"],
        active=True,
        signed_prekey_count=0,
        active_signed_prekey_count=0,
        available_prekeys=5,
    )
    _seed_device(
        device_id="low-prekeys-device",
        user_id=alice["user"]["id"],
        active=True,
        signed_prekey_count=1,
        active_signed_prekey_count=1,
        available_prekeys=1,
    )
    _seed_device(
        device_id="duplicate-active-signed-device",
        user_id=alice["user"]["id"],
        active=True,
        signed_prekey_count=2,
        active_signed_prekey_count=2,
        available_prekeys=5,
    )
    _seed_orphan_prekey()
    _seed_orphan_signed_prekey()

    response = client.get(
        "/api/v1/admin/e2ee/health",
        headers=_auth_header(admin_auth["access_token"]),
        params={"min_available_prekeys": 2},
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["status"] == "warning"
    issue_types = {item["issue_type"] for item in payload["issues"]}
    assert "e2ee_device_user_missing" in issue_types
    assert "e2ee_active_user_without_active_device" in issue_types
    assert "e2ee_active_device_missing_active_signed_prekey" in issue_types
    assert "e2ee_active_device_low_available_prekeys" in issue_types
    assert "e2ee_prekey_device_missing" in issue_types
    assert "e2ee_signed_prekey_device_missing" in issue_types
    assert "e2ee_device_duplicate_active_signed_prekeys" in issue_types
    assert any(
        item["issue_type"] == "e2ee_device_user_missing"
        and item["user_id"] == MISSING_DEVICE_USER_ID
        for item in payload["issues"]
    )
    assert any(
        item["issue_type"] == "e2ee_active_user_without_active_device"
        and item["user_id"] == no_device_user["user"]["id"]
        for item in payload["issues"]
    )
    assert any(
        item["issue_type"] == "e2ee_active_device_low_available_prekeys"
        and item["device_id"] == "low-prekeys-device"
        and item["available_prekeys"] == 1
        for item in payload["issues"]
    )
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "secret" not in serialized
    assert "public_key" not in serialized
    assert "signature" not in serialized

    with SessionLocal() as db:
        audit = db.query(AdminAuditLog).filter(AdminAuditLog.action == "admin.e2ee.health.read").one()
        assert audit.actor_user_id == admin_auth["user"]["id"]
        assert audit.success is True
