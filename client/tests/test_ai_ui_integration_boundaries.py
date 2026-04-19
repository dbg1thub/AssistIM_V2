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
    assert "self.chat_panel.ai_feature_toggled.connect(self._on_ai_feature_toggled)" in chat_interface
    assert "ai_draft_action_requested" not in chat_panel
    assert "ai_action_requested" not in message_input
    assert "def _on_ai_draft_action_requested" not in chat_interface


def test_ai_menu_is_session_feature_toggle_only() -> None:
    message_input = Path("client/ui/widgets/message_input.py").read_text(encoding="utf-8")

    assert "CheckableMenu" in message_input
    assert "class MarqueeSuggestionButton(PushButton):" in message_input
    assert 'tr("composer.ai.smart_reply", "智能回复")' in message_input
    assert 'tr("composer.ai.auto_translate", "来信翻译")' in message_input
    assert 'tr("composer.ai.polish", "润色")' not in message_input
    assert 'tr("composer.ai.shorten", "缩短")' not in message_input
    assert 'tr("composer.ai.rewrite", "重写")' not in message_input
    assert 'tr("composer.ai.translate", "翻译成中文")' not in message_input
    assert "self.ai_feature_toggled.emit" in message_input
    assert "normalized[:4]" in message_input
    assert "MarqueeSuggestionButton(text, self.reply_suggestion_widget)" in message_input
    assert "def set_reply_suggestion_status(self, text: str) -> None:" in message_input
    assert 'tr("composer.ai.reply_suggestions", "AI 回复")' in message_input


def test_ai_settings_are_exposed_in_settings_interface() -> None:
    settings_interface = Path("client/ui/windows/settings_interface.py").read_text(encoding="utf-8")
    config_module = Path("client/core/config.py").read_text(encoding="utf-8")

    assert "class AIModelSettingCard(SettingCard):" in settings_interface
    assert "detect_local_ai_capabilities" in settings_interface
    assert "installed_local_ai_model_specs" in settings_interface
    assert "cfg.aiModelId" in settings_interface
    assert "cfg.aiGpuAccelerationEnabled" in settings_interface
    assert "self.ai_group = SettingCardGroup" in settings_interface
    assert "ai_model_card" in settings_interface
    assert "ai_gpu_card" in settings_interface
    assert 'aiModelId = ConfigItem(' in config_module
    assert 'aiGpuAccelerationEnabled = ConfigItem(' in config_module


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

    assert 'show_ai_status = getattr(chat_interface, "show_startup_ai_status", None)' in main
    assert 'warmup_ai = getattr(chat_interface, "warmup_startup_ai", None)' in main
    assert "def show_startup_ai_status(self) -> None:" in chat_interface
    assert "def warmup_startup_ai(self) -> None:" in chat_interface
    assert "AI_STATUS_INFOBAR_DEDUPE_SECONDS = 6.0" in chat_interface
    assert "self._ai_status_last_state = \"\"" in chat_interface
    assert "self._ai_status_last_shown_at = 0.0" in chat_interface
    assert "AIHealthState.LOADING" in chat_interface
    assert "self._ai_controller.warmup()" in chat_interface
    assert "self._ai_controller.get_health_status()" in chat_interface
    assert "if status.state == AIHealthState.READY_NOT_LOADED:\n            return" not in chat_interface
    assert "def _should_skip_ai_status_info_bar(self, status, *, explicit_use: bool = False) -> bool:" in chat_interface
    assert "def _record_ai_status_info_bar(self, status, *, explicit_use: bool = False) -> None:" in chat_interface
    assert "def _ai_status_dedupe_state(status) -> str:" in chat_interface
    assert 'return "startup_pending"' in chat_interface
    assert "if explicit_use:\n            return False" in chat_interface
    assert "if explicit_use:\n            return" in chat_interface
    assert "user_message_for_health_status" not in chat_interface
    assert "def _ready_ai_status_message(self, status) -> str:" in chat_interface
    assert '"composer.ai.status.ready_gpu_named"' in chat_interface
    assert '"composer.ai.status.ready_gpu"' in chat_interface
    assert '"composer.ai.status.ready_gpu_hybrid_named"' in chat_interface
    assert '"composer.ai.status.ready_gpu_hybrid"' in chat_interface
    assert '"composer.ai.status.ready_cpu"' in chat_interface
    assert '"composer.ai.status.ready_cpu_fallback"' in chat_interface
    assert '"composer.ai.status.ready_cpu_cuda_missing"' in chat_interface
    assert '"composer.ai.error.cuda_runtime_missing_with_deps"' in chat_interface
    assert '"composer.ai.status.configured_not_loaded"' in chat_interface
    assert '"composer.ai.status.background_loading"' in chat_interface
    assert '"composer.ai.status.loading_in_progress"' in chat_interface
    assert '"composer.ai.status.loading_first_use"' in chat_interface
    assert '"本地 AI 已配置，将在后台加载模型，首次启动可能需要几秒。"' in chat_interface
    assert '"composer.ai.error.runtime_missing"' in chat_interface
    assert 'detail=str(exc)' not in chat_interface

    refresh_start = chat_interface.index("async def _refresh_ai_reply_suggestions")
    load_gate = chat_interface.index("await self._ai_controller.is_model_loaded()", refresh_start)
    generation_call = chat_interface.index("await self._ai_controller.suggest_replies", refresh_start)
    assert refresh_start < load_gate < generation_call


