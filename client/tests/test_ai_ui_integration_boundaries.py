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
    resource_probe = Path("client/services/local_model_resource_probe.py").read_text(encoding="utf-8")

    assert "class AIModelSettingCard(SettingCard):" in settings_interface
    assert "class LocalModelResourcesSettingCard(SettingCard):" in settings_interface
    assert "class LocalModelResourcesDialog(QDialog):" in settings_interface
    assert "class LocalModelImportWorker(QObject):" in settings_interface
    assert "probe_local_model_resources" in settings_interface
    assert "LocalModelResourceImporter" in settings_interface
    assert "QFileDialog.getOpenFileName" in settings_interface
    assert "QFileDialog.getExistingDirectory" in settings_interface
    assert "QDesktopServices.openUrl" in settings_interface
    assert "self.open_models_dir_button = PushButton" in settings_interface
    assert "self.import_chat_model_button = PushButton" in settings_interface
    assert "self.import_embedding_model_button = PushButton" in settings_interface
    assert "self.import_voice_model_button = PushButton" in settings_interface
    assert "def _open_models_dir(self) -> None:" in settings_interface
    assert "def _import_chat_model(self) -> None:" in settings_interface
    assert "def _import_embedding_model(self) -> None:" in settings_interface
    assert "def _import_voice_model(self) -> None:" in settings_interface
    assert "def _run_import_job(self, job, *, success_content: str) -> None:" in settings_interface
    assert "detect_local_ai_capabilities" in settings_interface
    assert "installed_local_ai_model_specs" in settings_interface
    assert "cfg.aiModelId" in settings_interface
    assert "cfg.aiGpuAccelerationEnabled" in settings_interface
    assert "self.ai_group = SettingCardGroup" in settings_interface
    assert "ai_model_card" in settings_interface
    assert "ai_gpu_card" in settings_interface
    assert "self.ai_resources_card = LocalModelResourcesSettingCard" in settings_interface
    assert "self.ai_group.addSettingCard(self.ai_resources_card)" in settings_interface
    assert "self.ai_resources_card.clicked.connect(self._open_local_model_resources_dialog)" in settings_interface
    assert "def _open_local_model_resources_dialog(self) -> None:" in settings_interface
    assert "def _refresh_report(self) -> None:" in settings_interface
    assert 'aiModelId = ConfigItem(' in config_module
    assert 'aiGpuAccelerationEnabled = ConfigItem(' in config_module
    assert "get_ai_service" not in settings_interface
    assert "get_local_voice_transcription_runtime" not in settings_interface
    assert "get_local_embedding_runtime" not in settings_interface
    assert "shutil." not in settings_interface
    assert "os.replace" not in settings_interface
    assert "LocalGGUFRuntime(" not in resource_probe
    assert "WhisperModel" not in resource_probe
    assert "Llama(" not in resource_probe


def test_developer_server_switch_is_source_runtime_only() -> None:
    settings_interface = Path("client/ui/windows/settings_interface.py").read_text(encoding="utf-8")
    config_module = Path("client/core/config.py").read_text(encoding="utf-8")
    config_backend_module = Path("client/core/config_backend.py").read_text(encoding="utf-8")

    assert "def is_development_runtime() -> bool:" in config_backend_module
    assert 'serverUseLocalhost = ConfigItem(' in config_module
    assert '"Server",\n        "UseLocalhost",' in config_module
    assert "is_development_runtime" in settings_interface
    assert "self.developer_group = SettingCardGroup" in settings_interface
    assert "self.server_localhost_card = SwitchSettingCard" in settings_interface
    assert "cfg.serverUseLocalhost" in settings_interface
    assert "if self._developer_settings_enabled:" in settings_interface


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


