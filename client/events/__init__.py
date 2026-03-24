# Events module - EventBus and typed event topics

from client.events.contact_events import ContactEvent
from client.events.event_bus import EventBus, get_event_bus

__all__ = ["ContactEvent", "EventBus", "get_event_bus"]
