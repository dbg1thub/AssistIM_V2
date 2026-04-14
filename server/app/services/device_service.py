"""Device and prekey service for private-chat E2EE bootstrap."""

from __future__ import annotations

from base64 import b64decode
from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.user import User
from app.repositories.device_repo import DeviceRepository
from app.repositories.user_repo import UserRepository


class DeviceService:
    MAX_PREKEYS_PER_REQUEST = 100
    X25519_PUBLIC_KEY_BYTES = 32
    ED25519_PUBLIC_KEY_BYTES = 32

    def __init__(self, db: Session) -> None:
        self.db = db
        self.devices = DeviceRepository(db)
        self.users = UserRepository(db)

    def register_device(self, current_user: User, payload: dict[str, Any]) -> dict[str, Any]:
        device_id = self._require_non_empty(payload.get("device_id"), "device_id")
        identity_key_public = self._require_non_empty(payload.get("identity_key_public"), "identity_key_public")
        signing_key_public = self._require_non_empty(payload.get("signing_key_public"), "signing_key_public")
        device_name = str(payload.get("device_name") or "").strip() or "AssistIM Desktop"
        self._require_public_key_bytes(identity_key_public, "identity_key_public", self.X25519_PUBLIC_KEY_BYTES)
        self._require_public_key_bytes(signing_key_public, "signing_key_public", self.ED25519_PUBLIC_KEY_BYTES)

        signed_prekey_payload = payload.get("signed_prekey")
        if not isinstance(signed_prekey_payload, dict):
            raise AppError(ErrorCode.INVALID_REQUEST, "signed_prekey is required", 422)
        signed_prekey = self._normalize_signed_prekey(signed_prekey_payload)
        self._verify_signed_prekey_signature(signing_key_public, signed_prekey)

        raw_prekeys = payload.get("prekeys")
        if not isinstance(raw_prekeys, list) or not raw_prekeys:
            raise AppError(ErrorCode.INVALID_REQUEST, "prekeys must contain at least one item", 422)
        if len(raw_prekeys) > self.MAX_PREKEYS_PER_REQUEST:
            raise AppError(ErrorCode.INVALID_REQUEST, "too many prekeys in one request", 422)
        prekeys = self._normalize_prekeys(raw_prekeys)

        device = self.devices.upsert_device(
            user_id=current_user.id,
            device_id=device_id,
            identity_key_public=identity_key_public,
            signing_key_public=signing_key_public,
            device_name=device_name,
        )
        self.devices.upsert_signed_prekey(
            device_id=device.device_id,
            key_id=signed_prekey["key_id"],
            public_key=signed_prekey["public_key"],
            signature=signed_prekey["signature"],
        )
        self.devices.replace_prekeys(device.device_id, prekeys)
        self.db.commit()
        self.db.refresh(device)
        return self.serialize_device(device, available_prekey_count=len(prekeys))

    def list_my_devices(self, current_user: User) -> list[dict[str, Any]]:
        items = self.devices.list_devices_for_user(current_user.id)
        prekey_counts = self.devices.count_available_prekeys_by_device_ids([str(item.device_id or "") for item in items])
        return [
            self.serialize_device(
                item,
                available_prekey_count=prekey_counts.get(str(item.device_id or ""), 0),
            )
            for item in items
        ]

    def refresh_my_device_keys(self, current_user: User, device_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        device = self.devices.get_device_for_user(current_user.id, device_id)
        if device is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "device not found", 404)

        signed_prekey_payload = payload.get("signed_prekey")
        signed_prekey = None
        if signed_prekey_payload is not None:
            if not isinstance(signed_prekey_payload, dict):
                raise AppError(ErrorCode.INVALID_REQUEST, "signed_prekey must be an object", 422)
            signed_prekey = self._normalize_signed_prekey(signed_prekey_payload)
            self._verify_signed_prekey_signature(str(device.signing_key_public or ""), signed_prekey)

        raw_prekeys = payload.get("prekeys")
        prekeys: list[dict[str, object]] = []
        if raw_prekeys is not None:
            if not isinstance(raw_prekeys, list):
                raise AppError(ErrorCode.INVALID_REQUEST, "prekeys must be a list", 422)
            if len(raw_prekeys) > self.MAX_PREKEYS_PER_REQUEST:
                raise AppError(ErrorCode.INVALID_REQUEST, "too many prekeys in one request", 422)
            prekeys = self._normalize_prekeys(raw_prekeys) if raw_prekeys else []

        if signed_prekey is None and not prekeys:
            raise AppError(ErrorCode.INVALID_REQUEST, "signed_prekey or prekeys is required", 422)

        if signed_prekey is not None:
            self.devices.upsert_signed_prekey(
                device_id=device.device_id,
                key_id=signed_prekey["key_id"],
                public_key=signed_prekey["public_key"],
                signature=signed_prekey["signature"],
            )

        if prekeys:
            duplicate_ids = self.devices.existing_prekey_ids(device.device_id, [int(item["prekey_id"]) for item in prekeys])
            if duplicate_ids:
                raise AppError(ErrorCode.INVALID_REQUEST, "prekey_id already exists for device", 422)
            self.devices.append_prekeys(device.device_id, prekeys)

        self.db.commit()
        self.db.refresh(device)
        return self.serialize_device(
            device,
            available_prekey_count=self.devices.count_available_prekeys(device.device_id),
        )

    def delete_my_device(self, current_user: User, device_id: str) -> None:
        device = self.devices.get_device_for_user(current_user.id, device_id)
        if device is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "device not found", 404)
        self.devices.delete_device(device)
        self.db.commit()

    def list_prekey_bundles(
        self,
        current_user: User,
        target_user_id: str,
        *,
        exclude_device_id: str | None = None,
    ) -> list[dict[str, Any]]:
        self._require_existing_user(target_user_id)
        normalized_target_user_id = str(target_user_id or "").strip()
        normalized_exclude_device_id = str(exclude_device_id or "").strip()
        should_exclude = False
        if normalized_exclude_device_id and normalized_target_user_id == str(current_user.id or ""):
            excluded_device = self.devices.get_device_for_user(current_user.id, normalized_exclude_device_id)
            if excluded_device is None or not excluded_device.is_active:
                raise AppError(ErrorCode.INVALID_REQUEST, "exclude_device_id is not an active device for current user", 422)
            should_exclude = True

        items = self.devices.list_active_devices_for_user(
            normalized_target_user_id,
            exclude_device_id=normalized_exclude_device_id if should_exclude else None,
        )
        device_ids = [str(item.device_id or "") for item in items]
        signed_prekeys = self.devices.get_active_signed_prekeys(device_ids)
        prekey_counts = self.devices.count_available_prekeys_by_device_ids(device_ids)
        missing_signed_prekey_ids = [device_id for device_id in device_ids if device_id not in signed_prekeys]
        if missing_signed_prekey_ids:
            raise AppError(ErrorCode.INVALID_REQUEST, "active device is missing signed prekey", 409)

        bundles: list[dict[str, Any]] = []
        for item in items:
            bundles.append(
                self.serialize_prekey_bundle(
                    item,
                    signed_prekey=signed_prekeys[str(item.device_id or "")],
                    claimed_prekey=None,
                    available_prekey_count=prekey_counts.get(str(item.device_id or ""), 0),
                )
            )
        return bundles

    def claim_prekeys(self, current_user: User, device_ids: list[str]) -> list[dict[str, Any]]:
        del current_user
        normalized_device_ids = [
            device_id
            for device_id in dict.fromkeys(str(raw_device_id or "").strip() for raw_device_id in device_ids)
            if device_id
        ]
        if not normalized_device_ids:
            raise AppError(ErrorCode.INVALID_REQUEST, "device_ids must contain at least one item", 422)

        devices_by_id = self.devices.list_devices_by_ids(normalized_device_ids)
        missing_device_ids = [
            device_id
            for device_id in normalized_device_ids
            if device_id not in devices_by_id or not bool(getattr(devices_by_id[device_id], "is_active", False))
        ]
        if missing_device_ids:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "device not found", 404)

        signed_prekeys = self.devices.get_active_signed_prekeys(normalized_device_ids)
        missing_signed_prekey_ids = [device_id for device_id in normalized_device_ids if device_id not in signed_prekeys]
        if missing_signed_prekey_ids:
            raise AppError(ErrorCode.INVALID_REQUEST, "active device is missing signed prekey", 409)

        claimed: list[dict[str, Any]] = []
        for device_id in normalized_device_ids:
            device = devices_by_id[device_id]
            signed_prekey = signed_prekeys[device_id]
            claimed_prekey = self.devices.claim_one_time_prekey(device_id)
            if claimed_prekey is None:
                raise AppError(ErrorCode.INVALID_REQUEST, "device has no available one-time prekey", 409)
            claimed.append(
                self.serialize_prekey_bundle(
                    device,
                    signed_prekey=signed_prekey,
                    claimed_prekey=claimed_prekey,
                    available_prekey_count=self.devices.count_available_prekeys(device_id),
                )
            )
        self.db.commit()
        return claimed

    def _require_existing_user(self, user_id: str) -> None:
        if self.users.get_by_id(str(user_id or "").strip()) is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "user not found", 404)

    @staticmethod
    def _require_non_empty(value: object, field_name: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise AppError(ErrorCode.INVALID_REQUEST, f"{field_name} is required", 422)
        return normalized

    def _normalize_signed_prekey(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            key_id = int(payload.get("key_id"))
        except (TypeError, ValueError):
            raise AppError(ErrorCode.INVALID_REQUEST, "signed_prekey.key_id is required", 422) from None
        public_key = self._require_non_empty(payload.get("public_key"), "signed_prekey.public_key")
        signature = self._require_non_empty(payload.get("signature"), "signed_prekey.signature")
        self._require_public_key_bytes(public_key, "signed_prekey.public_key", self.X25519_PUBLIC_KEY_BYTES)
        self._require_signature_bytes(signature, "signed_prekey.signature")
        return {
            "key_id": key_id,
            "public_key": public_key,
            "signature": signature,
        }

    def _normalize_prekeys(self, raw_prekeys: list[object]) -> list[dict[str, object]]:
        normalized: list[dict[str, object]] = []
        seen_prekey_ids: set[int] = set()
        for raw_item in raw_prekeys:
            if not isinstance(raw_item, dict):
                raise AppError(ErrorCode.INVALID_REQUEST, "each prekey must be an object", 422)
            try:
                prekey_id = int(raw_item.get("prekey_id"))
            except (TypeError, ValueError):
                raise AppError(ErrorCode.INVALID_REQUEST, "prekey_id is required for each prekey", 422) from None
            if prekey_id in seen_prekey_ids:
                raise AppError(ErrorCode.INVALID_REQUEST, "duplicate prekey_id in request", 422)
            seen_prekey_ids.add(prekey_id)
            public_key = self._require_non_empty(raw_item.get("public_key"), "prekey.public_key")
            self._require_public_key_bytes(public_key, "prekey.public_key", self.X25519_PUBLIC_KEY_BYTES)
            normalized.append(
                {
                    "prekey_id": prekey_id,
                    "public_key": public_key,
                }
            )
        return normalized

    @staticmethod
    def _decode_b64(value: str, field_name: str) -> bytes:
        try:
            return b64decode(str(value or "").strip(), validate=True)
        except Exception:
            raise AppError(ErrorCode.INVALID_REQUEST, f"{field_name} must be base64 encoded", 422) from None

    def _require_public_key_bytes(self, value: str, field_name: str, expected_size: int) -> bytes:
        decoded = self._decode_b64(value, field_name)
        if len(decoded) != expected_size:
            raise AppError(ErrorCode.INVALID_REQUEST, f"{field_name} has invalid key length", 422)
        return decoded

    def _require_signature_bytes(self, value: str, field_name: str) -> bytes:
        decoded = self._decode_b64(value, field_name)
        if len(decoded) != 64:
            raise AppError(ErrorCode.INVALID_REQUEST, f"{field_name} has invalid signature length", 422)
        return decoded

    def _verify_signed_prekey_signature(self, signing_key_public: str, signed_prekey: dict[str, Any]) -> None:
        try:
            from cryptography.hazmat.primitives.asymmetric import ed25519
        except Exception as exc:
            raise AppError(ErrorCode.INVALID_REQUEST, "signed prekey validation is unavailable", 422) from exc

        signing_key_bytes = self._require_public_key_bytes(
            signing_key_public,
            "signing_key_public",
            self.ED25519_PUBLIC_KEY_BYTES,
        )
        signed_prekey_public = self._require_public_key_bytes(
            str(signed_prekey.get("public_key") or ""),
            "signed_prekey.public_key",
            self.X25519_PUBLIC_KEY_BYTES,
        )
        signature = self._require_signature_bytes(
            str(signed_prekey.get("signature") or ""),
            "signed_prekey.signature",
        )
        try:
            ed25519.Ed25519PublicKey.from_public_bytes(signing_key_bytes).verify(signature, signed_prekey_public)
        except Exception:
            raise AppError(ErrorCode.INVALID_REQUEST, "signed_prekey signature is invalid", 422) from None

    @staticmethod
    def serialize_device(device, *, available_prekey_count: int) -> dict[str, Any]:
        return {
            "device_id": str(device.device_id or ""),
            "user_id": str(device.user_id or ""),
            "device_name": str(device.device_name or ""),
            "identity_key_public": str(device.identity_key_public or ""),
            "signing_key_public": str(device.signing_key_public or ""),
            "is_active": bool(device.is_active),
            "available_prekey_count": max(0, int(available_prekey_count or 0)),
            "created_at": device.created_at.isoformat() if getattr(device, "created_at", None) else None,
            "updated_at": device.updated_at.isoformat() if getattr(device, "updated_at", None) else None,
            "last_seen_at": device.last_seen_at.isoformat() if getattr(device, "last_seen_at", None) else None,
        }

    @staticmethod
    def serialize_prekey_bundle(device, *, signed_prekey, claimed_prekey, available_prekey_count: int) -> dict[str, Any]:
        return {
            "device_id": str(device.device_id or ""),
            "user_id": str(device.user_id or ""),
            "device_name": str(device.device_name or ""),
            "identity_key_public": str(device.identity_key_public or ""),
            "signing_key_public": str(device.signing_key_public or ""),
            "signed_prekey": {
                "key_id": int(getattr(signed_prekey, "key_id", 0) or 0),
                "public_key": str(getattr(signed_prekey, "public_key", "") or ""),
                "signature": str(getattr(signed_prekey, "signature", "") or ""),
            },
            "one_time_prekey": (
                {
                    "prekey_id": int(getattr(claimed_prekey, "prekey_id", 0) or 0),
                    "public_key": str(getattr(claimed_prekey, "public_key", "") or ""),
                }
                if claimed_prekey is not None
                else None
            ),
            "available_prekey_count": max(0, int(available_prekey_count or 0)),
            "last_seen_at": device.last_seen_at.isoformat() if getattr(device, "last_seen_at", None) else None,
        }
