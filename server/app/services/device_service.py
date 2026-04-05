"""Device and prekey service for private-chat E2EE bootstrap."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.user import User
from app.repositories.device_repo import DeviceRepository
from app.repositories.user_repo import UserRepository


class DeviceService:
    MAX_PREKEYS_PER_REQUEST = 100

    def __init__(self, db: Session) -> None:
        self.db = db
        self.devices = DeviceRepository(db)
        self.users = UserRepository(db)

    def register_device(self, current_user: User, payload: dict[str, Any]) -> dict[str, Any]:
        device_id = self._require_non_empty(payload.get("device_id"), "device_id")
        identity_key_public = self._require_non_empty(payload.get("identity_key_public"), "identity_key_public")
        signing_key_public = self._require_non_empty(payload.get("signing_key_public"), "signing_key_public")
        device_name = str(payload.get("device_name") or "").strip() or "AssistIM Desktop"

        signed_prekey_payload = payload.get("signed_prekey")
        if not isinstance(signed_prekey_payload, dict):
            raise AppError(ErrorCode.INVALID_REQUEST, "signed_prekey is required", 422)
        signed_prekey = self._normalize_signed_prekey(signed_prekey_payload)

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
        return [
            self.serialize_device(
                item,
                available_prekey_count=self.devices.count_available_prekeys(item.device_id),
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
        del current_user
        self._require_existing_user(target_user_id)
        items = self.devices.list_active_devices_for_user(target_user_id, exclude_device_id=exclude_device_id)
        bundles: list[dict[str, Any]] = []
        for item in items:
            signed_prekey = self.devices.get_active_signed_prekey(item.device_id)
            if signed_prekey is None:
                continue
            bundles.append(
                self.serialize_prekey_bundle(
                    item,
                    signed_prekey=signed_prekey,
                    claimed_prekey=None,
                    available_prekey_count=self.devices.count_available_prekeys(item.device_id),
                )
            )
        return bundles

    def claim_prekeys(self, current_user: User, device_ids: list[str]) -> list[dict[str, Any]]:
        del current_user
        normalized_device_ids = []
        for raw_device_id in device_ids:
            normalized_device_id = str(raw_device_id or "").strip()
            if normalized_device_id and normalized_device_id not in normalized_device_ids:
                normalized_device_ids.append(normalized_device_id)
        if not normalized_device_ids:
            raise AppError(ErrorCode.INVALID_REQUEST, "device_ids must contain at least one item", 422)

        claimed: list[dict[str, Any]] = []
        for device_id in normalized_device_ids:
            device = self.devices.get_device(device_id)
            if device is None or not device.is_active:
                continue
            signed_prekey = self.devices.get_active_signed_prekey(device_id)
            if signed_prekey is None:
                continue
            claimed_prekey = self.devices.claim_one_time_prekey(device_id)
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
            normalized.append(
                {
                    "prekey_id": prekey_id,
                    "public_key": public_key,
                }
            )
        return normalized

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
