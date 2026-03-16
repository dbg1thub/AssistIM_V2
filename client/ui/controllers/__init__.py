"""UI controllers module."""

from client.ui.controllers.auth_controller import AuthController, get_auth_controller
from client.ui.controllers.chat_controller import ChatController, get_chat_controller
from client.ui.controllers.contact_controller import ContactController, get_contact_controller
from client.ui.controllers.discovery_controller import DiscoveryController, get_discovery_controller

__all__ = [
    "AuthController",
    "ChatController",
    "ContactController",
    "DiscoveryController",
    "get_auth_controller",
    "get_chat_controller",
    "get_contact_controller",
    "get_discovery_controller",
]