def test_voice_transcription_right_click_flow_is_wired() -> None:
    message_manager = Path("client/managers/message_manager.py").read_text(encoding="utf-8")
    chat_controller = Path("client/ui/controllers/chat_controller.py").read_text(encoding="utf-8")
    chat_interface = Path("client/ui/windows/chat_interface.py").read_text(encoding="utf-8")
    message_delegate = Path("client/delegates/message_delegate.py").read_text(encoding="utf-8")
    requirements = Path("requirements.txt").read_text(encoding="utf-8")

    assert "faster-whisper" in requirements
    assert 'VOICE_TRANSCRIPT_UPDATED = "message_voice_transcript_updated"' in message_manager
    assert "async def update_message_voice_transcript(self, message_id: str, transcript: dict[str, Any])" in message_manager
    assert "async def update_message_voice_transcript(self, message_id: str, transcript: dict[str, Any])" in chat_controller
    assert "self._subscribe_sync(MessageEvent.VOICE_TRANSCRIPT_UPDATED, self._on_voice_transcript_updated)" in chat_interface
    assert 'transcribe_action = Action(tr("chat.context.transcribe_voice", "转文字"), self)' in chat_interface
    assert "def _schedule_voice_transcription(self, message: ChatMessage, *, generation: int) -> None:" in chat_interface
    assert "get_local_voice_transcription_runtime" in chat_interface
    assert "VOICE_TRANSCRIPT_EXTRA_KEY" in message_delegate
    assert "def _voice_transcript_display_text(self, message: ChatMessage) -> str:" in message_delegate
    assert 'tr("chat.voice_transcript.pending", "正在转文字...")' in message_delegate


def test_file_summary_right_click_flow_is_wired() -> None:
    message_manager = Path("client/managers/message_manager.py").read_text(encoding="utf-8")
    chat_controller = Path("client/ui/controllers/chat_controller.py").read_text(encoding="utf-8")
    chat_interface = Path("client/ui/windows/chat_interface.py").read_text(encoding="utf-8")
    message_delegate = Path("client/delegates/message_delegate.py").read_text(encoding="utf-8")
    prompt_builder = Path("client/managers/ai_prompt_builder.py").read_text(encoding="utf-8")

    assert 'FILE_ANALYSIS_UPDATED = "message_file_analysis_updated"' in message_manager
    assert "async def update_message_file_analysis(" in message_manager
    assert "async def update_message_file_analysis(" in chat_controller
    assert "self._subscribe_sync(MessageEvent.FILE_ANALYSIS_UPDATED, self._on_file_analysis_updated)" in chat_interface
    assert "file_summary_action_text = self._file_summary_action_text(message)" in chat_interface
    assert "file_summary_action = Action(file_summary_action_text, self)" in chat_interface
    assert 'copy_file_summary_action = Action(tr("chat.context.copy_file_summary", "复制总结内容"), self)' in chat_interface
    assert "def _file_summary_action_text(self, message: ChatMessage) -> str:" in chat_interface
    assert "def _has_ready_file_summary(message: ChatMessage) -> bool:" in chat_interface
    assert "def _has_file_summary_terminal_state(message: ChatMessage) -> bool:" in chat_interface
    assert "def _ready_file_summary_text(message: ChatMessage) -> str:" in chat_interface
    assert "def _copy_file_summary_to_clipboard(self, message: ChatMessage) -> None:" in chat_interface
    assert "def _schedule_file_summary(self, message: ChatMessage, *, generation: int, force: bool = False) -> None:" in chat_interface
    assert "self._schedule_file_summary(\n                    msg,\n                    generation=current,\n                    force=self._has_file_summary_terminal_state(msg)," in chat_interface
    assert "LocalFileTextExtractor" in chat_interface
    assert "summarize_file_text" in chat_interface
    assert "FILE_SUMMARY_EXTRA_KEY" in message_delegate
    assert "def _file_summary_display_text(self, message: ChatMessage) -> str:" in message_delegate
    assert "draw_attachment_card(\n            painter,\n            rect," in message_delegate
    assert "card_rect = QRect(rect.x(), rect.y(), rect.width(), min(self.FILE_HEIGHT, rect.height()))" not in message_delegate
    assert "def _draw_file_summary_content(self, painter: QPainter, rect: QRect, summary_text: str) -> None:" in message_delegate
    assert "summary_rect = rect.adjusted(10, self.FILE_HEIGHT + self.TRANSLATION_TOP_GAP, -10, -8)" in message_delegate
    assert "painter.drawLine(rect.x() + 10, divider_y, rect.right() - 10, divider_y)" in message_delegate
    assert "def build_file_summary_request(" in prompt_builder


