"""Auth Service Module.

HTTP-facing auth service that centralizes authentication requests and token state.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from client.network.http_client import get_http_client


class AuthService:
    """Encapsulate auth-related HTTP operations and token state access."""

    def __init__(self) -> None:
        self._http = get_http_client()

    @property
    def access_token(self) -> Optional[str]:
        """Return the current access token."""
        return self._http.access_token

    @property
    def refresh_token(self) -> Optional[str]:
        """Return the current refresh token."""
        return self._http.refresh_token

    def add_token_listener(self, listener: Callable[[Optional[str], Optional[str]], None]) -> None:
        """Subscribe to token updates."""
        self._http.add_token_listener(listener)

    def remove_token_listener(self, listener: Callable[[Optional[str], Optional[str]], None]) -> None:
        """Unsubscribe from token updates."""
        self._http.remove_token_listener(listener)

    def set_tokens(self, access_token: Optional[str], refresh_token: Optional[str] = None) -> None:
        """Update in-memory auth tokens."""
        self._http.set_tokens(access_token, refresh_token)

    def clear_tokens(self) -> None:
        """Clear in-memory auth tokens."""
        self._http.clear_tokens()

    async def fetch_current_user(self) -> dict[str, Any]:
        """Fetch the current authenticated user."""
        payload = await self._http.get("/auth/me")
        return dict(payload or {})

    async def login(self, username: str, password: str, *, force: bool = False) -> dict[str, Any]:
        """Authenticate one user and return the auth payload."""
        payload = await self._http.post(
            "/auth/login",
            json={
                "username": username,
                "password": password,
                "force": force,
            },
        )
        return dict(payload or {})

    async def register(self, username: str, nickname: str, password: str) -> dict[str, Any]:
        """Register one user and return the auth payload."""
        payload = await self._http.post(
            "/auth/register",
            json={
                "username": username,
                "password": password,
                "nickname": nickname,
            },
        )
        return dict(payload or {})

    async def logout(self) -> None:
        """Best-effort backend logout."""
        await self._http.delete("/auth/session")


_auth_service: Optional[AuthService] = None


def get_auth_service() -> AuthService:
    """Get the global auth service instance."""
    global _auth_service
    if _auth_service is None:
        _auth_service = AuthService()
    return _auth_service
