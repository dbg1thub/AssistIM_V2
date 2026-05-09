import asyncio
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtWidgets import QApplication, QStyleOptionViewItem

from client.models.ai_assistant import AIMessage, AIMessageRole, AIMessageStatus, AIThread
import client.ui.windows.ai_assistant_interface as assistant_interface_module
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


def _action_running_message(message_id: str = "action-running") -> AIMessage:
    message = _message(message_id, AIMessageRole.ASSISTANT, "")
    message.extra = {
        "ai_action": {
            "state": "running",
            "current_step_id": "draft_message",
            "steps": [
                {
                    "id": "resolve_target",
                    "state": "done",
                    "display_text": "确定联系人",
                },
                {
                    "id": "draft_message",
                    "state": "running",
                    "display_text": "生成草稿",
                    "explanation": "准备确认内容",
                },
                {
                    "id": "confirm_send",
                    "state": "pending",
                    "display_text": "等待确认",
                },
            ],
            "events": [
                {"type": "step_completed", "state": "completed", "step_id": "resolve_target"},
                {"type": "step_started", "state": "started", "step_id": "draft_message"},
            ],
        }
    }
    return message


def _thinking_message(message_id: str = "thinking") -> AIMessage:
    message = _message(message_id, AIMessageRole.ASSISTANT, "", status=AIMessageStatus.PENDING)
    message.extra = {"ai_thinking": {"state": "planning"}}
    return message


def _rect_in_panel(widget: AIAssistantInterface, child) -> QRect:
    top_left = widget.content_panel.mapFromGlobal(child.mapToGlobal(QPoint(0, 0)))
    return QRect(top_left, child.size())


def _tab_route_keys(widget: AIAssistantInterface) -> list[str]:
    return [
        str(widget.thread_tab_bar.tabItem(index).routeKey())
        for index in range(widget.thread_tab_bar.count())
    ]


class _FakeAssistantStore:
    def __init__(self) -> None:
        self.threads: list[AIThread] = []
        self.messages: dict[str, list[AIMessage]] = {}
        self.created = 0
        self.saved_orders: list[list[str]] = []

    async def initialize(self) -> None:
        return None

    async def list_threads(self) -> list[AIThread]:
        return list(self.threads)

    async def create_thread(self, *, title: str = "", model: str = "") -> AIThread:
        self.created += 1
        thread = AIThread(
            thread_id=f"thread-{self.created}",
            title=title or "New Chat",
            model=model,
            sort_order=len(self.threads),
        )
        self.threads.insert(0, thread)
        self.messages[thread.thread_id] = []
        return thread

    async def get_thread(self, thread_id: str) -> AIThread | None:
        return next((thread for thread in self.threads if thread.thread_id == thread_id), None)

    async def list_messages(self, thread_id: str, *, limit: int = 200) -> list[AIMessage]:
        return list(self.messages.get(thread_id, []))[:limit]

    async def find_empty_thread(self) -> AIThread | None:
        for thread in self.threads:
            if not self.messages.get(thread.thread_id):
                return thread
        return None

    async def thread_has_messages(self, thread_id: str) -> bool:
        return bool(self.messages.get(thread_id))

    async def delete_thread(self, thread_id: str) -> None:
        self.threads = [thread for thread in self.threads if thread.thread_id != thread_id]
        self.messages.pop(thread_id, None)

    async def update_thread_order(self, thread_ids: list[str]) -> None:
        self.saved_orders.append(list(thread_ids))
        order = {thread_id: index for index, thread_id in enumerate(thread_ids)}
        self.threads.sort(key=lambda thread: order.get(thread.thread_id, len(order)))
        for index, thread in enumerate(self.threads):
            thread.sort_order = index