def test_reply_suggestions_use_debounce_and_latest_version_wins() -> None:
    chat_interface = Path("client/ui/windows/chat_interface.py").read_text(encoding="utf-8")

    assert "REPLY_SUGGESTION_DEBOUNCE_MS = 800" in chat_interface
    assert "self._reply_suggestion_version" in chat_interface
    assert "self._reply_suggestion_pending_context" in chat_interface
    assert "self._reply_suggestion_rerun_context" in chat_interface
    assert "self._reply_suggestion_waiting_group" in chat_interface
    assert "self._reply_suggestion_refresh_task" in chat_interface
    assert "def _schedule_reply_suggestion_refresh" in chat_interface
    assert "def _on_reply_suggestion_timer_timeout" in chat_interface
    assert "def _on_reply_suggestion_refresh_done" in chat_interface
    assert "def _queue_reply_suggestion_group_update" in chat_interface
    assert "def _safe_clear_reply_suggestion_feedback(self) -> None:" in chat_interface
    assert "def _is_reply_suggestion_timer_alive(self) -> bool:" in chat_interface
    assert "[ai-perf] reply_suggestion_grouped" in chat_interface
    assert "[ai-perf] reply_suggestion_rerun_after_group" in chat_interface
    assert "[ai-perf] reply_suggestion_result_skipped" in chat_interface
    assert "self._reply_suggestion_refresh_task.cancel()" in chat_interface
    assert "reply_version != self._reply_suggestion_version" in chat_interface
    assert "self._schedule_reply_suggestion_refresh(message.session_id)" in chat_interface
    assert "composer.ai.reply_generating_progress" in chat_interface


def test_message_translation_ui_boundaries_are_wired() -> None:
    chat_interface = Path("client/ui/windows/chat_interface.py").read_text(encoding="utf-8")
    message_delegate = Path("client/delegates/message_delegate.py").read_text(encoding="utf-8")
    message_manager = Path("client/managers/message_manager.py").read_text(encoding="utf-8")
    chat_controller = Path("client/ui/controllers/chat_controller.py").read_text(encoding="utf-8")

    assert 'TRANSLATION_UPDATED = "message_translation_updated"' in message_manager
    assert "async def update_message_translation(self, message_id: str, translation: dict[str, Any])" in message_manager
    assert "await self._event_bus.emit(" in message_manager
    assert "MessageEvent.TRANSLATION_UPDATED" in message_manager
    assert "async def update_message_translation(self, message_id: str, translation: dict[str, Any])" in chat_controller
    assert "self._subscribe_sync(MessageEvent.TRANSLATION_UPDATED, self._on_translation_updated)" in chat_interface
    assert "def _on_translation_updated(self, data: dict) -> None:" in chat_interface
    assert "def _schedule_auto_message_translation(self, message: ChatMessage) -> None:" in chat_interface
    assert "def _auto_translation_skip_reason(" in chat_interface
    assert "self._schedule_auto_message_translation(message)" in chat_interface
    assert "if not manual and message.is_self:" in chat_interface
    assert "if self._can_translate_message_manually(message):" in chat_interface
    assert 'mode="manual"' in chat_interface
    assert "mode=\"auto\"" in chat_interface
    assert "await self._ai_controller.is_model_loaded()" in chat_interface
    assert "await self._ai_controller.translate_message(" in chat_interface
    assert "[ai-perf] translation_skip" in chat_interface
    assert "[ai-perf] translation_start" in chat_interface
    assert "[ai-perf] translation_waiting" in chat_interface
    assert "[ai-perf] translation_applied" in chat_interface
    assert 'if manual and status == "failed" and self._is_current_message_context(message, generation):' in chat_interface
    assert "AI_TRANSLATION_EXTRA_KEY" in message_delegate
    assert "def _translation_display_text(self, message: ChatMessage) -> str:" in message_delegate
    assert "def _draw_translation_content(self, painter: QPainter, rect: QRect, message: ChatMessage) -> None:" in message_delegate
    assert "def _primary_text_content_rect(self, content_rect: QRect, message: ChatMessage) -> QRect:" in message_delegate
    assert 'tr("chat.translation.pending", "正在翻译...")' in message_delegate
    assert 'tr("chat.translation.queued", "AI 正忙，等待当前任务完成...")' in message_delegate


