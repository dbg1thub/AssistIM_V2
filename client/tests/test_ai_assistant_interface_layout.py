import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtWidgets import QApplication, QStyleOptionViewItem

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


def _action_confirmation_message(message_id: str = "action-confirm") -> AIMessage:
    message = _message(
        message_id,
        AIMessageRole.ASSISTANT,
        "确认要发送消息给张三吗？\n内容预览：我晚点到\n这是高风险操作，确认后才会继续。",
    )
    message.extra = {
        "ai_action": {
            "state": "waiting_confirmation",
            "waiting": {
                "type": "confirmation",
                "risk": "high",
                "preview": {
                    "operation": "发送消息",
                    "target": "张三",
                    "content": "我晚点到",
                },
            },
        }
    }
    return message


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
        widget.message_list.doItemsLayout()
        app.processEvents()
        bottom_gap = widget.message_list.verticalScrollBar().maximum() - widget.message_list.verticalScrollBar().value()
        assert bottom_gap <= 2

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

    composer_rect = _rect_in_panel(widget, widget.composer_shell)
    assistant_index = widget._message_model.index(0, 0)
    user_index = widget._message_model.index(1, 0)
    assistant_layout = widget._message_delegate.layout_for_index(
        widget.message_list.visualRect(assistant_index),
        assistant_index,
    )
    user_layout = widget._message_delegate.layout_for_index(
        widget.message_list.visualRect(user_index),
        user_index,
    )
    assistant_track_rect = _rect_in_panel(widget, widget.message_list.viewport()).translated(
        assistant_layout.track_rect.topLeft()
    )
    assistant_track_rect.setSize(assistant_layout.track_rect.size())
    user_track_rect = _rect_in_panel(widget, widget.message_list.viewport()).translated(
        user_layout.track_rect.topLeft()
    )
    user_track_rect.setSize(user_layout.track_rect.size())
    user_bubble_rect = _rect_in_panel(widget, widget.message_list.viewport()).translated(
        user_layout.bubble_rect.topLeft()
    )
    user_bubble_rect.setSize(user_layout.bubble_rect.size())

    assert abs(assistant_track_rect.left() - composer_rect.left()) <= 1
    assert abs(assistant_track_rect.right() - composer_rect.right()) <= 1
    assert abs(user_track_rect.left() - composer_rect.left()) <= 1
    assert abs(user_track_rect.right() - composer_rect.right()) <= 1
    assert abs(user_bubble_rect.right() - composer_rect.right()) <= 1
    assert user_layout.text_rect.top() > user_layout.bubble_rect.top()
    assert user_layout.text_rect.bottom() < user_layout.bubble_rect.bottom()

    widget.resize(1024, 900)
    app.processEvents()
    widget._update_input_overlay_positions()
    app.processEvents()

    composer_rect = _rect_in_panel(widget, widget.composer_shell)
    assistant_layout = widget._message_delegate.layout_for_index(
        widget.message_list.visualRect(assistant_index),
        assistant_index,
    )
    user_layout = widget._message_delegate.layout_for_index(
        widget.message_list.visualRect(user_index),
        user_index,
    )
    assistant_track_rect = _rect_in_panel(widget, widget.message_list.viewport()).translated(
        assistant_layout.track_rect.topLeft()
    )
    assistant_track_rect.setSize(assistant_layout.track_rect.size())
    user_track_rect = _rect_in_panel(widget, widget.message_list.viewport()).translated(
        user_layout.track_rect.topLeft()
    )
    user_track_rect.setSize(user_layout.track_rect.size())
    user_bubble_rect = _rect_in_panel(widget, widget.message_list.viewport()).translated(
        user_layout.bubble_rect.topLeft()
    )
    user_bubble_rect.setSize(user_layout.bubble_rect.size())

    assert abs(assistant_track_rect.left() - composer_rect.left()) <= 1
    assert abs(assistant_track_rect.right() - composer_rect.right()) <= 1
    assert abs(user_track_rect.left() - composer_rect.left()) <= 1
    assert abs(user_track_rect.right() - composer_rect.right()) <= 1
    assert abs(user_bubble_rect.right() - composer_rect.right()) <= 1
    assert user_layout.text_rect.top() > user_layout.bubble_rect.top()
    assert user_layout.text_rect.bottom() < user_layout.bubble_rect.bottom()

    widget.close()
    app.processEvents()


def test_ai_assistant_message_delegate_reserves_full_height_for_korean_text() -> None:
    app = QApplication.instance() or QApplication([])
    text = (
        "안녕하세요. 저는 AssistIM의 AI 어시스턴트입니다. "
        "한국어로 자기소개를 드리겠습니다. "
        "사용자님의 메시지를 이해하고 요약, 정리, 답변 생성을 도와드립니다. "
    ) * 5
    widget = AIAssistantInterface()
    widget.resize(900, 720)
    widget.show()
    widget._append_message(_message("korean", AIMessageRole.ASSISTANT, text.strip()))
    app.processEvents()

    index = widget._message_model.index(0, 0)
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, widget.message_list.viewport().width(), 1)
    row_height = widget._message_delegate.sizeHint(option, index).height()
    layout = widget._message_delegate.layout_for_index(QRect(0, 0, option.rect.width(), row_height), index)

    assert layout.text_rect.height() > 0
    assert row_height >= layout.text_rect.bottom() + 1
    assert row_height <= layout.text_rect.height() + 80

    widget.close()
    app.processEvents()


def test_ai_assistant_message_delegate_hits_action_confirmation_controls() -> None:
    app = QApplication.instance() or QApplication([])
    widget = AIAssistantInterface()
    widget.resize(900, 720)
    widget.show()
    widget._append_message(_action_confirmation_message())
    app.processEvents()

    index = widget._message_model.index(0, 0)
    layout = widget._message_delegate.layout_for_index(widget.message_list.visualRect(index), index)

    assert layout.confirmation_rect is not None
    assert layout.confirm_button_rect is not None
    assert layout.cancel_button_rect is not None
    assert widget._message_delegate.action_command_at(
        widget.message_list,
        index,
        layout.confirm_button_rect.center(),
    ) == "confirm"
    assert widget._message_delegate.action_command_at(
        widget.message_list,
        index,
        layout.cancel_button_rect.center(),
    ) == "cancel"

    emitted: list[tuple[str, str]] = []
    widget._on_action_message_requested = lambda message_id, command: emitted.append((message_id, command))

    assert widget._handle_message_list_release(layout.confirm_button_rect.center(), Qt.MouseButton.LeftButton)
    assert widget._handle_message_list_release(layout.cancel_button_rect.center(), Qt.MouseButton.LeftButton)
    assert emitted == [("action-confirm", "confirm"), ("action-confirm", "cancel")]

    widget.close()
    app.processEvents()


def test_ai_assistant_message_copy_uses_bubble_text() -> None:
    app = QApplication.instance() or QApplication([])
    widget = AIAssistantInterface()
    widget.resize(900, 720)
    widget.show()
    widget._append_message(_message("copy-me", AIMessageRole.USER, "给 test3 说我晚点联系他"))
    app.processEvents()

    index = widget._message_model.index(0, 0)
    message = index.data(Qt.ItemDataRole.UserRole)

    assert widget._copy_message_to_clipboard(message)
    assert QApplication.clipboard().text() == "给 test3 说我晚点联系他"

    widget.close()
    app.processEvents()
