"""Repositories for user devices and E2EE key material."""

from __future__ import annotations

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.models.device import UserDevice, UserPreKey, UserSignedPreKey
from app.utils.time import utcnow


class DeviceRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_device(self, device_id: str) -> UserDevice | None:
        normalized_device_id = str(device_id or "").strip()
        if not normalized_device_id:
            return None
        return self.db.get(UserDevice, normalized_device_id)

    def get_device_for_user(self, user_id: str, device_id: str) -> UserDevice | None:
        device = self.get_device(device_id)
        if device is None or str(device.user_id or "") != str(user_id or ""):
            return None
        return device

    def list_devices_for_user(self, user_id: str) -> list[UserDevice]:
        stmt = (
            select(UserDevice)
            .where(UserDevice.user_id == str(user_id or "").strip())
            .order_by(UserDevice.last_seen_at.desc(), UserDevice.created_at.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def list_active_devices_for_user(self, user_id: str, *, exclude_device_id: str | None = None) -> list[UserDevice]:
        stmt = (
            select(UserDevice)
            .where(
                UserDevice.user_id == str(user_id or "").strip(),
                UserDevice.is_active.is_(True),
            )
            .order_by(UserDevice.last_seen_at.desc(), UserDevice.created_at.desc())
        )
        if exclude_device_id:
            stmt = stmt.where(UserDevice.device_id != str(exclude_device_id or "").strip())
        return list(self.db.execute(stmt).scalars().all())

    def upsert_device(
        self,
        *,
        user_id: str,
        device_id: str,
        identity_key_public: str,
        signing_key_public: str,
        device_name: str,
    ) -> UserDevice:
        normalized_device_id = str(device_id or "").strip()
        device = self.get_device(normalized_device_id)
        if device is None:
            device = UserDevice(
                device_id=normalized_device_id,
                user_id=str(user_id or "").strip(),
                identity_key_public=identity_key_public,
                signing_key_public=signing_key_public,
                device_name=device_name,
                is_active=True,
                last_seen_at=utcnow(),
            )
        else:
            device.user_id = str(user_id or "").strip()
            device.identity_key_public = identity_key_public
            device.signing_key_public = signing_key_public
            device.device_name = device_name
            device.is_active = True
            device.last_seen_at = utcnow()
        self.db.add(device)
        self.db.flush()
        return device

    def delete_device(self, device: UserDevice) -> None:
        self.db.execute(delete(UserPreKey).where(UserPreKey.device_id == device.device_id))
        self.db.execute(delete(UserSignedPreKey).where(UserSignedPreKey.device_id == device.device_id))
        self.db.delete(device)
        self.db.flush()

    def upsert_signed_prekey(
        self,
        *,
        device_id: str,
        key_id: int,
        public_key: str,
        signature: str,
    ) -> UserSignedPreKey:
        normalized_device_id = str(device_id or "").strip()
        existing = self.db.execute(
            select(UserSignedPreKey).where(
                UserSignedPreKey.device_id == normalized_device_id,
                UserSignedPreKey.key_id == int(key_id),
            )
        ).scalar_one_or_none()
        self.db.execute(
            update(UserSignedPreKey)
            .where(UserSignedPreKey.device_id == normalized_device_id)
            .values(is_active=False)
        )
        if existing is None:
            existing = UserSignedPreKey(
                device_id=normalized_device_id,
                key_id=int(key_id),
                public_key=public_key,
                signature=signature,
                is_active=True,
            )
        else:
            existing.public_key = public_key
            existing.signature = signature
            existing.is_active = True
        self.db.add(existing)
        self.db.flush()
        return existing

    def get_active_signed_prekey(self, device_id: str) -> UserSignedPreKey | None:
        stmt = (
            select(UserSignedPreKey)
            .where(
                UserSignedPreKey.device_id == str(device_id or "").strip(),
                UserSignedPreKey.is_active.is_(True),
            )
            .order_by(UserSignedPreKey.updated_at.desc(), UserSignedPreKey.created_at.desc())
            .limit(1)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def existing_prekey_ids(self, device_id: str, prekey_ids: list[int]) -> set[int]:
        normalized_device_id = str(device_id or "").strip()
        normalized_prekey_ids = [int(prekey_id) for prekey_id in prekey_ids]
        if not normalized_device_id or not normalized_prekey_ids:
            return set()
        stmt = select(UserPreKey.prekey_id).where(
            UserPreKey.device_id == normalized_device_id,
            UserPreKey.prekey_id.in_(normalized_prekey_ids),
        )
        return {int(value) for value in self.db.execute(stmt).scalars().all()}

    def append_prekeys(self, device_id: str, prekeys: list[dict[str, object]]) -> list[UserPreKey]:
        normalized_device_id = str(device_id or "").strip()
        items: list[UserPreKey] = []
        for item in prekeys:
            prekey = UserPreKey(
                device_id=normalized_device_id,
                prekey_id=int(item["prekey_id"]),
                public_key=str(item["public_key"]),
                is_consumed=False,
            )
            self.db.add(prekey)
            items.append(prekey)
        self.db.flush()
        return items

    def replace_prekeys(self, device_id: str, prekeys: list[dict[str, object]]) -> list[UserPreKey]:
        normalized_device_id = str(device_id or "").strip()
        self.db.execute(delete(UserPreKey).where(UserPreKey.device_id == normalized_device_id))
        items: list[UserPreKey] = []
        for item in prekeys:
            prekey = UserPreKey(
                device_id=normalized_device_id,
                prekey_id=int(item["prekey_id"]),
                public_key=str(item["public_key"]),
                is_consumed=False,
            )
            self.db.add(prekey)
            items.append(prekey)
        self.db.flush()
        return items

    def count_available_prekeys(self, device_id: str) -> int:
        stmt = select(UserPreKey).where(
            UserPreKey.device_id == str(device_id or "").strip(),
            UserPreKey.is_consumed.is_(False),
        )
        return len(list(self.db.execute(stmt).scalars().all()))

    def claim_one_time_prekey(self, device_id: str) -> UserPreKey | None:
        stmt = (
            select(UserPreKey)
            .where(
                UserPreKey.device_id == str(device_id or "").strip(),
                UserPreKey.is_consumed.is_(False),
            )
            .order_by(UserPreKey.prekey_id.asc(), UserPreKey.created_at.asc())
            .limit(1)
        )
        prekey = self.db.execute(stmt).scalar_one_or_none()
        if prekey is None:
            return None
        prekey.is_consumed = True
        prekey.claimed_at = utcnow()
        self.db.add(prekey)
        self.db.flush()
        return prekey