def test_local_ai_artifact_backfill_is_wired_after_authenticated_startup() -> None:
    main_py = Path("client/main.py").read_text(encoding="utf-8")
    indexing_service = Path("client/services/ai_memory_indexing_service.py").read_text(encoding="utf-8")
    database = Path("client/storage/database.py").read_text(encoding="utf-8")

    assert "from client.services.ai_memory_indexing_service import get_ai_memory_indexing_service" in main_py
    assert "self.create_task(self._sync_ready_local_ai_memory_artifacts(generation))" in main_py
    assert "async def _sync_ready_local_ai_memory_artifacts(self, generation: int) -> None:" in main_py
    assert "sync_ready_local_artifact_messages(limit=1000)" in main_py
    assert "async def sync_ready_local_artifact_messages(self, *, limit: int = 500)" in indexing_service
    assert "async def list_local_ai_artifact_messages(self, *, limit: int = 500)" in database


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
        "ai_assistant.message.cancelled",
        "ai_assistant.message.truncated_hint",
        "ai_assistant.message.failed_hint",
        "ai_assistant.attachment.add",
        "ai_assistant.attachment.remove",
        "ai_assistant.attachment.default_prompt",
        "ai_assistant.error.vision_projector_missing",
        "ai_assistant.error.vision_unavailable",
        "ai_assistant.preview.generating",
        "ai_assistant.preview.cancelled",
        "ai_assistant.preview.failed",
        "ai_assistant.delete.confirm_title",
        "ai_assistant.delete.confirm_content",
        "ai_assistant.delete.confirm_action",
        "settings.card.ai_gpu.gpu_unknown",
        "settings.card.ai_gpu.content_warning_vram",
        "settings.card.ai_resources.title",
        "settings.card.ai_resources.content",
        "settings.card.ai_resources.action",
        "settings.local_model_resources.title",
        "settings.local_model_resources.subtitle",
        "settings.local_model_resources.open_models_dir",
        "settings.local_model_resources.import_chat_model",
        "settings.local_model_resources.import_embedding_model",
        "settings.local_model_resources.import_voice_model",
        "settings.local_model_resources.refresh",
        "settings.local_model_resources.close",
        "settings.local_model_resources.busy",
        "settings.local_model_resources.import_success.title",
        "settings.local_model_resources.import_success.content",
        "settings.local_model_resources.import_failed.title",
        "settings.local_model_resources.import_failed.content",
        "settings.local_model_resources.file_filter.gguf",
        "settings.local_model_resources.select_voice_dir_title",
        "settings.local_model_resources.status.ready",
        "settings.local_model_resources.status.missing",
        "settings.local_model_resources.status.dependency_missing",
        "settings.local_model_resources.status.config_disabled",
        "settings.local_model_resources.section.models",
        "settings.local_model_resources.section.dependencies",
        "settings.local_model_resources.chat_model",
        "settings.local_model_resources.embedding_model",
        "settings.local_model_resources.voice_model",
        "settings.local_model_resources.llama_cpp",
        "settings.local_model_resources.llama_cpp_embedding",
        "settings.local_model_resources.faster_whisper",
        "settings.local_model_resources.cuda",
        "settings.local_model_resources.path",
        "settings.local_model_resources.size",
        "chat.translation.pending",
        "chat.translation.queued",
        "chat.translation.failed",
        "chat.context.summarize_file",
        "chat.context.resummarize_file",
        "chat.context.copy_file_summary",
        "chat.file_summary.pending",
        "chat.file_summary.extracting",
        "chat.file_summary.failed",
        "chat.file_summary.failed_short",
        "chat.file_summary.extract_failed",
        "chat.file_summary.unsupported_type",
        "chat.file_summary.file_too_large",
        "chat.file_summary.too_many_pages",
        "chat.file_summary.empty",
        "chat.file_summary.dependency_missing",
        "chat.file_summary.copied",
        "chat.summary.updated",
        "chat.summary.completed",
    }

    for language in ("zh-CN", "en-US", "ko-KR"):
        payload = json.loads(Path(f"client/resources/i18n/{language}.json").read_text(encoding="utf-8"))
        missing = sorted(required_keys - set(payload))
        assert missing == []


