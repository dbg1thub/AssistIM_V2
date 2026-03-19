"""
WebSocket Client Module

Async WebSocket client with auto-reconnect, heartbeat, and state management.
"""
import asyncio
import json
import threading
import uuid
from concurrent.futures import Future
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

import websockets
from websockets.legacy.client import WebSocketClientProtocol
from websockets.exceptions import ConnectionClosed, WebSocketException

from client.core import logging
from client.core.config_backend import get_config
from client.core.logging import setup_logging

setup_logging()
logger = logging.get_logger(__name__)

class ConnectionState(Enum):
    """WebSocket connection states."""
    
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"


# Try to import PySide6 signals, fall back to callback if not available
try:
    from PySide6.QtCore import Signal, QObject
    
    class WebSocketSignals(QObject):
        """PySide6 signals for WebSocket events."""
        
        connected = Signal()
        disconnected = Signal()
        message_received = Signal(dict)
        state_changed = Signal(str)
        error_occurred = Signal(str)
        
    _SIGNALS_AVAILABLE = True
except ImportError:
    _SIGNALS_AVAILABLE = False


@dataclass
class WebSocketClient:
    """
    Async WebSocket client with auto-reconnect and heartbeat.
    
    This is a transport-layer component that handles WebSocket communication
    without any business logic. All events are notified via signals or callbacks.
    """
    
    url: Optional[str] = None
    heartbeat_interval: float = 30.0
    heartbeat_timeout: float = 10.0
    max_reconnect_attempts: int = 10
    initial_reconnect_delay: float = 1.0
    max_reconnect_delay: float = 30.0
    reconnect_backoff_factor: float = 2.0
    
    # Internal state
    _state: ConnectionState = field(default=ConnectionState.DISCONNECTED, init=False)
    _ws: Optional[WebSocketClientProtocol] = field(default=None, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    _intentional_disconnect: bool = field(default=False, init=False)
    _main_loop: Optional[asyncio.AbstractEventLoop] = field(default=None, init=False)
    _thread_loop: Optional[asyncio.AbstractEventLoop] = field(default=None, init=False)
    _thread: Optional[threading.Thread] = field(default=None, init=False)
    _thread_ready: threading.Event = field(default_factory=threading.Event, init=False)
    
    # Tasks
    _connect_task: Optional[asyncio.Task] = field(default=None, init=False)
    _receive_task: Optional[asyncio.Task] = field(default=None, init=False)
    _heartbeat_task: Optional[asyncio.Task] = field(default=None, init=False)
    _reconnect_task: Optional[asyncio.Task] = field(default=None, init=False)
    
    # Callbacks (alternative to signals)
    _on_connect: Optional[Callable[[], None]] = field(default=None, init=False)
    _on_disconnect: Optional[Callable[[], None]] = field(default=None, init=False)
    _on_message: Optional[Callable[[dict], None]] = field(default=None, init=False)
    _on_error: Optional[Callable[[str], None]] = field(default=None, init=False)
    
    # PySide6 signals
    signals: Optional[WebSocketSignals] = field(default=None, init=False)
    
    def __post_init__(self) -> None:
        """Initialize WebSocket client."""
        config = get_config()
        self.url = self.url or config.server.ws_url
        
        if _SIGNALS_AVAILABLE:
            self.signals = WebSocketSignals()

        # Warm the dedicated websocket loop before the UI is shown so the first
        # connect() call does not block the main thread waiting for thread startup.
        self._ensure_worker_loop()
    
    @property
    def state(self) -> ConnectionState:
        """Get current connection state."""
        return self._state
    
    @property
    def is_connected(self) -> bool:
        """Check if WebSocket is connected."""
        return self._state == ConnectionState.CONNECTED and self._ws is not None
    
    def _set_state(self, new_state: ConnectionState) -> None:
        """Set connection state and notify."""
        def _emit_state() -> None:
            if self._state == new_state:
                return

            old_state = self._state
            self._state = new_state

            logger.info(f"WebSocket state: {old_state.value} -> {new_state.value}")

            if self.signals:
                self.signals.state_changed.emit(new_state.value)

            if new_state == ConnectionState.CONNECTED:
                if self.signals:
                    self.signals.connected.emit()
                if self._on_connect:
                    self._on_connect()

            elif new_state == ConnectionState.DISCONNECTED and old_state != ConnectionState.DISCONNECTED:
                if self.signals:
                    self.signals.disconnected.emit()
                if self._on_disconnect:
                    self._on_disconnect()

        self._dispatch_to_main(_emit_state)

    def _dispatch_to_main(self, callback: Callable[[], None]) -> None:
        """Run a callback on the main/UI asyncio loop."""
        loop = self._main_loop
        if loop and loop.is_running():
            loop.call_soon_threadsafe(callback)
            return
        callback()

    def _ensure_worker_loop(self) -> None:
        """Ensure the dedicated websocket worker loop is running."""
        if self._thread and self._thread.is_alive() and self._thread_loop and self._thread_loop.is_running():
            return

        self._thread_ready.clear()

        def _thread_main() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._thread_loop = loop
            self._thread_ready.set()
            try:
                loop.run_forever()
            finally:
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                loop.close()
                self._thread_loop = None

        self._thread = threading.Thread(
            target=_thread_main,
            name="AssistIMWebSocket",
            daemon=True,
        )
        self._thread.start()
        self._thread_ready.wait()

    def _run_in_worker(self, coro) -> Future:
        """Schedule a coroutine on the websocket worker loop."""
        self._ensure_worker_loop()
        return asyncio.run_coroutine_threadsafe(coro, self._thread_loop)
    
    def set_callbacks(
        self,
        on_connect: Optional[Callable[[], None]] = None,
        on_disconnect: Optional[Callable[[], None]] = None,
        on_message: Optional[Callable[[dict], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ) -> None:
        """Set callback handlers."""
        self._on_connect = on_connect
        self._on_disconnect = on_disconnect
        self._on_message = on_message
        self._on_error = on_error
    
    async def connect(self) -> None:
        """Start WebSocket connection."""
        self._main_loop = asyncio.get_running_loop()

        if self._state in (ConnectionState.CONNECTING, ConnectionState.RECONNECTING):
            logger.warning("WebSocket already connecting")
            return
        
        if self._state == ConnectionState.CONNECTED:
            logger.warning("WebSocket already connected")
            return
        
        self._intentional_disconnect = False
        self._set_state(ConnectionState.CONNECTING)

        self._run_in_worker(self._connect_loop())
    
    async def disconnect(self) -> None:
        """Disconnect WebSocket intentionally."""
        logger.info("Intentionally disconnecting WebSocket")
        self._intentional_disconnect = True
        if self._thread_loop and self._thread_loop.is_running():
            await asyncio.wrap_future(self._run_in_worker(self._cleanup()))
        self._set_state(ConnectionState.DISCONNECTED)
    
    async def _connect_loop(self) -> None:
        """Main connection loop with exponential backoff."""
        attempt = 0
        delay = self.initial_reconnect_delay
        
        while not self._intentional_disconnect:
            try:
                logger.info(f"WebSocket connecting (attempt {attempt + 1})")
                
                self._ws = await asyncio.wait_for(
                    websockets.connect(
                        self.url,
                        ping_interval=None,
                    ),
                    timeout=self.heartbeat_timeout,
                )
                
                logger.info("WebSocket connected")
                self._set_state(ConnectionState.CONNECTED)
                
                self._receive_task = asyncio.create_task(self._receive_loop())
                self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
                
                return
            
            except asyncio.CancelledError:
                # Task was cancelled, exit the loop immediately
                logger.info("Connect loop cancelled, exiting")
                raise
            
            except asyncio.TimeoutError:
                logger.warning(f"WebSocket connection timeout")
            except WebSocketException as e:
                logger.warning(f"WebSocket connection error: {e}")
            except Exception as e:
                logger.error(f"WebSocket unexpected error: {e}")
                if self._on_error:
                    self._on_error(str(e))
                if self.signals:
                    self.signals.error_occurred.emit(str(e))
            
            if self._intentional_disconnect:
                break
            
            attempt += 1
            if attempt >= self.max_reconnect_attempts:
                logger.error("Max reconnect attempts reached")
                self._set_state(ConnectionState.DISCONNECTED)
                return
            
            logger.info(f"Reconnecting in {delay:.1f}s")
            self._set_state(ConnectionState.RECONNECTING)
            
            await asyncio.sleep(delay)
            delay = min(delay * self.reconnect_backoff_factor, self.max_reconnect_delay)
    
    async def _receive_loop(self) -> None:
        """Receive messages from WebSocket."""
        while self._state == ConnectionState.CONNECTED and self._ws:
            try:
                message = await asyncio.wait_for(
                    self._ws.recv(),
                    timeout=self.heartbeat_interval + self.heartbeat_timeout,
                )
                
                try:
                    data = await asyncio.to_thread(json.loads, message)
                    logger.debug(f"Received message: {data.get('type')}")

                    def _dispatch_message() -> None:
                        if self.signals:
                            self.signals.message_received.emit(data)
                        if self._on_message:
                            self._on_message(data)

                    self._dispatch_to_main(_dispatch_message)
                
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON: {message[:100]}")
            
            except asyncio.CancelledError:
                logger.info("Receive loop cancelled")
                raise
            
            except asyncio.TimeoutError:
                logger.warning("Receive timeout, no message received")
                continue
            
            except ConnectionClosed:
                logger.warning("WebSocket connection closed")
                await self._handle_disconnect()
                break
            
            except Exception as e:
                logger.error(f"Receive error: {e}")
                await self._handle_disconnect()
                break
    
    async def _heartbeat_loop(self) -> None:
        """Send heartbeat ping to keep connection alive."""
        while self._state == ConnectionState.CONNECTED and self._ws:
            try:
                await asyncio.wait_for(
                    self._ws.ping(),
                    timeout=self.heartbeat_timeout,
                )
                logger.debug("Heartbeat sent")
            
            except asyncio.CancelledError:
                logger.info("Heartbeat loop cancelled")
                raise
            
            except asyncio.TimeoutError:
                logger.warning("Heartbeat timeout")
                await self._handle_disconnect()
                break
            
            except ConnectionClosed:
                logger.warning("WebSocket closed during heartbeat")
                await self._handle_disconnect()
                break
            
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")
                await self._handle_disconnect()
                break
            
            await asyncio.sleep(self.heartbeat_interval)
    
    async def _handle_disconnect(self) -> None:
        """Handle unexpected disconnection."""
        if self._intentional_disconnect:
            return

        await self._cleanup()

        if not self._intentional_disconnect:

            # 防止 shutdown 时 loop 已关闭
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return

            self._connect_task = loop.create_task(self._connect_loop())
    
    async def _cleanup(self) -> None:
        """Cleanup tasks and connection."""
        tasks = [self._receive_task, self._heartbeat_task]
        
        for task in tasks:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        
        self._receive_task = None
        self._heartbeat_task = None
    
    async def send(self, message: dict[str, Any], timeout: float = 10.0) -> bool:
        """
        Send message through WebSocket.
        
        Args:
            message: Message dict to send
            timeout: Send timeout in seconds
        
        Returns:
            True if sent successfully, False otherwise
        """
        if not self.is_connected or not self._thread_loop or not self._thread_loop.is_running():
            logger.warning("Cannot send: not connected")
            return False

        return await asyncio.wrap_future(self._run_in_worker(self._send_worker(message, timeout)))

    def send_nowait(self, message: dict[str, Any], timeout: float = 10.0) -> bool:
        """Schedule a JSON send on the worker loop without awaiting the result on the UI loop."""
        if not self.is_connected or not self._thread_loop or not self._thread_loop.is_running():
            logger.warning("Cannot send: not connected")
            return False

        future = self._run_in_worker(self._send_worker(message, timeout))

        def _log_result(done_future: Future) -> None:
            try:
                done_future.result()
            except Exception as exc:  # pragma: no cover - defensive
                logger.error(f"Background send error: {exc}")

        future.add_done_callback(_log_result)
        return True
    
    async def send_text(self, text: str, timeout: float = 10.0) -> bool:
        """Send raw text message."""
        if not self.is_connected or not self._thread_loop or not self._thread_loop.is_running():
            logger.warning("Cannot send: not connected")
            return False

        return await asyncio.wrap_future(self._run_in_worker(self._send_text_worker(text, timeout)))

    async def _send_worker(self, message: dict[str, Any], timeout: float = 10.0) -> bool:
        """Send a JSON message on the websocket worker loop."""
        try:
            data = json.dumps(message)
            await asyncio.wait_for(self._ws.send(data), timeout=timeout)
            logger.debug(f"Sent message: {message.get('type')}")
            return True

        except asyncio.TimeoutError:
            logger.error("Send timeout")
            return False

        except ConnectionClosed:
            logger.warning("Connection closed, cannot send")
            await self._handle_disconnect()
            return False

        except Exception as e:
            logger.error(f"Send error: {e}")
            return False

    async def _send_text_worker(self, text: str, timeout: float = 10.0) -> bool:
        """Send a raw text message on the websocket worker loop."""
        try:
            await asyncio.wait_for(self._ws.send(text), timeout=timeout)
            return True
        except Exception as e:
            logger.error(f"Send text error: {e}")
            return False
    
    def create_message(
        self,
        msg_type: str,
        data: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """
        Create a standardized message format.
        
        Args:
            msg_type: Message type
            data: Message payload
        
        Returns:
            Formatted message dict
        """
        return {
            "type": msg_type,
            "seq": 0,
            "msg_id": str(uuid.uuid4()),
            "timestamp": 0,
            "data": data or {},
        }
    
    async def close(self) -> None:
        """Close WebSocket and cancel all tasks."""
        self._intentional_disconnect = True

        if self._thread_loop and self._thread_loop.is_running():
            await asyncio.wrap_future(self._run_in_worker(self._cleanup()))
            self._thread_loop.call_soon_threadsafe(self._thread_loop.stop)

        if self._thread and self._thread.is_alive():
            await asyncio.to_thread(self._thread.join, 2.0)
            self._thread = None

        self._set_state(ConnectionState.DISCONNECTED)

        logger.info("WebSocket client closed")


_websocket_client: Optional[WebSocketClient] = None


def get_websocket_client(**kwargs) -> WebSocketClient:
    """Get or create the global WebSocket client instance."""
    global _websocket_client
    if _websocket_client is None:
        _websocket_client = WebSocketClient(**kwargs)
    return _websocket_client
