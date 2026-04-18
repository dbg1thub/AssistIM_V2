import json
from pathlib import Path


def test_ai_ui_uses_controller_boundary() -> None:
    message_input = Path("client/ui/widgets/message_input.py").read_text(encoding="utf-8")
    chat_panel = Path("client/ui/widgets/chat_panel.py").read_text(encoding="utf-8")
    chat_interface = Path("client/ui/windows/chat_interface.py").read_text(encoding="utf-8")

    assert "from client.managers.ai_assist_manager" not in message_input
    assert "from client.managers.ai_assist_manager" not in chat_panel
    assert "from client.managers.ai_assist_manager" not in chat_interface
    assert "from client.ui.controllers.ai_controller import" in chat_interface
    assert "get_ai_controller" in chat_interface
    assert "self.chat_panel.ai_draft_action_requested.connect(self._on_ai_draft_action_requested)" in chat_interface


def test_ai_reply_candidates_fill_draft_only() -> None:
    message_input = Path("client/ui/widgets/message_input.py").read_text(encoding="utf-8")
    chat_interface = Path("client/ui/windows/chat_interface.py").read_text(encoding="utf-8")

    assert "def _apply_reply_suggestion(self, text: str) -> None:" in message_input
    assert "self.replace_plain_text_draft(text)" in message_input
    assert "self.ai_reply_suggestion_selected.emit(text)" in message_input
    assert "def _on_ai_reply_suggestion_selected(self, _text: str) -> None:" in chat_interface
    assert "self._ai_controller.clear_suggestions(self._current_session_id)" in chat_interface


def test_ai_status_infobar_and_background_generation_boundaries() -> None:
    chat_interface = Path("client/ui/windows/chat_interface.py").read_text(encoding="utf-8")
    main = Path("client/main.py").read_text(encoding="utf-8")

    assert "show_ai_status = getattr(chat_interface, \"show_startup_ai_status\", None)" in main
    assert "warmup_ai = getattr(chat_interface, \"warmup_startup_ai\", None)" in main
    assert "def show_startup_ai_status(self) -> None:" in chat_interface
    assert "def warmup_startup_ai(self) -> None:" in chat_interface
    assert "AIHealthState.LOADING" in chat_interface
    assert "self._ai_controller.warmup()" in chat_interface
    assert "self._ai_controller.get_health_status()" in chat_interface
    assert "explicit_use=True" in chat_interface
    assert "user_message_for_health_status" not in chat_interface
    assert '"composer.ai.status.configured_not_loaded"' in chat_interface
    assert '"composer.ai.status.background_loading"' in chat_interface
    assert '"composer.ai.status.loading_in_progress"' in chat_interface
    assert '"composer.ai.status.loading_first_use"' in chat_interface
    assert '"composer.ai.error.runtime_missing"' in chat_interface

    refresh_start = chat_interface.index("async def _refresh_ai_reply_suggestions")
    load_gate = chat_interface.index("await self._ai_controller.is_model_loaded()", refresh_start)
    generation_call = chat_interface.index("await self._ai_controller.suggest_replies", refresh_start)
    assert refresh_start < load_gate < generation_call


def test_ai_ui_i18n_resources_are_registered() -> None:
    required_keys = {
        "composer.ai.title",
        "composer.ai.reply_suggestions",
        "composer.ai.empty_draft",
        "composer.ai.polish",
        "composer.ai.shorten",
        "composer.ai.translate",
        "composer.ai.rewrite",
        "composer.ai.running",
        "composer.ai.status.configured_not_loaded",
        "composer.ai.status.loading_first_use",
        "composer.ai.status.background_loading",
        "composer.ai.status.loading_in_progress",
        "composer.ai.status.ready",
        "composer.ai.status.disabled",
        "composer.ai.error.model_missing",
        "composer.ai.error.runtime_missing",
        "composer.ai.error.provider_unavailable",
        "composer.ai.error.local_required",
        "composer.ai.error.model_load_failed",
        "composer.ai.error.resource_exhausted",
        "composer.ai.error.context_too_long",
        "composer.ai.error.output_invalid",
        "composer.ai.failed",
    }

    for language in ("zh-CN", "en-US", "ko-KR"):
        payload = json.loads(Path(f"client/resources/i18n/{language}.json").read_text(encoding="utf-8"))
        missing = sorted(required_keys - set(payload))
        assert missing == []
