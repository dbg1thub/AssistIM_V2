import asyncio
from types import SimpleNamespace

from client.ui.controllers.session_controller import SessionController


class _FakeSessionManager:
    def __init__(self) -> None:
        self.sessions = [
            SimpleNamespace(session_id="group-session", avatar="/uploads/groups/1.png"),
            SimpleNamespace(session_id="direct-session", avatar="/uploads/users/1.png"),
        ]
        self.current_session = self.sessions[0]
        self.current_session_id = "group-session"
        self.ai_reply_toggle_calls: list[tuple[str, bool]] = []
        self.ai_translate_toggle_calls: list[tuple[str, bool]] = []

    async def set_ai_reply_suggestions_enabled(self, session_id: str, enabled: bool) -> None:
        self.ai_reply_toggle_calls.append((session_id, enabled))

    async def set_ai_auto_translate_enabled(self, session_id: str, enabled: bool) -> None:
        self.ai_translate_toggle_calls.append((session_id, enabled))


def test_session_controller_get_session_reads_cached_session() -> None:
    controller = SessionController.__new__(SessionController)
    controller._session_manager = _FakeSessionManager()
    controller._initialized = False

    session = controller.get_session("direct-session")

    assert session is controller._session_manager.sessions[1]


def test_session_controller_get_sessions_returns_snapshot_list() -> None:
    controller = SessionController.__new__(SessionController)
    controller._session_manager = _FakeSessionManager()
    controller._initialized = False

    sessions = controller.get_sessions()

    assert [item.session_id for item in sessions] == ["group-session", "direct-session"]
    assert sessions is not controller._session_manager.sessions


def test_session_controller_delegates_ai_feature_toggles() -> None:
    async def scenario() -> None:
        controller = SessionController.__new__(SessionController)
        controller._session_manager = _FakeSessionManager()
        controller._initialized = False

        await controller.set_ai_reply_suggestions_enabled("direct-session", True)
        await controller.set_ai_auto_translate_enabled("direct-session", False)

        assert controller._session_manager.ai_reply_toggle_calls == [("direct-session", True)]
        assert controller._session_manager.ai_translate_toggle_calls == [("direct-session", False)]

    asyncio.run(scenario())
