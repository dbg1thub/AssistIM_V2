"""Development admin diagnostics routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import get_db
from app.core.errors import AppError, ErrorCode
from app.dependencies.admin_dependency import get_current_admin_user, normalize_user_role
from app.dependencies.settings_dependency import get_request_settings
from app.models.user import User
from app.services.admin_audit_service import AdminAuditService
from app.services.admin_dashboard_service import AdminDashboardService
from app.utils.response import success_response


router = APIRouter()


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
    client_ip = request.client.host if request.client else ""
    AdminAuditService(db).record(
        actor=current_user,
        action="admin.dashboard.read",
        target_type="admin_dashboard",
        target_id="dashboard",
        request_path=str(request.url.path),
        request_method=request.method,
        client_ip=client_ip,
        success=True,
        detail={"sections": sorted(snapshot.keys())},
    )
    return success_response(snapshot)
