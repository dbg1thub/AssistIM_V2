"""Admin E2EE device and key inventory inspection service."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any
from uuid import UUID

from sqlalchemy import case, false, func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.device import UserDevice, UserPreKey, UserSignedPreKey
from app.models.user import User
from app.services.admin_audit_service import AdminAuditService
from app.utils.time import isoformat_utc


DEFAULT_MIN_AVAILABLE_PREKEYS = 5


class AdminE2EEInspectionService:
    """Read-only E2EE device and key inventory queries for admin tooling."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.audit = AdminAuditService(db)

    def list_devices(
        self,
        *,
        actor: User,
        user_id: str = "",
        active: bool | None = None,
        page: int = 1,
        size: int = 20,
        request_path: str = "",
        request_method: str = "",
        client_ip: str = "",
    ) -> dict[str, Any]:
        normalized_page, normalized_size = self._pagination(page, size)
        normalized_user_id = str(user_id or "").strip()
        statement = select(UserDevice)
        if normalized_user_id:
            statement = (
                statement.where(UserDevice.user_id == normalized_user_id)
                if self._is_uuid(normalized_user_id)
                else statement.where(false())
            )
        if active is not None:
            statement = statement.where(UserDevice.is_active.is_(bool(active)))

        total = self._count(statement)
        devices = list(
            self.db.execute(
                statement.order_by(UserDevice.created_at.desc(), UserDevice.device_id.asc())
                .offset((normalized_page - 1) * normalized_size)
                .limit(normalized_size)
            )
            .scalars()
            .all()
        )
        context = self._device_context(devices)
        payload = {
            "total": total,
            "page": normalized_page,
            "size": normalized_size,
            "items": [self._serialize_device(device, context=context) for device in devices],
        }
        self.audit.record(
            actor=actor,
            action="admin.e2ee.devices.read",
            target_type="e2ee_devices",
            target_id="list",
            request_path=request_path,
            request_method=request_method,
            client_ip=client_ip,
            success=True,
            detail={
                "user_id": normalized_user_id,
                "active": active,
                "page": normalized_page,
                "size": normalized_size,
                "total": total,
            },
        )
        return payload

    def get_device(
        self,
        device_id: str,
        *,
        actor: User,
        request_path: str = "",
        request_method: str = "",
        client_ip: str = "",
    ) -> dict[str, Any]:
        device = self._get_device_or_404(device_id)
        payload = self._serialize_device(device, context=self._device_context([device]))
        self.audit.record(
            actor=actor,
            action="admin.e2ee.device.read",
            target_type="e2ee_device",
            target_id=str(device.device_id or ""),
            request_path=request_path,
            request_method=request_method,
            client_ip=client_ip,
            success=True,
            detail={"device_id": str(device.device_id or "")},
        )
        return payload

    def list_prekeys(
        self,
        *,
        actor: User,
        device_id: str = "",
        user_id: str = "",
        consumed: bool | None = None,
        page: int = 1,
        size: int = 20,
        request_path: str = "",
        request_method: str = "",
        client_ip: str = "",
    ) -> dict[str, Any]:
        normalized_page, normalized_size = self._pagination(page, size, max_size=200)
        normalized_device_id = str(device_id or "").strip()
        normalized_user_id = str(user_id or "").strip()
        statement = select(UserPreKey)
        if normalized_device_id:
            statement = statement.where(UserPreKey.device_id == normalized_device_id)
        if consumed is not None:
            statement = statement.where(UserPreKey.is_consumed.is_(bool(consumed)))
        if normalized_user_id:
            device_ids = self._device_ids_for_user(normalized_user_id) if self._is_uuid(normalized_user_id) else []
            statement = statement.where(UserPreKey.device_id.in_(device_ids)) if device_ids else statement.where(false())

        total = self._count(statement)
        prekeys = list(
            self.db.execute(
                statement.order_by(UserPreKey.created_at.desc(), UserPreKey.id.asc())
                .offset((normalized_page - 1) * normalized_size)
                .limit(normalized_size)
            )
            .scalars()
            .all()
        )
        devices_by_id = self._devices_by_id([str(prekey.device_id or "") for prekey in prekeys])
        users_by_id = self._users_by_id([str(device.user_id or "") for device in devices_by_id.values()])
        payload = {
            "total": total,
            "page": normalized_page,
            "size": normalized_size,
            "items": [
                self._serialize_prekey(prekey, devices_by_id=devices_by_id, users_by_id=users_by_id)
                for prekey in prekeys
            ],
        }
        self.audit.record(
            actor=actor,
            action="admin.e2ee.prekeys.read",
            target_type="e2ee_prekeys",
            target_id="list",
            request_path=request_path,
            request_method=request_method,
            client_ip=client_ip,
            success=True,
            detail={
                "device_id": normalized_device_id,
                "user_id": normalized_user_id,
                "consumed": consumed,
                "page": normalized_page,
                "size": normalized_size,
                "total": total,
            },
        )
        return payload

    def build_health(
        self,
        *,
        actor: User,
        min_available_prekeys: int = DEFAULT_MIN_AVAILABLE_PREKEYS,
        request_path: str = "",
        request_method: str = "",
        client_ip: str = "",
    ) -> dict[str, Any]:
        devices = list(self.db.execute(select(UserDevice)).scalars().all())
        signed_prekeys = list(self.db.execute(select(UserSignedPreKey)).scalars().all())
        prekeys = list(self.db.execute(select(UserPreKey)).scalars().all())
        users = list(self.db.execute(select(User)).scalars().all())
        users_by_id = {str(user.id or ""): user for user in users}
        devices_by_id = {str(device.device_id or ""): device for device in devices}
        signed_stats = self._signed_prekey_stats_by_device_id(signed_prekeys)
        prekey_stats = self._prekey_stats_by_device_id(prekeys)
        normalized_min = max(0, int(min_available_prekeys or 0))
        issues = self._health_issues(
            users=users,
            devices=devices,
            signed_prekeys=signed_prekeys,
            prekeys=prekeys,
            users_by_id=users_by_id,
            devices_by_id=devices_by_id,
            signed_stats=signed_stats,
            prekey_stats=prekey_stats,
            min_available_prekeys=normalized_min,
        )
        payload = {
            "status": "ok" if not issues else "warning",
            "issue_count": len(issues),
            "issues": issues,
            "checks": {
                "users": len(users),
                "devices": len(devices),
                "active_devices": sum(1 for device in devices if bool(device.is_active)),
                "signed_prekeys": len(signed_prekeys),
                "one_time_prekeys": len(prekeys),
                "min_available_prekeys": normalized_min,
            },
        }
        self.audit.record(
            actor=actor,
            action="admin.e2ee.health.read",
            target_type="e2ee_health",
            target_id="health",
            request_path=request_path,
            request_method=request_method,
            client_ip=client_ip,
            success=True,
            detail={"status": payload["status"], "issue_count": len(issues), "min_available_prekeys": normalized_min},
        )
        return payload

    def _health_issues(
        self,
        *,
        users: list[User],
        devices: list[UserDevice],
        signed_prekeys: list[UserSignedPreKey],
        prekeys: list[UserPreKey],
        users_by_id: dict[str, User],
        devices_by_id: dict[str, UserDevice],
        signed_stats: dict[str, dict[str, int]],
        prekey_stats: dict[str, dict[str, int]],
        min_available_prekeys: int,
    ) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        active_devices_by_user_id: dict[str, list[UserDevice]] = defaultdict(list)
        for device in devices:
            device_id = str(device.device_id or "")
            user_id = str(device.user_id or "")
            if bool(device.is_active):
                active_devices_by_user_id[user_id].append(device)
            if user_id not in users_by_id:
                issues.append(
                    self._issue(
                        "e2ee_device_user_missing",
                        severity="error",
                        device_id=device_id,
                        user_id=user_id,
                    )
                )
            if bool(device.is_active):
                active_signed_count = signed_stats.get(device_id, {}).get("active", 0)
                available_prekeys = prekey_stats.get(device_id, {}).get("available", 0)
                if active_signed_count == 0:
                    issues.append(
                        self._issue(
                            "e2ee_active_device_missing_active_signed_prekey",
                            severity="error",
                            device_id=device_id,
                            user_id=user_id,
                        )
                    )
                elif active_signed_count > 1:
                    issues.append(
                        self._issue(
                            "e2ee_device_duplicate_active_signed_prekeys",
                            severity="warning",
                            device_id=device_id,
                            user_id=user_id,
                            active_signed_prekeys=active_signed_count,
                        )
                    )
                if available_prekeys < min_available_prekeys:
                    issues.append(
                        self._issue(
                            "e2ee_active_device_low_available_prekeys",
                            severity="warning",
                            device_id=device_id,
                            user_id=user_id,
                            available_prekeys=available_prekeys,
                            min_available_prekeys=min_available_prekeys,
                        )
                    )

        for user in users:
            if bool(getattr(user, "is_disabled", False)):
                continue
            user_id = str(user.id or "")
            if not active_devices_by_user_id.get(user_id):
                issues.append(
                    self._issue(
                        "e2ee_active_user_without_active_device",
                        severity="warning",
                        user_id=user_id,
                        username=str(user.username or ""),
                    )
                )

        for prekey in prekeys:
            device_id = str(prekey.device_id or "")
            if device_id not in devices_by_id:
                issues.append(
                    self._issue(
                        "e2ee_prekey_device_missing",
                        severity="error",
                        prekey_id=int(prekey.prekey_id or 0),
                        device_id=device_id,
                    )
                )

        for signed_prekey in signed_prekeys:
            device_id = str(signed_prekey.device_id or "")
            if device_id not in devices_by_id:
                issues.append(
                    self._issue(
                        "e2ee_signed_prekey_device_missing",
                        severity="error",
                        signed_prekey_id=str(signed_prekey.id or ""),
                        device_id=device_id,
                    )
                )

        return sorted(issues, key=self._issue_sort_key)

    def _serialize_device(self, device: UserDevice, *, context: dict[str, Any]) -> dict[str, Any]:
        device_id = str(device.device_id or "")
        user_id = str(device.user_id or "")
        return {
            "device_id": device_id,
            "user_id": user_id,
            "user": self._serialize_user_summary(context["users_by_id"].get(user_id), fallback_id=user_id),
            "device_name": str(device.device_name or ""),
            "is_active": bool(device.is_active),
            "last_seen_at": isoformat_utc(device.last_seen_at),
            "created_at": isoformat_utc(device.created_at),
            "updated_at": isoformat_utc(device.updated_at),
            "key_material": {
                "identity_key_public_present": bool(str(device.identity_key_public or "")),
                "signing_key_public_present": bool(str(device.signing_key_public or "")),
            },
            "signed_prekeys": context["signed_stats"].get(device_id, {"total": 0, "active": 0}),
            "one_time_prekeys": context["prekey_stats"].get(
                device_id,
                {"total": 0, "available": 0, "consumed": 0},
            ),
        }

    def _serialize_prekey(
        self,
        prekey: UserPreKey,
        *,
        devices_by_id: dict[str, UserDevice],
        users_by_id: dict[str, User],
    ) -> dict[str, Any]:
        device_id = str(prekey.device_id or "")
        device = devices_by_id.get(device_id)
        user = users_by_id.get(str(device.user_id or "")) if device is not None else None
        return {
            "id": str(prekey.id or ""),
            "device_id": device_id,
            "prekey_id": int(prekey.prekey_id or 0),
            "is_consumed": bool(prekey.is_consumed),
            "created_at": isoformat_utc(prekey.created_at),
            "claimed_at": isoformat_utc(prekey.claimed_at),
            "device": self._serialize_device_reference(device, user=user, fallback_id=device_id),
        }

    def _serialize_device_reference(
        self,
        device: UserDevice | None,
        *,
        user: User | None,
        fallback_id: str = "",
    ) -> dict[str, Any]:
        if device is None:
            return {"device_id": str(fallback_id or ""), "exists": False}
        user_id = str(device.user_id or "")
        return {
            "device_id": str(device.device_id or ""),
            "exists": True,
            "user_id": user_id,
            "user": self._serialize_user_summary(user, fallback_id=user_id),
            "device_name": str(device.device_name or ""),
            "is_active": bool(device.is_active),
        }

    def _serialize_user_summary(self, user: User | None, *, fallback_id: str = "") -> dict[str, Any]:
        if user is None:
            return {"id": str(fallback_id or ""), "exists": False}
        return {
            "id": str(user.id or ""),
            "username": str(user.username or ""),
            "nickname": str(user.nickname or ""),
            "avatar": user.avatar,
            "is_disabled": bool(user.is_disabled),
            "exists": True,
        }

    def _device_context(self, devices: list[UserDevice]) -> dict[str, Any]:
        device_ids = [str(device.device_id or "") for device in devices]
        return {
            "users_by_id": self._users_by_id([str(device.user_id or "") for device in devices]),
            "signed_stats": self._signed_prekey_stats(device_ids),
            "prekey_stats": self._prekey_stats(device_ids),
        }

    def _signed_prekey_stats(self, device_ids: list[str]) -> dict[str, dict[str, int]]:
        normalized_ids = self._valid_device_ids(device_ids)
        if not normalized_ids:
            return {}
        rows = self.db.execute(
            select(
                UserSignedPreKey.device_id,
                func.count(UserSignedPreKey.id),
                func.sum(case((UserSignedPreKey.is_active.is_(True), 1), else_=0)),
            )
            .where(UserSignedPreKey.device_id.in_(normalized_ids))
            .group_by(UserSignedPreKey.device_id)
        ).all()
        return {
            str(device_id or ""): {"total": int(total or 0), "active": int(active or 0)}
            for device_id, total, active in rows
        }

    def _prekey_stats(self, device_ids: list[str]) -> dict[str, dict[str, int]]:
        normalized_ids = self._valid_device_ids(device_ids)
        if not normalized_ids:
            return {}
        rows = self.db.execute(
            select(
                UserPreKey.device_id,
                func.count(UserPreKey.id),
                func.sum(case((UserPreKey.is_consumed.is_(True), 1), else_=0)),
            )
            .where(UserPreKey.device_id.in_(normalized_ids))
            .group_by(UserPreKey.device_id)
        ).all()
        result: dict[str, dict[str, int]] = {}
        for device_id, total, consumed in rows:
            normalized_device_id = str(device_id or "")
            normalized_total = int(total or 0)
            normalized_consumed = int(consumed or 0)
            result[normalized_device_id] = {
                "total": normalized_total,
                "available": max(0, normalized_total - normalized_consumed),
                "consumed": normalized_consumed,
            }
        return result

    def _signed_prekey_stats_by_device_id(self, signed_prekeys: list[UserSignedPreKey]) -> dict[str, dict[str, int]]:
        totals = Counter(str(item.device_id or "") for item in signed_prekeys)
        active = Counter(str(item.device_id or "") for item in signed_prekeys if bool(item.is_active))
        return {
            device_id: {"total": int(totals[device_id]), "active": int(active[device_id])}
            for device_id in totals
        }

    def _prekey_stats_by_device_id(self, prekeys: list[UserPreKey]) -> dict[str, dict[str, int]]:
        totals = Counter(str(item.device_id or "") for item in prekeys)
        consumed = Counter(str(item.device_id or "") for item in prekeys if bool(item.is_consumed))
        return {
            device_id: {
                "total": int(totals[device_id]),
                "available": max(0, int(totals[device_id]) - int(consumed[device_id])),
                "consumed": int(consumed[device_id]),
            }
            for device_id in totals
        }

    def _users_by_id(self, user_ids: list[str]) -> dict[str, User]:
        normalized_ids = self._valid_uuid_ids(user_ids)
        if not normalized_ids:
            return {}
        rows = self.db.execute(select(User).where(User.id.in_(normalized_ids))).scalars().all()
        return {str(row.id or ""): row for row in rows}

    def _devices_by_id(self, device_ids: list[str]) -> dict[str, UserDevice]:
        normalized_ids = self._valid_device_ids(device_ids)
        if not normalized_ids:
            return {}
        rows = self.db.execute(select(UserDevice).where(UserDevice.device_id.in_(normalized_ids))).scalars().all()
        return {str(row.device_id or ""): row for row in rows}

    def _device_ids_for_user(self, user_id: str) -> list[str]:
        rows = self.db.execute(
            select(UserDevice.device_id).where(UserDevice.user_id == str(user_id or "").strip())
        ).scalars().all()
        return [str(row or "") for row in rows if str(row or "")]

    def _get_device_or_404(self, device_id: str) -> UserDevice:
        normalized_id = str(device_id or "").strip()
        device = self.db.get(UserDevice, normalized_id) if normalized_id else None
        if device is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "device not found", 404)
        return device

    def _count(self, statement) -> int:
        return int(self.db.execute(select(func.count()).select_from(statement.order_by(None).subquery())).scalar_one() or 0)

    def _pagination(self, page: int, size: int, *, max_size: int = 100) -> tuple[int, int]:
        return max(1, int(page or 1)), min(max_size, max(1, int(size or 20)))

    def _valid_device_ids(self, values: list[str]) -> list[str]:
        return sorted({value for value in (str(item or "").strip() for item in values) if value})

    def _valid_uuid_ids(self, values: list[str]) -> list[str]:
        return sorted({value for value in (str(item or "").strip() for item in values) if self._is_uuid(value)})

    def _is_uuid(self, value: str) -> bool:
        try:
            UUID(str(value or ""))
        except ValueError:
            return False
        return True

    def _issue(self, issue_type: str, *, severity: str, **extra: Any) -> dict[str, Any]:
        payload = {"issue_type": issue_type, "severity": severity}
        payload.update(extra)
        return payload

    def _issue_sort_key(self, issue: dict[str, Any]) -> tuple[str, str, str, str]:
        return (
            str(issue.get("issue_type") or ""),
            str(issue.get("device_id") or ""),
            str(issue.get("user_id") or ""),
            str(issue.get("prekey_id") or issue.get("signed_prekey_id") or ""),
        )