def test_ai_assistant_rename_capability_exists_without_visible_entry() -> None:
    assistant_interface = Path("client/ui/windows/ai_assistant_interface.py").read_text(encoding="utf-8")

    assert "def rename_current_thread(self, title: str) -> asyncio.Task | None:" in assistant_interface
    assert "async def rename_thread(self, thread_id: str, title: str) -> AIThread | None:" in assistant_interface
    assert "await self._store.update_thread_title(normalized_thread_id, title)" in assistant_interface
    assert "aiAssistantHeaderRenameButton" not in assistant_interface


def test_ai_assistant_delete_uses_confirmation_dialog() -> None:
    assistant_interface = Path("client/ui/windows/ai_assistant_interface.py").read_text(encoding="utf-8")

    assert "class DeleteAIThreadConfirmDialog(MessageBoxBase):" in assistant_interface
    assert 'tr("ai_assistant.delete.confirm_title", "Delete Chat")' in assistant_interface
    assert 'tr("ai_assistant.delete.confirm_action", "Delete")' in assistant_interface
    assert "dialog = DeleteAIThreadConfirmDialog(" in assistant_interface
    assert "if dialog.exec() != QDialog.DialogCode.Accepted:" in assistant_interface


def test_ai_action_footer_does_not_repeat_pending_response_text() -> None:
    assistant_delegate = Path("client/delegates/ai_assistant_message_delegate.py").read_text(encoding="utf-8")
    footer_function = assistant_delegate.split("def _action_footer_text", 1)[1].split(
        "\n\n    @classmethod\n    def _action_status_text",
        1,
    )[0]

    assert 'if state == "waiting_confirmation":' in footer_function
    assert 'return "等待你确认后继续。"' in footer_function
    assert 'if state == "waiting_clarification":' in footer_function
    assert 'return "等待你补充信息后继续。"' in footer_function
    assert "response_text" not in footer_function


def test_ai_action_step_status_area_uses_safe_steps_and_events() -> None:
    assistant_delegate = Path("client/delegates/ai_assistant_message_delegate.py").read_text(encoding="utf-8")
    status_function = assistant_delegate.split("def _action_status_text", 1)[1].split(
        "\n\n    @classmethod\n    def _step_state_from_events",
        1,
    )[0]

    assert "steps = [item for item in list(action.get(\"steps\") or [])" in status_function
    assert "events = [item for item in list(action.get(\"events\") or [])" in status_function
    assert "cls._step_state_from_events(step_id, events)" in status_function
    assert "cls._step_state_label" in status_function
    assert '"running": "正在执行"' in assistant_delegate
    assert '"done": "已完成"' in assistant_delegate
    assert '"waiting_confirmation": "等待确认"' in assistant_delegate
    assert '"waiting_clarification": "等待补充"' in assistant_delegate
    assert '"failed": "执行失败"' in assistant_delegate
    assert '"retrying": "正在重试"' in assistant_delegate
    assert "response_text" not in status_function
    assert "waiting_payload" not in status_function

    assert "status_rect = None" in assistant_delegate
    assert "self._action_status_text(message.extra)" in assistant_delegate
    assert "self._draw_auxiliary_text(painter, layout.status_rect" in assistant_delegate


