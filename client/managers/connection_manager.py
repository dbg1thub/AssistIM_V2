"""
Connection Manager Module

Manager for WebSocket connection lifecycle and state management.
"""
import asyncio
import inspect
import json
import time
from concurrent.futures import Future
from typing import Any, Callable, Optional

from client.core import logging
from client.core.logging import setup_logging
from client.services.auth_service import get_auth_service
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

    LAST_SYNC_SESSION_CURSORS = "last_sync_session_cursors"
    LAST_SYNC_EVENT_CURSORS = "last_sync_event_cursors"
    LEGACY_LAST_SYNC_TIMESTAMP = "last_sync_timestamp"
    WS_AUTH_TIMEOUT_SECONDS = 10.0

    def __init__(self):
        self._ws_client: Optional[WebSocketClient] = None
        self._base_ws_url: str = ""
        self._tasks: set[asyncio.Task] = set()
        self._thread_futures: set[Future] = set()
        self._state = ConnectionState.DISCONNECTED
        self._message_dispatch_lock = asyncio.Lock()
        self._state_listeners: list[Callable[[ConnectionState, ConnectionState], None]] = []
        self._message_listeners: list[Callable[[dict], Any]] = []
        self._auth_waiters: list[asyncio.Future[None]] = []
        self._sync_waiters: list[asyncio.Future[None]] = []
        self._session_sync_cursors: dict[str, int] = {}
        self._event_sync_cursors: dict[str, int] = {}
        self._db = None
        self._connect_started_at: float = 0.0
        self._initialized = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._auth_service = get_auth_service()
        self._auth_service.add_token_listener(self._on_tokens_changed)
        self._ws_authenticated = False
        self._ws_auth_in_flight = False
        self._ws_auth_refresh_attempted = False
        self._ws_auth_attempt_id = 0
        self._sync_in_flight = False
        self._callback_generation = 0
        self._closing = False

    @property
    def state(self) -> ConnectionState:
        """Get current connection state."""
        return self._state

    @property
    def is_connected(self) -> bool:
        """Check if connected."""
        return self._state == ConnectionState.CONNECTED and self._ws_authenticated

    @property
    def ws_client(self) -> Optional[WebSocketClient]:
        """Get WebSocket client."""
        return self._ws_client

    @property
    def session_sync_cursors(self) -> dict[str, int]:
        """Return a snapshot of reconnect message cursors keyed by session id."""
        return dict(self._session_sync_cursors)

    @property
    def event_sync_cursors(self) -> dict[str, int]:
        """Return a snapshot of reconnect event cursors keyed by session id."""
        return dict(self._event_sync_cursors)

    async def reload_sync_timestamp(self) -> None:
        """Reload the sync cursors from persisted local state."""
        await self._load_sync_state()

    def clear_sync_state_memory(self) -> None:
        """Clear in-memory reconnect cursors after durable chat state has already been reset."""
        self._session_sync_cursors = {}
        self._event_sync_cursors = {}

    async def reset_sync_state(self) -> None:
        """Reset in-memory and persisted sync cursors for a fresh account context."""
        self._session_sync_cursors = {}
        self._event_sync_cursors = {}
        if self._db and self._db.is_connected:
            await self._db.delete_app_state(self.LAST_SYNC_SESSION_CURSORS)
            await self._db.delete_app_state(self.LAST_SYNC_EVENT_CURSORS)
            await self._db.delete_app_state(self.LEGACY_LAST_SYNC_TIMESTAMP)

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

    @property
    def sync_in_flight(self) -> bool:
        """Return whether one authenticated websocket sync request is still being processed."""
        return bool(self._sync_in_flight)

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

    async def _notify_message(self, message: dict) -> None:
        """Notify all listeners of one inbound transport payload in listener order."""
        for listener in list(self._message_listeners):
            try:
                result = listener(message)
                if inspect.isawaitable(result):
                    await result
            except Exception as e:
                logger.error(f"Message listener error: {e}")

    def _create_waiter(self, waiters: list[asyncio.Future[None]]) -> asyncio.Future[None]:
        """Allocate one main-loop waiter for a connection sub-stage."""
        loop = self._loop
        if loop is None or not loop.is_running():
            loop = asyncio.get_running_loop()
            self._loop = loop
        future: asyncio.Future[None] = loop.create_future()
        waiters.append(future)
        return future

    @staticmethod
    def _resolve_waiters(waiters: list[asyncio.Future[None]]) -> None:
        """Resolve and clear a waiter list."""
        for waiter in waiters:
            if not waiter.done():
                waiter.set_result(None)
        waiters.clear()

    @staticmethod
    def _fail_waiters(waiters: list[asyncio.Future[None]], reason: str) -> None:
        """Fail and clear a waiter list."""
        error = RuntimeError(reason)
        for waiter in waiters:
            if not waiter.done():
                waiter.set_exception(error)
        waiters.clear()

    @staticmethod
    def _normalize_session_cursors(raw_cursors: Any) -> dict[str, int]:
        """Normalize persisted or remote cursor payloads into safe integers."""
        if not isinstance(raw_cursors, dict):
            return {}

        normalized: dict[str, int] = {}
        for session_id, raw_value in raw_cursors.items():
            normalized_session_id = str(session_id or "").strip()
            if not normalized_session_id:
                continue
            try:
                session_seq = max(0, int(raw_value or 0))
            except (TypeError, ValueError):
                continue
            normalized[normalized_session_id] = session_seq
        return normalized

    @classmethod
    def _merge_session_cursors(cls, *cursor_maps: dict[str, int]) -> dict[str, int]:
        """Merge cursor maps by taking the maximum session seq for each session."""
        merged: dict[str, int] = {}
        for cursor_map in cursor_maps:
            for session_id, session_seq in cls._normalize_session_cursors(cursor_map).items():
                current_seq = merged.get(session_id, 0)
                if session_seq > current_seq:
                    merged[session_id] = session_seq
        return merged

    def _advance_session_cursor(self, session_id: Any, session_seq: Any) -> bool:
        """Advance one session cursor if the incoming seq is newer."""
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            return False

        try:
            normalized_seq = max(0, int(session_seq or 0))
        except (TypeError, ValueError):
            return False

        if normalized_seq <= 0:
            return False

        current_seq = self._session_sync_cursors.get(normalized_session_id, 0)
        if normalized_seq <= current_seq:
            return False

        self._session_sync_cursors[normalized_session_id] = normalized_seq
        return True

    def _advance_event_cursor(self, session_id: Any, event_seq: Any) -> bool:
        """Advance one event cursor if the incoming seq is newer."""
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            return False

        try:
            normalized_seq = max(0, int(event_seq or 0))
        except (TypeError, ValueError):
            return False

        if normalized_seq <= 0:
            return False

        current_seq = self._event_sync_cursors.get(normalized_session_id, 0)
        if normalized_seq <= current_seq:
            return False

        self._event_sync_cursors[normalized_session_id] = normalized_seq
        return True

    def _advance_cursor_from_message_payload(self, payload: Any) -> bool:
        """Advance one message cursor from a single message-like payload."""
        if not isinstance(payload, dict):
            return False
        return self._advance_session_cursor(payload.get("session_id"), payload.get("session_seq"))

    def _advance_event_cursor_from_event_payload(self, payload: Any) -> bool:
        """Advance one event cursor from a single event-like payload."""
        if not isinstance(payload, dict):
            return False
        return self._advance_event_cursor(payload.get("session_id"), payload.get("event_seq"))

    def _advance_cursors_from_history_payload(self, messages: Any) -> bool:
        """Advance cursors from a batch of history messages."""
        if not isinstance(messages, list):
            return False

        advanced = False
        for payload in messages:
            if self._advance_cursor_from_message_payload(payload):
                advanced = True
        return advanced

    def _advance_event_cursors_from_history_payload(self, events: Any) -> bool:
        """Advance event cursors from a batch of history events."""
        if not isinstance(events, list):
            return False

        advanced = False
        for envelope in events:
            if isinstance(envelope, dict) and self._advance_event_cursor_from_event_payload(envelope.get("data", {})):
                advanced = True
        return advanced

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
        self._closing = False
        self._callback_generation += 1
        callback_generation = self._callback_generation
        self._ws_client.set_callbacks(
            on_connect=lambda: self._dispatch_connect(callback_generation),
            on_disconnect=lambda: self._dispatch_disconnect(callback_generation),
            on_message=lambda message: self._dispatch_message(callback_generation, message),
            on_error=lambda error: self._dispatch_error(callback_generation, error),
        )

        await self._load_sync_state()
        self._initialized = True

        logger.info("Connection manager initialized")

    async def _load_sync_state(self) -> None:
        """Load message and event reconnect cursors from database state or local cache."""
        try:
            if self._db is None:
                from client.storage.database import get_database

                self._db = get_database()
            if not self._db or not self._db.is_connected:
                return

            persisted_session_cursors: dict[str, int] = {}
            persisted_session_value = await self._db.get_app_state(self.LAST_SYNC_SESSION_CURSORS)
            if persisted_session_value:
                try:
                    persisted_session_cursors = self._normalize_session_cursors(json.loads(persisted_session_value))
                except json.JSONDecodeError as exc:
                    logger.warning("Failed to decode message sync cursors: %s", exc)

            persisted_event_cursors: dict[str, int] = {}
            persisted_event_value = await self._db.get_app_state(self.LAST_SYNC_EVENT_CURSORS)
            if persisted_event_value:
                try:
                    persisted_event_cursors = self._normalize_session_cursors(json.loads(persisted_event_value))
                except json.JSONDecodeError as exc:
                    logger.warning("Failed to decode event sync cursors: %s", exc)

            db_cursors: dict[str, int] = {}
            if not persisted_session_cursors:
                db_cursors = await self._db.get_session_sync_cursors()

            self._session_sync_cursors = self._merge_session_cursors(persisted_session_cursors, db_cursors)
            self._event_sync_cursors = self._merge_session_cursors(persisted_event_cursors)
            if self._session_sync_cursors or self._event_sync_cursors:
                logger.info(
                    "Loaded reconnect cursors for %d message sessions and %d event sessions",
                    len(self._session_sync_cursors),
                    len(self._event_sync_cursors),
                )
        except Exception as e:
            logger.warning(f"Failed to load sync state: {e}")

    async def _save_sync_state(self) -> None:
        """Persist message and event reconnect cursors as one local recovery point."""
        try:
            if self._db and self._db.is_connected:
                values: dict[str, str] = {}
                delete_keys: list[str] = [self.LEGACY_LAST_SYNC_TIMESTAMP]
                if self._session_sync_cursors:
                    values[self.LAST_SYNC_SESSION_CURSORS] = json.dumps(self._session_sync_cursors, sort_keys=True)
                else:
                    delete_keys.append(self.LAST_SYNC_SESSION_CURSORS)

                if self._event_sync_cursors:
                    values[self.LAST_SYNC_EVENT_CURSORS] = json.dumps(self._event_sync_cursors, sort_keys=True)
                else:
                    delete_keys.append(self.LAST_SYNC_EVENT_CURSORS)

                await self._db.replace_app_state(values, delete_keys=delete_keys)
                logger.debug(
                    "Saved reconnect cursors for %d message sessions and %d event sessions",
                    len(self._session_sync_cursors),
                    len(self._event_sync_cursors),
                )
        except Exception as e:
            logger.warning(f"Failed to save sync state: {e}")

    def _create_task(self, coro) -> asyncio.Task:
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
        return task

    def _schedule_message_coroutine(self, coro) -> None:
        """Schedule websocket message processing back onto the main asyncio loop."""
        if self._closing:
            if inspect.iscoroutine(coro):
                coro.close()
            return
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
        self._thread_futures.add(future)

        def _cleanup(done_future: Future) -> None:
            self._thread_futures.discard(done_future)
            try:
                done_future.result()
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("Connection manager message task crashed")

        future.add_done_callback(_cleanup)

    def _is_callback_current(self, generation: int) -> bool:
        """Check whether one websocket callback still belongs to the active runtime generation."""
        return not self._closing and generation == self._callback_generation

    def _on_tokens_changed(self, access_token: Optional[str], refresh_token: Optional[str]) -> None:
        """Invalidate the current websocket runtime when auth tokens are cleared."""
        if access_token:
            return
        self._ws_authenticated = False
        self._ws_auth_in_flight = False
        self._sync_in_flight = False
        self._ws_auth_attempt_id += 1
        self._fail_waiters(self._auth_waiters, "WebSocket authentication was cancelled because credentials were cleared")
        self._fail_waiters(self._sync_waiters, "WebSocket sync was cancelled because credentials were cleared")
        if self._closing or not self._ws_client or not self._ws_client.is_connected:
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        self._create_task(self.disconnect())

    def _dispatch_connect(self, generation: int) -> None:
        if not self._is_callback_current(generation):
            return
        self._on_connect()

    def _dispatch_disconnect(self, generation: int) -> None:
        if not self._is_callback_current(generation):
            return
        self._on_disconnect()

    def _dispatch_message(self, generation: int, message: dict) -> None:
        if not self._is_callback_current(generation):
            return
        self._schedule_message_coroutine(self._handle_dispatched_message(message))

    def _dispatch_error(self, generation: int, error: str) -> None:
        if not self._is_callback_current(generation):
            return
        self._on_error(error)

    def _on_connect(self) -> None:
        """Handle connection established."""
        self._connect_started_at = time.perf_counter()
        self._ws_authenticated = False
        self._ws_auth_in_flight = False
        self._ws_auth_refresh_attempted = False
        self._sync_in_flight = False
        self._ws_auth_attempt_id += 1
        old_state = self._state
        self._notify_state_change(old_state, ConnectionState.AUTHENTICATING)

        logger.info("Connection established")
        self._schedule_post_connect_handshake()

    def _schedule_post_connect_handshake(self) -> None:
        """Schedule websocket authentication without awaiting worker sends on the UI loop."""
        started = time.perf_counter()
        logger.info("Post-connect handshake started (+%.1fms)", (time.perf_counter() - started) * 1000)

        auth_started = time.perf_counter()
        auth_sent = self._authenticate_websocket_nowait()
        logger.info(
            "WebSocket auth %s in %.1fms",
            "message sent" if auth_sent else "skipped",
            (time.perf_counter() - auth_started) * 1000,
        )

    async def _authenticate_websocket(self) -> bool:
        """Send auth payload over websocket if access token exists."""
        access_token = self._auth_service.access_token

        if not access_token:
            logger.info("Skipping websocket auth: no access token present")
            self._ws_auth_in_flight = False
            self._fail_waiters(self._auth_waiters, "WebSocket authentication requires an access token")
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
            self._ws_auth_in_flight = True
            self._schedule_ws_auth_timeout()
            logger.info("WebSocket auth message sent")
        else:
            self._ws_auth_in_flight = False
            self._ws_auth_attempt_id += 1
            self._fail_waiters(self._auth_waiters, "Failed to send websocket auth message")
            logger.warning("Failed to send websocket auth message")
        return success

    def _authenticate_websocket_nowait(self) -> bool:
        """Send auth payload over websocket without awaiting on the main loop."""
        access_token = self._auth_service.access_token

        if not access_token:
            logger.info("Skipping websocket auth: no access token present")
            self._ws_auth_in_flight = False
            self._fail_waiters(self._auth_waiters, "WebSocket authentication requires an access token")
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
            self._ws_auth_in_flight = True
            self._schedule_ws_auth_timeout()
            logger.info("WebSocket auth message sent")
        else:
            self._ws_auth_in_flight = False
            self._ws_auth_attempt_id += 1
            self._fail_waiters(self._auth_waiters, "Failed to send websocket auth message")
            logger.warning("Failed to send websocket auth message")
        return success

    def _schedule_ws_auth_timeout(self) -> None:
        """Start one timeout guard for the current websocket auth attempt."""
        self._ws_auth_attempt_id += 1
        attempt_id = self._ws_auth_attempt_id
        self._schedule_message_coroutine(self._handle_ws_auth_timeout(attempt_id))

    async def _handle_ws_auth_timeout(self, attempt_id: int) -> None:
        """Disconnect a websocket auth attempt that never receives a terminal ack/error."""
        await asyncio.sleep(self.WS_AUTH_TIMEOUT_SECONDS)
        if (
            self._closing
            or self._ws_auth_attempt_id != attempt_id
            or not self._ws_auth_in_flight
            or self._ws_authenticated
        ):
            return

        self._ws_auth_in_flight = False
        self._sync_in_flight = False
        self._ws_auth_attempt_id += 1
        logger.warning("WebSocket auth timed out after %.1fs", self.WS_AUTH_TIMEOUT_SECONDS)
        self._fail_waiters(self._auth_waiters, "WebSocket authentication timed out")
        self._fail_waiters(self._sync_waiters, "Initial websocket sync was cancelled because authentication timed out")
        await self._notify_message(
            {
                "type": "error",
                "data": {
                    "code": 408,
                    "reason": "ws_auth_timeout",
                    "message": "WebSocket authentication timed out",
                },
            }
        )
        await self.disconnect()

    async def _send_sync_request(self) -> bool:
        """Send sync request using per-session reconnect cursors."""
        if not self._ws_authenticated:
            logger.warning("Skipping sync request: websocket not authenticated")
            return False
        sync_message = {
            "type": "sync_messages",
            "seq": 0,
            "msg_id": f"sync_{int(time.time() * 1000)}",
            "timestamp": int(time.time()),
            "data": {
                "session_cursors": self.session_sync_cursors,
                "event_cursors": self.event_sync_cursors,
            },
        }

        success = await self.send(sync_message)
        if success:
            logger.info("Sync request sent for %d sessions", len(self._session_sync_cursors))
        else:
            logger.warning("Failed to send sync request")
            self._fail_waiters(self._sync_waiters, "Failed to send initial websocket sync request")
        return success

    def _send_sync_request_nowait(self) -> bool:
        """Send sync request without awaiting worker send completion on the main loop."""
        if not self._ws_authenticated:
            logger.warning("Skipping sync request: websocket not authenticated")
            return False
        sync_started = time.perf_counter()
        sync_message = {
            "type": "sync_messages",
            "seq": 0,
            "msg_id": f"sync_{int(time.time() * 1000)}",
            "timestamp": int(time.time()),
            "data": {
                "session_cursors": self.session_sync_cursors,
                "event_cursors": self.event_sync_cursors,
            },
        }

        success = bool(self._ws_client and self._ws_client.send_nowait(sync_message))
        if success:
            logger.info("Sync request sent for %d sessions", len(self._session_sync_cursors))
        else:
            logger.warning("Failed to send sync request")
            self._fail_waiters(self._sync_waiters, "Failed to send initial websocket sync request")
        logger.info("Sync request dispatch finished in %.1fms", (time.perf_counter() - sync_started) * 1000)
        return success

    def _on_disconnect(self) -> None:
        """Handle disconnection."""
        self._ws_authenticated = False
        self._ws_auth_in_flight = False
        self._ws_auth_refresh_attempted = False
        self._sync_in_flight = False
        self._ws_auth_attempt_id += 1
        self._fail_waiters(self._auth_waiters, "WebSocket disconnected before authentication completed")
        self._fail_waiters(self._sync_waiters, "WebSocket disconnected before initial sync completed")
        old_state = self._state

        if old_state != ConnectionState.RECONNECTING:
            self._notify_state_change(old_state, ConnectionState.DISCONNECTED)

        logger.info("Connection disconnected")

    def _on_message(self, message: dict) -> None:
        """Handle incoming message."""
        self._schedule_message_coroutine(self._handle_dispatched_message(message))

    async def _handle_dispatched_message(self, message: dict) -> None:
        """Serialize inbound message processing on the main loop."""
        async with self._message_dispatch_lock:
            await self._process_inbound_message(message)

    async def _process_inbound_message(self, message: dict) -> None:
        """Handle one inbound message and await listener-side processing before advancing sync stage."""
        msg_type = message.get("type")
        message_started = time.perf_counter()
        sync_state_changed = False
        sync_completed = False

        if msg_type == "auth_ack":
            data = message.get("data", {})
            self._ws_auth_in_flight = False
            self._ws_auth_attempt_id += 1
            self._ws_authenticated = bool(isinstance(data, dict) and data.get("success"))
            if self._ws_authenticated:
                self._ws_auth_refresh_attempted = False
                old_state = self._state
                self._notify_state_change(old_state, ConnectionState.CONNECTED)
                self._sync_in_flight = True
                if await self._send_sync_request():
                    self._resolve_waiters(self._auth_waiters)
                else:
                    self._ws_authenticated = False
                    self._sync_in_flight = False
                    self._fail_waiters(self._auth_waiters, "Failed to dispatch initial websocket sync request")
            else:
                self._fail_waiters(self._auth_waiters, "WebSocket authentication rejected")
                self._fail_waiters(self._sync_waiters, "Initial websocket sync was cancelled because authentication was rejected")
        elif msg_type == "history_messages":
            data = message.get("data", {})
            messages = data.get("messages", [])
            sync_state_changed = self._advance_cursors_from_history_payload(messages)
            if self._connect_started_at:
                logger.info(
                    "History payload received %.1fms after connect (%d messages)",
                    (time.perf_counter() - self._connect_started_at) * 1000,
                    len(messages),
                )
        elif msg_type == "history_events":
            data = message.get("data", {})
            events = data.get("events", [])
            sync_state_changed = self._advance_event_cursors_from_history_payload(events)
            sync_completed = self._sync_in_flight
        elif msg_type == "chat_message":
            sync_state_changed = self._advance_cursor_from_message_payload(message.get("data", {}))
        elif msg_type == "message_ack":
            sync_state_changed = self._advance_cursor_from_message_payload(
                (message.get("data") or {}).get("message", {})
            )
        elif msg_type == "error" and self._ws_auth_in_flight:
            self._ws_auth_in_flight = False
            self._ws_auth_attempt_id += 1
            data = message.get("data", {}) if isinstance(message.get("data"), dict) else {}
            try:
                code = int(data.get("code", 0) or 0)
            except (TypeError, ValueError):
                code = 0
            if code in {401, 40101, 403} and not self._ws_auth_refresh_attempted:
                self._ws_auth_refresh_attempted = True
                self._schedule_message_coroutine(self._refresh_and_reauthenticate_websocket(message))
                return
            self._fail_waiters(self._auth_waiters, "WebSocket authentication failed")
            self._fail_waiters(self._sync_waiters, "Initial websocket sync was cancelled because authentication failed")
        elif msg_type in {"message_edit", "message_recall", "message_delete", "read", "group_profile_update", "group_self_profile_update"}:
            sync_state_changed = self._advance_event_cursor_from_event_payload(message.get("data", {}))

        if sync_state_changed:
            await self._save_sync_state()

        await self._notify_message(message)
        if sync_completed:
            self._sync_in_flight = False
            self._resolve_waiters(self._sync_waiters)
        if msg_type in {"history_messages", "history_events"}:
            logger.info(
                "History dispatch finished in %.1fms for %s",
                (time.perf_counter() - message_started) * 1000,
                msg_type,
            )

    async def _refresh_and_reauthenticate_websocket(self, terminal_message: dict) -> None:
        """Refresh an expired access token and retry websocket auth once before surfacing auth loss."""
        refresh = getattr(self._auth_service, "refresh_access_token", None)
        if not callable(refresh):
            await self._notify_message(terminal_message)
            return

        try:
            refreshed = await refresh()
        except Exception:
            logger.exception("WebSocket auth token refresh failed")
            refreshed = False

        if not refreshed:
            await self._notify_message(terminal_message)
            return

        if self._closing or not self._ws_client or not self._ws_client.is_connected:
            return

        sent = await self._authenticate_websocket()
        if not sent:
            await self._notify_message(terminal_message)
    def _on_error(self, error: str) -> None:
        """Handle connection error."""
        logger.error(f"Connection error: {error}")

    async def connect(self) -> bool:
        """
        Connect to WebSocket server.

        Returns:
            True when websocket authentication has completed successfully
        """
        if not self._ws_client:
            await self.initialize()

        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            pass

        if self._ws_authenticated and self._state == ConnectionState.CONNECTED:
            return True

        auth_waiter = self._create_waiter(self._auth_waiters)
        should_start_connect = not bool(self._ws_client and self._ws_client.is_connected)

        if should_start_connect:
            old_state = self._state
            self._notify_state_change(old_state, ConnectionState.CONNECTING)
            await self._ws_client.connect()
        elif not self._ws_auth_in_flight:
            old_state = self._state
            self._notify_state_change(old_state, ConnectionState.AUTHENTICATING)
            if not self._authenticate_websocket_nowait():
                if auth_waiter in self._auth_waiters:
                    self._auth_waiters.remove(auth_waiter)
                raise RuntimeError("Failed to send websocket auth message")

        await auth_waiter
        return True

    async def wait_for_initial_sync(self) -> None:
        """Wait until the current authenticated websocket sync batch has been fully replayed."""
        if not self._ws_authenticated:
            raise RuntimeError("Cannot wait for websocket sync before authentication succeeds")
        if not self._sync_in_flight:
            return
        sync_waiter = self._create_waiter(self._sync_waiters)
        await sync_waiter

    async def disconnect(self) -> None:
        """
        Disconnect from WebSocket server intentionally.

        This will NOT trigger auto-reconnect.
        """
        if not self._ws_client:
            return

        old_state = self._state
        self._notify_state_change(old_state, ConnectionState.DISCONNECTED)
        self._fail_waiters(self._auth_waiters, "WebSocket connection was disconnected intentionally")
        self._fail_waiters(self._sync_waiters, "WebSocket sync was interrupted by intentional disconnect")
        self._sync_in_flight = False

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

        msg_type = str(message.get("type") or "")
        if msg_type != "auth" and not self._auth_service.access_token:
            logger.warning("Cannot send %s: no access token", msg_type or "<unknown>")
            return False
        if msg_type != "auth" and not self._ws_authenticated:
            logger.warning("Cannot send %s: websocket not authenticated", msg_type or "<unknown>")
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

    async def send_typing(self, session_id: str, *, typing: bool = True) -> bool:
        """Send typing indicator."""
        message = {
            "type": "typing",
            "seq": 0,
            "msg_id": "",
            "timestamp": int(time.time()),
            "data": {
                "session_id": session_id,
                "typing": typing,
            },
        }

        return await self.send(message)

    async def send_recall(self, session_id: str, message_id: str) -> bool:
        """Send message recall request."""
        message = {
            "type": "message_recall",
            "seq": 0,
            "msg_id": "",
            "timestamp": int(time.time()),
            "data": {
                "session_id": session_id,
                "message_id": message_id,
            },
        }

        return await self.send(message)

    async def send_edit(self, session_id: str, message_id: str, new_content: str) -> bool:
        """Send message edit request."""
        message = {
            "type": "message_edit",
            "seq": 0,
            "msg_id": "",
            "timestamp": int(time.time()),
            "data": {
                "session_id": session_id,
                "message_id": message_id,
                "content": new_content,
            },
        }

        return await self.send(message)

    async def send_call_event(
        self,
        event_type: str,
        data: dict[str, Any],
        *,
        msg_id: str = "",
    ) -> bool:
        """Send one call signaling event."""
        message = {
            "type": event_type,
            "seq": 0,
            "msg_id": msg_id,
            "timestamp": int(time.time()),
            "data": dict(data or {}),
        }
        return await self.send(message)

    async def prune_sync_state(self, active_session_ids) -> None:
        """Remove reconnect cursors for sessions outside the current authoritative snapshot."""
        active_ids = {str(session_id or "").strip() for session_id in active_session_ids if str(session_id or "").strip()}
        previous_session_cursors = dict(self._session_sync_cursors)
        previous_event_cursors = dict(self._event_sync_cursors)
        self._session_sync_cursors = {
            session_id: cursor
            for session_id, cursor in self._session_sync_cursors.items()
            if session_id in active_ids
        }
        self._event_sync_cursors = {
            session_id: cursor
            for session_id, cursor in self._event_sync_cursors.items()
            if session_id in active_ids
        }
        if self._session_sync_cursors != previous_session_cursors or self._event_sync_cursors != previous_event_cursors:
            await self._save_sync_state()

    async def close(self) -> None:
        """Close connection manager and cleanup."""
        logger.info("Closing connection manager")
        self._closing = True
        self._callback_generation += 1
        self._auth_service.remove_token_listener(self._on_tokens_changed)

        for task in list(self._tasks):
            if not task.done():
                task.cancel()

        if self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)
            self._tasks.clear()

        for future in list(self._thread_futures):
            future.cancel()
        self._thread_futures.clear()

        if self._ws_client:
            self._ws_client.set_callbacks()
            await self._ws_client.close()
            self._ws_client = None

        self._state_listeners.clear()
        self._message_listeners.clear()
        self._state = ConnectionState.DISCONNECTED
        self._connect_started_at = 0.0
        self._loop = None
        self._db = None
        self._session_sync_cursors = {}
        self._event_sync_cursors = {}
        self._ws_authenticated = False
        self._ws_auth_in_flight = False
        self._sync_in_flight = False
        self._ws_auth_attempt_id += 1
        self._fail_waiters(self._auth_waiters, "Connection manager closed before websocket authentication completed")
        self._fail_waiters(self._sync_waiters, "Connection manager closed before websocket sync completed")
        self._initialized = False
        self._closing = False
        global _connection_manager
        if _connection_manager is self:
            _connection_manager = None

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
