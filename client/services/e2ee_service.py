"""Local device-key management and MVP private-message encryption helpers."""

from __future__ import annotations

import json
import mimetypes
import os
import platform
import tempfile
import uuid
from hashlib import sha256
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from base64 import b64decode, b64encode
from os import urandom
from typing import Any, Optional

from client.core import logging
from client.core.secure_storage import SecureStorage
from client.network.http_client import get_http_client
from client.storage.database import get_database


logger = logging.get_logger(__name__)


@dataclass
class EncryptedAttachmentUpload:
    upload_file_path: str
    attachment_encryption: dict[str, Any]
    cleanup_file_path: str


class E2EEService:
    """Manage the local device identity and E2EE bootstrap APIs."""

    DEVICE_STATE_KEY = "e2ee.device_state"
    GROUP_SESSION_STATE_KEY = "e2ee.group_session_state"
    HISTORY_RECOVERY_STATE_KEY = "e2ee.history_recovery_state"
    IDENTITY_TRUST_STATE_KEY = "e2ee.identity_trust_state"
    DEFAULT_PREKEY_COUNT = 32
    MIN_AVAILABLE_PREKEY_COUNT = 8
    SIGNED_PREKEY_ROTATION_INTERVAL = timedelta(days=14)
    ENVELOPE_SCHEME = "x25519-aesgcm-v1"
    LOCAL_PLAINTEXT_VERSION = "dpapi-text-v1"
    ATTACHMENT_SCHEME = "aesgcm-file+x25519-v1"
    GROUP_ATTACHMENT_SCHEME = "aesgcm-file+group-sender-key-v1"
    GROUP_FANOUT_SCHEME = "group-sender-key-fanout-v1"
    GROUP_SENDER_KEY_SCHEME = "group-sender-key-v1"
    DEVICE_HISTORY_RECOVERY_SCHEME = "device-history-recovery-v1"
    GROUP_RETIRED_LOCAL_KEY_LIMIT = 8
    DECRYPTION_STATE_READY = "ready"
    DECRYPTION_STATE_MISSING_LOCAL_BUNDLE = "missing_local_bundle"
    DECRYPTION_STATE_NOT_FOR_CURRENT_DEVICE = "not_for_current_device"
    DECRYPTION_STATE_MISSING_PRIVATE_KEY = "missing_private_key"
    DECRYPTION_STATE_MISSING_GROUP_SENDER_KEY = "missing_group_sender_key"
    DECRYPTION_STATE_UNSUPPORTED_SCHEME = "unsupported_scheme"
    IDENTITY_STATUS_UNAVAILABLE = "unavailable"
    IDENTITY_STATUS_UNVERIFIED = "unverified"
    IDENTITY_STATUS_VERIFIED = "verified"
    IDENTITY_STATUS_CHANGED = "identity_changed"

    def __init__(self) -> None:
        self._http = get_http_client()
        self._db = get_database()

    async def ensure_registered_device(self) -> dict[str, Any]:
        """Ensure one local device stays registered and that its published key inventory remains healthy."""
        bundle = await self.get_or_create_local_bundle()

        try:
            devices = await self.list_my_devices()
        except Exception as exc:
            logger.warning("Failed to load remote E2EE devices, falling back to register: %s", exc)
            devices = []

        remote_device = self._find_device_record(devices, str(bundle.get("device_id") or ""))
        if self._requires_full_registration(bundle, remote_device):
            response = await self._register_bundle(bundle)
            await self._save_local_bundle(bundle)
            return response

        refresh_bundle = self._normalize_loaded_bundle(deepcopy(bundle))
        refresh_signed_prekey = False
        refresh_prekeys: list[dict[str, Any]] = []

        if self._should_rotate_signed_prekey(refresh_bundle):
            refresh_signed_prekey = True
            self._rotate_signed_prekey_in_bundle(refresh_bundle)

        available_prekey_count = int((remote_device or {}).get("available_prekey_count") or 0)
        if available_prekey_count < self.MIN_AVAILABLE_PREKEY_COUNT:
            missing_prekey_count = max(0, self.DEFAULT_PREKEY_COUNT - available_prekey_count)
            refresh_prekeys = self._append_one_time_prekeys(refresh_bundle, missing_prekey_count)

        if refresh_signed_prekey or refresh_prekeys:
            response = await self.refresh_device_keys(
                str(refresh_bundle["device_id"]),
                signed_prekey=(dict(refresh_bundle["signed_prekey"]) if refresh_signed_prekey else None),
                prekeys=refresh_prekeys,
            )
            await self._save_local_bundle(refresh_bundle)
            return response

        return dict(remote_device or {})

    async def list_my_devices(self) -> list[dict[str, Any]]:
        payload = await self._http.get("/devices")
        return [dict(item) for item in payload or [] if isinstance(item, dict)]

    async def refresh_device_keys(
        self,
        device_id: str,
        *,
        signed_prekey: dict[str, Any] | None = None,
        prekeys: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if signed_prekey is not None:
            payload["signed_prekey"] = {
                "key_id": int(signed_prekey.get("key_id") or 0),
                "public_key": str(signed_prekey.get("public_key") or ""),
                "signature": str(signed_prekey.get("signature") or ""),
            }
        normalized_prekeys = [
            {
                "prekey_id": int(item.get("prekey_id") or 0),
                "public_key": str(item.get("public_key") or ""),
            }
            for item in list(prekeys or [])
        ]
        if normalized_prekeys:
            payload["prekeys"] = normalized_prekeys
        response = await self._http.post(f"/devices/{device_id}/keys/refresh", json=payload)
        return dict(response or {})

    async def delete_device(self, device_id: str) -> None:
        await self._http.delete(f"/devices/{device_id}")

    async def clear_local_bundle(self) -> None:
        await self._db.delete_app_state(self.DEVICE_STATE_KEY)
        await self._db.delete_app_state(self.GROUP_SESSION_STATE_KEY)
        await self._db.delete_app_state(self.HISTORY_RECOVERY_STATE_KEY)
        await self._db.delete_app_state(self.IDENTITY_TRUST_STATE_KEY)

    async def reprovision_local_device(self, *, delete_remote: bool = True) -> dict[str, Any]:
        previous_bundle = await self._load_local_bundle()
        previous_device_id = str((previous_bundle or {}).get("device_id") or "").strip()
        if delete_remote and previous_device_id:
            try:
                await self.delete_device(previous_device_id)
            except Exception as exc:
                logger.warning("Failed to delete previous remote E2EE device %s: %s", previous_device_id, exc)

        await self.clear_local_bundle()
        new_bundle = self._generate_local_bundle()
        await self._save_local_bundle(new_bundle)
        return await self._register_bundle(new_bundle)

    async def fetch_prekey_bundle(self, user_id: str) -> list[dict[str, Any]]:
        bundle = await self.get_or_create_local_bundle()
        payload = await self._http.get(
            f"/keys/prekey-bundle/{user_id}",
            params={"exclude_device_id": bundle["device_id"]},
        )
        return [dict(item) for item in payload or [] if isinstance(item, dict)]

    async def claim_prekeys(self, device_ids: list[str]) -> list[dict[str, Any]]:
        payload = await self._http.post("/keys/prekeys/claim", json={"device_ids": list(device_ids or [])})
        return [dict(item) for item in payload or [] if isinstance(item, dict)]

    async def get_or_create_local_bundle(self) -> dict[str, Any]:
        existing = await self._load_local_bundle()
        if existing is not None:
            normalized_existing = self._normalize_loaded_bundle(existing)
            await self._save_local_bundle(normalized_existing)
            return normalized_existing

        generated = self._generate_local_bundle()
        await self._save_local_bundle(generated)
        return generated

    async def get_local_device_summary(self) -> dict[str, Any]:
        """Return one lightweight summary of the local E2EE device state, if provisioned."""
        bundle = await self._load_local_bundle()
        if not isinstance(bundle, dict):
            return {}
        device_id = str(bundle.get("device_id") or "").strip()
        return {
            "device_id": device_id,
            "has_local_bundle": bool(device_id),
        }

    async def get_peer_identity_summary(self, user_id: str) -> dict[str, Any]:
        normalized_user_id = str(user_id or "").strip()
        if not normalized_user_id:
            raise RuntimeError("user id is required")

        local_bundle = await self._load_local_bundle()
        local_device_id = str((local_bundle or {}).get("device_id") or "").strip()
        local_fingerprint = (
            self._device_identity_fingerprint(dict(local_bundle or {}))
            if isinstance(local_bundle, dict)
            else ""
        )
        remote_bundles = [dict(item) for item in await self.fetch_prekey_bundle(normalized_user_id) if isinstance(item, dict)]
        trust_state = await self._load_identity_trust_state()
        trusted_user_record = dict(dict(trust_state.get("users") or {}).get(normalized_user_id) or {})
        trusted_devices = dict(trusted_user_record.get("devices") or {})

        users = dict(trust_state.get("users") or {})
        user_record = dict(users.get(normalized_user_id) or {})
        tracked_devices = dict(user_record.get("devices") or {})
        devices: list[dict[str, Any]] = []
        trusted_device_count = 0
        unverified_device_count = 0
        changed_device_count = 0
        verified_device_ids: list[str] = []
        unverified_device_ids: list[str] = []
        changed_device_ids: list[str] = []
        checked_at = _utcnow().isoformat()
        trust_state_changed = False

        for bundle in remote_bundles:
            normalized_device = self._normalize_remote_identity_bundle(bundle)
            device_id = str(normalized_device.get("device_id") or "").strip()
            if not device_id:
                continue
            fingerprint = self._device_identity_fingerprint(normalized_device)
            trusted_record = dict(trusted_devices.get(device_id) or {})
            trusted_fingerprint = str(trusted_record.get("fingerprint") or "").strip()
            trusted_at = str(trusted_record.get("trusted_at") or trusted_record.get("last_trusted_at") or "").strip()
            if not trusted_at:
                trust_status = self.IDENTITY_STATUS_UNVERIFIED
                unverified_device_count += 1
                unverified_device_ids.append(device_id)
            elif trusted_fingerprint and trusted_fingerprint != fingerprint:
                trust_status = self.IDENTITY_STATUS_CHANGED
                changed_device_count += 1
                changed_device_ids.append(device_id)
            else:
                trust_status = self.IDENTITY_STATUS_VERIFIED
                trusted_device_count += 1
                verified_device_ids.append(device_id)

            observed_record = self._record_identity_observation(
                trusted_record,
                normalized_device,
                trust_status=trust_status,
                fingerprint=fingerprint,
                observed_at=checked_at,
            )
            if observed_record != tracked_devices.get(device_id):
                tracked_devices[device_id] = observed_record
                trust_state_changed = True

            devices.append(
                {
                    "device_id": device_id,
                    "device_name": str(normalized_device.get("device_name") or "").strip(),
                    "fingerprint": fingerprint,
                    "fingerprint_short": fingerprint[:12],
                    "verification_code": self._identity_verification_code(local_fingerprint, fingerprint),
                    "verification_code_short": self._short_verification_code(
                        self._identity_verification_code(local_fingerprint, fingerprint)
                    ),
                    "identity_key_public": str(normalized_device.get("identity_key_public") or "").strip(),
                    "signing_key_public": str(normalized_device.get("signing_key_public") or "").strip(),
                    "trust_status": trust_status,
                    "trusted_at": str(observed_record.get("trusted_at") or ""),
                    "last_trusted_at": str(observed_record.get("last_trusted_at") or ""),
                    "first_seen_at": str(observed_record.get("first_seen_at") or ""),
                    "last_seen_at": str(observed_record.get("last_seen_at") or ""),
                    "last_changed_at": str(observed_record.get("last_changed_at") or ""),
                    "status_updated_at": str(observed_record.get("status_updated_at") or ""),
                    "change_count": int(observed_record.get("change_count", 0) or 0),
                    "trust_source": str(observed_record.get("trust_source") or ""),
                }
            )

        primary_device = self._select_primary_identity_device(devices)
        if trust_state_changed:
            user_record["devices"] = tracked_devices
            user_record["updated_at"] = checked_at
            users[normalized_user_id] = user_record
            trust_state["users"] = users
            await self._save_identity_trust_state(trust_state)
        if not devices:
            status = self.IDENTITY_STATUS_UNAVAILABLE
        elif changed_device_count:
            status = self.IDENTITY_STATUS_CHANGED
        elif unverified_device_count:
            status = self.IDENTITY_STATUS_UNVERIFIED
        else:
            status = self.IDENTITY_STATUS_VERIFIED

        last_changed_at = max((str(item.get("last_changed_at") or "") for item in devices), default="")
        last_trusted_at = max((str(item.get("last_trusted_at") or "") for item in devices), default="")
        change_count = sum(int(item.get("change_count", 0) or 0) for item in devices)
        return {
            "user_id": normalized_user_id,
            "local_device_id": local_device_id,
            "local_fingerprint": local_fingerprint,
            "local_fingerprint_short": local_fingerprint[:12],
            "status": status,
            "checked_at": checked_at,
            "device_count": len(devices),
            "trusted_device_count": trusted_device_count,
            "unverified_device_count": unverified_device_count,
            "changed_device_count": changed_device_count,
            "verified_device_ids": sorted(verified_device_ids),
            "unverified_device_ids": sorted(unverified_device_ids),
            "changed_device_ids": sorted(changed_device_ids),
            "last_changed_at": last_changed_at,
            "last_trusted_at": last_trusted_at,
            "change_count": change_count,
            "verification_available": bool(local_fingerprint and devices),
            "primary_verification_device_id": str(primary_device.get("device_id") or ""),
            "primary_verification_fingerprint": str(primary_device.get("fingerprint") or ""),
            "primary_verification_fingerprint_short": str(primary_device.get("fingerprint_short") or ""),
            "primary_verification_code": str(primary_device.get("verification_code") or ""),
            "primary_verification_code_short": str(primary_device.get("verification_code_short") or ""),
            "devices": devices,
        }

    async def trust_peer_identities(self, user_id: str, *, device_ids: list[str] | None = None) -> dict[str, Any]:
        normalized_user_id = str(user_id or "").strip()
        if not normalized_user_id:
            raise RuntimeError("user id is required")

        remote_bundles = [dict(item) for item in await self.fetch_prekey_bundle(normalized_user_id) if isinstance(item, dict)]
        normalized_device_ids = {
            value
            for value in dict.fromkeys(str(raw_id or "").strip() for raw_id in list(device_ids or []))
            if value
        }

        trust_state = await self._load_identity_trust_state()
        users = dict(trust_state.get("users") or {})
        user_record = dict(users.get(normalized_user_id) or {})
        trusted_devices = dict(user_record.get("devices") or {})
        trusted_at = _utcnow().isoformat()
        updated_device_ids: list[str] = []

        for bundle in remote_bundles:
            normalized_device = self._normalize_remote_identity_bundle(bundle)
            device_id = str(normalized_device.get("device_id") or "").strip()
            if not device_id:
                continue
            if normalized_device_ids and device_id not in normalized_device_ids:
                continue
            fingerprint = self._device_identity_fingerprint(normalized_device)
            trusted_devices[device_id] = self._record_identity_observation(
                dict(trusted_devices.get(device_id) or {}),
                normalized_device,
                trust_status=self.IDENTITY_STATUS_VERIFIED,
                fingerprint=fingerprint,
                observed_at=trusted_at,
                mark_trusted=True,
            )
            updated_device_ids.append(device_id)

        user_record["devices"] = trusted_devices
        user_record["updated_at"] = trusted_at
        users[normalized_user_id] = user_record
        trust_state["users"] = users
        await self._save_identity_trust_state(trust_state)

        summary = await self.get_peer_identity_summary(normalized_user_id)
        summary["trusted_now_device_ids"] = sorted(updated_device_ids)
        return summary

    async def get_group_session_summary(self, session_id: str) -> dict[str, Any]:
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            raise RuntimeError("session id is required")

        local_bundle = await self._load_local_bundle()
        local_device_id = str((local_bundle or {}).get("device_id") or "").strip()
        state = await self._load_group_session_state()
        record = self._normalize_group_session_record(
            normalized_session_id,
            dict(state.get(normalized_session_id) or {}),
        )
        local_sender_key = dict(record.get("local_sender_key") or {})
        retired_local_sender_keys = {
            str(key_id or "").strip(): dict(payload)
            for key_id, payload in dict(record.get("retired_local_sender_keys") or {}).items()
            if str(key_id or "").strip() and isinstance(payload, dict)
        }
        inbound_sender_keys = {
            str(device_id or "").strip(): dict(payload)
            for device_id, payload in dict(record.get("inbound_sender_keys") or {}).items()
            if str(device_id or "").strip() and isinstance(payload, dict)
        }
        return {
            "session_id": normalized_session_id,
            "local_device_id": local_device_id,
            "has_local_sender_key": bool(local_sender_key),
            "local_sender_key_id": str(local_sender_key.get("key_id") or "").strip(),
            "member_version": int(local_sender_key.get("member_version") or 0),
            "retired_local_sender_key_ids": sorted(retired_local_sender_keys.keys()),
            "inbound_sender_devices": sorted(inbound_sender_keys.keys()),
            "total_sender_keys": len(inbound_sender_keys) + len(retired_local_sender_keys) + (1 if local_sender_key else 0),
            "updated_at": str(record.get("updated_at") or ""),
        }

    async def get_history_recovery_summary(self) -> dict[str, Any]:
        state = await self._load_history_recovery_state()
        devices = dict(state.get("devices") or {})
        signed_prekey_count = 0
        one_time_prekey_count = 0
        group_session_ids: set[str] = set()
        group_sender_key_count = 0
        for device_record in devices.values():
            record = dict(device_record or {})
            signed_prekey_count += len(dict(record.get("signed_prekeys") or {}))
            one_time_prekey_count += len(dict(record.get("one_time_prekeys") or {}))
            for session_id, group_record in dict(record.get("group_sessions") or {}).items():
                normalized_session_id = str(session_id or "").strip()
                if normalized_session_id:
                    group_session_ids.add(normalized_session_id)
                group_sender_key_count += len(dict(dict(group_record or {}).get("sender_keys") or {}))
        return {
            "source_device_count": len(devices),
            "signed_prekey_count": signed_prekey_count,
            "one_time_prekey_count": one_time_prekey_count,
            "group_session_count": len(group_session_ids),
            "group_sender_key_count": group_sender_key_count,
        }

    async def get_history_recovery_diagnostics(self) -> dict[str, Any]:
        local_bundle = await self._load_local_bundle()
        local_device_id = str((local_bundle or {}).get("device_id") or "").strip()
        state = await self._load_history_recovery_state()
        devices = dict(state.get("devices") or {})
        source_devices: list[dict[str, Any]] = []

        for source_device_id, raw_record in devices.items():
            normalized_source_device_id = str(source_device_id or "").strip()
            if not normalized_source_device_id or not isinstance(raw_record, dict):
                continue
            record = self._normalize_history_recovery_device_record(
                normalized_source_device_id,
                dict(raw_record or {}),
            )
            group_sessions = dict(record.get("group_sessions") or {})
            session_ids = sorted(
                session_id
                for session_id in (str(raw_session_id or "").strip() for raw_session_id in group_sessions.keys())
                if session_id
            )
            group_sender_key_count = sum(
                len(dict(dict(group_record or {}).get("sender_keys") or {}))
                for group_record in group_sessions.values()
                if isinstance(group_record, dict)
            )
            source_devices.append(
                {
                    "source_device_id": normalized_source_device_id,
                    "source_user_id": str(record.get("source_user_id") or "").strip(),
                    "imported_at": str(record.get("imported_at") or ""),
                    "exported_at": str(record.get("exported_at") or ""),
                    "signed_prekey_count": len(dict(record.get("signed_prekeys") or {})),
                    "one_time_prekey_count": len(dict(record.get("one_time_prekeys") or {})),
                    "group_session_count": len(session_ids),
                    "group_sender_key_count": group_sender_key_count,
                    "session_ids": session_ids,
                }
            )

        source_devices.sort(
            key=lambda item: (
                str(item.get("imported_at") or ""),
                str(item.get("exported_at") or ""),
                str(item.get("source_device_id") or ""),
            ),
            reverse=True,
        )
        summary = await self.get_history_recovery_summary()
        primary_source_device = dict(source_devices[0]) if source_devices else {}
        return {
            "local_device_id": local_device_id,
            "available": bool(source_devices),
            "source_device_count": int(summary.get("source_device_count", 0) or 0),
            "signed_prekey_count": int(summary.get("signed_prekey_count", 0) or 0),
            "one_time_prekey_count": int(summary.get("one_time_prekey_count", 0) or 0),
            "group_session_count": int(summary.get("group_session_count", 0) or 0),
            "group_sender_key_count": int(summary.get("group_sender_key_count", 0) or 0),
            "primary_source_device_id": str(primary_source_device.get("source_device_id") or ""),
            "primary_source_user_id": str(primary_source_device.get("source_user_id") or ""),
            "last_imported_at": str(primary_source_device.get("imported_at") or ""),
            "source_devices": source_devices,
        }

    async def export_history_recovery_package(
        self,
        target_user_id: str,
        target_device_id: str,
        *,
        source_user_id: str = "",
    ) -> dict[str, Any]:
        local_bundle = await self._load_local_bundle()
        if not isinstance(local_bundle, dict):
            raise RuntimeError("local device bundle is unavailable")

        normalized_target_user_id = str(target_user_id or "").strip()
        normalized_target_device_id = str(target_device_id or "").strip()
        if not normalized_target_user_id or not normalized_target_device_id:
            raise RuntimeError("target user id and target device id are required")

        target_bundle = await self._claim_or_fetch_bundle_for_device(
            normalized_target_user_id,
            normalized_target_device_id,
        )
        if target_bundle is None:
            raise RuntimeError("target device bundle is unavailable")

        self._verify_bundle_signature(target_bundle)
        key_payload = self._resolve_recipient_key_material(target_bundle)
        group_state = await self._load_group_session_state()
        exported_at = _utcnow().isoformat()

        signed_prekeys: list[dict[str, Any]] = []
        for signed_prekey in [
            dict(local_bundle.get("signed_prekey") or {}),
            *[dict(item) for item in list(local_bundle.get("retired_signed_prekeys") or []) if isinstance(item, dict)],
        ]:
            private_key = str(signed_prekey.get("private_key") or "").strip()
            key_id = int(signed_prekey.get("key_id") or 0)
            if not private_key or key_id <= 0:
                continue
            signed_prekeys.append(
                {
                    "key_id": key_id,
                    "private_key": private_key,
                }
            )

        one_time_prekeys: list[dict[str, Any]] = []
        for prekey in [dict(item) for item in list(local_bundle.get("one_time_prekeys") or []) if isinstance(item, dict)]:
            private_key = str(prekey.get("private_key") or "").strip()
            prekey_id = int(prekey.get("prekey_id") or 0)
            if not private_key or prekey_id <= 0:
                continue
            one_time_prekeys.append(
                {
                    "prekey_id": prekey_id,
                    "private_key": private_key,
                }
            )

        exported_group_sessions: list[dict[str, Any]] = []
        for session_id, raw_record in dict(group_state or {}).items():
            normalized_session_id = str(session_id or "").strip()
            if not normalized_session_id:
                continue
            record = self._normalize_group_session_record(normalized_session_id, dict(raw_record or {}))
            sender_keys: list[dict[str, Any]] = []
            local_sender_key = dict(record.get("local_sender_key") or {})
            if local_sender_key:
                sender_keys.append(dict(local_sender_key))
            for payload in dict(record.get("retired_local_sender_keys") or {}).values():
                if isinstance(payload, dict):
                    sender_keys.append(dict(payload))
            for payload in dict(record.get("inbound_sender_keys") or {}).values():
                if isinstance(payload, dict):
                    sender_keys.append(dict(payload))

            normalized_sender_keys: list[dict[str, Any]] = []
            seen_sender_keys: set[tuple[str, str]] = set()
            for sender_key in sender_keys:
                key_id = str(sender_key.get("key_id") or "").strip()
                owner_device_id = str(sender_key.get("owner_device_id") or "").strip()
                sender_key_b64 = str(sender_key.get("sender_key") or "").strip()
                if not key_id or not owner_device_id or not sender_key_b64:
                    continue
                dedupe_key = (owner_device_id, key_id)
                if dedupe_key in seen_sender_keys:
                    continue
                seen_sender_keys.add(dedupe_key)
                normalized_sender_keys.append(
                    {
                        "key_id": key_id,
                        "sender_key": sender_key_b64,
                        "sender_key_scheme": str(sender_key.get("sender_key_scheme") or self.GROUP_SENDER_KEY_SCHEME),
                        "owner_device_id": owner_device_id,
                        "owner_user_id": str(sender_key.get("owner_user_id") or "").strip(),
                        "member_version": int(sender_key.get("member_version") or 0),
                        "created_at": str(sender_key.get("created_at") or sender_key.get("installed_at") or exported_at),
                        "updated_at": str(
                            sender_key.get("updated_at")
                            or sender_key.get("created_at")
                            or sender_key.get("installed_at")
                            or exported_at
                        ),
                    }
                )
            if normalized_sender_keys:
                exported_group_sessions.append(
                    {
                        "session_id": normalized_session_id,
                        "sender_keys": normalized_sender_keys,
                    }
                )

        payload = {
            "scheme": self.DEVICE_HISTORY_RECOVERY_SCHEME,
            "source_user_id": str(source_user_id or "").strip(),
            "source_device_id": str(local_bundle.get("device_id") or "").strip(),
            "exported_at": exported_at,
            "signed_prekeys": signed_prekeys,
            "one_time_prekeys": one_time_prekeys,
            "group_sessions": exported_group_sessions,
        }
        ciphertext_b64, nonce_b64 = self._encrypt_payload(
            plaintext=json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
            sender_identity_private_b64=str(local_bundle["identity_key_private"]),
            recipient_public_key_b64=str(key_payload["public_key"]),
            sender_device_id=str(local_bundle.get("device_id") or ""),
            recipient_device_id=normalized_target_device_id,
        )
        return {
            "enabled": True,
            "scheme": self.DEVICE_HISTORY_RECOVERY_SCHEME,
            "source_user_id": str(source_user_id or "").strip(),
            "source_device_id": str(local_bundle.get("device_id") or "").strip(),
            "sender_device_id": str(local_bundle.get("device_id") or "").strip(),
            "sender_identity_key_public": str(local_bundle.get("identity_key_public") or ""),
            "recipient_user_id": normalized_target_user_id,
            "recipient_device_id": normalized_target_device_id,
            "recipient_prekey_type": str(key_payload.get("prekey_type") or ""),
            "recipient_prekey_id": int(key_payload.get("key_id") or 0),
            "payload_ciphertext": ciphertext_b64,
            "nonce": nonce_b64,
            "exported_at": exported_at,
            "package_summary": {
                "signed_prekey_count": len(signed_prekeys),
                "one_time_prekey_count": len(one_time_prekeys),
                "group_session_count": len(exported_group_sessions),
                "group_sender_key_count": sum(len(list(item.get("sender_keys") or [])) for item in exported_group_sessions),
            },
        }

    async def import_history_recovery_package(self, package: dict[str, Any] | None) -> dict[str, Any]:
        normalized = dict(package or {})
        if not normalized or not normalized.get("enabled"):
            raise RuntimeError("history recovery package is unavailable")
        if str(normalized.get("scheme") or "").strip() != self.DEVICE_HISTORY_RECOVERY_SCHEME:
            raise RuntimeError("unsupported history recovery package scheme")

        local_bundle = await self._load_local_bundle()
        if not isinstance(local_bundle, dict):
            raise RuntimeError("local device bundle is unavailable")

        recipient_device_id = str(normalized.get("recipient_device_id") or "").strip()
        local_device_id = str(local_bundle.get("device_id") or "").strip()
        if recipient_device_id and recipient_device_id != local_device_id:
            raise RuntimeError("history recovery package is not for the current device")

        key_payload = self._resolve_local_private_key(local_bundle, normalized)
        if key_payload is None:
            raise RuntimeError("local device does not have the required private prekey for history recovery")

        plaintext = self._decrypt_payload(
            ciphertext_b64=str(normalized.get("payload_ciphertext") or "").strip(),
            nonce_b64=str(normalized.get("nonce") or "").strip(),
            sender_identity_public_b64=str(normalized.get("sender_identity_key_public") or "").strip(),
            recipient_private_key_b64=str(key_payload.get("private_key") or ""),
            sender_device_id=str(normalized.get("sender_device_id") or ""),
            recipient_device_id=recipient_device_id or local_device_id,
        )
        payload = json.loads(plaintext)
        if not isinstance(payload, dict):
            raise RuntimeError("invalid history recovery package payload")

        source_device_id = str(payload.get("source_device_id") or normalized.get("source_device_id") or "").strip()
        if not source_device_id:
            raise RuntimeError("history recovery package is missing source device id")

        state = await self._load_history_recovery_state()
        devices = dict(state.get("devices") or {})
        device_record = self._normalize_history_recovery_device_record(
            source_device_id,
            dict(devices.get(source_device_id) or {}),
        )
        device_record["source_user_id"] = str(payload.get("source_user_id") or device_record.get("source_user_id") or "").strip()
        device_record["imported_at"] = _utcnow().isoformat()
        device_record["exported_at"] = str(
            payload.get("exported_at") or normalized.get("exported_at") or device_record.get("exported_at") or ""
        )

        imported_signed_prekeys = 0
        signed_prekeys = dict(device_record.get("signed_prekeys") or {})
        for item in list(payload.get("signed_prekeys") or []):
            if not isinstance(item, dict):
                continue
            key_id = int(item.get("key_id") or 0)
            private_key = str(item.get("private_key") or "").strip()
            if key_id <= 0 or not private_key:
                continue
            key_name = str(key_id)
            if key_name not in signed_prekeys:
                imported_signed_prekeys += 1
            signed_prekeys[key_name] = {
                "key_id": key_id,
                "private_key": private_key,
            }
        device_record["signed_prekeys"] = signed_prekeys

        imported_one_time_prekeys = 0
        one_time_prekeys = dict(device_record.get("one_time_prekeys") or {})
        for item in list(payload.get("one_time_prekeys") or []):
            if not isinstance(item, dict):
                continue
            prekey_id = int(item.get("prekey_id") or 0)
            private_key = str(item.get("private_key") or "").strip()
            if prekey_id <= 0 or not private_key:
                continue
            key_name = str(prekey_id)
            if key_name not in one_time_prekeys:
                imported_one_time_prekeys += 1
            one_time_prekeys[key_name] = {
                "prekey_id": prekey_id,
                "private_key": private_key,
            }
        device_record["one_time_prekeys"] = one_time_prekeys

        imported_group_sessions = 0
        imported_group_sender_keys = 0
        group_sessions = dict(device_record.get("group_sessions") or {})
        for item in list(payload.get("group_sessions") or []):
            if not isinstance(item, dict):
                continue
            session_id = str(item.get("session_id") or "").strip()
            if not session_id:
                continue
            existing_group_record = self._normalize_history_group_session_record(
                session_id,
                dict(group_sessions.get(session_id) or {}),
                source_device_id=source_device_id,
                source_user_id=str(device_record.get("source_user_id") or "").strip(),
            )
            sender_keys = dict(existing_group_record.get("sender_keys") or {})
            before_count = len(sender_keys)
            for sender_key in list(item.get("sender_keys") or []):
                if not isinstance(sender_key, dict):
                    continue
                normalized_sender_key = self._normalize_history_sender_key_record(
                    dict(sender_key),
                    source_device_id=source_device_id,
                    source_user_id=str(device_record.get("source_user_id") or "").strip(),
                )
                key_id = str(normalized_sender_key.get("key_id") or "").strip()
                sender_key_b64 = str(normalized_sender_key.get("sender_key") or "").strip()
                if not key_id or not sender_key_b64:
                    continue
                sender_keys[key_id] = normalized_sender_key
            existing_group_record["sender_keys"] = sender_keys
            existing_group_record["updated_at"] = _utcnow().isoformat()
            group_sessions[session_id] = existing_group_record
            if before_count == 0:
                imported_group_sessions += 1
            imported_group_sender_keys += max(0, len(sender_keys) - before_count)
        device_record["group_sessions"] = group_sessions

        devices[source_device_id] = device_record
        state["devices"] = devices
        await self._save_history_recovery_state(state)

        return {
            "source_device_id": source_device_id,
            "source_user_id": str(device_record.get("source_user_id") or "").strip(),
            "imported_signed_prekeys": imported_signed_prekeys,
            "imported_one_time_prekeys": imported_one_time_prekeys,
            "imported_group_sessions": imported_group_sessions,
            "imported_group_sender_keys": imported_group_sender_keys,
        }

    async def get_group_sender_key_record(
        self,
        session_id: str,
        *,
        owner_device_id: str | None = None,
        sender_key_id: str | None = None,
    ) -> dict[str, Any] | None:
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            raise RuntimeError("session id is required")

        state = await self._load_group_session_state()
        record = self._normalize_group_session_record(
            normalized_session_id,
            dict(state.get(normalized_session_id) or {}),
        )
        normalized_owner_device_id = str(owner_device_id or "").strip()
        normalized_sender_key_id = str(sender_key_id or "").strip()
        local_sender_key = dict(record.get("local_sender_key") or {})
        retired_local_sender_keys = {
            str(key_id or "").strip(): dict(payload)
            for key_id, payload in dict(record.get("retired_local_sender_keys") or {}).items()
            if str(key_id or "").strip() and isinstance(payload, dict)
        }
        inbound = dict(record.get("inbound_sender_keys") or {})
        if normalized_sender_key_id:
            if (
                local_sender_key
                and str(local_sender_key.get("key_id") or "").strip() == normalized_sender_key_id
                and (
                    not normalized_owner_device_id
                    or str(local_sender_key.get("owner_device_id") or "").strip() == normalized_owner_device_id
                )
            ):
                return dict(local_sender_key)
            retired_sender_key = dict(retired_local_sender_keys.get(normalized_sender_key_id) or {})
            if retired_sender_key and (
                not normalized_owner_device_id
                or str(retired_sender_key.get("owner_device_id") or "").strip() == normalized_owner_device_id
            ):
                return retired_sender_key
            if normalized_owner_device_id:
                sender_key = dict(inbound.get(normalized_owner_device_id) or {})
                if str(sender_key.get("key_id") or "").strip() == normalized_sender_key_id:
                    return sender_key or None
            for payload in inbound.values():
                sender_key = dict(payload or {})
                if str(sender_key.get("key_id") or "").strip() == normalized_sender_key_id:
                    return sender_key
            return await self._find_history_group_sender_key_record(
                normalized_session_id,
                owner_device_id=normalized_owner_device_id,
                sender_key_id=normalized_sender_key_id,
            )
        if not normalized_owner_device_id:
            return dict(local_sender_key) if local_sender_key else None
        if str(local_sender_key.get("owner_device_id") or "").strip() == normalized_owner_device_id:
            return dict(local_sender_key)
        sender_key = dict(inbound.get(normalized_owner_device_id) or {})
        if sender_key:
            return sender_key
        return await self._find_history_group_sender_key_record(
            normalized_session_id,
            owner_device_id=normalized_owner_device_id,
            sender_key_id=normalized_sender_key_id,
        )

    async def prepare_group_session_fanout(
        self,
        session_id: str,
        recipient_bundles: list[dict[str, Any]],
        *,
        member_version: int = 0,
        force_rotate: bool = False,
        owner_user_id: str = "",
    ) -> dict[str, Any]:
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            raise RuntimeError("session id is required")

        local_bundle = await self.get_or_create_local_bundle()
        group_state = await self._load_group_session_state()
        session_record = self._normalize_group_session_record(
            normalized_session_id,
            dict(group_state.get(normalized_session_id) or {}),
        )
        normalized_member_version = max(0, int(member_version or 0))
        current_local_sender_key = dict(session_record.get("local_sender_key") or {})
        should_rotate = (
            force_rotate
            or not current_local_sender_key
            or int(current_local_sender_key.get("member_version") or -1) != normalized_member_version
            or not str(current_local_sender_key.get("sender_key") or "").strip()
        )
        if should_rotate:
            self._archive_retired_local_sender_key(session_record, current_local_sender_key)
            current_local_sender_key = self._generate_group_sender_key_record(
                session_id=normalized_session_id,
                owner_device_id=str(local_bundle.get("device_id") or ""),
                owner_user_id=str(owner_user_id or "").strip(),
                member_version=normalized_member_version,
            )
            session_record["local_sender_key"] = current_local_sender_key
        else:
            current_local_sender_key["updated_at"] = _utcnow().isoformat()
            session_record["local_sender_key"] = current_local_sender_key

        fanout_payloads: list[dict[str, Any]] = []
        seen_device_ids: set[str] = set()
        for raw_bundle in list(recipient_bundles or []):
            bundle = dict(raw_bundle or {})
            recipient_device_id = str(bundle.get("device_id") or "").strip()
            if not recipient_device_id or recipient_device_id in seen_device_ids:
                continue
            seen_device_ids.add(recipient_device_id)
            if recipient_device_id == str(local_bundle.get("device_id") or "").strip():
                continue

            self._verify_bundle_signature(bundle)
            key_payload = self._resolve_recipient_key_material(bundle)
            payload = {
                "session_id": normalized_session_id,
                "sender_key_id": str(current_local_sender_key.get("key_id") or ""),
                "sender_key": str(current_local_sender_key.get("sender_key") or ""),
                "sender_key_scheme": self.GROUP_SENDER_KEY_SCHEME,
                "member_version": normalized_member_version,
                "owner_user_id": str(owner_user_id or "").strip(),
                "owner_device_id": str(local_bundle.get("device_id") or ""),
                "issued_at": str(current_local_sender_key.get("created_at") or _utcnow().isoformat()),
            }
            ciphertext_b64, nonce_b64 = self._encrypt_payload(
                plaintext=json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
                sender_identity_private_b64=str(local_bundle["identity_key_private"]),
                recipient_public_key_b64=str(key_payload["public_key"]),
                sender_device_id=str(local_bundle.get("device_id") or ""),
                recipient_device_id=recipient_device_id,
            )
            fanout_payloads.append(
                {
                    "enabled": True,
                    "scheme": self.GROUP_FANOUT_SCHEME,
                    "session_id": normalized_session_id,
                    "sender_key_id": str(current_local_sender_key.get("key_id") or ""),
                    "member_version": normalized_member_version,
                    "sender_device_id": str(local_bundle.get("device_id") or ""),
                    "sender_identity_key_public": str(local_bundle.get("identity_key_public") or ""),
                    "recipient_user_id": str(bundle.get("user_id") or "").strip(),
                    "recipient_device_id": recipient_device_id,
                    "recipient_prekey_type": str(key_payload.get("prekey_type") or ""),
                    "recipient_prekey_id": int(key_payload.get("key_id") or 0),
                    "payload_ciphertext": ciphertext_b64,
                    "nonce": nonce_b64,
                }
            )

        session_record["updated_at"] = _utcnow().isoformat()
        group_state[normalized_session_id] = session_record
        await self._save_group_session_state(group_state)
        return {
            "session_id": normalized_session_id,
            "sender_device_id": str(local_bundle.get("device_id") or ""),
            "sender_key_id": str(current_local_sender_key.get("key_id") or ""),
            "sender_key": str(current_local_sender_key.get("sender_key") or ""),
            "member_version": normalized_member_version,
            "owner_user_id": str(owner_user_id or "").strip(),
            "reused": not should_rotate,
            "fanout": fanout_payloads,
        }

    async def reconcile_group_session_state(
        self,
        session_id: str,
        *,
        member_version: int = 0,
        member_user_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            raise RuntimeError("session id is required")

        normalized_member_version = max(0, int(member_version or 0))
        allowed_user_ids = {
            value
            for value in dict.fromkeys(str(raw_id or "").strip() for raw_id in member_user_ids or [])
            if value
        }

        group_state = await self._load_group_session_state()
        session_record = self._normalize_group_session_record(
            normalized_session_id,
            dict(group_state.get(normalized_session_id) or {}),
        )
        changed = False
        local_sender_key = dict(session_record.get("local_sender_key") or {})
        local_sender_key_cleared = False
        if (
            local_sender_key
            and normalized_member_version > 0
            and int(local_sender_key.get("member_version") or -1) != normalized_member_version
        ):
            self._archive_retired_local_sender_key(session_record, local_sender_key)
            session_record["local_sender_key"] = {}
            local_sender_key_cleared = True
            changed = True

        inbound_sender_keys = dict(session_record.get("inbound_sender_keys") or {})
        pruned_inbound_sender_devices: list[str] = []
        if allowed_user_ids:
            filtered_inbound_sender_keys: dict[str, Any] = {}
            for device_id, payload in inbound_sender_keys.items():
                owner_user_id = str(dict(payload or {}).get("owner_user_id") or "").strip()
                if owner_user_id and owner_user_id not in allowed_user_ids:
                    pruned_inbound_sender_devices.append(str(device_id or "").strip())
                    changed = True
                    continue
                filtered_inbound_sender_keys[str(device_id or "").strip()] = dict(payload or {})
            session_record["inbound_sender_keys"] = filtered_inbound_sender_keys

        if changed:
            session_record["updated_at"] = _utcnow().isoformat()
            group_state[normalized_session_id] = session_record
            await self._save_group_session_state(group_state)

        summary = await self.get_group_session_summary(normalized_session_id)
        summary["changed"] = changed
        summary["local_sender_key_cleared"] = local_sender_key_cleared
        summary["pruned_inbound_sender_devices"] = sorted(
            [device_id for device_id in pruned_inbound_sender_devices if device_id]
        )
        return summary

    async def apply_group_session_fanout(self, envelope: dict[str, Any] | None) -> dict[str, Any] | None:
        normalized = dict(envelope or {})
        if not normalized or not normalized.get("enabled"):
            return None
        if str(normalized.get("scheme") or "").strip() != self.GROUP_FANOUT_SCHEME:
            raise RuntimeError("unsupported group fanout scheme")

        local_bundle = await self._load_local_bundle()
        if not isinstance(local_bundle, dict):
            raise RuntimeError("local device bundle is unavailable")
        recipient_device_id = str(normalized.get("recipient_device_id") or "").strip()
        local_device_id = str(local_bundle.get("device_id") or "").strip()
        if recipient_device_id != local_device_id:
            return None

        key_payload = self._resolve_local_private_key(local_bundle, normalized)
        if key_payload is None:
            raise RuntimeError("local device does not have the required private prekey for group fanout")

        plaintext = self._decrypt_payload(
            ciphertext_b64=str(normalized.get("payload_ciphertext") or "").strip(),
            nonce_b64=str(normalized.get("nonce") or "").strip(),
            sender_identity_public_b64=str(normalized.get("sender_identity_key_public") or "").strip(),
            recipient_private_key_b64=str(key_payload.get("private_key") or ""),
            sender_device_id=str(normalized.get("sender_device_id") or ""),
            recipient_device_id=recipient_device_id,
        )
        payload = json.loads(plaintext)
        if not isinstance(payload, dict):
            raise RuntimeError("invalid group fanout payload")

        normalized_session_id = str(payload.get("session_id") or normalized.get("session_id") or "").strip()
        owner_device_id = str(payload.get("owner_device_id") or normalized.get("sender_device_id") or "").strip()
        if not normalized_session_id or not owner_device_id:
            raise RuntimeError("group fanout payload is incomplete")

        group_state = await self._load_group_session_state()
        session_record = self._normalize_group_session_record(
            normalized_session_id,
            dict(group_state.get(normalized_session_id) or {}),
        )
        inbound_sender_keys = dict(session_record.get("inbound_sender_keys") or {})
        inbound_sender_keys[owner_device_id] = {
            "key_id": str(payload.get("sender_key_id") or normalized.get("sender_key_id") or ""),
            "sender_key": str(payload.get("sender_key") or ""),
            "sender_key_scheme": str(payload.get("sender_key_scheme") or self.GROUP_SENDER_KEY_SCHEME),
            "member_version": int(payload.get("member_version") or normalized.get("member_version") or 0),
            "owner_user_id": str(payload.get("owner_user_id") or normalized.get("recipient_user_id") or ""),
            "owner_device_id": owner_device_id,
            "sender_identity_key_public": str(normalized.get("sender_identity_key_public") or ""),
            "installed_at": _utcnow().isoformat(),
            "updated_at": _utcnow().isoformat(),
        }
        session_record["inbound_sender_keys"] = inbound_sender_keys
        session_record["updated_at"] = _utcnow().isoformat()
        group_state[normalized_session_id] = session_record
        await self._save_group_session_state(group_state)
        return {
            "session_id": normalized_session_id,
            "sender_key_id": str(inbound_sender_keys[owner_device_id].get("key_id") or ""),
            "member_version": int(inbound_sender_keys[owner_device_id].get("member_version") or 0),
            "owner_device_id": owner_device_id,
        }
    async def describe_text_decryption_state(self, extra: dict[str, Any] | None) -> dict[str, Any]:
        encryption = dict((extra or {}).get("encryption") or {})
        scheme = str(encryption.get("scheme") or "").strip()
        if scheme == self.GROUP_SENDER_KEY_SCHEME:
            return await self._describe_group_text_decryption_state(extra)
        return await self._describe_local_envelope_state(encryption, expected_scheme=self.ENVELOPE_SCHEME)

    async def describe_attachment_decryption_state(self, attachment_encryption: dict[str, Any] | None) -> dict[str, Any]:
        normalized = dict(attachment_encryption or {})
        if str(normalized.get("scheme") or "").strip() == self.GROUP_ATTACHMENT_SCHEME:
            return await self._describe_group_attachment_decryption_state(normalized)
        return await self._describe_local_envelope_state(
            normalized,
            expected_scheme=self.ATTACHMENT_SCHEME,
        )

    @staticmethod
    def is_encrypted_extra(extra: dict[str, Any] | None) -> bool:
        encryption = dict((extra or {}).get("encryption") or {})
        return bool(encryption.get("enabled"))

    def protect_local_plaintext(self, plaintext: str) -> str:
        return SecureStorage.encrypt_text(str(plaintext or ""))

    def recover_local_plaintext(self, protected_text: str) -> str:
        return SecureStorage.decrypt_text(str(protected_text or ""))

    async def encrypt_text_for_user(self, recipient_user_id: str, plaintext: str) -> tuple[str, dict[str, Any]]:
        normalized_recipient_id = str(recipient_user_id or "").strip()
        if not normalized_recipient_id:
            raise RuntimeError("recipient user id is required for E2EE encryption")

        local_bundle = await self.get_or_create_local_bundle()
        recipient_bundle = await self._claim_or_fetch_recipient_bundle(normalized_recipient_id)
        if recipient_bundle is None:
            raise RuntimeError("recipient has no registered E2EE device")

        self._verify_bundle_signature(recipient_bundle)

        key_payload = self._resolve_recipient_key_material(recipient_bundle)
        ciphertext_b64, nonce_b64 = self._encrypt_payload(
            plaintext=str(plaintext or ""),
            sender_identity_private_b64=str(local_bundle["identity_key_private"]),
            recipient_public_key_b64=str(key_payload["public_key"]),
            sender_device_id=str(local_bundle["device_id"]),
            recipient_device_id=str(recipient_bundle["device_id"]),
        )
        encryption = {
            "enabled": True,
            "scheme": self.ENVELOPE_SCHEME,
            "sender_device_id": str(local_bundle["device_id"]),
            "sender_identity_key_public": str(local_bundle["identity_key_public"]),
            "recipient_user_id": normalized_recipient_id,
            "recipient_device_id": str(recipient_bundle["device_id"]),
            "recipient_prekey_type": str(key_payload["prekey_type"]),
            "recipient_prekey_id": int(key_payload["key_id"]),
            "content_ciphertext": ciphertext_b64,
            "nonce": nonce_b64,
            "local_plaintext": self.protect_local_plaintext(plaintext),
            "local_plaintext_version": self.LOCAL_PLAINTEXT_VERSION,
        }
        return ciphertext_b64, encryption

    async def encrypt_text_for_group_session(
        self,
        session_id: str,
        plaintext: str,
        recipient_bundles: list[dict[str, Any]],
        *,
        member_version: int = 0,
        owner_user_id: str = "",
        force_rotate: bool = False,
    ) -> tuple[str, dict[str, Any]]:
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            raise RuntimeError("session id is required for group encryption")

        fanout_result = await self.prepare_group_session_fanout(
            normalized_session_id,
            recipient_bundles,
            member_version=member_version,
            force_rotate=force_rotate,
            owner_user_id=owner_user_id,
        )
        sender_key_record = await self.get_group_sender_key_record(normalized_session_id)
        if not sender_key_record:
            raise RuntimeError("group sender key is unavailable")

        local_bundle = await self.get_or_create_local_bundle()
        ciphertext_b64, nonce_b64 = self._encrypt_group_sender_payload(
            plaintext=str(plaintext or ""),
            sender_key_b64=str(sender_key_record.get("sender_key") or ""),
            session_id=normalized_session_id,
            sender_device_id=str(local_bundle.get("device_id") or ""),
            sender_key_id=str(sender_key_record.get("key_id") or ""),
        )
        encryption = {
            "enabled": True,
            "scheme": self.GROUP_SENDER_KEY_SCHEME,
            "session_id": normalized_session_id,
            "sender_device_id": str(local_bundle.get("device_id") or ""),
            "sender_key_id": str(sender_key_record.get("key_id") or ""),
            "member_version": int(sender_key_record.get("member_version") or member_version or 0),
            "owner_user_id": str(owner_user_id or sender_key_record.get("owner_user_id") or "").strip(),
            "content_ciphertext": ciphertext_b64,
            "nonce": nonce_b64,
            "fanout": [dict(item) for item in list(fanout_result.get("fanout") or []) if isinstance(item, dict)],
            "local_plaintext": self.protect_local_plaintext(plaintext),
            "local_plaintext_version": self.LOCAL_PLAINTEXT_VERSION,
        }
        return ciphertext_b64, encryption
    async def decrypt_text_content(self, content: str, extra: dict[str, Any] | None) -> str | None:
        encryption = dict((extra or {}).get("encryption") or {})
        if not encryption or not encryption.get("enabled"):
            return None

        protected_plaintext = str(encryption.get("local_plaintext") or "").strip()
        if protected_plaintext:
            try:
                return self.recover_local_plaintext(protected_plaintext)
            except Exception as exc:
                logger.warning("Failed to recover locally protected plaintext: %s", exc)

        scheme = str(encryption.get("scheme") or "").strip()
        if scheme == self.GROUP_SENDER_KEY_SCHEME:
            return await self.decrypt_group_text_content(content, extra)
        if scheme != self.ENVELOPE_SCHEME:
            raise RuntimeError("unsupported E2EE scheme")

        local_bundle = await self._load_local_bundle()
        if not isinstance(local_bundle, dict):
            raise RuntimeError("local device bundle is unavailable")
        recipient_device_id = str(encryption.get("recipient_device_id") or "").strip()

        key_payload = await self._resolve_envelope_private_key(local_bundle, encryption)
        if key_payload is None:
            if recipient_device_id and recipient_device_id != str(local_bundle.get("device_id") or ""):
                return None
            raise RuntimeError("local device does not have the required private prekey")

        sender_identity_key_public = str(encryption.get("sender_identity_key_public") or "").strip()
        nonce_b64 = str(encryption.get("nonce") or "").strip()
        ciphertext_b64 = str(encryption.get("content_ciphertext") or content or "").strip()
        if not sender_identity_key_public or not nonce_b64 or not ciphertext_b64:
            raise RuntimeError("incomplete encrypted message envelope")

        return self._decrypt_payload(
            ciphertext_b64=ciphertext_b64,
            nonce_b64=nonce_b64,
            sender_identity_public_b64=sender_identity_key_public,
            recipient_private_key_b64=str(key_payload["private_key"]),
            sender_device_id=str(encryption.get("sender_device_id") or ""),
            recipient_device_id=recipient_device_id,
        )

    async def decrypt_group_text_content(self, content: str, extra: dict[str, Any] | None) -> str | None:
        encryption = dict((extra or {}).get("encryption") or {})
        if not encryption or not encryption.get("enabled"):
            return None
        if str(encryption.get("scheme") or "").strip() != self.GROUP_SENDER_KEY_SCHEME:
            raise RuntimeError("unsupported group E2EE scheme")

        local_bundle = await self._load_local_bundle()
        if not isinstance(local_bundle, dict):
            raise RuntimeError("local device bundle is unavailable")

        normalized_extra = dict(extra or {})
        session_id = str(encryption.get("session_id") or normalized_extra.get("session_id") or "").strip()
        sender_device_id = str(encryption.get("sender_device_id") or "").strip()
        sender_key_id = str(encryption.get("sender_key_id") or "").strip()
        nonce_b64 = str(encryption.get("nonce") or "").strip()
        ciphertext_b64 = str(encryption.get("content_ciphertext") or content or "").strip()
        if not session_id or not sender_device_id or not sender_key_id or not nonce_b64 or not ciphertext_b64:
            raise RuntimeError("incomplete encrypted group message envelope")

        sender_key_record = await self.get_group_sender_key_record(session_id, owner_device_id=sender_device_id)
        if sender_key_record is None:
            matching_fanout = self._select_group_fanout_envelope(
                encryption.get("fanout"),
                local_device_id=str(local_bundle.get("device_id") or "").strip(),
                session_id=session_id,
            )
            if matching_fanout is not None:
                await self.apply_group_session_fanout(matching_fanout)
                sender_key_record = await self.get_group_sender_key_record(session_id, owner_device_id=sender_device_id)
        if sender_key_record is None:
            return None

        sender_key_b64 = str(sender_key_record.get("sender_key") or "").strip()
        if not sender_key_b64:
            raise RuntimeError("group sender key is unavailable")
        return self._decrypt_group_sender_payload(
            ciphertext_b64=ciphertext_b64,
            nonce_b64=nonce_b64,
            sender_key_b64=sender_key_b64,
            session_id=session_id,
            sender_device_id=sender_device_id,
            sender_key_id=sender_key_id,
        )

    async def encrypt_attachment_for_user(
        self,
        recipient_user_id: str,
        file_path: str,
        *,
        fallback_name: str = "",
        size_bytes: int | None = None,
        mime_type: str = "",
    ) -> EncryptedAttachmentUpload:
        local_bundle = await self.get_or_create_local_bundle()
        recipient_bundle = await self._claim_or_fetch_recipient_bundle(str(recipient_user_id or "").strip())
        if recipient_bundle is None:
            raise RuntimeError("recipient has no registered E2EE device")

        self._verify_bundle_signature(recipient_bundle)
        key_payload = self._resolve_recipient_key_material(recipient_bundle)

        with open(file_path, "rb") as file_handle:
            plaintext_bytes = file_handle.read()

        file_key = urandom(32)
        file_nonce = urandom(12)
        _, _, _, _, _, aesgcm = _load_encryption_primitives()
        ciphertext_bytes = aesgcm(file_key).encrypt(
            file_nonce,
            plaintext_bytes,
            self._attachment_aad_bytes(),
        )

        suffix = ".bin"
        encrypted_file = tempfile.NamedTemporaryFile(prefix="assistim_e2ee_", suffix=suffix, delete=False)
        try:
            encrypted_file.write(ciphertext_bytes)
        finally:
            encrypted_file.close()

        metadata = {
            "file_key": b64encode(file_key).decode("ascii"),
            "file_nonce": b64encode(file_nonce).decode("ascii"),
            "original_name": str(fallback_name or os.path.basename(file_path) or "attachment.bin"),
            "size_bytes": int(size_bytes if size_bytes is not None else len(plaintext_bytes)),
            "mime_type": str(mime_type or mimetypes.guess_type(file_path)[0] or "application/octet-stream"),
        }
        metadata_ciphertext_b64, metadata_nonce_b64 = self._encrypt_payload(
            plaintext=json.dumps(metadata, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
            sender_identity_private_b64=str(local_bundle["identity_key_private"]),
            recipient_public_key_b64=str(key_payload["public_key"]),
            sender_device_id=str(local_bundle["device_id"]),
            recipient_device_id=str(recipient_bundle["device_id"]),
        )
        attachment_encryption = {
            "enabled": True,
            "scheme": self.ATTACHMENT_SCHEME,
            "sender_device_id": str(local_bundle["device_id"]),
            "sender_identity_key_public": str(local_bundle["identity_key_public"]),
            "recipient_user_id": str(recipient_user_id or ""),
            "recipient_device_id": str(recipient_bundle["device_id"]),
            "recipient_prekey_type": str(key_payload["prekey_type"]),
            "recipient_prekey_id": int(key_payload["key_id"]),
            "metadata_ciphertext": metadata_ciphertext_b64,
            "nonce": metadata_nonce_b64,
            "local_metadata": self.protect_local_plaintext(
                json.dumps(metadata, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
            ),
            "local_plaintext_version": self.LOCAL_PLAINTEXT_VERSION,
        }
        return EncryptedAttachmentUpload(
            upload_file_path=encrypted_file.name,
            attachment_encryption=attachment_encryption,
            cleanup_file_path=encrypted_file.name,
        )

    async def encrypt_attachment_for_group_session(
        self,
        session_id: str,
        file_path: str,
        recipient_bundles: list[dict[str, Any]],
        *,
        fallback_name: str = "",
        size_bytes: int | None = None,
        mime_type: str = "",
        member_version: int = 0,
        owner_user_id: str = "",
        force_rotate: bool = False,
    ) -> EncryptedAttachmentUpload:
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            raise RuntimeError("session id is required for group attachment encryption")

        fanout_result = await self.prepare_group_session_fanout(
            normalized_session_id,
            recipient_bundles,
            member_version=member_version,
            force_rotate=force_rotate,
            owner_user_id=owner_user_id,
        )
        sender_key_b64 = str(fanout_result.get("sender_key") or "").strip()
        sender_key_id = str(fanout_result.get("sender_key_id") or "").strip()
        sender_device_id = str(fanout_result.get("sender_device_id") or "").strip()
        if not sender_key_b64 or not sender_key_id or not sender_device_id:
            raise RuntimeError("group sender key could not be prepared for attachment encryption")

        with open(file_path, "rb") as file_handle:
            plaintext_bytes = file_handle.read()

        file_key = urandom(32)
        file_nonce = urandom(12)
        _, _, _, _, _, aesgcm = _load_encryption_primitives()
        ciphertext_bytes = aesgcm(file_key).encrypt(
            file_nonce,
            plaintext_bytes,
            self._attachment_aad_bytes(),
        )

        suffix = ".bin"
        encrypted_file = tempfile.NamedTemporaryFile(prefix="assistim_e2ee_", suffix=suffix, delete=False)
        try:
            encrypted_file.write(ciphertext_bytes)
        finally:
            encrypted_file.close()

        metadata = {
            "file_key": b64encode(file_key).decode("ascii"),
            "file_nonce": b64encode(file_nonce).decode("ascii"),
            "original_name": str(fallback_name or os.path.basename(file_path) or "attachment.bin"),
            "size_bytes": int(size_bytes if size_bytes is not None else len(plaintext_bytes)),
            "mime_type": str(mime_type or mimetypes.guess_type(file_path)[0] or "application/octet-stream"),
        }
        metadata_ciphertext_b64, metadata_nonce_b64 = self._encrypt_group_attachment_metadata(
            metadata=json.dumps(metadata, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
            sender_key_b64=sender_key_b64,
            session_id=normalized_session_id,
            sender_device_id=sender_device_id,
            sender_key_id=sender_key_id,
        )
        attachment_encryption = {
            "enabled": True,
            "scheme": self.GROUP_ATTACHMENT_SCHEME,
            "session_id": normalized_session_id,
            "sender_device_id": sender_device_id,
            "sender_key_id": sender_key_id,
            "member_version": int(fanout_result.get("member_version") or member_version or 0),
            "owner_user_id": str(owner_user_id or ""),
            "metadata_ciphertext": metadata_ciphertext_b64,
            "nonce": metadata_nonce_b64,
            "fanout": [dict(item) for item in list(fanout_result.get("fanout") or []) if isinstance(item, dict)],
            "local_metadata": self.protect_local_plaintext(
                json.dumps(metadata, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
            ),
            "local_plaintext_version": self.LOCAL_PLAINTEXT_VERSION,
        }
        return EncryptedAttachmentUpload(
            upload_file_path=encrypted_file.name,
            attachment_encryption=attachment_encryption,
            cleanup_file_path=encrypted_file.name,
        )

    async def decrypt_attachment_metadata(self, attachment_encryption: dict[str, Any] | None) -> dict[str, Any] | None:
        normalized = dict(attachment_encryption or {})
        if not normalized or not normalized.get("enabled"):
            return None

        protected_metadata = str(normalized.get("local_metadata") or "").strip()
        if protected_metadata:
            try:
                payload = json.loads(self.recover_local_plaintext(protected_metadata))
                return payload if isinstance(payload, dict) else None
            except Exception as exc:
                logger.warning("Failed to recover protected attachment metadata: %s", exc)

        if str(normalized.get("scheme") or "").strip() == self.GROUP_ATTACHMENT_SCHEME:
            return await self._decrypt_group_attachment_metadata(normalized)

        local_bundle = await self._load_local_bundle()
        if not isinstance(local_bundle, dict):
            raise RuntimeError("local device bundle is unavailable")
        recipient_device_id = str(normalized.get("recipient_device_id") or "").strip()

        key_payload = await self._resolve_envelope_private_key(local_bundle, normalized)
        if key_payload is None:
            if recipient_device_id and recipient_device_id != str(local_bundle.get("device_id") or ""):
                return None
            raise RuntimeError("local device does not have the required private prekey for attachment metadata")

        plaintext = self._decrypt_payload(
            ciphertext_b64=str(normalized.get("metadata_ciphertext") or "").strip(),
            nonce_b64=str(normalized.get("nonce") or "").strip(),
            sender_identity_public_b64=str(normalized.get("sender_identity_key_public") or "").strip(),
            recipient_private_key_b64=str(key_payload["private_key"]),
            sender_device_id=str(normalized.get("sender_device_id") or ""),
            recipient_device_id=recipient_device_id,
        )
        payload = json.loads(plaintext)
        if not isinstance(payload, dict):
            return None
        return payload

    async def decrypt_attachment_bytes(
        self,
        ciphertext_bytes: bytes,
        attachment_encryption: dict[str, Any] | None,
    ) -> tuple[bytes, dict[str, Any]]:
        """Decrypt one downloaded attachment payload into plaintext bytes and metadata."""
        metadata = await self.decrypt_attachment_metadata(attachment_encryption)
        if not metadata:
            raise RuntimeError("attachment metadata is unavailable for decryption")

        try:
            file_key = b64decode(str(metadata.get("file_key") or "").strip())
            file_nonce = b64decode(str(metadata.get("file_nonce") or "").strip())
        except Exception as exc:
            raise RuntimeError("attachment metadata is missing file key material") from exc

        _, _, _, _, _, aesgcm = _load_encryption_primitives()
        plaintext_bytes = aesgcm(file_key).decrypt(
            file_nonce,
            bytes(ciphertext_bytes or b""),
            self._attachment_aad_bytes(),
        )
        return plaintext_bytes, metadata

    async def _decrypt_group_attachment_metadata(self, attachment_encryption: dict[str, Any]) -> dict[str, Any] | None:
        normalized = dict(attachment_encryption or {})
        local_bundle = await self._load_local_bundle()
        if not isinstance(local_bundle, dict):
            raise RuntimeError("local device bundle is unavailable")

        session_id = str(normalized.get("session_id") or "").strip()
        sender_device_id = str(normalized.get("sender_device_id") or "").strip()
        sender_key_id = str(normalized.get("sender_key_id") or "").strip()
        local_device_id = str(local_bundle.get("device_id") or "").strip()
        sender_key_record = await self.get_group_sender_key_record(
            session_id,
            owner_device_id=sender_device_id,
            sender_key_id=sender_key_id,
        )
        if sender_key_record is None:
            matching_fanout = self._select_group_fanout_envelope(
                normalized.get("fanout"),
                local_device_id=local_device_id,
                session_id=session_id,
            )
            if matching_fanout is not None:
                await self.apply_group_session_fanout(matching_fanout)
                sender_key_record = await self.get_group_sender_key_record(
                    session_id,
                    owner_device_id=sender_device_id,
                    sender_key_id=sender_key_id,
                )
        if sender_key_record is None:
            return None

        plaintext = self._decrypt_group_attachment_metadata_payload(
            ciphertext_b64=str(normalized.get("metadata_ciphertext") or "").strip(),
            nonce_b64=str(normalized.get("nonce") or "").strip(),
            sender_key_b64=str(sender_key_record.get("sender_key") or "").strip(),
            session_id=session_id,
            sender_device_id=sender_device_id,
            sender_key_id=sender_key_id or str(sender_key_record.get("key_id") or ""),
        )
        payload = json.loads(plaintext)
        if not isinstance(payload, dict):
            return None
        return payload

    async def _describe_group_text_decryption_state(self, extra: dict[str, Any] | None) -> dict[str, Any]:
        normalized_extra = dict(extra or {})
        encryption = dict(normalized_extra.get("encryption") or {})
        local_bundle = await self._load_local_bundle()
        local_device_id = str((local_bundle or {}).get("device_id") or "").strip()
        sender_device_id = str(encryption.get("sender_device_id") or "").strip()
        sender_key_id = str(encryption.get("sender_key_id") or "").strip()
        session_id = str(encryption.get("session_id") or normalized_extra.get("session_id") or "").strip()

        if not encryption.get("enabled"):
            return {
                "state": self.DECRYPTION_STATE_READY,
                "can_decrypt": False,
                "reprovision_required": False,
                "local_device_id": local_device_id,
                "target_device_id": sender_device_id,
            }
        if not isinstance(local_bundle, dict):
            return {
                "state": self.DECRYPTION_STATE_MISSING_LOCAL_BUNDLE,
                "can_decrypt": False,
                "reprovision_required": True,
                "local_device_id": "",
                "target_device_id": sender_device_id,
            }
        if session_id and sender_device_id:
            sender_key_record = await self.get_group_sender_key_record(
                session_id,
                owner_device_id=sender_device_id,
                sender_key_id=sender_key_id,
            )
            if sender_key_record is not None:
                return {
                    "state": self.DECRYPTION_STATE_READY,
                    "can_decrypt": True,
                    "reprovision_required": False,
                    "local_device_id": local_device_id,
                    "target_device_id": sender_device_id,
                }

        matching_fanout = self._select_group_fanout_envelope(
            encryption.get("fanout"),
            local_device_id=local_device_id,
            session_id=session_id,
        )
        if matching_fanout is not None:
            if self._resolve_local_private_key(local_bundle, matching_fanout) is None:
                return {
                    "state": self.DECRYPTION_STATE_MISSING_PRIVATE_KEY,
                    "can_decrypt": False,
                    "reprovision_required": True,
                    "local_device_id": local_device_id,
                    "target_device_id": local_device_id,
                }
            return {
                "state": self.DECRYPTION_STATE_MISSING_GROUP_SENDER_KEY,
                "can_decrypt": False,
                "reprovision_required": False,
                "local_device_id": local_device_id,
                "target_device_id": sender_device_id,
            }

        return {
            "state": self.DECRYPTION_STATE_MISSING_GROUP_SENDER_KEY,
            "can_decrypt": False,
            "reprovision_required": False,
            "local_device_id": local_device_id,
            "target_device_id": sender_device_id,
        }

    async def _describe_group_attachment_decryption_state(
        self,
        attachment_encryption: dict[str, Any] | None,
    ) -> dict[str, Any]:
        normalized = dict(attachment_encryption or {})
        local_bundle = await self._load_local_bundle()
        local_device_id = str((local_bundle or {}).get("device_id") or "").strip()
        sender_device_id = str(normalized.get("sender_device_id") or "").strip()
        sender_key_id = str(normalized.get("sender_key_id") or "").strip()
        session_id = str(normalized.get("session_id") or "").strip()

        if not normalized.get("enabled"):
            return {
                "state": self.DECRYPTION_STATE_READY,
                "can_decrypt": False,
                "reprovision_required": False,
                "local_device_id": local_device_id,
                "target_device_id": sender_device_id,
            }
        if not isinstance(local_bundle, dict):
            return {
                "state": self.DECRYPTION_STATE_MISSING_LOCAL_BUNDLE,
                "can_decrypt": False,
                "reprovision_required": True,
                "local_device_id": "",
                "target_device_id": sender_device_id,
            }
        if session_id and sender_device_id:
            sender_key_record = await self.get_group_sender_key_record(
                session_id,
                owner_device_id=sender_device_id,
                sender_key_id=sender_key_id,
            )
            if sender_key_record is not None:
                return {
                    "state": self.DECRYPTION_STATE_READY,
                    "can_decrypt": True,
                    "reprovision_required": False,
                    "local_device_id": local_device_id,
                    "target_device_id": sender_device_id,
                }

        matching_fanout = self._select_group_fanout_envelope(
            normalized.get("fanout"),
            local_device_id=local_device_id,
            session_id=session_id,
        )
        if matching_fanout is not None:
            if self._resolve_local_private_key(local_bundle, matching_fanout) is None:
                return {
                    "state": self.DECRYPTION_STATE_MISSING_PRIVATE_KEY,
                    "can_decrypt": False,
                    "reprovision_required": True,
                    "local_device_id": local_device_id,
                    "target_device_id": str(matching_fanout.get("recipient_device_id") or local_device_id),
                }
            return {
                "state": self.DECRYPTION_STATE_READY,
                "can_decrypt": True,
                "reprovision_required": False,
                "local_device_id": local_device_id,
                "target_device_id": sender_device_id,
            }

        return {
            "state": self.DECRYPTION_STATE_MISSING_GROUP_SENDER_KEY,
            "can_decrypt": False,
            "reprovision_required": False,
            "local_device_id": local_device_id,
            "target_device_id": sender_device_id,
        }
    async def _describe_local_envelope_state(
        self,
        envelope: dict[str, Any] | None,
        *,
        expected_scheme: str,
    ) -> dict[str, Any]:
        normalized = dict(envelope or {})
        local_bundle = await self._load_local_bundle()
        local_device_id = str((local_bundle or {}).get("device_id") or "").strip()
        recipient_device_id = str(normalized.get("recipient_device_id") or "").strip()
        scheme = str(normalized.get("scheme") or "").strip()
        if not normalized.get("enabled"):
            return {
                "state": self.DECRYPTION_STATE_READY,
                "can_decrypt": False,
                "reprovision_required": False,
                "local_device_id": local_device_id,
                "target_device_id": recipient_device_id,
            }
        if scheme and scheme != expected_scheme:
            return {
                "state": self.DECRYPTION_STATE_UNSUPPORTED_SCHEME,
                "can_decrypt": False,
                "reprovision_required": False,
                "local_device_id": local_device_id,
                "target_device_id": recipient_device_id,
            }
        if not isinstance(local_bundle, dict):
            return {
                "state": self.DECRYPTION_STATE_MISSING_LOCAL_BUNDLE,
                "can_decrypt": False,
                "reprovision_required": True,
                "local_device_id": "",
                "target_device_id": recipient_device_id,
            }
        key_payload = await self._resolve_envelope_private_key(local_bundle, normalized)
        if recipient_device_id and recipient_device_id != local_device_id and key_payload is None:
            return {
                "state": self.DECRYPTION_STATE_NOT_FOR_CURRENT_DEVICE,
                "can_decrypt": False,
                "reprovision_required": False,
                "local_device_id": local_device_id,
                "target_device_id": recipient_device_id,
            }
        if key_payload is None:
            return {
                "state": self.DECRYPTION_STATE_MISSING_PRIVATE_KEY,
                "can_decrypt": False,
                "reprovision_required": True,
                "local_device_id": local_device_id,
                "target_device_id": recipient_device_id or local_device_id,
            }
        return {
            "state": self.DECRYPTION_STATE_READY,
            "can_decrypt": True,
            "reprovision_required": False,
            "local_device_id": local_device_id,
            "target_device_id": recipient_device_id or local_device_id,
        }

    async def _load_local_bundle(self) -> dict[str, Any] | None:
        raw_value = await self._db.get_app_state(self.DEVICE_STATE_KEY)
        if not raw_value:
            return None
        try:
            decrypted = SecureStorage.decrypt_text(str(raw_value))
            payload = json.loads(decrypted)
        except Exception as exc:
            logger.warning("Failed to load persisted E2EE device state: %s", exc)
            return None
        if not isinstance(payload, dict):
            return None
        return self._normalize_loaded_bundle(payload)

    async def _save_local_bundle(self, bundle: dict[str, Any]) -> None:
        normalized_bundle = self._normalize_loaded_bundle(bundle)
        serialized = json.dumps(normalized_bundle, ensure_ascii=True, sort_keys=True)
        encrypted = SecureStorage.encrypt_text(serialized)
        await self._db.set_app_state(self.DEVICE_STATE_KEY, encrypted)

    async def _load_group_session_state(self) -> dict[str, Any]:
        raw_value = await self._db.get_app_state(self.GROUP_SESSION_STATE_KEY)
        if not raw_value:
            return {}
        try:
            decrypted = SecureStorage.decrypt_text(str(raw_value))
            payload = json.loads(decrypted)
        except Exception as exc:
            logger.warning("Failed to load persisted group E2EE session state: %s", exc)
            return {}
        if not isinstance(payload, dict):
            return {}
        normalized: dict[str, Any] = {}
        for session_id, record in payload.items():
            normalized_session_id = str(session_id or "").strip()
            if not normalized_session_id:
                continue
            normalized[normalized_session_id] = self._normalize_group_session_record(
                normalized_session_id,
                dict(record or {}),
            )
        return normalized

    async def _save_group_session_state(self, state: dict[str, Any]) -> None:
        normalized_state: dict[str, Any] = {}
        for session_id, record in dict(state or {}).items():
            normalized_session_id = str(session_id or "").strip()
            if not normalized_session_id:
                continue
            normalized_state[normalized_session_id] = self._normalize_group_session_record(
                normalized_session_id,
                dict(record or {}),
            )
        serialized = json.dumps(normalized_state, ensure_ascii=True, sort_keys=True)
        encrypted = SecureStorage.encrypt_text(serialized)
        await self._db.set_app_state(self.GROUP_SESSION_STATE_KEY, encrypted)

    async def _load_history_recovery_state(self) -> dict[str, Any]:
        raw_value = await self._db.get_app_state(self.HISTORY_RECOVERY_STATE_KEY)
        if not raw_value:
            return {"devices": {}}
        try:
            decrypted = SecureStorage.decrypt_text(str(raw_value))
            payload = json.loads(decrypted)
        except Exception as exc:
            logger.warning("Failed to load persisted E2EE history recovery state: %s", exc)
            return {"devices": {}}
        return self._normalize_history_recovery_state(payload)

    async def _save_history_recovery_state(self, state: dict[str, Any]) -> None:
        normalized_state = self._normalize_history_recovery_state(state)
        serialized = json.dumps(normalized_state, ensure_ascii=True, sort_keys=True)
        encrypted = SecureStorage.encrypt_text(serialized)
        await self._db.set_app_state(self.HISTORY_RECOVERY_STATE_KEY, encrypted)

    async def _load_identity_trust_state(self) -> dict[str, Any]:
        raw_value = await self._db.get_app_state(self.IDENTITY_TRUST_STATE_KEY)
        if not raw_value:
            return {"users": {}}
        try:
            decrypted = SecureStorage.decrypt_text(str(raw_value))
            payload = json.loads(decrypted)
        except Exception as exc:
            logger.warning("Failed to load persisted E2EE identity trust state: %s", exc)
            return {"users": {}}
        return self._normalize_identity_trust_state(payload)

    async def _save_identity_trust_state(self, state: dict[str, Any]) -> None:
        normalized_state = self._normalize_identity_trust_state(state)
        serialized = json.dumps(normalized_state, ensure_ascii=True, sort_keys=True)
        encrypted = SecureStorage.encrypt_text(serialized)
        await self._db.set_app_state(self.IDENTITY_TRUST_STATE_KEY, encrypted)

    def _normalize_group_session_record(self, session_id: str, record: dict[str, Any]) -> dict[str, Any]:
        normalized_session_id = str(session_id or "").strip()
        normalized = dict(record or {})
        normalized["session_id"] = normalized_session_id
        local_sender_key = dict(normalized.get("local_sender_key") or {})
        if local_sender_key:
            local_sender_key.setdefault("sender_key_scheme", self.GROUP_SENDER_KEY_SCHEME)
            local_sender_key.setdefault("owner_device_id", str(local_sender_key.get("owner_device_id") or "").strip())
            local_sender_key.setdefault("member_version", int(local_sender_key.get("member_version") or 0))
            local_sender_key.setdefault("updated_at", str(local_sender_key.get("created_at") or _utcnow().isoformat()))
            normalized["local_sender_key"] = local_sender_key
        else:
            normalized["local_sender_key"] = {}

        retired_local_sender_keys: dict[str, Any] = {}
        for key_id, payload in dict(normalized.get("retired_local_sender_keys") or {}).items():
            normalized_key_id = str(key_id or "").strip()
            if not normalized_key_id or not isinstance(payload, dict):
                continue
            item = dict(payload)
            item.setdefault("sender_key_scheme", self.GROUP_SENDER_KEY_SCHEME)
            item.setdefault("key_id", normalized_key_id)
            item.setdefault("owner_device_id", str(item.get("owner_device_id") or "").strip())
            item.setdefault("member_version", int(item.get("member_version") or 0))
            item.setdefault("updated_at", str(item.get("created_at") or item.get("updated_at") or _utcnow().isoformat()))
            retired_local_sender_keys[normalized_key_id] = item
        normalized["retired_local_sender_keys"] = self._prune_retired_local_sender_keys(retired_local_sender_keys)

        inbound_sender_keys: dict[str, Any] = {}
        for device_id, payload in dict(normalized.get("inbound_sender_keys") or {}).items():
            normalized_device_id = str(device_id or "").strip()
            if not normalized_device_id or not isinstance(payload, dict):
                continue
            item = dict(payload)
            item.setdefault("sender_key_scheme", self.GROUP_SENDER_KEY_SCHEME)
            item.setdefault("owner_device_id", normalized_device_id)
            item.setdefault("member_version", int(item.get("member_version") or 0))
            item.setdefault("updated_at", str(item.get("installed_at") or _utcnow().isoformat()))
            inbound_sender_keys[normalized_device_id] = item
        normalized["inbound_sender_keys"] = inbound_sender_keys
        normalized.setdefault("updated_at", _utcnow().isoformat())
        return normalized

    def _generate_group_sender_key_record(
        self,
        *,
        session_id: str,
        owner_device_id: str,
        owner_user_id: str,
        member_version: int,
    ) -> dict[str, Any]:
        issued_at = _utcnow().isoformat()
        return {
            "session_id": str(session_id or "").strip(),
            "key_id": str(uuid.uuid4()),
            "sender_key": b64encode(urandom(32)).decode("ascii"),
            "sender_key_scheme": self.GROUP_SENDER_KEY_SCHEME,
            "owner_device_id": str(owner_device_id or "").strip(),
            "owner_user_id": str(owner_user_id or "").strip(),
            "member_version": max(0, int(member_version or 0)),
            "created_at": issued_at,
            "updated_at": issued_at,
        }

    def _archive_retired_local_sender_key(self, session_record: dict[str, Any], local_sender_key: dict[str, Any] | None) -> None:
        candidate = dict(local_sender_key or {})
        key_id = str(candidate.get("key_id") or "").strip()
        sender_key = str(candidate.get("sender_key") or "").strip()
        if not key_id or not sender_key:
            return
        retired_local_sender_keys = {
            str(existing_key_id or "").strip(): dict(payload)
            for existing_key_id, payload in dict(session_record.get("retired_local_sender_keys") or {}).items()
            if str(existing_key_id or "").strip() and isinstance(payload, dict)
        }
        candidate.setdefault("sender_key_scheme", self.GROUP_SENDER_KEY_SCHEME)
        candidate["updated_at"] = _utcnow().isoformat()
        retired_local_sender_keys[key_id] = candidate
        session_record["retired_local_sender_keys"] = self._prune_retired_local_sender_keys(retired_local_sender_keys)

    def _prune_retired_local_sender_keys(self, retired_local_sender_keys: dict[str, Any]) -> dict[str, Any]:
        items: list[tuple[str, dict[str, Any]]] = []
        for key_id, payload in dict(retired_local_sender_keys or {}).items():
            normalized_key_id = str(key_id or "").strip()
            if not normalized_key_id or not isinstance(payload, dict):
                continue
            item = dict(payload)
            item.setdefault("key_id", normalized_key_id)
            items.append((normalized_key_id, item))

        items.sort(
            key=lambda item: (
                str(item[1].get("updated_at") or item[1].get("created_at") or ""),
                str(item[0] or ""),
            ),
            reverse=True,
        )
        return {
            key_id: payload
            for key_id, payload in items[: self.GROUP_RETIRED_LOCAL_KEY_LIMIT]
        }

    def _normalize_history_recovery_state(self, payload: Any) -> dict[str, Any]:
        root = dict(payload or {}) if isinstance(payload, dict) else {}
        normalized_devices: dict[str, Any] = {}
        for device_id, record in dict(root.get("devices") or {}).items():
            normalized_device_id = str(device_id or "").strip()
            if not normalized_device_id or not isinstance(record, dict):
                continue
            normalized_devices[normalized_device_id] = self._normalize_history_recovery_device_record(
                normalized_device_id,
                dict(record),
            )
        return {"devices": normalized_devices}

    def _normalize_history_recovery_device_record(self, source_device_id: str, record: dict[str, Any]) -> dict[str, Any]:
        normalized_source_device_id = str(source_device_id or "").strip()
        normalized = dict(record or {})
        normalized["source_device_id"] = normalized_source_device_id
        normalized["source_user_id"] = str(normalized.get("source_user_id") or "").strip()
        normalized["imported_at"] = str(normalized.get("imported_at") or "")
        normalized["exported_at"] = str(normalized.get("exported_at") or "")

        signed_prekeys: dict[str, Any] = {}
        for key_id, payload in dict(normalized.get("signed_prekeys") or {}).items():
            normalized_key_id = str(key_id or "").strip()
            item = dict(payload or {})
            private_key = str(item.get("private_key") or "").strip()
            resolved_key_id = int(item.get("key_id") or normalized_key_id or 0)
            if resolved_key_id <= 0 or not private_key:
                continue
            signed_prekeys[str(resolved_key_id)] = {
                "key_id": resolved_key_id,
                "private_key": private_key,
            }
        normalized["signed_prekeys"] = signed_prekeys

        one_time_prekeys: dict[str, Any] = {}
        for prekey_id, payload in dict(normalized.get("one_time_prekeys") or {}).items():
            normalized_prekey_id = str(prekey_id or "").strip()
            item = dict(payload or {})
            private_key = str(item.get("private_key") or "").strip()
            resolved_prekey_id = int(item.get("prekey_id") or normalized_prekey_id or 0)
            if resolved_prekey_id <= 0 or not private_key:
                continue
            one_time_prekeys[str(resolved_prekey_id)] = {
                "prekey_id": resolved_prekey_id,
                "private_key": private_key,
            }
        normalized["one_time_prekeys"] = one_time_prekeys

        group_sessions: dict[str, Any] = {}
        for session_id, payload in dict(normalized.get("group_sessions") or {}).items():
            normalized_session_id = str(session_id or "").strip()
            if not normalized_session_id or not isinstance(payload, dict):
                continue
            group_sessions[normalized_session_id] = self._normalize_history_group_session_record(
                normalized_session_id,
                dict(payload),
                source_device_id=normalized_source_device_id,
                source_user_id=str(normalized.get("source_user_id") or "").strip(),
            )
        normalized["group_sessions"] = group_sessions
        return normalized

    def _normalize_history_group_session_record(
        self,
        session_id: str,
        record: dict[str, Any],
        *,
        source_device_id: str,
        source_user_id: str,
    ) -> dict[str, Any]:
        normalized_session_id = str(session_id or "").strip()
        normalized = dict(record or {})
        normalized["session_id"] = normalized_session_id
        normalized["source_device_id"] = str(source_device_id or "").strip()
        normalized["source_user_id"] = str(source_user_id or "").strip()
        sender_keys: dict[str, Any] = {}
        for key_id, payload in dict(normalized.get("sender_keys") or {}).items():
            normalized_key_id = str(key_id or "").strip()
            if not normalized_key_id or not isinstance(payload, dict):
                continue
            item = self._normalize_history_sender_key_record(
                dict(payload),
                source_device_id=str(source_device_id or "").strip(),
                source_user_id=str(source_user_id or "").strip(),
            )
            resolved_key_id = str(item.get("key_id") or normalized_key_id).strip()
            if not resolved_key_id or not str(item.get("sender_key") or "").strip():
                continue
            sender_keys[resolved_key_id] = item
        normalized["sender_keys"] = sender_keys
        normalized["updated_at"] = str(normalized.get("updated_at") or _utcnow().isoformat())
        return normalized

    def _normalize_history_sender_key_record(
        self,
        record: dict[str, Any],
        *,
        source_device_id: str,
        source_user_id: str,
    ) -> dict[str, Any]:
        normalized = dict(record or {})
        normalized["key_id"] = str(normalized.get("key_id") or "").strip()
        normalized["sender_key"] = str(normalized.get("sender_key") or "").strip()
        normalized["sender_key_scheme"] = str(normalized.get("sender_key_scheme") or self.GROUP_SENDER_KEY_SCHEME)
        normalized["owner_device_id"] = str(normalized.get("owner_device_id") or source_device_id or "").strip()
        normalized["owner_user_id"] = str(normalized.get("owner_user_id") or source_user_id or "").strip()
        normalized["member_version"] = int(normalized.get("member_version") or 0)
        normalized["created_at"] = str(normalized.get("created_at") or normalized.get("installed_at") or _utcnow().isoformat())
        normalized["updated_at"] = str(
            normalized.get("updated_at")
            or normalized.get("created_at")
            or normalized.get("installed_at")
            or _utcnow().isoformat()
        )
        return normalized

    def _normalize_identity_trust_state(self, payload: Any) -> dict[str, Any]:
        root = dict(payload or {}) if isinstance(payload, dict) else {}
        normalized_users: dict[str, Any] = {}
        for user_id, record in dict(root.get("users") or {}).items():
            normalized_user_id = str(user_id or "").strip()
            if not normalized_user_id or not isinstance(record, dict):
                continue
            user_record = dict(record)
            devices: dict[str, Any] = {}
            for device_id, device_record in dict(user_record.get("devices") or {}).items():
                normalized_device_id = str(device_id or "").strip()
                if not normalized_device_id or not isinstance(device_record, dict):
                    continue
                normalized_device_record = self._normalize_remote_identity_bundle(device_record)
                fingerprint = str(device_record.get("fingerprint") or "").strip() or self._device_identity_fingerprint(
                    normalized_device_record
                )
                if not fingerprint:
                    continue
                devices[normalized_device_id] = {
                    "device_id": normalized_device_id,
                    "device_name": str(normalized_device_record.get("device_name") or "").strip(),
                    "identity_key_public": str(normalized_device_record.get("identity_key_public") or "").strip(),
                    "signing_key_public": str(normalized_device_record.get("signing_key_public") or "").strip(),
                    "fingerprint": fingerprint,
                    "trusted_at": str(device_record.get("trusted_at") or ""),
                    "last_trusted_at": str(device_record.get("last_trusted_at") or device_record.get("trusted_at") or ""),
                    "first_seen_at": str(device_record.get("first_seen_at") or ""),
                    "last_seen_at": str(device_record.get("last_seen_at") or ""),
                    "last_status": str(device_record.get("last_status") or ""),
                    "status_updated_at": str(device_record.get("status_updated_at") or ""),
                    "last_changed_at": str(device_record.get("last_changed_at") or ""),
                    "change_count": int(device_record.get("change_count", 0) or 0),
                    "trust_source": str(device_record.get("trust_source") or ""),
                    "last_observed_fingerprint": str(device_record.get("last_observed_fingerprint") or fingerprint),
                }
            normalized_users[normalized_user_id] = {
                "devices": devices,
                "updated_at": str(user_record.get("updated_at") or ""),
            }
        return {"users": normalized_users}

    @staticmethod
    def _normalize_remote_identity_bundle(payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload or {})
        normalized["device_id"] = str(normalized.get("device_id") or "").strip()
        normalized["device_name"] = str(normalized.get("device_name") or "").strip()
        normalized["identity_key_public"] = str(normalized.get("identity_key_public") or "").strip()
        normalized["signing_key_public"] = str(normalized.get("signing_key_public") or "").strip()
        return normalized

    @staticmethod
    def _device_identity_fingerprint(payload: dict[str, Any]) -> str:
        identity_key_public = str(payload.get("identity_key_public") or "").strip()
        signing_key_public = str(payload.get("signing_key_public") or "").strip()
        if not identity_key_public or not signing_key_public:
            return ""
        digest = sha256(f"{identity_key_public}:{signing_key_public}".encode("utf-8")).hexdigest().upper()
        return digest

    @classmethod
    def _identity_verification_code(cls, local_fingerprint: str, remote_fingerprint: str) -> str:
        normalized_local = str(local_fingerprint or "").strip().upper()
        normalized_remote = str(remote_fingerprint or "").strip().upper()
        if not normalized_local or not normalized_remote:
            return ""
        digest = sha256("::".join(sorted([normalized_local, normalized_remote])).encode("utf-8")).digest()
        decimal = str(int.from_bytes(digest, "big")).zfill(80)[:60]
        return " ".join(decimal[index:index + 5] for index in range(0, len(decimal), 5))

    @staticmethod
    def _short_verification_code(code: str) -> str:
        groups = [group for group in str(code or "").split() if group]
        if not groups:
            return ""
        return " ".join(groups[:3])

    @classmethod
    def _select_primary_identity_device(cls, devices: list[dict[str, Any]]) -> dict[str, Any]:
        ordered_statuses = [
            cls.IDENTITY_STATUS_CHANGED,
            cls.IDENTITY_STATUS_UNVERIFIED,
            cls.IDENTITY_STATUS_VERIFIED,
        ]
        for status in ordered_statuses:
            for device in devices:
                if str(device.get("trust_status") or "").strip() == status:
                    return dict(device)
        return dict(devices[0]) if devices else {}

    @staticmethod
    def _record_identity_observation(
        existing_record: dict[str, Any],
        normalized_device: dict[str, Any],
        *,
        trust_status: str,
        fingerprint: str,
        observed_at: str,
        mark_trusted: bool = False,
    ) -> dict[str, Any]:
        record = dict(existing_record or {})
        previous_status = str(record.get("last_status") or "").strip()
        previous_observed_fingerprint = str(record.get("last_observed_fingerprint") or "").strip()
        trusted_fingerprint = str(record.get("fingerprint") or "").strip()
        if not trusted_fingerprint or mark_trusted or trust_status != "identity_changed":
            trusted_fingerprint = fingerprint
        record.update(
            {
                "device_id": str(normalized_device.get("device_id") or "").strip(),
                "device_name": str(normalized_device.get("device_name") or "").strip(),
                "identity_key_public": str(normalized_device.get("identity_key_public") or "").strip(),
                "signing_key_public": str(normalized_device.get("signing_key_public") or "").strip(),
                "fingerprint": trusted_fingerprint,
                "first_seen_at": str(record.get("first_seen_at") or observed_at or ""),
                "last_seen_at": str(observed_at or ""),
                "last_status": str(trust_status or "").strip(),
                "last_observed_fingerprint": str(fingerprint or ""),
                "change_count": int(record.get("change_count", 0) or 0),
                "trusted_at": str(record.get("trusted_at") or ""),
                "last_trusted_at": str(record.get("last_trusted_at") or record.get("trusted_at") or ""),
                "last_changed_at": str(record.get("last_changed_at") or ""),
                "status_updated_at": str(record.get("status_updated_at") or ""),
                "trust_source": str(record.get("trust_source") or ""),
            }
        )
        if previous_status != record["last_status"]:
            record["status_updated_at"] = str(observed_at or "")
        if record["last_status"] == "identity_changed" and previous_observed_fingerprint != fingerprint:
            record["last_changed_at"] = str(observed_at or "")
            record["change_count"] = int(record.get("change_count", 0) or 0) + 1
        if mark_trusted:
            record["trusted_at"] = str(observed_at or "")
            record["last_trusted_at"] = str(observed_at or "")
            record["trust_source"] = "local_manual"
        return record
    def _generate_local_bundle(self) -> dict[str, Any]:
        x25519, ed25519, serialization = _load_crypto_primitives()

        identity_private = x25519.X25519PrivateKey.generate()
        signing_private = ed25519.Ed25519PrivateKey.generate()
        signed_prekey_private = x25519.X25519PrivateKey.generate()

        signed_prekey_public_bytes = _x25519_public_bytes(signed_prekey_private.public_key(), serialization)
        signing_private_bytes = _ed25519_private_bytes(signing_private, serialization)
        bundle = {
            "device_id": str(uuid.uuid4()),
            "device_name": self._default_device_name(),
            "identity_key_private": _x25519_private_b64(identity_private, serialization),
            "identity_key_public": _x25519_public_b64(identity_private.public_key(), serialization),
            "signing_key_private": b64encode(signing_private_bytes).decode("ascii"),
            "signing_key_public": _ed25519_public_b64(signing_private.public_key(), serialization),
            "signed_prekey": {
                "key_id": 1,
                "private_key": _x25519_private_b64(signed_prekey_private, serialization),
                "public_key": b64encode(signed_prekey_public_bytes).decode("ascii"),
                "signature": b64encode(signing_private.sign(signed_prekey_public_bytes)).decode("ascii"),
            },
            "signed_prekey_created_at": _utcnow().isoformat(),
            "next_signed_prekey_id": 2,
            "retired_signed_prekeys": [],
            "one_time_prekeys": [],
            "next_prekey_id": self.DEFAULT_PREKEY_COUNT + 1,
        }

        for prekey_id in range(1, self.DEFAULT_PREKEY_COUNT + 1):
            private_key = x25519.X25519PrivateKey.generate()
            bundle["one_time_prekeys"].append(
                {
                    "prekey_id": prekey_id,
                    "private_key": _x25519_private_b64(private_key, serialization),
                    "public_key": _x25519_public_b64(private_key.public_key(), serialization),
                }
            )
        return bundle

    @staticmethod
    def _default_device_name() -> str:
        node_name = str(platform.node() or "").strip()
        return f"AssistIM Desktop ({node_name})" if node_name else "AssistIM Desktop"

    def _normalize_loaded_bundle(self, payload: dict[str, Any]) -> dict[str, Any]:
        bundle = dict(payload or {})
        bundle.setdefault("device_name", self._default_device_name())
        bundle.setdefault("retired_signed_prekeys", [])
        retired_signed_prekeys = [
            dict(item)
            for item in list(bundle.get("retired_signed_prekeys") or [])
            if isinstance(item, dict)
        ]
        bundle["retired_signed_prekeys"] = retired_signed_prekeys
        bundle["one_time_prekeys"] = [
            dict(item)
            for item in list(bundle.get("one_time_prekeys") or [])
            if isinstance(item, dict)
        ]
        signed_prekey = dict(bundle.get("signed_prekey") or {})
        bundle["signed_prekey"] = signed_prekey
        signed_prekey_key_id = int(signed_prekey.get("key_id") or 0)
        bundle.setdefault("signed_prekey_created_at", _utcnow().isoformat())
        bundle.setdefault("next_signed_prekey_id", max(1, signed_prekey_key_id + 1))
        highest_known_prekey_id = max((int(item.get("prekey_id") or 0) for item in bundle["one_time_prekeys"]), default=0)
        bundle.setdefault("next_prekey_id", max(1, highest_known_prekey_id + 1))
        return bundle

    async def _register_bundle(self, bundle: dict[str, Any]) -> dict[str, Any]:
        response = await self._http.post("/devices/register", json=self._device_register_payload(bundle))
        return dict(response or {})

    @staticmethod
    def _find_device_record(devices: list[dict[str, Any]], device_id: str) -> dict[str, Any] | None:
        normalized_device_id = str(device_id or "").strip()
        for item in devices:
            if str(item.get("device_id") or "").strip() == normalized_device_id:
                return dict(item)
        return None

    @staticmethod
    def _device_register_payload(bundle: dict[str, Any]) -> dict[str, Any]:
        return {
            "device_id": bundle["device_id"],
            "device_name": bundle["device_name"],
            "identity_key_public": bundle["identity_key_public"],
            "signing_key_public": bundle["signing_key_public"],
            "signed_prekey": {
                "key_id": int(bundle["signed_prekey"]["key_id"]),
                "public_key": str(bundle["signed_prekey"]["public_key"]),
                "signature": str(bundle["signed_prekey"]["signature"]),
            },
            "prekeys": [
                {
                    "prekey_id": int(item["prekey_id"]),
                    "public_key": str(item["public_key"]),
                }
                for item in bundle.get("one_time_prekeys", [])
            ],
        }

    @classmethod
    def _requires_full_registration(cls, bundle: dict[str, Any], remote_device: dict[str, Any] | None) -> bool:
        if not remote_device:
            return True
        if not bool(remote_device.get("is_active", True)):
            return True
        return (
            str(remote_device.get("identity_key_public") or "").strip() != str(bundle.get("identity_key_public") or "").strip()
            or str(remote_device.get("signing_key_public") or "").strip() != str(bundle.get("signing_key_public") or "").strip()
        )

    @classmethod
    def _should_rotate_signed_prekey(cls, bundle: dict[str, Any]) -> bool:
        raw_created_at = str(bundle.get("signed_prekey_created_at") or "").strip()
        if not raw_created_at:
            return True
        try:
            created_at = datetime.fromisoformat(raw_created_at.replace("Z", "+00:00"))
        except ValueError:
            return True
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        return (_utcnow() - created_at) >= cls.SIGNED_PREKEY_ROTATION_INTERVAL

    def _rotate_signed_prekey_in_bundle(self, bundle: dict[str, Any]) -> dict[str, Any]:
        normalized_bundle = self._normalize_loaded_bundle(bundle)
        current_signed_prekey = dict(normalized_bundle.get("signed_prekey") or {})
        if current_signed_prekey:
            normalized_bundle.setdefault("retired_signed_prekeys", []).append(current_signed_prekey)

        x25519, ed25519, serialization = _load_crypto_primitives()
        signing_private = ed25519.Ed25519PrivateKey.from_private_bytes(
            b64decode(str(normalized_bundle.get("signing_key_private") or ""))
        )
        signed_prekey_private = x25519.X25519PrivateKey.generate()
        signed_prekey_public_bytes = _x25519_public_bytes(signed_prekey_private.public_key(), serialization)
        key_id = int(normalized_bundle.get("next_signed_prekey_id") or 1)
        normalized_bundle["signed_prekey"] = {
            "key_id": key_id,
            "private_key": _x25519_private_b64(signed_prekey_private, serialization),
            "public_key": b64encode(signed_prekey_public_bytes).decode("ascii"),
            "signature": b64encode(signing_private.sign(signed_prekey_public_bytes)).decode("ascii"),
        }
        normalized_bundle["signed_prekey_created_at"] = _utcnow().isoformat()
        normalized_bundle["next_signed_prekey_id"] = key_id + 1
        bundle.clear()
        bundle.update(normalized_bundle)
        return dict(bundle["signed_prekey"])

    def _append_one_time_prekeys(self, bundle: dict[str, Any], count: int) -> list[dict[str, Any]]:
        normalized_bundle = self._normalize_loaded_bundle(bundle)
        requested_count = max(0, int(count or 0))
        if requested_count <= 0:
            return []
        x25519, _, serialization = _load_crypto_primitives()
        next_prekey_id = int(normalized_bundle.get("next_prekey_id") or 1)
        generated: list[dict[str, Any]] = []
        for offset in range(requested_count):
            private_key = x25519.X25519PrivateKey.generate()
            item = {
                "prekey_id": next_prekey_id + offset,
                "private_key": _x25519_private_b64(private_key, serialization),
                "public_key": _x25519_public_b64(private_key.public_key(), serialization),
            }
            normalized_bundle.setdefault("one_time_prekeys", []).append(item)
            generated.append(item)
        normalized_bundle["next_prekey_id"] = next_prekey_id + requested_count
        bundle.clear()
        bundle.update(normalized_bundle)
        return [dict(item) for item in generated]

    async def _claim_or_fetch_bundle_for_device(
        self,
        recipient_user_id: str,
        recipient_device_id: str,
    ) -> dict[str, Any] | None:
        normalized_user_id = str(recipient_user_id or "").strip()
        normalized_device_id = str(recipient_device_id or "").strip()
        if not normalized_user_id or not normalized_device_id:
            return None

        bundles = await self.fetch_prekey_bundle(normalized_user_id)
        selected = None
        for bundle in bundles:
            if str(dict(bundle or {}).get("device_id") or "").strip() == normalized_device_id:
                selected = dict(bundle)
                break
        if selected is None:
            return None

        try:
            claimed = await self.claim_prekeys([normalized_device_id])
        except Exception as exc:
            logger.warning("Failed to claim recipient prekey for %s/%s: %s", normalized_user_id, normalized_device_id, exc)
            claimed = []

        for bundle in claimed:
            if str(dict(bundle or {}).get("device_id") or "").strip() == normalized_device_id:
                return dict(bundle)
        return selected

    async def _claim_or_fetch_recipient_bundle(self, recipient_user_id: str) -> dict[str, Any] | None:
        bundles = await self.fetch_prekey_bundle(recipient_user_id)
        if not bundles:
            return None

        selected = dict(bundles[0])
        selected_device_id = str(selected.get("device_id") or "").strip()
        if not selected_device_id:
            return selected
        claimed_bundle = await self._claim_or_fetch_bundle_for_device(recipient_user_id, selected_device_id)
        return claimed_bundle or selected

    def _verify_bundle_signature(self, bundle: dict[str, Any]) -> None:
        _, ed25519, _ = _load_crypto_primitives()
        signed_prekey = dict(bundle.get("signed_prekey") or {})
        signing_key_public = str(bundle.get("signing_key_public") or "").strip()
        signature = str(signed_prekey.get("signature") or "").strip()
        signed_prekey_public = str(signed_prekey.get("public_key") or "").strip()
        if not signing_key_public or not signature or not signed_prekey_public:
            raise RuntimeError("recipient bundle is missing signed prekey material")

        try:
            ed25519.Ed25519PublicKey.from_public_bytes(b64decode(signing_key_public)).verify(
                b64decode(signature),
                b64decode(signed_prekey_public),
            )
        except Exception as exc:
            raise RuntimeError("recipient signed prekey signature verification failed") from exc

    @staticmethod
    def _resolve_recipient_key_material(bundle: dict[str, Any]) -> dict[str, Any]:
        one_time_prekey = dict(bundle.get("one_time_prekey") or {})
        one_time_public = str(one_time_prekey.get("public_key") or "").strip()
        if one_time_public:
            return {
                "prekey_type": "one_time",
                "key_id": int(one_time_prekey.get("prekey_id") or 0),
                "public_key": one_time_public,
            }

        signed_prekey = dict(bundle.get("signed_prekey") or {})
        signed_public = str(signed_prekey.get("public_key") or "").strip()
        if not signed_public:
            raise RuntimeError("recipient bundle does not contain a usable prekey")
        return {
            "prekey_type": "signed",
            "key_id": int(signed_prekey.get("key_id") or 0),
            "public_key": signed_public,
        }

    async def _resolve_envelope_private_key(
        self,
        local_bundle: dict[str, Any],
        encryption: dict[str, Any],
    ) -> dict[str, Any] | None:
        recipient_device_id = str(encryption.get("recipient_device_id") or "").strip()
        local_device_id = str(local_bundle.get("device_id") or "").strip()
        if recipient_device_id and recipient_device_id != local_device_id:
            return await self._resolve_history_private_key(recipient_device_id, encryption)

        key_payload = self._resolve_local_private_key(local_bundle, encryption)
        if key_payload is not None:
            return key_payload
        if recipient_device_id and recipient_device_id != local_device_id:
            return await self._resolve_history_private_key(recipient_device_id, encryption)
        return None

    async def _resolve_history_private_key(
        self,
        recipient_device_id: str,
        encryption: dict[str, Any],
    ) -> dict[str, Any] | None:
        normalized_recipient_device_id = str(recipient_device_id or "").strip()
        if not normalized_recipient_device_id:
            return None
        state = await self._load_history_recovery_state()
        devices = dict(state.get("devices") or {})
        device_record = dict(devices.get(normalized_recipient_device_id) or {})
        if not device_record:
            return None

        prekey_type = str(encryption.get("recipient_prekey_type") or "").strip().lower()
        prekey_id = int(encryption.get("recipient_prekey_id") or 0)
        if prekey_type == "signed":
            payload = dict(dict(device_record.get("signed_prekeys") or {}).get(str(prekey_id)) or {})
            private_key = str(payload.get("private_key") or "").strip()
            if private_key:
                return {"private_key": private_key}
            return None
        if prekey_type == "one_time":
            payload = dict(dict(device_record.get("one_time_prekeys") or {}).get(str(prekey_id)) or {})
            private_key = str(payload.get("private_key") or "").strip()
            if private_key:
                return {"private_key": private_key}
        return None

    async def _find_history_group_sender_key_record(
        self,
        session_id: str,
        *,
        owner_device_id: str = "",
        sender_key_id: str = "",
    ) -> dict[str, Any] | None:
        normalized_session_id = str(session_id or "").strip()
        normalized_owner_device_id = str(owner_device_id or "").strip()
        normalized_sender_key_id = str(sender_key_id or "").strip()
        if not normalized_session_id:
            return None

        state = await self._load_history_recovery_state()
        devices = dict(state.get("devices") or {})
        candidate_records: list[dict[str, Any]] = [dict(record or {}) for record in devices.values()]

        for device_record in candidate_records:
            group_record = dict(dict(device_record.get("group_sessions") or {}).get(normalized_session_id) or {})
            if not group_record:
                continue
            sender_keys = dict(group_record.get("sender_keys") or {})
            if normalized_sender_key_id:
                sender_key = dict(sender_keys.get(normalized_sender_key_id) or {})
                if sender_key and (
                    not normalized_owner_device_id
                    or str(sender_key.get("owner_device_id") or "").strip() == normalized_owner_device_id
                ):
                    return sender_key
                continue
            for payload in sender_keys.values():
                sender_key = dict(payload or {})
                if not normalized_owner_device_id or str(sender_key.get("owner_device_id") or "").strip() == normalized_owner_device_id:
                    return sender_key
        return None

    @staticmethod
    def _resolve_local_private_key(local_bundle: dict[str, Any], encryption: dict[str, Any]) -> dict[str, Any] | None:
        prekey_type = str(encryption.get("recipient_prekey_type") or "").strip().lower()
        prekey_id = int(encryption.get("recipient_prekey_id") or 0)
        if prekey_type == "signed":
            candidate_signed_prekeys = [
                dict(local_bundle.get("signed_prekey") or {}),
                *[dict(item) for item in list(local_bundle.get("retired_signed_prekeys") or []) if isinstance(item, dict)],
            ]
            for signed_prekey in candidate_signed_prekeys:
                if int(signed_prekey.get("key_id") or 0) == prekey_id:
                    return {
                        "private_key": str(signed_prekey.get("private_key") or ""),
                    }
            return None

        if prekey_type == "one_time":
            for item in local_bundle.get("one_time_prekeys", []):
                if int(item.get("prekey_id") or 0) == prekey_id:
                    return {
                        "private_key": str(item.get("private_key") or ""),
                    }
        return None

    def _encrypt_payload(
        self,
        *,
        plaintext: str,
        sender_identity_private_b64: str,
        recipient_public_key_b64: str,
        sender_device_id: str,
        recipient_device_id: str,
    ) -> tuple[str, str]:
        key = self._derive_message_key(
            local_private_key_b64=sender_identity_private_b64,
            peer_public_key_b64=recipient_public_key_b64,
            sender_device_id=sender_device_id,
            recipient_device_id=recipient_device_id,
        )
        _, _, _, hashes, hkdf, aesgcm = _load_encryption_primitives()
        del hashes, hkdf
        nonce = urandom(12)
        aad = self._aad_bytes(sender_device_id=sender_device_id, recipient_device_id=recipient_device_id)
        ciphertext = aesgcm(key).encrypt(nonce, str(plaintext or "").encode("utf-8"), aad)
        return b64encode(ciphertext).decode("ascii"), b64encode(nonce).decode("ascii")

    def _decrypt_payload(
        self,
        *,
        ciphertext_b64: str,
        nonce_b64: str,
        sender_identity_public_b64: str,
        recipient_private_key_b64: str,
        sender_device_id: str,
        recipient_device_id: str,
    ) -> str:
        key = self._derive_message_key(
            local_private_key_b64=recipient_private_key_b64,
            peer_public_key_b64=sender_identity_public_b64,
            sender_device_id=sender_device_id,
            recipient_device_id=recipient_device_id,
        )
        _, _, _, hashes, hkdf, aesgcm = _load_encryption_primitives()
        del hashes, hkdf
        aad = self._aad_bytes(sender_device_id=sender_device_id, recipient_device_id=recipient_device_id)
        plaintext = aesgcm(key).decrypt(
            b64decode(nonce_b64),
            b64decode(ciphertext_b64),
            aad,
        )
        return plaintext.decode("utf-8")

    @staticmethod
    def _select_group_fanout_envelope(
        fanout: Any,
        *,
        local_device_id: str,
        session_id: str,
    ) -> dict[str, Any] | None:
        normalized_local_device_id = str(local_device_id or "").strip()
        normalized_session_id = str(session_id or "").strip()
        for item in list(fanout or []):
            if not isinstance(item, dict):
                continue
            if str(item.get("scheme") or "").strip() != E2EEService.GROUP_FANOUT_SCHEME:
                continue
            if normalized_session_id and str(item.get("session_id") or "").strip() != normalized_session_id:
                continue
            if str(item.get("recipient_device_id") or "").strip() != normalized_local_device_id:
                continue
            return dict(item)
        return None

    def _encrypt_group_sender_payload(
        self,
        *,
        plaintext: str,
        sender_key_b64: str,
        session_id: str,
        sender_device_id: str,
        sender_key_id: str,
    ) -> tuple[str, str]:
        _, _, _, _, _, aesgcm = _load_encryption_primitives()
        try:
            sender_key = b64decode(str(sender_key_b64 or "").strip())
        except Exception as exc:
            raise RuntimeError("group sender key is invalid") from exc
        nonce = urandom(12)
        aad = self._group_sender_key_aad_bytes(
            session_id=session_id,
            sender_device_id=sender_device_id,
            sender_key_id=sender_key_id,
        )
        ciphertext = aesgcm(sender_key).encrypt(nonce, str(plaintext or "").encode("utf-8"), aad)
        return b64encode(ciphertext).decode("ascii"), b64encode(nonce).decode("ascii")

    def _decrypt_group_sender_payload(
        self,
        *,
        ciphertext_b64: str,
        nonce_b64: str,
        sender_key_b64: str,
        session_id: str,
        sender_device_id: str,
        sender_key_id: str,
    ) -> str:
        _, _, _, _, _, aesgcm = _load_encryption_primitives()
        try:
            sender_key = b64decode(str(sender_key_b64 or "").strip())
        except Exception as exc:
            raise RuntimeError("group sender key is invalid") from exc
        aad = self._group_sender_key_aad_bytes(
            session_id=session_id,
            sender_device_id=sender_device_id,
            sender_key_id=sender_key_id,
        )
        plaintext = aesgcm(sender_key).decrypt(
            b64decode(nonce_b64),
            b64decode(ciphertext_b64),
            aad,
        )
        return plaintext.decode("utf-8")

    @staticmethod
    def _group_sender_key_aad_bytes(*, session_id: str, sender_device_id: str, sender_key_id: str) -> bytes:
        payload = {
            "scheme": E2EEService.GROUP_SENDER_KEY_SCHEME,
            "session_id": str(session_id or ""),
            "sender_device_id": str(sender_device_id or ""),
            "sender_key_id": str(sender_key_id or ""),
        }
        return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def _encrypt_group_attachment_metadata(
        self,
        *,
        metadata: str,
        sender_key_b64: str,
        session_id: str,
        sender_device_id: str,
        sender_key_id: str,
    ) -> tuple[str, str]:
        _, _, _, _, _, aesgcm = _load_encryption_primitives()
        try:
            sender_key = b64decode(str(sender_key_b64 or "").strip())
        except Exception as exc:
            raise RuntimeError("group sender key is invalid") from exc
        nonce = urandom(12)
        aad = self._group_attachment_metadata_aad_bytes(
            session_id=session_id,
            sender_device_id=sender_device_id,
            sender_key_id=sender_key_id,
        )
        ciphertext = aesgcm(sender_key).encrypt(nonce, str(metadata or "").encode("utf-8"), aad)
        return b64encode(ciphertext).decode("ascii"), b64encode(nonce).decode("ascii")

    def _decrypt_group_attachment_metadata_payload(
        self,
        *,
        ciphertext_b64: str,
        nonce_b64: str,
        sender_key_b64: str,
        session_id: str,
        sender_device_id: str,
        sender_key_id: str,
    ) -> str:
        _, _, _, _, _, aesgcm = _load_encryption_primitives()
        try:
            sender_key = b64decode(str(sender_key_b64 or "").strip())
        except Exception as exc:
            raise RuntimeError("group sender key is invalid") from exc
        aad = self._group_attachment_metadata_aad_bytes(
            session_id=session_id,
            sender_device_id=sender_device_id,
            sender_key_id=sender_key_id,
        )
        plaintext = aesgcm(sender_key).decrypt(
            b64decode(nonce_b64),
            b64decode(ciphertext_b64),
            aad,
        )
        return plaintext.decode("utf-8")

    @staticmethod
    def _group_attachment_metadata_aad_bytes(*, session_id: str, sender_device_id: str, sender_key_id: str) -> bytes:
        payload = {
            "scheme": E2EEService.GROUP_ATTACHMENT_SCHEME,
            "session_id": str(session_id or ""),
            "sender_device_id": str(sender_device_id or ""),
            "sender_key_id": str(sender_key_id or ""),
        }
        return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    def _derive_message_key(
        self,
        *,
        local_private_key_b64: str,
        peer_public_key_b64: str,
        sender_device_id: str,
        recipient_device_id: str,
    ) -> bytes:
        x25519, _, serialization = _load_crypto_primitives()
        _, _, _, hashes, hkdf, _ = _load_encryption_primitives()
        private_key = x25519.X25519PrivateKey.from_private_bytes(b64decode(local_private_key_b64))
        peer_public_key = x25519.X25519PublicKey.from_public_bytes(b64decode(peer_public_key_b64))
        shared_secret = private_key.exchange(peer_public_key)
        hkdf_context = hkdf(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"AssistIM:E2EE:x25519-aesgcm-v1",
            info=self._aad_bytes(sender_device_id=sender_device_id, recipient_device_id=recipient_device_id),
        )
        del serialization
        return hkdf_context.derive(shared_secret)

    @staticmethod
    def _aad_bytes(*, sender_device_id: str, recipient_device_id: str) -> bytes:
        payload = {
            "scheme": E2EEService.ENVELOPE_SCHEME,
            "sender_device_id": str(sender_device_id or ""),
            "recipient_device_id": str(recipient_device_id or ""),
        }
        return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")

    @staticmethod
    def _attachment_aad_bytes() -> bytes:
        return b"AssistIM:E2EE:attachment-file:v1"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _load_crypto_primitives():
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ed25519, x25519
    except Exception as exc:  # pragma: no cover - depends on local runtime setup
        raise RuntimeError("cryptography is required for E2EE device key generation") from exc
    return x25519, ed25519, serialization


def _load_encryption_primitives():
    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    except Exception as exc:  # pragma: no cover - depends on local runtime setup
        raise RuntimeError("cryptography is required for E2EE message encryption") from exc
    return _load_crypto_primitives() + (hashes, HKDF, AESGCM)


def _x25519_private_b64(private_key, serialization_module) -> str:
    return b64encode(
        private_key.private_bytes(
            encoding=serialization_module.Encoding.Raw,
            format=serialization_module.PrivateFormat.Raw,
            encryption_algorithm=serialization_module.NoEncryption(),
        )
    ).decode("ascii")


def _x25519_public_bytes(public_key, serialization_module) -> bytes:
    return public_key.public_bytes(
        encoding=serialization_module.Encoding.Raw,
        format=serialization_module.PublicFormat.Raw,
    )


def _x25519_public_b64(public_key, serialization_module) -> str:
    return b64encode(_x25519_public_bytes(public_key, serialization_module)).decode("ascii")


def _ed25519_private_bytes(private_key, serialization_module) -> bytes:
    return private_key.private_bytes(
        encoding=serialization_module.Encoding.Raw,
        format=serialization_module.PrivateFormat.Raw,
        encryption_algorithm=serialization_module.NoEncryption(),
    )


def _ed25519_public_b64(public_key, serialization_module) -> str:
    return b64encode(
        public_key.public_bytes(
            encoding=serialization_module.Encoding.Raw,
            format=serialization_module.PublicFormat.Raw,
        )
    ).decode("ascii")


_e2ee_service: Optional[E2EEService] = None


def get_e2ee_service() -> E2EEService:
    """Return the global E2EE service instance."""
    global _e2ee_service
    if _e2ee_service is None:
        _e2ee_service = E2EEService()
    return _e2ee_service










