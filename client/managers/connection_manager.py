"""
Connection Manager Module

Manager for WebSocket connection lifecycle and state management.
"""
import asyncio
from enum import Enum
from typing import Any, Callable, Optional

from client.core import logging
from client.core.logging import setup_logging
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
    
    def __init__(self):
        self._ws_client: Optional[WebSocketClient] = None
        self._tasks: set[asyncio.Task] = set()
        self._state = ConnectionState.DISCONNECTED
        self._state_listeners: list[Callable[[ConnectionState, ConnectionState], None]] = []
        self._message_listeners: list[Callable[[dict], None]] = []
    
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
    
    def add_message_listener(self, listener: Callable[[dict], None]) -> None:
        """Add message listener."""
        self._message_listeners.append(listener)
    
    def remove_message_listener(self, listener: Callable[[dict], None]) -> None:
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
                listener(message)
            except Exception as e:
                logger.error(f"Message listener error: {e}")
    
    async def initialize(self) -> None:
        """Initialize connection manager."""
        self._ws_client = get_websocket_client()
        
        self._ws_client.set_callbacks(
            on_connect=self._on_connect,
            on_disconnect=self._on_disconnect,
            on_message=self._on_message,
            on_error=self._on_error,
        )
        
        logger.info("Connection manager initialized")
    
    def _on_connect(self) -> None:
        """Handle connection established."""
        old_state = self._state
        self._notify_state_change(old_state, ConnectionState.CONNECTED)
        
        for task in self._tasks:
            if task.done():
                self._tasks.discard(task)
        
        logger.info("Connection established")
    
    def _on_disconnect(self) -> None:
        """Handle disconnection."""
        old_state = self._state
        
        if old_state != ConnectionState.RECONNECTING:
            self._notify_state_change(old_state, ConnectionState.DISCONNECTED)
        
        logger.info("Connection disconnected")
    
    def _on_message(self, message: dict) -> None:
        """Handle incoming message."""
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
    ) -> bool:
        """
        Send chat message through WebSocket.
        
        Args:
            session_id: Target session ID
            content: Message content
            msg_id: Unique message ID
        
        Returns:
            True if sent successfully
        """
        import time
        
        message = {
            "type": "chat_message",
            "seq": 0,
            "msg_id": msg_id,
            "timestamp": int(time.time()),
            "data": {
                "session_id": session_id,
                "content": content,
            },
        }
        
        return await self.send(message)
    
    async def send_typing(self, session_id: str) -> bool:
        """
        Send typing indicator.
        
        Args:
            session_id: Session ID
        
        Returns:
            True if sent successfully
        """
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
        """
        Send read acknowledgment.
        
        Args:
            session_id: Session ID
            message_id: Message ID to mark as read
        
        Returns:
            True if sent successfully
        """
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
    
    async def close(self) -> None:
        """Close connection manager and cleanup."""
        logger.info("Closing connection manager")
        
        for task in self._tasks:
            if not task.done():
                task.cancel()
        
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        
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
