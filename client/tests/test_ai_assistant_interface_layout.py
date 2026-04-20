import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QApplication

from client.models.ai_assistant import AIMessage, AIMessageRole, AIMessageStatus
from client.ui.windows.ai_assistant_interface import AIAssistantInterface


def _message(message_id: str, role: AIMessageRole, content: str, *, status: AIMessageStatus = AIMessageStatus.DONE) -> AIMessage:
    return AIMessage(
        message_id=message_id,
        thread_id="thread-1",
        role=role,
        content=content,
        status=status,
        created_at="2026-04-21T00:00:00Z",
        updated_at="2026-04-21T00:00:00Z",
        task_id="",
        model="",
        extra=None,
    )


def _rect_in_panel(widget: AIAssistantInterface, child) -> QRect:
    top_left = widget.content_panel.mapFromGlobal(child.mapToGlobal(QPoint(0, 0)))
    return QRect(top_left, child.size())


def test_ai_assistant_streaming_layout_keeps_bottom_gap_stable() -> None:
    app = QApplication.instance() or QApplication([])
    widget = AIAssistantInterface()
    widget.resize(1200, 900)
    widget.show()
    app.processEvents()

    for index in range(10):
        role = AIMessageRole.USER if index % 2 == 0 else AIMessageRole.ASSISTANT
        text = (("用户消息 " if role == AIMessageRole.USER else "AI消息 ") + str(index) + "。") * 8
        widget._append_message(_message(f"m{index}", role, text))
        app.processEvents()

    stream = _message("stream", AIMessageRole.ASSISTANT, "", status=AIMessageStatus.STREAMING)
    stream.task_id = "task-stream"
    widget._append_message(stream)
    widget._active_assistant_message = stream
    widget._is_generating = True
    app.processEvents()

    for _step in range(8):
        stream.content += "这是流式输出的较长内容。" * 10
        widget._update_message_card(stream)
        app.processEvents()
        last_row = widget.message_layout.itemAt(widget.message_layout.count() - 1).widget()
        assert last_row is not None
        bottom_gap = widget.message_container.height() - last_row.geometry().bottom() - 1
        assert bottom_gap <= widget.MESSAGE_BOTTOM_MARGIN + 1
        assert bottom_gap >= max(0, widget.MESSAGE_BOTTOM_MARGIN - 1)

    widget.close()
    app.processEvents()


def test_ai_assistant_message_track_follows_composer_edges() -> None:
    app = QApplication.instance() or QApplication([])
    widget = AIAssistantInterface()
    widget.resize(1400, 900)
    widget.show()
    app.processEvents()
    widget._update_input_overlay_positions()
    app.processEvents()

    widget._append_message(_message("assistant", AIMessageRole.ASSISTANT, "AI 回复。" * 20))
    widget._append_message(_message("user", AIMessageRole.USER, "我的消息。" * 8))
    app.processEvents()
    widget._update_input_overlay_positions()
    app.processEvents()

    assistant_row = widget.message_layout.itemAt(0).widget()
    user_row = widget.message_layout.itemAt(1).widget()
    assert assistant_row is not None
    assert user_row is not None

    composer_rect = _rect_in_panel(widget, widget.composer_shell)
    assistant_lane_rect = _rect_in_panel(widget, assistant_row._content_lane)
    user_lane_rect = _rect_in_panel(widget, user_row._content_lane)
    user_card_rect = _rect_in_panel(widget, user_row.card)

    assert abs(assistant_lane_rect.left() - composer_rect.left()) <= 1
    assert abs(assistant_lane_rect.right() - composer_rect.right()) <= 1
    assert abs(user_lane_rect.left() - composer_rect.left()) <= 1
    assert abs(user_lane_rect.right() - composer_rect.right()) <= 1
    assert abs(user_card_rect.right() - composer_rect.right()) <= 1

    widget.resize(1024, 900)
    app.processEvents()
    widget._update_input_overlay_positions()
    app.processEvents()

    composer_rect = _rect_in_panel(widget, widget.composer_shell)
    assistant_lane_rect = _rect_in_panel(widget, assistant_row._content_lane)
    user_lane_rect = _rect_in_panel(widget, user_row._content_lane)
    user_card_rect = _rect_in_panel(widget, user_row.card)

    assert abs(assistant_lane_rect.left() - composer_rect.left()) <= 1
    assert abs(assistant_lane_rect.right() - composer_rect.right()) <= 1
    assert abs(user_lane_rect.left() - composer_rect.left()) <= 1
    assert abs(user_lane_rect.right() - composer_rect.right()) <= 1
    assert abs(user_card_rect.right() - composer_rect.right()) <= 1

    widget.close()
    app.processEvents()
