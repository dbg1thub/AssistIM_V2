"""Admin realtime and call inspection service."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.session import ChatSession, SessionMember
from app.models.user import User
from app.realtime.call_registry import ACTIVE_CALL_STATUSES, get_call_registry
from app.services.admin_audit_service import AdminAuditService
from app.websocket.manager import connection_manager


class AdminRealtimeCallInspectionService:
    """Read-only runtime diagnostics for websocket connections and active calls."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.audit = AdminAuditService(db)

    def list_realtime_connections(
        self,
        *,
        actor: User,
        user_id: str = "",
        request_path: str = "",
        request_method: str = "",
        client_ip: str = "",
    ) -> dict[str, Any]:
        normalized_user_id = str(user_id or "").strip()
        diagnostics = connection_manager.connection_diagnostics()
        connections = [
            item
            for item in diagnostics["connections"]
            if item.get("bound") and (not normalized_user_id or item.get("user_id") == normalized_user_id)
        ]
        user_ids = sorted({str(item.get("user_id") or "") for item in connections if str(item.get("user_id") or "")})
        users_by_id = self._users_by_id(user_ids)
        items = []
        for current_user_id in user_ids:
            user_connections = [
                item for item in connections if str(item.get("user_id") or "") == current_user_id
            ]
            items.append(
                {
                    "user_id": current_user_id,
                    "user": self._serialize_user_summary(users_by_id.get(current_user_id), fallback_id=current_user_id),
                    "connection_count": len(user_connections),
                    "connections": sorted(user_connections, key=lambda item: str(item.get("connection_id") or "")),
                }
            )

        payload = {
            "snapshot": diagnostics["snapshot"],
            "total_users": len(items),
            "total_connections": len(connections),
            "items": items,
        }
        self.audit.record(
            actor=actor,
            action="admin.realtime.connections.read",
            target_type="realtime_connections",
            target_id="list",
            request_path=request_path,
            request_method=request_method,
            client_ip=client_ip,
            success=True,
            detail={
                "user_id": normalized_user_id,
                "total_users": len(items),
                "total_connections": len(connections),
            },
        )
        return payload

    def build_realtime_health(
        self,
        *,
        actor: User,
        request_path: str = "",
        request_method: str = "",
        client_ip: str = "",
    ) -> dict[str, Any]:
        diagnostics = connection_manager.connection_diagnostics()
        connections = diagnostics["connections"]
        user_ids = [str(item.get("user_id") or "") for item in connections if str(item.get("user_id") or "")]
        users_by_id = self._users_by_id(user_ids)
        issues = self._realtime_issues(connections=connections, users_by_id=users_by_id)
        payload = {
            "status": "ok" if not issues else "warning",
            "issue_count": len(issues),
            "issues": issues,
            "checks": {
                "raw_connections": int(diagnostics["snapshot"].get("raw_connections", 0) or 0),
                "bound_connections": int(diagnostics["snapshot"].get("bound_connections", 0) or 0),
                "online_users": int(diagnostics["snapshot"].get("online_users", 0) or 0),
            },
        }
        self.audit.record(
            actor=actor,
            action="admin.realtime.health.read",
            target_type="realtime_health",
            target_id="health",
            request_path=request_path,
            request_method=request_method,
            client_ip=client_ip,
            success=True,
            detail={"status": payload["status"], "issue_count": len(issues)},
        )
        return payload

    def list_active_calls(
        self,
        *,
        actor: User,
        user_id: str = "",
        request_path: str = "",
        request_method: str = "",
        client_ip: str = "",
    ) -> dict[str, Any]:
        normalized_user_id = str(user_id or "").strip()
        diagnostics = get_call_registry().diagnostics()
        calls = [
            call
            for call in diagnostics["calls"]
            if str(call.get("status") or "") in ACTIVE_CALL_STATUSES
            and (
                not normalized_user_id
                or normalized_user_id in {str(call.get("initiator_id") or ""), str(call.get("recipient_id") or "")}
            )
        ]
        context = self._call_context(calls)
        payload = {
            "snapshot": diagnostics["snapshot"],
            "total": len(calls),
            "items": [self._serialize_call(call, context=context) for call in calls],
        }
        self.audit.record(
            actor=actor,
            action="admin.calls.active.read",
            target_type="active_calls",
            target_id="list",
            request_path=request_path,
            request_method=request_method,
            client_ip=client_ip,
            success=True,
            detail={"user_id": normalized_user_id, "total": len(calls)},
        )
        return payload

    def build_calls_health(
        self,
        *,
        actor: User,
        request_path: str = "",
        request_method: str = "",
        client_ip: str = "",
    ) -> dict[str, Any]:
        diagnostics = get_call_registry().diagnostics()
        calls = list(diagnostics["calls"])
        context = self._call_context(calls)
        issues = self._call_issues(
            calls=calls,
            context=context,
            user_call_mappings=diagnostics["user_call_mappings"],
        )
        payload = {
            "status": "ok" if not issues else "warning",
            "issue_count": len(issues),
            "issues": issues,
            "checks": {
                "active_calls": int(diagnostics["snapshot"].get("active", 0) or 0),
                "runtime_call_records": len(calls),
                "user_call_mappings": len(diagnostics["user_call_mappings"]),
            },
        }
        self.audit.record(
            actor=actor,
            action="admin.calls.health.read",
            target_type="calls_health",
            target_id="health",
            request_path=request_path,
            request_method=request_method,
            client_ip=client_ip,
            success=True,
            detail={"status": payload["status"], "issue_count": len(issues)},
        )
        return payload

    def _realtime_issues(
        self,
        *,
        connections: list[dict[str, Any]],
        users_by_id: dict[str, User],
    ) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        for connection in connections:
            connection_id = str(connection.get("connection_id") or "")
            user_id = str(connection.get("user_id") or "")
            if connection.get("has_socket") and not connection.get("bound"):
                issues.append(
                    self._issue(
                        "realtime_raw_connection_unbound",
                        severity="warning",
                        connection_id=connection_id,
                    )
                )
            if connection.get("bound") and not connection.get("has_socket"):
                issues.append(
                    self._issue(
                        "realtime_bound_connection_missing_socket",
                        severity="warning",
                        connection_id=connection_id,
                        user_id=user_id,
                    )
                )
            if user_id and user_id not in users_by_id:
                issues.append(
                    self._issue(
                        "realtime_connection_user_missing",
                        severity="error",
                        connection_id=connection_id,
                        user_id=user_id,
                    )
                )
        return sorted(issues, key=self._issue_sort_key)

    def _call_issues(
        self,
        *,
        calls: list[dict[str, Any]],
        context: dict[str, Any],
        user_call_mappings: dict[str, str],
    ) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        call_ids = {str(call.get("call_id") or "") for call in calls}
        for call in calls:
            call_id = str(call.get("call_id") or "")
            session_id = str(call.get("session_id") or "")
            status = str(call.get("status") or "")
            session = context["sessions_by_id"].get(session_id)
            member_ids = context["session_member_ids_by_session"].get(session_id, set())
            if status not in ACTIVE_CALL_STATUSES:
                issues.append(self._issue("call_status_invalid", severity="error", call_id=call_id, status=status))
            if session is None:
                issues.append(
                    self._issue(
                        "call_session_missing",
                        severity="error",
                        call_id=call_id,
                        session_id=session_id,
                    )
                )
            else:
                if str(session.type or "") != "private":
                    issues.append(
                        self._issue(
                            "call_session_type_invalid",
                            severity="error",
                            call_id=call_id,
                            session_id=session_id,
                            actual_type=str(session.type or ""),
                        )
                    )
                if bool(session.is_ai_session):
                    issues.append(
                        self._issue(
                            "call_session_ai_unsupported",
                            severity="error",
                            call_id=call_id,
                            session_id=session_id,
                        )
                    )

            for role, participant_id in (
                ("initiator", str(call.get("initiator_id") or "")),
                ("recipient", str(call.get("recipient_id") or "")),
            ):
                if participant_id not in context["users_by_id"]:
                    issues.append(
                        self._issue(
                            "call_participant_user_missing",
                            severity="error",
                            call_id=call_id,
                            role=role,
                            user_id=participant_id,
                        )
                    )
                if session is not None and participant_id not in member_ids:
                    issues.append(
                        self._issue(
                            "call_participant_not_session_member",
                            severity="warning",
                            call_id=call_id,
                            session_id=session_id,
                            role=role,
                            user_id=participant_id,
                        )
                    )
                mapped_call_id = str(user_call_mappings.get(participant_id) or "")
                if status in ACTIVE_CALL_STATUSES and not mapped_call_id:
                    issues.append(
                        self._issue(
                            "call_user_mapping_missing",
                            severity="warning",
                            call_id=call_id,
                            role=role,
                            user_id=participant_id,
                        )
                    )
                elif status in ACTIVE_CALL_STATUSES and mapped_call_id != call_id:
                    issues.append(
                        self._issue(
                            "call_user_mapping_mismatch",
                            severity="warning",
                            call_id=call_id,
                            mapped_call_id=mapped_call_id,
                            role=role,
                            user_id=participant_id,
                        )
                    )

        for mapped_user_id, mapped_call_id in sorted(user_call_mappings.items()):
            if mapped_call_id not in call_ids:
                issues.append(
                    self._issue(
                        "call_user_mapping_orphan",
                        severity="warning",
                        call_id=mapped_call_id,
                        user_id=mapped_user_id,
                    )
                )
        return sorted(issues, key=self._issue_sort_key)

    def _serialize_call(self, call: dict[str, Any], *, context: dict[str, Any]) -> dict[str, Any]:
        session_id = str(call.get("session_id") or "")
        initiator_id = str(call.get("initiator_id") or "")
        recipient_id = str(call.get("recipient_id") or "")
        participants = [
            self._serialize_call_participant("initiator", initiator_id, context=context),
            self._serialize_call_participant("recipient", recipient_id, context=context),
        ]
        return {
            "call_id": str(call.get("call_id") or ""),
            "session_id": session_id,
            "session": self._serialize_session(context["sessions_by_id"].get(session_id), fallback_id=session_id),
            "initiator_id": initiator_id,
            "initiator": self._serialize_user_summary(context["users_by_id"].get(initiator_id), fallback_id=initiator_id),
            "recipient_id": recipient_id,
            "recipient": self._serialize_user_summary(context["users_by_id"].get(recipient_id), fallback_id=recipient_id),
            "participants": participants,
            "media_type": str(call.get("media_type") or ""),
            "status": str(call.get("status") or ""),
            "created_at": call.get("created_at"),
            "answered_at": call.get("answered_at"),
            "ended_at": call.get("ended_at"),
            "ended_by": str(call.get("ended_by") or ""),
            "reason": str(call.get("reason") or ""),
        }

    def _serialize_call_participant(self, role: str, user_id: str, *, context: dict[str, Any]) -> dict[str, Any]:
        return {
            "role": role,
            "user_id": user_id,
            "user": self._serialize_user_summary(context["users_by_id"].get(user_id), fallback_id=user_id),
            "online": bool(connection_manager.has_user_connections(user_id)),
        }

    def _serialize_session(self, session: ChatSession | None, *, fallback_id: str = "") -> dict[str, Any]:
        if session is None:
            return {"id": str(fallback_id or ""), "exists": False}
        return {
            "id": str(session.id or ""),
            "exists": True,
            "type": str(session.type or ""),
            "name": str(session.name or ""),
            "is_ai_session": bool(session.is_ai_session),
            "encryption_mode": str(session.encryption_mode or ""),
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

    def _call_context(self, calls: list[dict[str, Any]]) -> dict[str, Any]:
        user_ids = [
            user_id
            for call in calls
            for user_id in (str(call.get("initiator_id") or ""), str(call.get("recipient_id") or ""))
        ]
        session_ids = [str(call.get("session_id") or "") for call in calls]
        sessions_by_id = self._sessions_by_id(session_ids)
        return {
            "users_by_id": self._users_by_id(user_ids),
            "sessions_by_id": sessions_by_id,
            "session_member_ids_by_session": self._session_member_ids_by_session(list(sessions_by_id)),
        }

    def _users_by_id(self, user_ids: list[str]) -> dict[str, User]:
        normalized_ids = self._valid_uuid_ids(user_ids)
        if not normalized_ids:
            return {}
        users = self.db.execute(select(User).where(User.id.in_(normalized_ids))).scalars().all()
        return {str(user.id or ""): user for user in users}

    def _sessions_by_id(self, session_ids: list[str]) -> dict[str, ChatSession]:
        normalized_ids = self._valid_uuid_ids(session_ids)
        if not normalized_ids:
            return {}
        sessions = self.db.execute(select(ChatSession).where(ChatSession.id.in_(normalized_ids))).scalars().all()
        return {str(session.id or ""): session for session in sessions}

    def _session_member_ids_by_session(self, session_ids: list[str]) -> dict[str, set[str]]:
        normalized_ids = self._valid_uuid_ids(session_ids)
        if not normalized_ids:
            return {}
        rows = self.db.execute(select(SessionMember).where(SessionMember.session_id.in_(normalized_ids))).scalars().all()
        result: dict[str, set[str]] = {session_id: set() for session_id in normalized_ids}
        for member in rows:
            result.setdefault(str(member.session_id or ""), set()).add(str(member.user_id or ""))
        return result

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
            str(issue.get("call_id") or ""),
            str(issue.get("connection_id") or ""),
            str(issue.get("user_id") or ""),
        )
