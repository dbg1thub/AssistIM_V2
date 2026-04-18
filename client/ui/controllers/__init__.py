"""UI controllers module with lazy exports."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "AIController": ("client.ui.controllers.ai_controller", "AIController"),
    "AuthController": ("client.ui.controllers.auth_controller", "AuthController"),
    "ChatController": ("client.ui.controllers.chat_controller", "ChatController"),
    "ContactController": ("client.ui.controllers.contact_controller", "ContactController"),
    "DiscoveryController": ("client.ui.controllers.discovery_controller", "DiscoveryController"),
    "get_ai_controller": ("client.ui.controllers.ai_controller", "get_ai_controller"),
    "get_auth_controller": ("client.ui.controllers.auth_controller", "get_auth_controller"),
    "get_chat_controller": ("client.ui.controllers.chat_controller", "get_chat_controller"),
    "get_contact_controller": ("client.ui.controllers.contact_controller", "get_contact_controller"),
    "get_discovery_controller": ("client.ui.controllers.discovery_controller", "get_discovery_controller"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    """Resolve controller exports lazily so importing one controller stays isolated."""
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = _EXPORTS[name]
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value