def test_ai_action_terminal_state_does_not_render_step_status() -> None:
    from client.delegates.ai_assistant_message_delegate import AIAssistantMessageDelegate

    terminal_extra = {
        "ai_action": {
            "state": "done",
            "steps": [
                {
                    "id": "resolve_target",
                    "state": "done",
                    "display_text": "确定联系人",
                },
                {
                    "id": "send_message",
                    "state": "done",
                    "display_text": "发送消息",
                },
            ],
            "events": [
                {"type": "step_completed", "step_id": "resolve_target"},
                {"type": "step_completed", "step_id": "send_message"},
            ],
        }
    }
    assert AIAssistantMessageDelegate._action_status_text(terminal_extra) == ""

    waiting_extra = {
        "ai_action": {
            "state": "waiting_confirmation",
            "steps": [
                {
                    "id": "confirm_send",
                    "state": "waiting_confirmation",
                    "display_text": "确认发送",
                }
            ],
            "events": [{"type": "step_waiting_confirmation", "step_id": "confirm_send"}],
        }
    }
    assert AIAssistantMessageDelegate._action_status_text(waiting_extra) == "等待确认：确认发送"

    retrying_extra = {
        "ai_action": {
            "state": "running",
            "steps": [
                {
                    "id": "resolve_target",
                    "state": "running",
                    "display_text": "确定联系人",
                }
            ],
            "events": [{"type": "step_retrying", "state": "retrying", "step_id": "resolve_target"}],
        }
    }
    assert AIAssistantMessageDelegate._action_status_text(retrying_extra) == "正在重试：确定联系人"

    resource_limit_extra = {
        "ai_action": {
            "state": "failed",
            "steps": [
                {
                    "id": "search_memory",
                    "state": "done",
                    "display_text": "检索聊天记录",
                }
            ],
            "events": [
                {"type": "step_completed", "state": "completed", "step_id": "search_memory"},
                {"type": "plan_resource_limit_exceeded", "state": "failed", "step_id": "search_memory"},
            ],
        }
    }
    assert AIAssistantMessageDelegate._action_status_text(resource_limit_extra) == "执行失败：检索聊天记录"


def test_ai_action_status_renders_structured_explanation_without_reasoning_chain() -> None:
    from client.delegates.ai_assistant_message_delegate import AIAssistantMessageDelegate

    running_extra = {
        "ai_action": {
            "state": "running",
            "steps": [
                {
                    "id": "search_memory",
                    "state": "running",
                    "action": "memory.search",
                    "display_text": "检索聊天记录",
                    "explanation": "只读取本地记忆索引",
                    "reasoning": "完整推理链不应展示",
                    "thought": "模型思考不应展示",
                    "prompt": "planner prompt 不应展示",
                    "raw_output": "模型原始输出不应展示",
                },
                {
                    "id": "summarize_memory",
                    "state": "pending",
                    "action": "memory.summarize",
                    "explanation": "根据检索证据总结",
                },
            ],
            "events": [{"type": "step_started", "state": "started", "step_id": "search_memory"}],
            "reasoning": "plan 级推理链不应展示",
            "raw_output": "plan 原始输出不应展示",
        }
    }

    status = AIAssistantMessageDelegate._action_status_text(running_extra)

    assert "正在执行：检索聊天记录（只读取本地记忆索引）" in status
    assert "待执行：根据检索证据总结" in status
    assert "完整推理链不应展示" not in status
    assert "模型思考不应展示" not in status
    assert "planner prompt 不应展示" not in status
    assert "模型原始输出不应展示" not in status
    assert "plan 级推理链不应展示" not in status
    assert "plan 原始输出不应展示" not in status

    cancelled_extra = {
        "ai_action": {
            "state": "cancelled",
            "steps": [
                {
                    "id": "search_memory",
                    "state": "cancelled",
                    "display_text": "检索聊天记录",
                    "explanation": "只读取本地记忆索引",
                }
            ],
        }
    }
    assert AIAssistantMessageDelegate._action_status_text(cancelled_extra) == ""


