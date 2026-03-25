"""Realtime hub abstraction and in-memory implementation."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from collections import defaultdict

from fastapi import WebSocket, WebSocketDisconnect


class RealtimeHub(ABC):
    """Abstract connection/presence/fanout boundary."""

    @abstractmethod
    async def connect(self, websocket: WebSocket) -> str:
        """Accept one websocket and return its connection id."""

    @abstractmethod
    def bind_user(self, connection_id: str, user_id: str) -> None:
        """Bind one connection to one authenticated user."""

    @abstractmethod
    def get_user_id(self, connection_id: str) -> str | None:
        """Return the bound user id for one connection."""

    @abstractmethod
    def online_user_ids(self) -> list[str]:
        """Return all currently online user ids."""

    @abstractmethod
    def has_user_connections(self, user_id: str) -> bool:
        """Return whether one user still has any active connection."""

    @abstractmethod
    async def disconnect(self, websocket: WebSocket) -> tuple[str | None, bool]:
        """Drop one websocket and report offline transition."""

    @abstractmethod
    def disconnect_by_connection_id(self, connection_id: str) -> tuple[str | None, bool]:
        """Drop one connection by id and report offline transition."""

    @abstractmethod
    async def send_json(self, connection_id: str, payload: dict) -> bool:
        """Send one payload to one connection."""

    @abstractmethod
    async def send_json_to_users(
        self,
        user_ids: list[str],
        payload: dict,
        exclude_connection_id: str | None = None,
    ) -> set[str]:
        """Fan out one payload to all active connections of the target users."""

    @abstractmethod
    async def broadcast_json(self, payload: dict, exclude_connection_id: str | None = None) -> None:
        """Broadcast one payload to all active connections."""

    @abstractmethod
    async def disconnect_user_connections(
        self,
        user_id: str,
        *,
        exclude_connection_id: str | None = None,
        close_code: int = 4001,
        reason: str = "",
        payload: dict | None = None,
    ) -> bool:
        """Close every active connection for one user and report whether they became offline."""

    @abstractmethod
    def reset(self) -> None:
        """Clear all in-memory runtime state."""


class InMemoryRealtimeHub(RealtimeHub):
    """Single-process in-memory realtime hub."""

    def __init__(self) -> None:
        self._connections: dict[str, WebSocket] = {}
        self._user_by_connection: dict[str, str] = {}
        self._connection_by_socket: dict[int, str] = {}
        self._connections_by_user: dict[str, set[str]] = defaultdict(set)

    async def connect(self, websocket: WebSocket) -> str:
        await websocket.accept()
        connection_id = str(uuid.uuid4())
        self._connections[connection_id] = websocket
        self._connection_by_socket[id(websocket)] = connection_id
        return connection_id

    def bind_user(self, connection_id: str, user_id: str) -> None:
        previous = self._user_by_connection.get(connection_id)
        if previous:
            self._connections_by_user[previous].discard(connection_id)
            if not self._connections_by_user[previous]:
                self._connections_by_user.pop(previous, None)
        self._user_by_connection[connection_id] = user_id
        self._connections_by_user[user_id].add(connection_id)

    def get_user_id(self, connection_id: str) -> str | None:
        return self._user_by_connection.get(connection_id)

    def online_user_ids(self) -> list[str]:
        return sorted(self._connections_by_user.keys())

    def has_user_connections(self, user_id: str) -> bool:
        return bool(self._connections_by_user.get(user_id))

    def _drop_connection(self, connection_id: str) -> str | None:
        websocket = self._connections.pop(connection_id, None)
        if websocket is not None:
            self._connection_by_socket.pop(id(websocket), None)
        user_id = self._user_by_connection.pop(connection_id, None)
        if user_id:
            self._connections_by_user[user_id].discard(connection_id)
            if not self._connections_by_user[user_id]:
                self._connections_by_user.pop(user_id, None)
        return user_id

    async def disconnect(self, websocket: WebSocket) -> tuple[str | None, bool]:
        connection_id = self._connection_by_socket.get(id(websocket))
        if not connection_id:
            return None, False
        return self.disconnect_by_connection_id(connection_id)

    def disconnect_by_connection_id(self, connection_id: str) -> tuple[str | None, bool]:
        if not connection_id:
            return None, False
        user_id = self._drop_connection(connection_id)
        became_offline = bool(user_id) and not self.has_user_connections(user_id)
        return user_id, became_offline

    async def send_json(self, connection_id: str, payload: dict) -> bool:
        websocket = self._connections.get(connection_id)
        if websocket is None:
            return False
        try:
            await websocket.send_json(payload)
            return True
        except (RuntimeError, WebSocketDisconnect):
            self.disconnect_by_connection_id(connection_id)
            return False

    async def send_json_to_users(
        self,
        user_ids: list[str],
        payload: dict,
        exclude_connection_id: str | None = None,
    ) -> set[str]:
        delivered_user_ids: set[str] = set()
        for user_id in user_ids:
            delivered = False
            for connection_id in list(self._connections_by_user.get(user_id, set())):
                if exclude_connection_id is not None and connection_id == exclude_connection_id:
                    continue
                if await self.send_json(connection_id, payload):
                    delivered = True
            if delivered:
                delivered_user_ids.add(user_id)
        return delivered_user_ids

    async def broadcast_json(self, payload: dict, exclude_connection_id: str | None = None) -> None:
        for connection_id in list(self._connections):
            if exclude_connection_id is not None and connection_id == exclude_connection_id:
                continue
            await self.send_json(connection_id, payload)

    async def disconnect_user_connections(
        self,
        user_id: str,
        *,
        exclude_connection_id: str | None = None,
        close_code: int = 4001,
        reason: str = "",
        payload: dict | None = None,
    ) -> bool:
        connection_ids = list(self._connections_by_user.get(user_id, set()))
        disconnected_any = False
        for connection_id in connection_ids:
            if exclude_connection_id is not None and connection_id == exclude_connection_id:
                continue

            websocket = self._connections.get(connection_id)
            if websocket is not None:
                if payload:
                    try:
                        await websocket.send_json(payload)
                    except (RuntimeError, WebSocketDisconnect):
                        pass
                try:
                    await websocket.close(code=close_code, reason=reason)
                except (RuntimeError, WebSocketDisconnect):
                    pass

            self.disconnect_by_connection_id(connection_id)
            disconnected_any = True

        return disconnected_any and not self.has_user_connections(user_id)

    def reset(self) -> None:
        self._connections.clear()
        self._user_by_connection.clear()
        self._connection_by_socket.clear()
        self._connections_by_user.clear()


_realtime_hub: RealtimeHub | None = None


def get_realtime_hub() -> RealtimeHub:
    """Return the singleton realtime hub."""
    global _realtime_hub
    if _realtime_hub is None:
        _realtime_hub = InMemoryRealtimeHub()
    return _realtime_hub
