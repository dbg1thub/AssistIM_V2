"""
WebSocket Client Module

Async WebSocket client with auto-reconnect, heartbeat, and state management.
"""
import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

import websockets
from websockets.legacy.client import WebSocketClientProtocol
from websockets.exceptions import ConnectionClosed, WebSocketException

from client.core.config import get_config


logger = logging.getLogger(__name__)


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
        
        elif new_state == ConnectionState.DISCONNECTED:
            if old_state != ConnectionState.DISCONNECTED:
                if self.signals:
                    self.signals.disconnected.emit()
                if self._on_disconnect:
                    self._on_disconnect()
    
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
        if self._state in (ConnectionState.CONNECTING, ConnectionState.RECONNECTING):
            logger.warning("WebSocket already connecting")
            return
        
        if self._state == ConnectionState.CONNECTED:
            logger.warning("WebSocket already connected")
            return
        
        self._intentional_disconnect = False
        self._set_state(ConnectionState.CONNECTING)
        
        self._connect_task = asyncio.create_task(self._connect_loop())
    
    async def disconnect(self) -> None:
        """Disconnect WebSocket intentionally."""
        logger.info("Intentionally disconnecting WebSocket")
        self._intentional_disconnect = True
        await self._cleanup()
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
                    data = json.loads(message)
                    logger.debug(f"Received message: {data.get('type')}")
                    
                    if self.signals:
                        self.signals.message_received.emit(data)
                    if self._on_message:
                        self._on_message(data)
                
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
        if not self.is_connected:
            logger.warning("Cannot send: not connected")
            return False
        
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
    
    async def send_text(self, text: str, timeout: float = 10.0) -> bool:
        """Send raw text message."""
        if not self.is_connected:
            logger.warning("Cannot send: not connected")
            return False
        
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

        tasks = [
            self._connect_task,
            self._receive_task,
            self._heartbeat_task,
            self._reconnect_task,
        ]

        for task in tasks:
            if task and not task.done():
                task.cancel()

        await asyncio.gather(
            *[t for t in tasks if t],
            return_exceptions=True
        )

        await self._cleanup()

        self._set_state(ConnectionState.DISCONNECTED)

        logger.info("WebSocket client closed")


_websocket_client: Optional[WebSocketClient] = None


def get_websocket_client(**kwargs) -> WebSocketClient:
    """Get or create the global WebSocket client instance."""
    global _websocket_client
    if _websocket_client is None:
        _websocket_client = WebSocketClient(**kwargs)
    return _websocket_client
