"""Settings dependencies."""

from __future__ import annotations

from typing import Any

from fastapi import Request, WebSocket

from app.core.config import Settings, get_settings


def _resolve_settings_from_app(app: Any) -> Settings:
    settings = getattr(getattr(app, "state", None), "settings", None)
    if isinstance(settings, Settings):
        return settings
    return get_settings()


def get_request_settings(request: Request) -> Settings:
    """Return the current app settings snapshot for one HTTP request."""
    return _resolve_settings_from_app(request.app)


def get_websocket_settings(websocket: WebSocket) -> Settings:
    """Return the current app settings snapshot for one websocket connection."""
    return _resolve_settings_from_app(websocket.app)
