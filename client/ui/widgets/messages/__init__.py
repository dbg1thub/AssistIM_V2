"""
Message Widgets Package

Widgets for displaying different message types.
"""

from client.ui.widgets.messages.message_text_widget import MessageTextWidget
from client.ui.widgets.messages.message_image_widget import MessageImageWidget
from client.ui.widgets.messages.message_file_widget import MessageFileWidget
from client.ui.widgets.messages.message_video_widget import MessageVideoWidget

__all__ = [
    "MessageTextWidget",
    "MessageImageWidget",
    "MessageFileWidget",
    "MessageVideoWidget",
]