def test_ai_assistant_empty_tabs_are_user_created_unique_and_deletable(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    store = _FakeAssistantStore()
    monkeypatch.setattr(assistant_interface_module, "get_ai_assistant_store", lambda _owner_user_id: store)
    widget = AIAssistantInterface(owner_user_id="user-a")
    widget.resize(1000, 700)
    widget.show()
    app.processEvents()

    async def scenario() -> None:
        await widget._reload_threads(select_first=True)
        assert store.created == 0
        assert widget._threads == []
        assert widget._current_thread_id == ""

        await widget._create_and_select_thread()
        assert store.created == 1
        assert widget._current_thread_id == "thread-1"

        await widget._create_and_select_thread()
        assert store.created == 1
        assert widget._current_thread_id == "thread-1"

        await widget._delete_thread("thread-1")
        assert store.threads == []
        assert widget._threads == []
        assert widget._current_thread_id == ""
        assert widget.empty_widget.isVisible()

    try:
        asyncio.run(scenario())
    finally:
        widget.close()
        app.processEvents()


def test_ai_assistant_empty_new_thread_stays_right_and_order_is_saved(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    store = _FakeAssistantStore()
    first = AIThread(thread_id="thread-a", title="A", sort_order=0)
    second = AIThread(thread_id="thread-b", title="B", sort_order=1)
    store.threads = [first, second]
    store.messages = {
        "thread-a": [_message("a-user", AIMessageRole.USER, "A prompt")],
        "thread-b": [_message("b-user", AIMessageRole.USER, "B prompt")],
    }
    monkeypatch.setattr(assistant_interface_module, "get_ai_assistant_store", lambda _owner_user_id: store)
    widget = AIAssistantInterface(owner_user_id="user-a")
    widget.resize(1000, 700)
    widget.show()
    app.processEvents()

    async def scenario() -> None:
        await widget._reload_threads(select_first=True)
        assert _tab_route_keys(widget) == ["thread-a", "thread-b"]

        await widget._create_and_select_thread()
        assert widget._current_thread_id == "thread-1"
        assert _tab_route_keys(widget) == ["thread-a", "thread-b", "thread-1"]

        await widget._persist_thread_tab_order(["thread-b", "thread-a", "thread-1"])
        assert store.saved_orders[-1] == ["thread-b", "thread-a", "thread-1"]
        assert [thread.thread_id for thread in await store.list_threads()] == [
            "thread-b",
            "thread-a",
            "thread-1",
        ]

    try:
        asyncio.run(scenario())
    finally:
        widget.close()
        app.processEvents()


def test_ai_assistant_tab_move_updates_memory_before_deferred_save(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    store = _FakeAssistantStore()
    store.threads = [
        AIThread(thread_id="thread-a", title="A", sort_order=0),
        AIThread(thread_id="thread-b", title="B", sort_order=1),
        AIThread(thread_id="thread-c", title="C", sort_order=2),
    ]
    store.messages = {
        "thread-a": [_message("a-user", AIMessageRole.USER, "A prompt")],
        "thread-b": [_message("b-user", AIMessageRole.USER, "B prompt")],
        "thread-c": [_message("c-user", AIMessageRole.USER, "C prompt")],
    }
    monkeypatch.setattr(assistant_interface_module, "get_ai_assistant_store", lambda _owner_user_id: store)
    widget = AIAssistantInterface(owner_user_id="user-a")
    widget.resize(1000, 700)
    widget.show()
    app.processEvents()

    async def scenario() -> None:
        await widget._reload_threads(select_first=True)
        assert _tab_route_keys(widget) == ["thread-a", "thread-b", "thread-c"]

        widget._sync_thread_order_from_tab_keys(["thread-c", "thread-a", "thread-b"])
        widget._render_thread_tabs()

        assert _tab_route_keys(widget) == ["thread-c", "thread-a", "thread-b"]
        assert [thread.thread_id for thread in widget._threads] == ["thread-c", "thread-a", "thread-b"]
        assert store.saved_orders == []

    try:
        asyncio.run(scenario())
    finally:
        widget.close()
        app.processEvents()


def test_ai_assistant_streaming_layout_keeps_bottom_gap_stable() -> None:
    app = QApplication.instance() or QApplication([])
    widget = AIAssistantInterface(owner_user_id="user-a")
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
    widget = AIAssistantInterface(owner_user_id="user-a")
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
    widget = AIAssistantInterface(owner_user_id="user-a")
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
    widget = AIAssistantInterface(owner_user_id="user-a")
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


def test_ai_assistant_action_status_collapses_and_expands_steps() -> None:
    app = QApplication.instance() or QApplication([])
    widget = AIAssistantInterface(owner_user_id="user-a")
    widget.resize(900, 720)
    widget.show()
    widget._append_message(_action_running_message())
    app.processEvents()

    index = widget._message_model.index(0, 0)
    collapsed_height = widget._message_delegate.sizeHint(
        QStyleOptionViewItem(),
        index,
    ).height()
    collapsed_layout = widget._message_delegate.layout_for_index(
        QRect(0, 0, widget.message_list.viewport().width(), collapsed_height),
        index,
    )

    assert collapsed_layout.status_rect is not None
    message = index.data(Qt.ItemDataRole.UserRole)
    assert widget._message_delegate._action_status_summary_text(
        message.extra,
        animation_frame=0,
    ) == "正在执行：生成草稿 · 1/3"
    assert widget._message_delegate._action_status_text(message.extra).splitlines() == [
        "已完成：确定联系人",
        "正在执行：生成草稿（准备确认内容）",
        "待执行：等待确认",
    ]

    assert widget._handle_message_list_release(collapsed_layout.status_rect.center(), Qt.MouseButton.LeftButton)
    assert widget._message_delegate.is_action_status_expanded("action-running")

    expanded_height = widget._message_delegate.sizeHint(
        QStyleOptionViewItem(),
        index,
    ).height()
    assert expanded_height > collapsed_height

    widget.close()
    app.processEvents()


def test_ai_assistant_thinking_placeholder_uses_stable_delegate_text() -> None:
    app = QApplication.instance() or QApplication([])
    widget = AIAssistantInterface(owner_user_id="user-a")
    widget.resize(900, 720)
    widget.show()
    widget._append_message(_thinking_message())
    app.processEvents()

    index = widget._message_model.index(0, 0)
    message = index.data(Qt.ItemDataRole.UserRole)
    widget._message_delegate.set_animation_frame(0, widget.message_list)
    first = widget._message_delegate._message_display_text(message)
    first_height = widget._message_delegate.sizeHint(QStyleOptionViewItem(), index).height()
    widget._message_delegate.set_animation_frame(2, widget.message_list)
    second = widget._message_delegate._message_display_text(message)
    second_height = widget._message_delegate.sizeHint(QStyleOptionViewItem(), index).height()

    assert first == "正在理解请求"
    assert second == "正在理解请求.."
    assert first_height == second_height

    widget.close()
    app.processEvents()


def test_ai_assistant_message_copy_uses_bubble_text() -> None:
    app = QApplication.instance() or QApplication([])
    widget = AIAssistantInterface(owner_user_id="user-a")
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
