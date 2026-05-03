"""Development admin diagnostics routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import get_db
from app.core.errors import AppError, ErrorCode
from app.dependencies.admin_dependency import get_current_admin_user, normalize_user_role
from app.dependencies.settings_dependency import get_request_settings
from app.models.user import User
from app.schemas.admin import AdminDatabaseBackupPruneRequest, AdminDisableUserRequest, AdminSetUserRoleRequest
from app.services.admin_audit_service import AdminAuditService
from app.services.admin_chat_inspection_service import AdminChatInspectionService
from app.services.admin_contacts_inspection_service import AdminContactsInspectionService
from app.services.admin_database_backup_service import AdminDatabaseBackupService
from app.services.admin_database_service import AdminDatabaseService
from app.services.admin_dashboard_service import AdminDashboardService
from app.services.admin_e2ee_inspection_service import AdminE2EEInspectionService
from app.services.admin_file_storage_service import AdminFileStorageService
from app.services.admin_groups_inspection_service import AdminGroupsInspectionService
from app.services.admin_http_rate_limit_inspection_service import AdminHttpRateLimitInspectionService
from app.services.admin_log_service import AdminLogService
from app.services.admin_moments_inspection_service import AdminMomentsInspectionService
from app.services.admin_realtime_call_inspection_service import AdminRealtimeCallInspectionService
from app.services.admin_user_service import AdminUserService
from app.utils.response import success_response
from app.websocket.manager import connection_manager
from app.websocket.payloads import ws_message


router = APIRouter()


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


@router.get("/dashboard")
def get_admin_dashboard(
    request: Request,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_request_settings),
) -> dict:
    """Return one backend-only development diagnostics snapshot."""
    if not settings.admin_dashboard_enabled:
        raise AppError(ErrorCode.FORBIDDEN, "admin dashboard is disabled", 403)

    started_at = getattr(request.app.state, "started_at", None)
    snapshot = AdminDashboardService(db, settings, started_at=started_at).build()
    snapshot["actor"] = {
        "user_id": str(current_user.id or ""),
        "username": str(current_user.username or ""),
        "role": normalize_user_role(getattr(current_user, "role", "user")),
    }
    AdminAuditService(db).record(
        actor=current_user,
        action="admin.dashboard.read",
        target_type="admin_dashboard",
        target_id="dashboard",
        request_path=str(request.url.path),
        request_method=request.method,
        client_ip=_client_ip(request),
        success=True,
        detail={"sections": sorted(snapshot.keys())},
    )
    return success_response(snapshot)


@router.get("/audit-logs")
def list_admin_audit_logs(
    actor_username: str = "",
    action: str = "",
    target_type: str = "",
    target_id: str = "",
    success: bool | None = None,
    created_from: str = "",
    created_to: str = "",
    page: int = 1,
    size: int = 20,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
) -> dict:
    """List admin operation audit logs."""
    _ = current_user
    payload = AdminAuditService(db).list_logs(
        actor_username=actor_username,
        action=action,
        target_type=target_type,
        target_id=target_id,
        success=success,
        created_from=created_from,
        created_to=created_to,
        page=page,
        size=size,
    )
    return success_response(payload)


@router.get("/audit-logs/{log_id}")
def get_admin_audit_log(
    log_id: str,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return one admin operation audit log."""
    _ = current_user
    return success_response(AdminAuditService(db).get_log(log_id))


@router.get("/database/status")
def get_admin_database_status(
    request: Request,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_request_settings),
) -> dict:
    """Return a read-only database runtime status snapshot."""
    AdminAuditService(db).record(
        actor=current_user,
        action="admin.database.status.read",
        target_type="database",
        target_id="status",
        request_path=str(request.url.path),
        request_method=request.method,
        client_ip=_client_ip(request),
        success=True,
        commit=False,
    )
    payload = AdminDatabaseService(db, settings).build_status()
    db.commit()
    return success_response(payload)


@router.get("/database/tables")
def get_admin_database_tables(
    request: Request,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_request_settings),
) -> dict:
    """Return read-only table and index inspection data."""
    AdminAuditService(db).record(
        actor=current_user,
        action="admin.database.tables.read",
        target_type="database",
        target_id="tables",
        request_path=str(request.url.path),
        request_method=request.method,
        client_ip=_client_ip(request),
        success=True,
        commit=False,
    )
    payload = AdminDatabaseService(db, settings).build_tables()
    db.commit()
    return success_response(payload)