def test_ai_assistant_tries_action_workflow_before_rag_and_ai_chat() -> None:
    assistant_interface = Path("client/ui/windows/ai_assistant_interface.py").read_text(encoding="utf-8")
    send_prompt = assistant_interface.split("async def _send_prompt", 1)[1].split(
        "\n    async def _run_stream",
        1,
    )[0]
    regenerate = assistant_interface.split("async def _regenerate_last", 1)[1].split(
        "\n    def _on_clear_clicked",
        1,
    )[0]

    assert "from client.managers.ai_action_permission_policy import AIPermissionScope" in assistant_interface
    assert "from client.managers.ai_action_workflow import AIActionWorkflow" in assistant_interface
    assert "permission_scope_provider=self._current_action_permission_scope" in assistant_interface
    assert "action_result = await self._action_workflow.handle_user_turn" in send_prompt
    assert "has_attachments=bool(attachments)" in send_prompt
    assert "progress_callback=on_action_progress" in send_prompt
    assert "if action_result.handled:" in send_prompt
    assert "await self._handle_action_turn_result(" in send_prompt
    assert "assistant_message=action_message" in send_prompt
    assert "async def _upsert_action_progress_message(" in assistant_interface
    assert "status=AIMessageStatus.PENDING" in assistant_interface.split("async def _upsert_action_progress_message", 1)[1].split(
        "\n    async def _run_stream",
        1,
    )[0]
    assert "build_rag_context_for_ai_chat" in send_prompt
    assert "rag_history_messages = [" in send_prompt
    assert "if message.message_id != user_message.message_id" in send_prompt
    assert "memory_context_lines=memory_context.lines" in send_prompt
    assert "_prompt_builder.build_ai_chat_request" in send_prompt
    assert send_prompt.index("_action_workflow.handle_user_turn") < send_prompt.index(
        "build_rag_context_for_ai_chat"
    )
    assert send_prompt.index("build_rag_context_for_ai_chat") < send_prompt.index(
        "_prompt_builder.build_ai_chat_request"
    )

    assert "action_result = await self._action_workflow.handle_user_turn" in regenerate
    assert "has_attachments=bool(attachments)" in regenerate
    assert "progress_callback=on_action_progress" in regenerate
    assert "if action_result.handled:" in regenerate
    assert "await self._handle_action_turn_result(" in regenerate
    assert "assistant_message=action_message" in regenerate
    assert "build_rag_context_for_ai_chat" in regenerate
    assert "rag_history_messages = [" in regenerate
    assert "if message.message_id != last_user.message_id" in regenerate
    assert "memory_context_lines=memory_context.lines" in regenerate
    assert "_prompt_builder.build_ai_chat_request" in regenerate
    assert regenerate.index("_action_workflow.handle_user_turn") < regenerate.index(
        "build_rag_context_for_ai_chat"
    )
    assert regenerate.index("build_rag_context_for_ai_chat") < regenerate.index(
        "_prompt_builder.build_ai_chat_request"
    )

    assert "async def _handle_action_turn_result(" in assistant_interface
    assert "assistant_message: AIMessage | None = None" in assistant_interface
    assert "extra=action_result.message_extra" in assistant_interface
    assert "memory_context_lines=action_result.memory_context_lines" in assistant_interface
    assert "await self._action_workflow.finish_streamed_action(" in assistant_interface


def test_ai_assistant_permission_scope_allows_local_account_memory() -> None:
    assistant_interface = Path("client/ui/windows/ai_assistant_interface.py").read_text(encoding="utf-8")
    scope_method = assistant_interface.split("def _current_action_permission_scope", 1)[1].split(
        "\n    def _setup_ui",
        1,
    )[0]

    assert "allow_e2ee_plaintext=True" in scope_method
    assert "get_current_session()" not in scope_method
    assert "allowed_contacts=" not in scope_method
    assert "allowed_groups=" not in scope_method
    assert "excluded_contacts=" not in scope_method
    assert "excluded_groups=" not in scope_method
    assert "uses_e2ee()" not in scope_method


def test_ai_assistant_action_confirmation_controls_continue_pending_plan() -> None:
    assistant_interface = Path("client/ui/windows/ai_assistant_interface.py").read_text(encoding="utf-8")
    assistant_delegate = Path("client/delegates/ai_assistant_message_delegate.py").read_text(encoding="utf-8")

    assert "QListView" in assistant_interface
    assert "AIAssistantMessageDelegate" in assistant_interface
    assert "def action_command_at" in assistant_delegate
    assert 'return "confirm"' in assistant_delegate
    assert 'return "cancel"' in assistant_delegate
    assert "def _handle_message_list_release" in assistant_interface
    assert "self._on_action_message_requested(message.message_id, command)" in assistant_interface
    assert "async def _continue_action_from_message" in assistant_interface
    assert "await self._action_workflow.handle_pending_control(" in assistant_interface
    assert "control_type=normalized_command" in assistant_interface
    assert "set_action_message_enabled" in assistant_interface


