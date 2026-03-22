"""
Connection Manager Module

Manager for WebSocket connection lifecycle and state management.
"""
import asyncio
import inspect
import time
from concurrent.futures import Future
from datetime import datetime
from typing import Any, Callable, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from client.core.datetime_utils import to_epoch_seconds
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
        self._base_ws_url: str = ""
        self._tasks: set[asyncio.Task] = set()
        self._state = ConnectionState.DISCONNECTED
        self._state_listeners: list[Callable[[ConnectionState, ConnectionState], None]] = []
        self._message_listeners: list[Callable[[dict], Any]] = []
        self._last_sync_timestamp: float = 0.0
        self._db = None
        self._connect_started_at: float = 0.0
        self._initialized = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None

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

    async def reload_sync_timestamp(self) -> None:
        """Reload the sync cursor from persisted local state."""
        await self._load_sync_timestamp()

    async def reset_sync_state(self) -> None:
        """Reset in-memory and persisted sync cursors for a fresh account context."""
        self._last_sync_timestamp = 0.0
        if self._db and self._db.is_connected:
            await self._db.delete_app_state(self.LAST_SYNC_TIMESTAMP)

    def add_state_listener(
        self,
        listener: Callable[[ConnectionState, ConnectionState], None],
    ) -> None:
        """Add connection state change listener."""
        if listener not in self._state_listeners:
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
        if listener not in self._message_listeners:
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

        for listener in list(self._state_listeners):
            try:
                listener(old_state, new_state)
            except Exception as e:
                logger.error(f"State listener error: {e}")

    def _notify_message(self, message: dict) -> None:
        """Notify all listeners of new message."""
        for listener in list(self._message_listeners):
            try:
                result = listener(message)
                if inspect.isawaitable(result):
                    self._schedule_message_coroutine(result)
            except Exception as e:
                logger.error(f"Message listener error: {e}")

    def _coerce_message_timestamp(self, value: Any) -> float:
        """Normalize backend timestamps to epoch seconds."""
        if value is None or value == "":
            return 0.0
        return to_epoch_seconds(value)

    async def initialize(self) -> None:
        """Initialize connection manager."""
        if self._initialized and self._ws_client is not None:
            return

        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None

        self._ws_client = get_websocket_client()
        self._base_ws_url = self._base_ws_url or str(self._ws_client.url or "")
        self._apply_authenticated_ws_url()

        self._ws_client.set_callbacks(
            on_connect=self._on_connect,
            on_disconnect=self._on_disconnect,
            on_message=self._on_message,
            on_error=self._on_error,
        )

        await self._load_sync_timestamp()
        self._initialized = True

        logger.info("Connection manager initialized")

    def _apply_authenticated_ws_url(self) -> None:
        """Attach the current access token to the websocket URL for early server binding."""
        if self._ws_client is None:
            return

        base_url = self._base_ws_url or str(self._ws_client.url or "")
        if not base_url:
            return

        parts = urlsplit(base_url)
        query_items = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key != "token"]

        access_token = get_http_client().access_token
        if access_token:
            query_items.append(("token", access_token))

        self._ws_client.url = urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urlencode(query_items), parts.fragment)
        )

    async def _load_sync_timestamp(self) -> None:
        """Load last sync timestamp from database."""
        try:
            from client.storage.database import get_database
            self._db = get_database()

            if self._db.is_connected:
                value = await self._db.get_app_state(self.LAST_SYNC_TIMESTAMP)
                persisted_timestamp = float(value) if value else 0.0
                db_latest_timestamp = await self._db.get_latest_message_timestamp() or 0.0
                self._last_sync_timestamp = max(persisted_timestamp, db_latest_timestamp)
                if self._last_sync_timestamp:
                    logger.info(
                        "Loaded last sync timestamp: %s (persisted=%s, db_latest=%s)",
                        self._last_sync_timestamp,
                        persisted_timestamp,
                        db_latest_timestamp,
                    )
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

    def _schedule_message_coroutine(self, coro) -> None:
        """Schedule websocket message processing back onto the main asyncio loop."""
        loop = self._loop
        if loop is None or not loop.is_running():
            self._create_task(coro)
            return

        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        if current_loop is loop:
            self._create_task(coro)
            return

        future = asyncio.run_coroutine_threadsafe(coro, loop)

        def _cleanup(done_future: Future) -> None:
            try:
                done_future.result()
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("Connection manager message task crashed")

        future.add_done_callback(_cleanup)

    def _on_connect(self) -> None:
        """Handle connection established."""
        self._connect_started_at = time.perf_counter()
        old_state = self._state
        self._notify_state_change(old_state, ConnectionState.CONNECTED)

        logger.info("Connection established")
        self._schedule_post_connect_handshake()

    def _schedule_post_connect_handshake(self) -> None:
        """Schedule auth/sync without awaiting worker sends on the UI loop."""
        started = time.perf_counter()
        logger.info("Post-connect handshake started (+%.1fms)", (time.perf_counter() - started) * 1000)

        auth_started = time.perf_counter()
        auth_sent = self._authenticate_websocket_nowait()
        logger.info(
            "WebSocket auth %s in %.1fms",
            "message sent" if auth_sent else "skipped",
            (time.perf_counter() - auth_started) * 1000,
        )

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        loop.call_later(0.2, self._send_sync_request_nowait)

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

    def _authenticate_websocket_nowait(self) -> bool:
        """Send auth payload over websocket without awaiting on the main loop."""
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
        success = bool(self._ws_client and self._ws_client.send_nowait(auth_message))
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

    def _send_sync_request_nowait(self) -> None:
        """Send sync request without awaiting worker send completion on the main loop."""
        import time

        sync_started = time.perf_counter()
        sync_message = {
            "type": "sync_messages",
            "seq": 0,
            "msg_id": f"sync_{int(time.time() * 1000)}",
            "timestamp": int(time.time()),
            "data": {
                "last_timestamp": self._last_sync_timestamp,
            },
        }

        success = bool(self._ws_client and self._ws_client.send_nowait(sync_message))
        if success:
            logger.info(f"Sync request sent, last_timestamp: {self._last_sync_timestamp}")
        else:
            logger.warning("Failed to send sync request")
        logger.info("Sync request dispatch finished in %.1fms", (time.perf_counter() - sync_started) * 1000)

    def _on_disconnect(self) -> None:
        """Handle disconnection."""
        old_state = self._state

        if old_state != ConnectionState.RECONNECTING:
            self._notify_state_change(old_state, ConnectionState.DISCONNECTED)

        logger.info("Connection disconnected")

    def _on_message(self, message: dict) -> None:
        """Handle incoming message."""
        msg_type = message.get("type")
        message_started = time.perf_counter()
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
                    self._schedule_message_coroutine(self._save_sync_timestamp())
            if self._connect_started_at:
                logger.info(
                    "History payload received %.1fms after connect (%d messages)",
                    (time.perf_counter() - self._connect_started_at) * 1000,
                    len(messages),
                )

        self._notify_message(message)
        if msg_type == "history_messages":
            logger.info(
                "History message dispatch scheduling took %.1fms",
                (time.perf_counter() - message_started) * 1000,
            )

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

        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            pass

        self._apply_authenticated_ws_url()

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
            self._tasks.clear()

        if self._ws_client:
            await self._ws_client.close()
            self._ws_client.set_callbacks()
            self._ws_client = None

        self._state_listeners.clear()
        self._message_listeners.clear()
        self._state = ConnectionState.DISCONNECTED
        self._connect_started_at = 0.0
        self._db = None
        self._last_sync_timestamp = 0.0
        self._initialized = False

        logger.info("Connection manager closed")


_connection_manager: Optional[ConnectionManager] = None


def peek_connection_manager() -> Optional[ConnectionManager]:
    """Return the existing connection manager singleton if it was created."""
    return _connection_manager


def get_connection_manager() -> ConnectionManager:
    """Get the global connection manager instance."""
    global _connection_manager
    if _connection_manager is None:
        _connection_manager = ConnectionManager()
    return _connection_manager