@router.get("/database/health")
def get_admin_database_health(
    request: Request,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_request_settings),
) -> dict:
    """Return read-only database health checks."""
    AdminAuditService(db).record(
        actor=current_user,
        action="admin.database.health.read",
        target_type="database",
        target_id="health",
        request_path=str(request.url.path),
        request_method=request.method,
        client_ip=_client_ip(request),
        success=True,
        commit=False,
    )
    payload = AdminDatabaseService(db, settings).build_health()
    db.commit()
    return success_response(payload)


@router.get("/logs/files")
def list_admin_log_files(
    request: Request,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_request_settings),
) -> dict:
    """List server-controlled log files."""
    payload = AdminLogService(db, settings).list_files(
        actor=current_user,
        request_path=str(request.url.path),
        request_method=request.method,
        client_ip=_client_ip(request),
    )
    return success_response(payload)


@router.get("/files/storage/status")
def get_admin_file_storage_status(
    request: Request,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_request_settings),
) -> dict:
    """Return a read-only local file storage consistency summary."""
    payload = AdminFileStorageService(db, settings).build_status(
        actor=current_user,
        request_path=str(request.url.path),
        request_method=request.method,
        client_ip=_client_ip(request),
    )
    return success_response(payload)


@router.get("/files/storage/issues")
def list_admin_file_storage_issues(
    request: Request,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_request_settings),
) -> dict:
    """Return local file records or disk objects that need admin attention."""
    payload = AdminFileStorageService(db, settings).list_issues(
        actor=current_user,
        request_path=str(request.url.path),
        request_method=request.method,
        client_ip=_client_ip(request),
    )
    return success_response(payload)


@router.get("/chat/sessions")
def list_admin_chat_sessions(
    request: Request,
    type: str = "",
    keyword: str = "",
    user_id: str = "",
    page: int = 1,
    size: int = 20,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
) -> dict:
    """List chat sessions for backend admin tooling."""
    payload = AdminChatInspectionService(db).list_sessions(
        actor=current_user,
        session_type=type,
        keyword=keyword,
        user_id=user_id,
        page=page,
        size=size,
        request_path=str(request.url.path),
        request_method=request.method,
        client_ip=_client_ip(request),
    )
    return success_response(payload)


