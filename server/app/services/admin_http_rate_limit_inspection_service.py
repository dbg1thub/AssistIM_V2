"""Admin HTTP diagnostics and rate-limit inspection service."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.rate_limit import rate_limiter
from app.core.runtime_diagnostics import MAX_HTTP_RECORDS, runtime_diagnostics_snapshot
from app.models.user import User
from app.services.admin_audit_service import AdminAuditService


class AdminHttpRateLimitInspectionService:
    """Read-only HTTP request and rate-limit diagnostics for admin tooling."""

    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.audit = AdminAuditService(db)

    def list_http_requests(
        self,
        *,
        actor: User,
        method: str = "",
        path_contains: str = "",
        status_code: int | None = None,
        user_id: str = "",
        limit: int = 50,
        request_path: str = "",
        request_method: str = "",
        client_ip: str = "",
    ) -> dict[str, Any]:
        normalized_limit = self._limit(limit, max_limit=MAX_HTTP_RECORDS)
        normalized_method = str(method or "").strip().upper()
        normalized_path_contains = str(path_contains or "").strip()
        normalized_user_id = str(user_id or "").strip()
        normalized_status = int(status_code) if status_code is not None else None
        diagnostics = runtime_diagnostics_snapshot()["http"]
        records = [
            item
            for item in diagnostics["recent"]
            if self._matches_http_record(
                item,
                method=normalized_method,
                path_contains=normalized_path_contains,
                status_code=normalized_status,
                user_id=normalized_user_id,
            )
        ]
        payload = {
            "total": len(records),
            "limit": normalized_limit,
            "retention_limit": MAX_HTTP_RECORDS,
            "filters": {
                "method": normalized_method,
                "path_contains": normalized_path_contains,
                "status_code": normalized_status,
                "user_id": normalized_user_id,
            },
            "counters": {
                "total_requests": int(diagnostics.get("total_requests", 0) or 0),
                "error_requests": int(diagnostics.get("error_requests", 0) or 0),
                "slow_requests": int(diagnostics.get("slow_requests", 0) or 0),
            },
            "items": records[:normalized_limit],
        }
        self.audit.record(
            actor=actor,
            action="admin.http.requests.read",
            target_type="http_requests",
            target_id="list",
            request_path=request_path,
            request_method=request_method,
            client_ip=client_ip,
            success=True,
            detail={
                "method": normalized_method,
                "path_contains": normalized_path_contains,
                "status_code": normalized_status,
                "user_id": normalized_user_id,
                "limit": normalized_limit,
                "total": len(records),
            },
        )
        return payload

    def build_http_health(
        self,
        *,
        actor: User,
        request_path: str = "",
        request_method: str = "",
        client_ip: str = "",
    ) -> dict[str, Any]:
        diagnostics = runtime_diagnostics_snapshot()["http"]
        records = list(diagnostics["recent"])
        total_requests = int(diagnostics.get("total_requests", 0) or 0)
        error_requests = int(diagnostics.get("error_requests", 0) or 0)
        slow_requests = int(diagnostics.get("slow_requests", 0) or 0)
        server_error_records = [item for item in records if int(item.get("status_code", 0) or 0) >= 500]
        recent_error_requests = [item for item in records if int(item.get("status_code", 0) or 0) >= 400]
        slowest_requests = sorted(
            records,
            key=lambda item: float(item.get("duration_ms", 0.0) or 0.0),
            reverse=True,
        )[:20]
        issues = []
        if error_requests:
            issues.append(
                self._issue(
                    "http_error_responses_observed",
                    severity="warning",
                    count=error_requests,
                    total_requests=total_requests,
                )
            )
        if server_error_records:
            issues.append(
                self._issue(
                    "http_5xx_responses_observed",
                    severity="error",
                    count=len(server_error_records),
                )
            )
        if slow_requests:
            issues.append(
                self._issue(
                    "http_slow_requests_observed",
                    severity="warning",
                    count=slow_requests,
                    slow_request_ms=max(0, int(self.settings.admin_dashboard_slow_request_ms or 0)),
                )
            )
        payload = {
            "status": "ok" if not issues else "warning",
            "issue_count": len(issues),
            "issues": issues,
            "checks": {
                "total_requests": total_requests,
                "retained_requests": len(records),
                "error_requests": error_requests,
                "slow_requests": slow_requests,
                "server_error_requests": len(server_error_records),
                "slow_request_ms": max(0, int(self.settings.admin_dashboard_slow_request_ms or 0)),
                "retention_limit": MAX_HTTP_RECORDS,
            },
            "recent_error_requests": recent_error_requests[:20],
            "slowest_requests": slowest_requests,
        }
        self.audit.record(
            actor=actor,
            action="admin.http.health.read",
            target_type="http_health",
            target_id="health",
            request_path=request_path,
            request_method=request_method,
            client_ip=client_ip,
            success=True,
            detail={"status": payload["status"], "issue_count": len(issues)},
        )
        return payload

    def build_rate_limit_status(
        self,
        *,
        actor: User,
        key_prefix: str = "",
        limit: int = 100,
        request_path: str = "",
        request_method: str = "",
        client_ip: str = "",
    ) -> dict[str, Any]:
        normalized_limit = self._limit(limit, max_limit=500)
        normalized_key_prefix = str(key_prefix or "").strip()
        diagnostics = rate_limiter.diagnostics(settings=self.settings, bucket_limit=500)
        store = dict(diagnostics["store"])
        buckets = [
            item
            for item in list(store.pop("buckets", []))
            if not normalized_key_prefix or item.get("key_prefix") == normalized_key_prefix
        ]
        payload = {
            "backend": diagnostics["backend"],
            "limits": diagnostics["limits"],
            "filters": {
                "key_prefix": normalized_key_prefix,
                "limit": normalized_limit,
            },
            "store": store,
            "by_key_prefix": self._rate_limit_summary_by_prefix(buckets),
            "items": buckets[:normalized_limit],
        }
        self.audit.record(
            actor=actor,
            action="admin.rate_limits.status.read",
            target_type="rate_limits",
            target_id="status",
            request_path=request_path,
            request_method=request_method,
            client_ip=client_ip,
            success=True,
            detail={
                "key_prefix": normalized_key_prefix,
                "limit": normalized_limit,
                "bucket_count": int(store.get("bucket_count", 0) or 0),
            },
        )
        return payload

    def build_rate_limit_health(
        self,
        *,
        actor: User,
        max_bucket_count: int = 5000,
        max_stale_hit_count: int = 1000,
        request_path: str = "",
        request_method: str = "",
        client_ip: str = "",
    ) -> dict[str, Any]:
        normalized_max_bucket_count = max(0, int(max_bucket_count or 0))
        normalized_max_stale_hit_count = max(0, int(max_stale_hit_count or 0))
        diagnostics = rate_limiter.diagnostics(settings=self.settings, bucket_limit=100)
        store = diagnostics["store"]
        bucket_count = int(store.get("bucket_count", 0) or 0)
        active_hit_count = int(store.get("active_hit_count", 0) or 0)
        stale_hit_count = int(store.get("stale_hit_count", 0) or 0)
        issues = []
        if not bool(store.get("supported")):
            issues.append(
                self._issue(
                    "rate_limit_store_diagnostics_unsupported",
                    severity="warning",
                    store=diagnostics["backend"]["active_store"],
                )
            )
        if str(store.get("status") or "") == "error":
            issues.append(
                self._issue(
                    "rate_limit_store_diagnostics_error",
                    severity="error",
                    error=str(store.get("error") or ""),
                )
            )
        if bucket_count > normalized_max_bucket_count:
            issues.append(
                self._issue(
                    "rate_limit_bucket_count_exceeded",
                    severity="warning",
                    bucket_count=bucket_count,
                    max_bucket_count=normalized_max_bucket_count,
                )
            )
        if stale_hit_count > normalized_max_stale_hit_count:
            issues.append(
                self._issue(
                    "rate_limit_stale_hits_observed",
                    severity="warning",
                    stale_hit_count=stale_hit_count,
                    max_stale_hit_count=normalized_max_stale_hit_count,
                )
            )
        payload = {
            "status": "ok" if not issues else "warning",
            "issue_count": len(issues),
            "issues": issues,
            "checks": {
                "store_supported": bool(store.get("supported")),
                "store_status": str(store.get("status") or ""),
                "store_backend_configured": diagnostics["backend"]["configured"],
                "active_store": diagnostics["backend"]["active_store"],
                "bucket_count": bucket_count,
                "active_hit_count": active_hit_count,
                "stale_hit_count": stale_hit_count,
                "max_bucket_count": normalized_max_bucket_count,
                "max_stale_hit_count": normalized_max_stale_hit_count,
            },
        }
        self.audit.record(
            actor=actor,
            action="admin.rate_limits.health.read",
            target_type="rate_limits_health",
            target_id="health",
            request_path=request_path,
            request_method=request_method,
            client_ip=client_ip,
            success=True,
            detail={"status": payload["status"], "issue_count": len(issues)},
        )
        return payload

    def _matches_http_record(
        self,
        item: dict[str, Any],
        *,
        method: str,
        path_contains: str,
        status_code: int | None,
        user_id: str,
    ) -> bool:
        if method and str(item.get("method") or "").upper() != method:
            return False
        if path_contains and path_contains not in str(item.get("path") or ""):
            return False
        if status_code is not None and int(item.get("status_code", 0) or 0) != status_code:
            return False
        if user_id and str(item.get("user_id") or "") != user_id:
            return False
        return True

    def _rate_limit_summary_by_prefix(self, buckets: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
        summary: dict[str, dict[str, int]] = defaultdict(
            lambda: {
                "bucket_count": 0,
                "hit_count": 0,
                "active_hit_count": 0,
                "stale_hit_count": 0,
            }
        )
        for bucket in buckets:
            key_prefix = str(bucket.get("key_prefix") or "unknown")
            summary[key_prefix]["bucket_count"] += 1
            summary[key_prefix]["hit_count"] += int(bucket.get("hit_count", 0) or 0)
            summary[key_prefix]["active_hit_count"] += int(bucket.get("active_hit_count", 0) or 0)
            summary[key_prefix]["stale_hit_count"] += int(bucket.get("stale_hit_count", 0) or 0)
        return dict(sorted(summary.items()))

    def _limit(self, value: int, *, max_limit: int) -> int:
        return min(max_limit, max(1, int(value or 1)))

    def _issue(self, issue_type: str, *, severity: str, **extra: Any) -> dict[str, Any]:
        payload = {"issue_type": issue_type, "severity": severity}
        payload.update(extra)
        return payload
