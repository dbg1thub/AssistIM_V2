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
from app.services.admin_database_backup_service import AdminDatabaseBackupService
from app.services.admin_database_service import AdminDatabaseService
from app.services.admin_dashboard_service import AdminDashboardService
from app.services.admin_file_storage_service import AdminFileStorageService
from app.services.admin_log_service import AdminLogService
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
