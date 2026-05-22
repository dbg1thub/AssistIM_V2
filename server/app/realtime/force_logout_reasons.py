"""Formal force-logout control reasons shared by realtime senders."""

from __future__ import annotations

from app.websocket.payloads import ws_message


FORCE_LOGOUT_REASON_SESSION_REPLACED = "session_replaced"
FORCE_LOGOUT_REASON_LOGOUT = "logout"
FORCE_LOGOUT_REASON_PASSWORD_RESET = "password_reset"
FORCE_LOGOUT_REASON_ADMIN_DISABLE_USER = "admin_disable_user"
FORCE_LOGOUT_REASON_ADMIN_FORCE_LOGOUT = "admin_force_logout"

FORMAL_FORCE_LOGOUT_REASONS = {
    FORCE_LOGOUT_REASON_SESSION_REPLACED,
    FORCE_LOGOUT_REASON_LOGOUT,
    FORCE_LOGOUT_REASON_PASSWORD_RESET,
    FORCE_LOGOUT_REASON_ADMIN_DISABLE_USER,
    FORCE_LOGOUT_REASON_ADMIN_FORCE_LOGOUT,
}


def force_logout_payload(reason: str) -> dict:
    """Build one formal realtime force-logout payload."""
    normalized_reason = str(reason or "").strip()
    if normalized_reason not in FORMAL_FORCE_LOGOUT_REASONS:
        raise ValueError(f"unsupported force_logout reason: {normalized_reason}")
    return ws_message("force_logout", {"reason": normalized_reason})