def test_summary_infobar_only_targets_current_active_session() -> None:
    chat_interface = Path("client/ui/windows/chat_interface.py").read_text(encoding="utf-8")

    assert "ConversationSummaryEvent.READY" in chat_interface
    assert "self._subscribe_sync(ConversationSummaryEvent.READY, self._on_conversation_summary_ready)" in chat_interface
    assert "def _on_conversation_summary_ready(self, data: dict) -> None:" in chat_interface
    assert 'if session_id != str(self._current_session_id or "").strip():' in chat_interface
    assert "if not self._can_mark_session_read():" in chat_interface
    assert "self._summary_notified_buckets" in chat_interface
    assert "self._summary_info_bar_last_shown_at" in chat_interface
    assert '"chat.summary.updated"' in chat_interface
    assert '"chat.summary.completed"' in chat_interface


def test_ai_perf_ui_logging_uses_decision_fields_without_content() -> None:
    chat_interface = Path("client/ui/windows/chat_interface.py").read_text(encoding="utf-8")

    assert "[ai-perf] reply_suggestion_scheduled" in chat_interface
    assert "[ai-perf] reply_suggestion_skip" in chat_interface
    assert "[ai-perf] reply_suggestion_start" in chat_interface
    assert "[ai-perf] reply_suggestion_applied" in chat_interface
    assert "def _auto_reply_trigger_skip_reason(self, session_id: str) -> str:" in chat_interface
    assert "reason=model_not_loaded" in chat_interface
    assert "message.content=%s" not in chat_interface
    assert "prompt=%s" not in chat_interface


def test_ai_ui_i18n_resources_are_registered() -> None:
    required_keys = {
        "composer.ai.title",
        "composer.ai.reply_suggestions",
        "composer.ai.smart_reply",
        "composer.ai.auto_translate",
        "composer.ai.running",
        "composer.ai.reply_waiting",
        "composer.ai.reply_generating",
        "composer.ai.reply_generating_progress",
        "composer.ai.status.configured_not_loaded",
        "composer.ai.status.loading_first_use",
        "composer.ai.status.background_loading",
        "composer.ai.status.loading_in_progress",
        "composer.ai.status.ready",
        "composer.ai.status.ready_gpu_named",
        "composer.ai.status.ready_gpu",
        "composer.ai.status.ready_gpu_hybrid_named",
        "composer.ai.status.ready_gpu_hybrid",
        "composer.ai.status.ready_cpu",
        "composer.ai.status.ready_cpu_fallback",
        "composer.ai.status.ready_cpu_cuda_missing",
        "composer.ai.status.unknown_model",
        "composer.ai.status.disabled",
        "composer.ai.error.model_missing",
        "composer.ai.error.runtime_missing",
        "composer.ai.error.cuda_runtime_missing",
        "composer.ai.error.cuda_runtime_missing_with_deps",
        "composer.ai.error.provider_unavailable",
        "composer.ai.error.local_required",
        "composer.ai.error.model_load_failed",
        "composer.ai.error.resource_exhausted",
        "composer.ai.error.context_too_long",
        "composer.ai.error.output_invalid",
        "composer.ai.failed",
        "settings.card.ai_gpu.gpu_unknown",
        "settings.card.ai_gpu.content_warning_vram",
        "chat.translation.pending",
        "chat.translation.queued",
        "chat.translation.failed",
        "chat.summary.updated",
        "chat.summary.completed",
    }

    for language in ("zh-CN", "en-US", "ko-KR"):
        payload = json.loads(Path(f"client/resources/i18n/{language}.json").read_text(encoding="utf-8"))
        missing = sorted(required_keys - set(payload))
        assert missing == []
