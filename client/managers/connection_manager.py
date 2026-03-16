"""
Connection Manager Module

Manager for WebSocket connection lifecycle and state management.
"""
import asyncio
import inspect
from datetime import datetime
from typing import Any, Callable, Optional

from client.core import logging
from client.core.logging import setup_logging
from client.network.http_client import get_http_client
from client.network.websocket_client import (
    ConnectionState,
    WebSocketClient,
    get_websocket_client,
)


setup_logging()
logger = logging.get_logger(__name__)


class ConnectionManager:
    """
    Manager for WebSocket connection lifecycle.

    Responsibilities:
        - Manage connection state
        - Handle reconnection strategy
        - Coordinate with services
        - Emit connection events
    """

    LAST_SYNC_TIMESTAMP = "last_sync_timestamp"

    def __init__(self):
        self._ws_client: Optional[WebSocketClient] = None
        self._tasks: set[asyncio.Task] = set()
        self._state = ConnectionState.DISCONNECTED
        self._state_listeners: list[Callable[[ConnectionState, ConnectionState], None]] = []
        self._message_listeners: list[Callable[[dict], Any]] = []
        self._last_sync_timestamp: float = 0.0
        self._db = None

    @property
    def state(self) -> ConnectionState:
        """Get current connection state."""
        return self._state

    @property
    def is_connected(self) -> bool:
        """Check if connected."""
        return self._state == ConnectionState.CONNECTED

    @property
    def ws_client(self) -> Optional[WebSocketClient]:
        """Get WebSocket client."""
        return self._ws_client

    @property
    def last_sync_timestamp(self) -> float:
        """Get last sync timestamp."""
        return self._last_sync_timestamp

    def set_last_sync_timestamp(self, timestamp: float) -> None:
        """Set last sync timestamp."""
        self._last_sync_timestamp = timestamp

    def add_state_listener(
        self,
        listener: Callable[[ConnectionState, ConnectionState], None],
    ) -> None:
        """Add connection state change listener."""
        self._state_listeners.append(listener)

    def remove_state_listener(
        self,
        listener: Callable[[ConnectionState, ConnectionState], None],
    ) -> None:
        """Remove connection state change listener."""
        if listener in self._state_listeners:
            self._state_listeners.remove(listener)

    def add_message_listener(self, listener: Callable[[dict], Any]) -> None:
        """Add message listener."""
        self._message_listeners.append(listener)

    def remove_message_listener(self, listener: Callable[[dict], Any]) -> None:
        """Remove message listener."""
        if listener in self._message_listeners:
            self._message_listeners.remove(listener)

    def _notify_state_change(
        self,
        old_state: ConnectionState,
        new_state: ConnectionState,
    ) -> None:
        """Notify all listeners of state change."""
        self._state = new_state

        for listener in self._state_listeners:
            try:
                listener(old_state, new_state)
            except Exception as e:
                logger.error(f"State listener error: {e}")

    def _notify_message(self, message: dict) -> None:
        """Notify all listeners of new message."""
        for listener in self._message_listeners:
            try:
                result = listener(message)
                if inspect.isawaitable(result):
                    self._create_task(result)
            except Exception as e:
                logger.error(f"Message listener error: {e}")

    def _coerce_message_timestamp(self, value: Any) -> float:
        """Normalize backend timestamps to epoch seconds."""
        if value is None or value == "":
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
            except ValueError:
                try:
                    return float(value)
                except ValueError:
                    return 0.0
        return 0.0

    async def initialize(self) -> None:
        """Initialize connection manager."""
        self._ws_client = get_websocket_client()

        self._ws_client.set_callbacks(
            on_connect=self._on_connect,
            on_disconnect=self._on_disconnect,
            on_message=self._on_message,
            on_error=self._on_error,
        )

        await self._load_sync_timestamp()

        logger.info("Connection manager initialized")

    async def _load_sync_timestamp(self) -> None:
        """Load last sync timestamp from database."""
        try:
            from client.storage.database import get_database
            self._db = get_database()

            if self._db.is_connected:
                value = await self._db.get_app_state(self.LAST_SYNC_TIMESTAMP)
                if value:
                    self._last_sync_timestamp = float(value)
                    logger.info(f"Loaded last sync timestamp: {self._last_sync_timestamp}")
        except Exception as e:
            logger.warning(f"Failed to load sync timestamp: {e}")

    async def _save_sync_timestamp(self) -> None:
        """Save last sync timestamp to database."""
        try:
            if self._db and self._db.is_connected:
                await self._db.set_app_state(
                    self.LAST_SYNC_TIMESTAMP,
                    str(self._last_sync_timestamp)
                )
                logger.debug(f"Saved sync timestamp: {self._last_sync_timestamp}")
        except Exception as e:
            logger.warning(f"Failed to save sync timestamp: {e}")

    def _create_task(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)

        def _cleanup(done_task: asyncio.Task) -> None:
            self._tasks.discard(done_task)
            try:
                done_task.result()
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("Connection manager background task crashed")

        task.add_done_callback(_cleanup)

    def _on_connect(self) -> None:
        """Handle connection established."""
        old_state = self._state
        self._notify_state_change(old_state, ConnectionState.CONNECTED)

        logger.info("Connection established")
        self._create_task(self._post_connect_handshake())

    async def _post_connect_handshake(self) -> None:
        """Authenticate websocket and then request missed messages."""
        await self._authenticate_websocket()
        await asyncio.sleep(0.2)
        await self._send_sync_request()

    async def _authenticate_websocket(self) -> bool:
        """Send auth payload over websocket if access token exists."""
        http_client = get_http_client()
        access_token = http_client.access_token

        if not access_token:
            logger.info("Skipping websocket auth: no access token present")
            return False

        auth_message = {
            "type": "auth",
            "seq": 0,
            "msg_id": "",
            "timestamp": 0,
            "data": {
                "token": access_token,
            },
        }
        success = await self.send(auth_message)
        if success:
            logger.info("WebSocket auth message sent")
        else:
            logger.warning("Failed to send websocket auth message")
        return success

    async def _send_sync_request(self) -> None:
        """Send sync request to fetch messages since last timestamp."""
        import time

        sync_message = {
            "type": "sync_messages",
            "seq": 0,
            "msg_id": f"sync_{int(time.time() * 1000)}",
            "timestamp": int(time.time()),
            "data": {
                "last_timestamp": self._last_sync_timestamp,
            },
        }

        success = await self.send(sync_message)
        if success:
            logger.info(f"Sync request sent, last_timestamp: {self._last_sync_timestamp}")
        else:
            logger.warning("Failed to send sync request")

    def _on_disconnect(self) -> None:
        """Handle disconnection."""
        old_state = self._state

        if old_state != ConnectionState.RECONNECTING:
            self._notify_state_change(old_state, ConnectionState.DISCONNECTED)

        logger.info("Connection disconnected")

    def _on_message(self, message: dict) -> None:
        """Handle incoming message."""
        msg_type = message.get("type")
        if msg_type == "history_messages":
            data = message.get("data", {})
            messages = data.get("messages", [])
            if messages:
                latest_timestamp = max(
                    (self._coerce_message_timestamp(m.get("timestamp", 0)) for m in messages),
                    default=0
                )
                if latest_timestamp > self._last_sync_timestamp:
                    self._last_sync_timestamp = latest_timestamp
                    logger.info(f"Updated sync timestamp to {latest_timestamp}")
                    self._create_task(self._save_sync_timestamp())

        self._notify_message(message)

    def _on_error(self, error: str) -> None:
        """Handle connection error."""
        logger.error(f"Connection error: {error}")

    async def connect(self) -> bool:
        """
        Connect to WebSocket server.

        Returns:
            True if connection started successfully
        """
        if not self._ws_client:
            await self.initialize()

        old_state = self._state
        self._notify_state_change(old_state, ConnectionState.CONNECTING)

        await self._ws_client.connect()

        return True

    async def disconnect(self) -> None:
        """
        Disconnect from WebSocket server intentionally.

        This will NOT trigger auto-reconnect.
        """
        if not self._ws_client:
            return

        old_state = self._state
        self._notify_state_change(old_state, ConnectionState.DISCONNECTED)

        await self._ws_client.disconnect()

        logger.info("Disconnected intentionally")

    async def reconnect(self) -> None:
        """
        Force reconnection.

        This is useful when user wants to manually reconnect
        after a failed connection attempt.
        """
        if self._ws_client:
            await self._ws_client.disconnect()

        await asyncio.sleep(0.5)

        await self.connect()

    async def send(self, message: dict[str, Any], timeout: float = 10.0) -> bool:
        """
        Send message through WebSocket.

        Args:
            message: Message dict to send
            timeout: Send timeout in seconds

        Returns:
            True if sent successfully
        """
        if not self._ws_client or not self._ws_client.is_connected:
            logger.warning("Cannot send: not connected")
            return False

        return await self._ws_client.send(message, timeout)

    async def send_chat_message(
        self,
        session_id: str,
        content: str,
        msg_id: str,
        message_type: str = "text",
        extra: Optional[dict] = None,
    ) -> bool:
        """
        Send chat message through WebSocket.

        Args:
            session_id: Target session ID
            content: Message content
            msg_id: Unique message ID
            message_type: Message type (text, image, file, video)
            extra: Additional fields

        Returns:
            True if sent successfully
        """
        import time

        message_data = {
            "session_id": session_id,
            "content": content,
            "message_type": message_type,
        }

        if extra:
            message_data["extra"] = extra

        message = {
            "type": "chat_message",
            "seq": 0,
            "msg_id": msg_id,
            "timestamp": int(time.time()),
            "data": message_data,
        }

        return await self.send(message)

    async def send_typing(self, session_id: str) -> bool:
        """Send typing indicator."""
        import time

        message = {
            "type": "typing",
            "seq": 0,
            "msg_id": "",
            "timestamp": int(time.time()),
            "data": {
                "session_id": session_id,
            },
        }

        return await self.send(message)

    async def send_read_ack(self, session_id: str, message_id: str) -> bool:
        """Send read acknowledgment."""
        import time

        message = {
            "type": "read_ack",
            "seq": 0,
            "msg_id": "",
            "timestamp": int(time.time()),
            "data": {
                "session_id": session_id,
                "message_id": message_id,
            },
        }

        return await self.send(message)

    async def send_recall(self, session_id: str, message_id: str) -> bool:
        """Send message recall request."""
        import time

        message = {
            "type": "message_recall",
            "seq": 0,
            "msg_id": "",
            "timestamp": int(time.time()),
            "data": {
                "session_id": session_id,
                "msg_id": message_id,
            },
        }

        return await self.send(message)

    async def send_edit(self, session_id: str, message_id: str, new_content: str) -> bool:
        """Send message edit request."""
        import time

        message = {
            "type": "message_edit",
            "seq": 0,
            "msg_id": "",
            "timestamp": int(time.time()),
            "data": {
                "session_id": session_id,
                "msg_id": message_id,
                "content": new_content,
            },
        }

        return await self.send(message)

    async def close(self) -> None:
        """Close connection manager and cleanup."""
        logger.info("Closing connection manager")

        for task in list(self._tasks):
            if not task.done():
                task.cancel()

        if self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

        if self._ws_client:
            await self._ws_client.close()

        self._state_listeners.clear()
        self._message_listeners.clear()

        logger.info("Connection manager closed")


_connection_manager: Optional[ConnectionManager] = None


def get_connection_manager() -> ConnectionManager:
    """Get the global connection manager instance."""
    global _connection_manager
    if _connection_manager is None:
        _connection_manager = ConnectionManager()
    return _connection_manager