def test_ai_assistant_stop_button_cancels_active_action_plan() -> None:
    assistant_interface = Path("client/ui/windows/ai_assistant_interface.py").read_text(encoding="utf-8")
    stop_method = assistant_interface.split("async def _stop_active_generation", 1)[1].split(
        "\n    def _on_regenerate_clicked",
        1,
    )[0]
    progress_method = assistant_interface.split("async def _upsert_action_progress_message", 1)[1].split(
        "\n    async def _run_stream",
        1,
    )[0]

    assert "self._active_action_plan_id = \"\"" in assistant_interface
    assert "self._active_action_message: AIMessage | None = None" in assistant_interface
    assert "await self._action_workflow.cancel_plan(" in stop_method
    assert "self._active_action_plan_id" in stop_method
    assert "self._active_action_message" in stop_method
    assert "self._clear_active_action()" in stop_method
    assert "self._set_generating(bool(self._active_task_id or self._active_action_plan_id))" in assistant_interface
    assert 'if state == "running" and plan_id:' in progress_method
    assert "self._active_action_plan_id = plan_id" in progress_method


def test_ai_assistant_initial_load_recovers_interrupted_action_plans_first() -> None:
    assistant_interface = Path("client/ui/windows/ai_assistant_interface.py").read_text(encoding="utf-8")
    initial_load = assistant_interface.split("async def _ensure_initial_load_async", 1)[1].split(
        "\n    def _subscribe_to_events",
        1,
    )[0]

    assert "await self._store.initialize()" in initial_load
    assert "await self._action_workflow.recover_interrupted_plans()" in initial_load
    assert "await self._reload_threads(select_first=True)" in initial_load
    assert initial_load.index("_store.initialize") < initial_load.index("_action_workflow.recover_interrupted_plans")
    assert initial_load.index("_action_workflow.recover_interrupted_plans") < initial_load.index("_reload_threads")


def test_ai_assistant_regenerate_capability_exists_without_visible_entry() -> None:
    assistant_interface = Path("client/ui/windows/ai_assistant_interface.py").read_text(encoding="utf-8")

    assert "def regenerate_current_thread(self) -> asyncio.Task | None:" in assistant_interface
    assert "self._regenerate_last()" in assistant_interface
    assert 'f"regenerate AI assistant thread {self._current_thread_id}"' in assistant_interface
    assert "self.regenerate_current_thread()" in assistant_interface


def test_ai_assistant_truncation_is_marked_in_message_footer() -> None:
    assistant_interface = Path("client/ui/windows/ai_assistant_interface.py").read_text(encoding="utf-8")
    assistant_delegate = Path("client/delegates/ai_assistant_message_delegate.py").read_text(encoding="utf-8")

    assert '"ai_assistant.message.truncated_hint"' in assistant_delegate
    assert 'if bool((message.extra or {}).get("truncated")):' in assistant_delegate
    assert '"ai_assistant.message.failed_hint"' in assistant_delegate
    assert 'if message.status == AIMessageStatus.FAILED:' in assistant_delegate
    assert "def _draw_auxiliary_text" in assistant_delegate
    assert "QColor(236, 239, 243, 166)" in assistant_delegate
    assert "QColor(26, 26, 26, 150)" in assistant_delegate
    assert 'message_extra["truncated"] = True' in assistant_interface
    assert 'message_extra.pop("truncated", None)' in assistant_interface


def test_ai_assistant_image_attachment_flow_is_wired() -> None:
    assistant_interface = Path("client/ui/windows/ai_assistant_interface.py").read_text(encoding="utf-8")
    prompt_builder = Path("client/managers/ai_prompt_builder.py").read_text(encoding="utf-8")
    ai_service = Path("client/services/ai_service.py").read_text(encoding="utf-8")

    assert "class AIAssistantPendingAttachmentPreview(QFrame):" in assistant_interface
    assert "self.attachment_button.setEnabled(True)" in assistant_interface
    assert "self.attachment_button.clicked.connect(self._on_attachment_clicked)" in assistant_interface
    assert "QFileDialog.getOpenFileName" in assistant_interface
    assert '"type": "image"' in assistant_interface
    assert "extra={\"attachments\": list(attachments or [])} if attachments else None" in assistant_interface
    assert "self._pending_image_attachment = None" in assistant_interface
    assert "request.attachments" in ai_service
    assert "LocalVisionGGUFRuntime" in ai_service
    assert "attachments=attachments" in prompt_builder