@router.get("/chat/health")
def get_admin_chat_health(
    request: Request,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return read-only chat data consistency checks."""
    payload = AdminChatInspectionService(db).build_health(
        actor=current_user,
        request_path=str(request.url.path),
        request_method=request.method,
        client_ip=_client_ip(request),
    )
    return success_response(payload)


@router.get("/chat/sessions/{session_id}/messages")
def list_admin_chat_messages(
    session_id: str,
    request: Request,
    type: str = "",
    page: int = 1,
    size: int = 50,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
) -> dict:
    """List messages in one chat session for backend admin tooling."""
    payload = AdminChatInspectionService(db).list_messages(
        session_id,
        actor=current_user,
        message_type=type,
        page=page,
        size=size,
        request_path=str(request.url.path),
        request_method=request.method,
        client_ip=_client_ip(request),
    )
    return success_response(payload)


@router.get("/chat/sessions/{session_id}")
def get_admin_chat_session(
    session_id: str,
    request: Request,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return one chat session detail for backend admin tooling."""
    payload = AdminChatInspectionService(db).get_session(
        session_id,
        actor=current_user,
        request_path=str(request.url.path),
        request_method=request.method,
        client_ip=_client_ip(request),
    )
    return success_response(payload)


@router.get("/contacts/friend-requests")
def list_admin_contact_friend_requests(
    request: Request,
    status: str = "",
    sender_id: str = "",
    receiver_id: str = "",
    page: int = 1,
    size: int = 20,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
) -> dict:
    """List friend requests for backend admin tooling."""
    payload = AdminContactsInspectionService(db).list_friend_requests(
        actor=current_user,
        status=status,
        sender_id=sender_id,
        receiver_id=receiver_id,
        page=page,
        size=size,
        request_path=str(request.url.path),
        request_method=request.method,
        client_ip=_client_ip(request),
    )
    return success_response(payload)


@router.get("/contacts/friendships")
def list_admin_contact_friendships(
    request: Request,
    user_id: str = "",
    friend_id: str = "",
    page: int = 1,
    size: int = 20,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
) -> dict:
    """List friendship rows for backend admin tooling."""
    payload = AdminContactsInspectionService(db).list_friendships(
        actor=current_user,
        user_id=user_id,
        friend_id=friend_id,
        page=page,
        size=size,
        request_path=str(request.url.path),
        request_method=request.method,
        client_ip=_client_ip(request),
    )
    return success_response(payload)


@router.get("/contacts/health")
def get_admin_contacts_health(
    request: Request,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return read-only contacts data consistency checks."""
    payload = AdminContactsInspectionService(db).build_health(
        actor=current_user,
        request_path=str(request.url.path),
        request_method=request.method,
        client_ip=_client_ip(request),
    )
    return success_response(payload)


@router.get("/groups")
def list_admin_groups(
    request: Request,
    keyword: str = "",
    owner_id: str = "",
    page: int = 1,
    size: int = 20,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
) -> dict:
    """List groups for backend admin tooling."""
    payload = AdminGroupsInspectionService(db).list_groups(
        actor=current_user,
        keyword=keyword,
        owner_id=owner_id,
        page=page,
        size=size,
        request_path=str(request.url.path),
        request_method=request.method,
        client_ip=_client_ip(request),
    )
    return success_response(payload)


@router.get("/groups/health")
def get_admin_groups_health(
    request: Request,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return read-only group data consistency checks."""
    payload = AdminGroupsInspectionService(db).build_health(
        actor=current_user,
        request_path=str(request.url.path),
        request_method=request.method,
        client_ip=_client_ip(request),
    )
    return success_response(payload)


@router.get("/groups/{group_id}/members")
def list_admin_group_members(
    group_id: str,
    request: Request,
    role: str = "",
    user_id: str = "",
    page: int = 1,
    size: int = 20,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
) -> dict:
    """List group members for backend admin tooling."""
    payload = AdminGroupsInspectionService(db).list_members(
        group_id,
        actor=current_user,
        role=role,
        user_id=user_id,
        page=page,
        size=size,
        request_path=str(request.url.path),
        request_method=request.method,
        client_ip=_client_ip(request),
    )
    return success_response(payload)


@router.get("/groups/{group_id}")
def get_admin_group(
    group_id: str,
    request: Request,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return one group detail for backend admin tooling."""
    payload = AdminGroupsInspectionService(db).get_group(
        group_id,
        actor=current_user,
        request_path=str(request.url.path),
        request_method=request.method,
        client_ip=_client_ip(request),
    )
    return success_response(payload)


@router.get("/moments")
def list_admin_moments(
    request: Request,
    keyword: str = "",
    user_id: str = "",
    page: int = 1,
    size: int = 20,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
) -> dict:
    """List moments for backend admin tooling."""
    payload = AdminMomentsInspectionService(db).list_moments(
        actor=current_user,
        keyword=keyword,
        user_id=user_id,
        page=page,
        size=size,
        request_path=str(request.url.path),
        request_method=request.method,
        client_ip=_client_ip(request),
    )
    return success_response(payload)


@router.get("/moments/health")
def get_admin_moments_health(
    request: Request,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return read-only moments data consistency checks."""
    payload = AdminMomentsInspectionService(db).build_health(
        actor=current_user,
        request_path=str(request.url.path),
        request_method=request.method,
        client_ip=_client_ip(request),
    )
    return success_response(payload)


@router.get("/moments/{moment_id}/comments")
def list_admin_moment_comments(
    moment_id: str,
    request: Request,
    user_id: str = "",
    page: int = 1,
    size: int = 20,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
) -> dict:
    """List comments on one moment for backend admin tooling."""
    payload = AdminMomentsInspectionService(db).list_comments(
        moment_id,
        actor=current_user,
        user_id=user_id,
        page=page,
        size=size,
        request_path=str(request.url.path),
        request_method=request.method,
        client_ip=_client_ip(request),
    )
    return success_response(payload)


@router.get("/moments/{moment_id}/likes")
def list_admin_moment_likes(
    moment_id: str,
    request: Request,
    user_id: str = "",
    page: int = 1,
    size: int = 20,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
) -> dict:
    """List likes on one moment for backend admin tooling."""
    payload = AdminMomentsInspectionService(db).list_likes(
        moment_id,
        actor=current_user,
        user_id=user_id,
        page=page,
        size=size,
        request_path=str(request.url.path),
        request_method=request.method,
        client_ip=_client_ip(request),
    )
    return success_response(payload)


@router.get("/moments/{moment_id}")
def get_admin_moment(
    moment_id: str,
    request: Request,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return one moment detail for backend admin tooling."""
    payload = AdminMomentsInspectionService(db).get_moment(
        moment_id,
        actor=current_user,
        request_path=str(request.url.path),
        request_method=request.method,
        client_ip=_client_ip(request),
    )
    return success_response(payload)


@router.get("/realtime/connections")
def list_admin_realtime_connections(
    request: Request,
    user_id: str = "",
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
) -> dict:
    """List currently bound realtime websocket connections."""
    payload = AdminRealtimeCallInspectionService(db).list_realtime_connections(
        actor=current_user,
        user_id=user_id,
        request_path=str(request.url.path),
        request_method=request.method,
        client_ip=_client_ip(request),
    )
    return success_response(payload)


@router.get("/realtime/health")
def get_admin_realtime_health(
    request: Request,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return read-only realtime connection integrity checks."""
    payload = AdminRealtimeCallInspectionService(db).build_realtime_health(
        actor=current_user,
        request_path=str(request.url.path),
        request_method=request.method,
        client_ip=_client_ip(request),
    )
    return success_response(payload)


@router.get("/calls/active")
def list_admin_active_calls(
    request: Request,
    user_id: str = "",
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
) -> dict:
    """List active in-memory calls for backend admin tooling."""
    payload = AdminRealtimeCallInspectionService(db).list_active_calls(
        actor=current_user,
        user_id=user_id,
        request_path=str(request.url.path),
        request_method=request.method,
        client_ip=_client_ip(request),
    )
    return success_response(payload)


@router.get("/calls/health")
def get_admin_calls_health(
    request: Request,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return read-only active call registry integrity checks."""
    payload = AdminRealtimeCallInspectionService(db).build_calls_health(
        actor=current_user,
        request_path=str(request.url.path),
        request_method=request.method,
        client_ip=_client_ip(request),
    )
    return success_response(payload)


@router.get("/http/requests")
def list_admin_http_requests(
    request: Request,
    method: str = "",
    path_contains: str = "",
    status_code: int | None = None,
    user_id: str = "",
    limit: int = 50,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_request_settings),
) -> dict:
    """List recent in-process HTTP request diagnostics."""
    payload = AdminHttpRateLimitInspectionService(db, settings).list_http_requests(
        actor=current_user,
        method=method,
        path_contains=path_contains,
        status_code=status_code,
        user_id=user_id,
        limit=limit,
        request_path=str(request.url.path),
        request_method=request.method,
        client_ip=_client_ip(request),
    )
    return success_response(payload)


@router.get("/http/health")
def get_admin_http_health(
    request: Request,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_request_settings),
) -> dict:
    """Return read-only HTTP request diagnostics health checks."""
    payload = AdminHttpRateLimitInspectionService(db, settings).build_http_health(
        actor=current_user,
        request_path=str(request.url.path),
        request_method=request.method,
        client_ip=_client_ip(request),
    )
    return success_response(payload)


@router.get("/rate-limits/status")
def get_admin_rate_limit_status(
    request: Request,
    key_prefix: str = "",
    limit: int = 100,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_request_settings),
) -> dict:
    """Return read-only rate-limit store status."""
    payload = AdminHttpRateLimitInspectionService(db, settings).build_rate_limit_status(
        actor=current_user,
        key_prefix=key_prefix,
        limit=limit,
        request_path=str(request.url.path),
        request_method=request.method,
        client_ip=_client_ip(request),
    )
    return success_response(payload)


@router.get("/rate-limits/health")
def get_admin_rate_limit_health(
    request: Request,
    max_bucket_count: int = 5000,
    max_stale_hit_count: int = 1000,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_request_settings),
) -> dict:
    """Return read-only rate-limit store health checks."""
    payload = AdminHttpRateLimitInspectionService(db, settings).build_rate_limit_health(
        actor=current_user,
        max_bucket_count=max_bucket_count,
        max_stale_hit_count=max_stale_hit_count,
        request_path=str(request.url.path),
        request_method=request.method,
        client_ip=_client_ip(request),
    )
    return success_response(payload)


@router.get("/e2ee/devices")
def list_admin_e2ee_devices(
    request: Request,
    user_id: str = "",
    active: bool | None = None,
    page: int = 1,
    size: int = 20,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
) -> dict:
    """List E2EE devices without exposing key material."""
    payload = AdminE2EEInspectionService(db).list_devices(
        actor=current_user,
        user_id=user_id,
        active=active,
        page=page,
        size=size,
        request_path=str(request.url.path),
        request_method=request.method,
        client_ip=_client_ip(request),
    )
    return success_response(payload)


@router.get("/e2ee/health")
def get_admin_e2ee_health(
    request: Request,
    min_available_prekeys: int = 5,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return read-only E2EE device and key inventory checks."""
    payload = AdminE2EEInspectionService(db).build_health(
        actor=current_user,
        min_available_prekeys=min_available_prekeys,
        request_path=str(request.url.path),
        request_method=request.method,
        client_ip=_client_ip(request),
    )
    return success_response(payload)


@router.get("/e2ee/prekeys")
def list_admin_e2ee_prekeys(
    request: Request,
    device_id: str = "",
    user_id: str = "",
    consumed: bool | None = None,
    page: int = 1,
    size: int = 20,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
) -> dict:
    """List one-time prekey inventory without exposing public keys."""
    payload = AdminE2EEInspectionService(db).list_prekeys(
        actor=current_user,
        device_id=device_id,
        user_id=user_id,
        consumed=consumed,
        page=page,
        size=size,
        request_path=str(request.url.path),
        request_method=request.method,
        client_ip=_client_ip(request),
    )
    return success_response(payload)


@router.get("/e2ee/devices/{device_id}")
def get_admin_e2ee_device(
    device_id: str,
    request: Request,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return one E2EE device inventory detail without key material."""
    payload = AdminE2EEInspectionService(db).get_device(
        device_id,
        actor=current_user,
        request_path=str(request.url.path),
        request_method=request.method,
        client_ip=_client_ip(request),
    )
    return success_response(payload)


@router.get("/logs")
def query_admin_logs(
    request: Request,
    file_name: str = "",
    level: str = "",
    keyword: str = "",
    created_from: str = "",
    created_to: str = "",
    limit: int = 100,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_request_settings),
) -> dict:
    """Query server-controlled log files."""
    payload = AdminLogService(db, settings).query_logs(
        actor=current_user,
        file_name=file_name,
        level=level,
        keyword=keyword,
        created_from=created_from,
        created_to=created_to,
        limit=limit,
        request_path=str(request.url.path),
        request_method=request.method,
        client_ip=_client_ip(request),
    )
    return success_response(payload)


@router.get("/logs/files/{file_name}/download")
def download_admin_log_file(
    file_name: str,
    request: Request,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_request_settings),
) -> Response:
    """Download one sanitized server log file."""
    payload = AdminLogService(db, settings).download_file(
        file_name,
        actor=current_user,
        request_path=str(request.url.path),
        request_method=request.method,
        client_ip=_client_ip(request),
    )
    return Response(
        content=payload["content"],
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{payload["file_name"]}"'},
    )


@router.post("/database/backups")
def create_admin_database_backup(
    request: Request,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_request_settings),
) -> dict:
    """Create one server-local database backup."""
    payload = AdminDatabaseBackupService(db, settings).create_backup(
        actor=current_user,
        request_path=str(request.url.path),
        request_method=request.method,
        client_ip=_client_ip(request),
    )
    return success_response(payload)


@router.get("/database/backups")
def list_admin_database_backups(
    page: int = 1,
    size: int = 20,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_request_settings),
) -> dict:
    """List server-local database backup records."""
    _ = current_user
    return success_response(AdminDatabaseBackupService(db, settings).list_backups(page=page, size=size))


@router.post("/database/backups/prune")
def prune_admin_database_backups(
    payload: AdminDatabaseBackupPruneRequest,
    request: Request,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_request_settings),
) -> dict:
    """Prune server-local database backups by retention criteria."""
    result = AdminDatabaseBackupService(db, settings).prune_backups(
        keep_last=payload.keep_last,
        older_than_days=payload.older_than_days,
        include_failed=payload.include_failed,
        include_deleted=payload.include_deleted,
        dry_run=payload.dry_run,
        actor=current_user,
        request_path=str(request.url.path),
        request_method=request.method,
        client_ip=_client_ip(request),
    )
    return success_response(result)


@router.get("/database/backups/{backup_id}/download")
def download_admin_database_backup(
    backup_id: str,
    request: Request,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_request_settings),
) -> FileResponse:
    """Download one completed server-local database backup."""
    payload = AdminDatabaseBackupService(db, settings).prepare_download(
        backup_id,
        actor=current_user,
        request_path=str(request.url.path),
        request_method=request.method,
        client_ip=_client_ip(request),
    )
    return FileResponse(
        path=payload["path"],
        filename=payload["file_name"],
        media_type=payload["media_type"],
    )


@router.post("/database/backups/{backup_id}/verify")
def verify_admin_database_backup(
    backup_id: str,
    request: Request,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_request_settings),
) -> dict:
    """Verify one completed server-local database backup without restoring it."""
    payload = AdminDatabaseBackupService(db, settings).verify_backup(
        backup_id,
        actor=current_user,
        request_path=str(request.url.path),
        request_method=request.method,
        client_ip=_client_ip(request),
    )
    return success_response(payload)


@router.delete("/database/backups/{backup_id}")
def delete_admin_database_backup(
    backup_id: str,
    request: Request,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_request_settings),
) -> dict:
    """Delete one server-local database backup file and mark its record deleted."""
    payload = AdminDatabaseBackupService(db, settings).delete_backup(
        backup_id,
        actor=current_user,
        request_path=str(request.url.path),
        request_method=request.method,
        client_ip=_client_ip(request),
    )
    return success_response(payload)


@router.get("/database/backups/{backup_id}")
def get_admin_database_backup(
    backup_id: str,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_request_settings),
) -> dict:
    """Return one server-local database backup record."""
    _ = current_user
    return success_response(AdminDatabaseBackupService(db, settings).get_backup(backup_id))


@router.get("/users")
def list_admin_users(
    keyword: str = "",
    role: str = "",
    disabled: bool | None = None,
    page: int = 1,
    size: int = 20,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
) -> dict:
    """List users for backend admin tooling."""
    _ = current_user
    payload = AdminUserService(db).list_users(
        keyword=keyword,
        role=role,
        disabled=disabled,
        page=page,
        size=size,
    )
    return success_response(payload)


@router.get("/users/{user_id}")
def get_admin_user_detail(
    user_id: str,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return a safe admin detail view for one user."""
    _ = current_user
    return success_response(AdminUserService(db).get_user_detail(user_id))


@router.patch("/users/{user_id}/role")
def set_admin_user_role(
    user_id: str,
    payload: AdminSetUserRoleRequest,
    request: Request,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
) -> dict:
    service = AdminUserService(db)
    result = service.set_user_role_by_id(
        user_id,
        payload.role,
        actor=current_user,
        request_path=str(request.url.path),
        request_method=request.method,
        client_ip=_client_ip(request),
    )
    return success_response(result)


@router.post("/users/{user_id}/disable")
async def disable_admin_user(
    user_id: str,
    payload: AdminDisableUserRequest,
    request: Request,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
) -> dict:
    service = AdminUserService(db)
    result = service.disable_user(
        user_id,
        actor=current_user,
        reason=payload.reason,
        request_path=str(request.url.path),
        request_method=request.method,
        client_ip=_client_ip(request),
    )
    await connection_manager.disconnect_user_connections(
        user_id,
        close_code=4001,
        reason="admin_disable_user",
        payload=ws_message("force_logout", {"reason": "admin_disable_user"}),
    )
    return success_response(result)


@router.post("/users/{user_id}/enable")
def enable_admin_user(
    user_id: str,
    request: Request,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
) -> dict:
    service = AdminUserService(db)
    result = service.enable_user(
        user_id,
        actor=current_user,
        request_path=str(request.url.path),
        request_method=request.method,
        client_ip=_client_ip(request),
    )
    return success_response(result)


@router.post("/users/{user_id}/force-logout")
async def force_logout_admin_user(
    user_id: str,
    request: Request,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
) -> dict:
    service = AdminUserService(db)
    result = service.force_logout_user(
        user_id,
        actor=current_user,
        request_path=str(request.url.path),
        request_method=request.method,
        client_ip=_client_ip(request),
    )
    disconnected = await connection_manager.disconnect_user_connections(
        user_id,
        close_code=4001,
        reason="admin_force_logout",
        payload=ws_message("force_logout", {"reason": "admin_force_logout"}),
    )
    result["disconnected"] = bool(disconnected)
    return success_response(result)
