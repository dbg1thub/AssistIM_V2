"""
Event Bus Module

Thread-safe event bus for communication between UI and business logic.
Supports both synchronous and asynchronous event handlers.
"""
import asyncio
import inspect
import weakref
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from client.core import logging
from client.core.logging import setup_logging

setup_logging()
logger = logging.get_logger(__name__)

EventHandler = Callable[[Any], Optional[Awaitable[None]]]


@dataclass
class EventBus:
    """
    Thread-safe event bus for pub-sub communication.
    
    Supports both sync and async handlers. All operations are thread-safe
    and can be used with asyncio.
    """

    _listeners: dict[str, list[weakref.ReferenceType]] = field(default_factory=lambda: defaultdict(list))
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _sync_lock: object = field(default_factory=lambda: __import__("threading").Lock())

    def __post_init__(self) -> None:
        """Initialize the event bus."""
        self._listeners = defaultdict(list)

    @staticmethod
    def _create_handler_ref(handler: EventHandler) -> weakref.ReferenceType:
        """Create a weak reference that works for both functions and bound methods."""
        if inspect.ismethod(handler) and getattr(handler, "__self__", None) is not None:
            return weakref.WeakMethod(handler)
        return weakref.ref(handler)

    def _get_live_handlers(self, event_type: str) -> list[EventHandler]:
        """Return live handlers and prune dead weak references."""
        refs = self._listeners.get(event_type, [])
        live_handlers: list[EventHandler] = []
        alive_refs: list[weakref.ReferenceType] = []

        for ref in refs:
            handler = ref()
            if handler is None:
                continue
            live_handlers.append(handler)
            alive_refs.append(ref)

        if len(alive_refs) != len(refs):
            self._listeners[event_type] = alive_refs

        return live_handlers

    async def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """
        Subscribe to an event type.
        
        Args:
            event_type: The type of event to listen for
            handler: Callback function to handle the event
        """
        async with self._lock:
            self._listeners[event_type].append(self._create_handler_ref(handler))
            logger.debug(f"Subscribed handler to event: {event_type}")

    def subscribe_sync(self, event_type: str, handler: EventHandler) -> None:
        """
        Subscribe to an event type (synchronous version).
        
        Args:
            event_type: The type of event to listen for
            handler: Callback function to handle the event
        """
        with self._sync_lock:
            self._listeners[event_type].append(self._create_handler_ref(handler))
            logger.debug(f"Subscribed handler to event (sync): {event_type}")

    async def unsubscribe(self, event_type: str, handler: EventHandler) -> None:
        """
        Unsubscribe a handler from an event type.
        
        Args:
            event_type: The type of event
            handler: The handler to remove
        """
        async with self._lock:
            self._remove_handler(event_type, handler)

    def unsubscribe_sync(self, event_type: str, handler: EventHandler) -> None:
        """
        Unsubscribe a handler from an event type (synchronous version).
        
        Args:
            event_type: The type of event
            handler: The handler to remove
        """
        with self._sync_lock:
            self._remove_handler(event_type, handler)

    def _remove_handler(self, event_type: str, handler: EventHandler) -> None:
        """Remove a handler from the listeners."""
        refs = self._listeners.get(event_type, [])
        self._listeners[event_type] = [ref for ref in refs if ref() is not handler]
        logger.debug(f"Unsubscribed handler from event: {event_type}")

    async def emit(self, event_type: str, data: Any = None) -> None:
        """
        Emit an event to all subscribed handlers.
        
        Handlers are called concurrently. If a handler is a coroutine function,
        it will be awaited. Errors in handlers are logged but don't stop
        other handlers from executing.
        
        Args:
            event_type: The type of event to emit
            data: Optional data to pass to handlers
        """
        async with self._lock:
            handlers = list(self._get_live_handlers(event_type))

        tasks = []
        for handler in handlers:
            try:
                result = handler(data)
                if asyncio.iscoroutine(result):
                    tasks.append(asyncio.create_task(result))
                elif asyncio.iscoroutinefunction(handler):
                    tasks.append(asyncio.create_task(handler(data)))
            except Exception as e:
                logger.error(f"Error in event handler for {event_type}: {e}")

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        logger.debug(f"Emitted event: {event_type} to {len(tasks)} handlers")

    def emit_sync(self, event_type: str, data: Any = None) -> None:
        """
        Emit an event synchronously.
        
        Args:
            event_type: The type of event to emit
            data: Optional data to pass to handlers
        """
        with self._sync_lock:
            handlers = list(self._get_live_handlers(event_type))

        for handler in handlers:
            try:
                result = handler(data)
                if asyncio.iscoroutine(result):
                    logger.warning(f"Async handler called sync for event: {event_type}")
                    result.close()
            except Exception as e:
                logger.error(f"Error in event handler for {event_type}: {e}")

    async def clear(self, event_type: Optional[str] = None) -> None:
        """
        Clear all handlers for an event type, or all handlers if no type specified.
        
        Args:
            event_type: Optional event type to clear. If None, clears all.
        """
        async with self._lock:
            if event_type:
                self._listeners[event_type].clear()
            else:
                self._listeners.clear()

    def clear_sync(self, event_type: Optional[str] = None) -> None:
        """Clear all handlers synchronously."""
        with self._sync_lock:
            if event_type:
                self._listeners[event_type].clear()
            else:
                self._listeners.clear()

    def listener_count(self, event_type: str) -> int:
        """Get the number of listeners for an event type."""
        with self._sync_lock:
            return len(self._get_live_handlers(event_type))


_event_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """Get the global event bus instance."""
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus
