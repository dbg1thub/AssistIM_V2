# coding: utf-8
"""Settings interface built with qfluentwidgets."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, QSignalBlocker, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QDialog, QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    ComboBox,
    ComboBoxSettingCard,
    CustomColorSettingCard,
    ExpandLayout,
    InfoBar,
    OptionsSettingCard,
    PushButton,
    ScrollArea,
    SettingCard,
    SettingCardGroup,
    SubtitleLabel,
    SwitchSettingCard,
    Theme,
    isDarkTheme,
    setTheme,
    setThemeColor,
)

from client.core.app_icons import AppIcon, CollectionIcon
from client.core.config import cfg, is_win11
from client.core.config_backend import is_development_runtime
from client.core.i18n import tr
from client.services.local_ai_selection import LocalAIModelSpec, detect_local_ai_capabilities, installed_local_ai_model_specs
from client.services.local_model_resource_probe import (
    STATUS_CONFIG_DISABLED,
    STATUS_DEPENDENCY_MISSING,
    STATUS_MISSING,
    STATUS_READY,
    LocalModelResourceItem,
    LocalModelResourceReport,
    probe_local_model_resources,
)
from client.services.local_model_resource_importer import (
    LocalModelImportError,
    LocalModelImportResult,
    LocalModelResourceImporter,
)
from client.ui.styles import StyleSheet


class AIModelSettingCard(SettingCard):
    """One dynamic model-selection setting card backed by the UI config."""

    modelChanged = Signal(str)

    def __init__(self, icon, title: str, content: str | None = None, parent=None) -> None:
        super().__init__(icon, title, content, parent=parent)
        self.combo_box = ComboBox(self)
        self.combo_box.setMinimumWidth(280)
        self.combo_box.currentIndexChanged.connect(self._emit_model_changed)
        self.hBoxLayout.addWidget(self.combo_box, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)

    def set_options(self, options: list[tuple[str, str]], current_value: str) -> None:
        blocker = QSignalBlocker(self.combo_box)
        self.combo_box.clear()
        current_index = -1
        for index, (model_id, label) in enumerate(options):
            self.combo_box.addItem(label, userData=model_id)
            if model_id == current_value:
                current_index = index
        if current_index < 0 and options:
            current_index = 0
        if current_index >= 0:
            self.combo_box.setCurrentIndex(current_index)
        del blocker

    def current_value(self) -> str:
        return str(self.combo_box.currentData() or "").strip()

    def _emit_model_changed(self, index: int) -> None:
        if index < 0:
            return
        value = self.current_value()
        if value:
            self.modelChanged.emit(value)


class LocalModelResourcesSettingCard(SettingCard):
    """Open the local model resource report dialog."""

    clicked = Signal()

    def __init__(self, icon, title: str, content: str | None = None, parent=None) -> None:
        super().__init__(icon, title, content, parent=parent)
        self.button = PushButton(tr("settings.card.ai_resources.action", "查看"), self)
        self.button.clicked.connect(self.clicked.emit)
        self.hBoxLayout.addWidget(self.button, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)


class LocalModelImportWorker(QObject):
    """Run one model import outside the UI thread."""

    finished = Signal(object)
    failed = Signal(str, str)

    def __init__(self, job: Callable[[], LocalModelImportResult], parent=None) -> None:
        super().__init__(parent)
        self._job = job

    def run(self) -> None:
        try:
            self.finished.emit(self._job())
        except LocalModelImportError as exc:
            self.failed.emit(exc.code, str(exc))
        except Exception as exc:
            self.failed.emit("IMPORT_FAILED", str(exc))


class LocalModelResourcesDialog(QDialog):
    """Read-only local model/dependency report."""

    def __init__(
        self,
        report_provider=probe_local_model_resources,
        importer: LocalModelResourceImporter | None = None,
        on_imported: Callable[[LocalModelImportResult], None] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._report_provider = report_provider
        self._importer = importer or LocalModelResourceImporter()
        self._on_imported = on_imported
        self._import_thread: QThread | None = None
        self._import_worker: LocalModelImportWorker | None = None
        self.setObjectName("LocalModelResourcesDialog")
        self.setWindowTitle(tr("settings.local_model_resources.title", "本地模型资源"))
        self.resize(720, 580)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 20)
        root.setSpacing(16)

        self.title_label = SubtitleLabel(tr("settings.local_model_resources.title", "本地模型资源"), self)
        self.subtitle_label = CaptionLabel(
            tr(
                "settings.local_model_resources.subtitle",
                "只检查本地文件、依赖和硬件状态，不会加载大模型。",
            ),
            self,
        )
        root.addWidget(self.title_label)
        root.addWidget(self.subtitle_label)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self.open_models_dir_button = PushButton(tr("settings.local_model_resources.open_models_dir", "打开模型目录"), self)
        self.import_chat_model_button = PushButton(tr("settings.local_model_resources.import_chat_model", "导入聊天模型"), self)
        self.import_embedding_model_button = PushButton(
            tr("settings.local_model_resources.import_embedding_model", "导入嵌入模型"),
            self,
        )
        self.import_voice_model_button = PushButton(tr("settings.local_model_resources.import_voice_model", "导入语音模型"), self)
        self.open_models_dir_button.clicked.connect(self._open_models_dir)
        self.import_chat_model_button.clicked.connect(self._import_chat_model)
        self.import_embedding_model_button.clicked.connect(self._import_embedding_model)
        self.import_voice_model_button.clicked.connect(self._import_voice_model)
        action_row.addWidget(self.open_models_dir_button)
        action_row.addWidget(self.import_chat_model_button)
        action_row.addWidget(self.import_embedding_model_button)
        action_row.addWidget(self.import_voice_model_button)
        action_row.addStretch(1)
        root.addLayout(action_row)

        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_content = QWidget(self.scroll_area)
        self.report_layout = QVBoxLayout(self.scroll_content)
        self.report_layout.setContentsMargins(0, 0, 0, 0)
        self.report_layout.setSpacing(12)
        self.scroll_area.setWidget(self.scroll_content)
        root.addWidget(self.scroll_area, 1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.refresh_button = PushButton(tr("settings.local_model_resources.refresh", "刷新"), self)
        self.close_button = PushButton(tr("settings.local_model_resources.close", "关闭"), self)
        self.refresh_button.clicked.connect(self._refresh_report)
        self.close_button.clicked.connect(self.close)
        button_row.addWidget(self.refresh_button)
        button_row.addWidget(self.close_button)
        root.addLayout(button_row)

        self._refresh_report()

    def closeEvent(self, event) -> None:
        if self._import_thread is not None:
            event.ignore()
            InfoBar.info(
                tr("settings.local_model_resources.title", "本地模型资源"),
                tr("settings.local_model_resources.busy", "模型正在导入，请等待完成。"),
                parent=self,
                duration=1800,
            )
            return
        super().closeEvent(event)

    def _refresh_report(self) -> None:
        report = self._report_provider()
        self._render_report(report)

    def _open_models_dir(self) -> None:
        try:
            self._importer.models_dir.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._importer.models_dir)))
        except OSError as exc:
            InfoBar.error(
                tr("settings.local_model_resources.import_failed.title", "导入失败"),
                str(exc),
                parent=self,
                duration=4500,
            )

    def _import_chat_model(self) -> None:
        file_path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            tr("settings.local_model_resources.import_chat_model", "导入聊天模型"),
            str(self._importer.models_dir),
            tr("settings.local_model_resources.file_filter.gguf", "GGUF 模型 (*.gguf)"),
        )
        if not file_path:
            return
        self._run_import_job(
            lambda: self._importer.import_chat_gguf(file_path),
            success_content=tr("settings.local_model_resources.import_success.content", "已导入 {model}：{target}"),
        )

    def _import_embedding_model(self) -> None:
        file_path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            tr("settings.local_model_resources.import_embedding_model", "导入嵌入模型"),
            str(self._importer.models_dir),
            tr("settings.local_model_resources.file_filter.gguf", "GGUF 模型 (*.gguf)"),
        )
        if not file_path:
            return
        self._run_import_job(
            lambda: self._importer.import_embedding_gguf(file_path),
            success_content=tr("settings.local_model_resources.import_success.content", "已导入 {model}：{target}"),
        )

    def _import_voice_model(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            tr("settings.local_model_resources.select_voice_dir_title", "选择 faster-whisper small 目录"),
            str(self._importer.models_dir),
        )
        if not directory:
            return
        self._run_import_job(
            lambda: self._importer.import_faster_whisper_directory(directory),
            success_content=tr("settings.local_model_resources.import_success.content", "已导入 {model}：{target}"),
        )

    def _run_import_job(self, job, *, success_content: str) -> None:
        if self._import_thread is not None:
            InfoBar.info(
                tr("settings.local_model_resources.title", "本地模型资源"),
                tr("settings.local_model_resources.busy", "模型正在导入，请等待完成。"),
                parent=self,
                duration=1800,
            )
            return

        thread = QThread(self)
        worker = LocalModelImportWorker(job)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(lambda result: self._on_import_finished(result, success_content))
        worker.failed.connect(self._on_import_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_import_thread_finished)
        self._import_thread = thread
        self._import_worker = worker
        self._set_import_actions_enabled(False)
        thread.start()

    def _on_import_finished(self, result: LocalModelImportResult, success_content: str) -> None:
        if self._on_imported is not None:
            self._on_imported(result)
        elif result.kind == "chat" and result.model_id:
            cfg.set(cfg.aiModelId, result.model_id)
        self._refresh_report()
        try:
            content = success_content.format(model=result.model_id, target=str(result.target_path))
        except Exception:
            content = success_content
        InfoBar.success(
            tr("settings.local_model_resources.import_success.title", "导入完成"),
            content,
            parent=self,
            duration=3000,
        )

    def _on_import_failed(self, _code: str, message: str) -> None:
        InfoBar.error(
            tr("settings.local_model_resources.import_failed.title", "导入失败"),
            tr("settings.local_model_resources.import_failed.content", "{error}", error=message),
            parent=self,
            duration=5500,
        )

    def _on_import_thread_finished(self) -> None:
        self._import_thread = None
        self._import_worker = None
        self._set_import_actions_enabled(True)

    def _set_import_actions_enabled(self, enabled: bool) -> None:
        for button in (
            self.open_models_dir_button,
            self.import_chat_model_button,
            self.import_embedding_model_button,
            self.import_voice_model_button,
            self.refresh_button,
        ):
            button.setEnabled(enabled)

    def _render_report(self, report: LocalModelResourceReport) -> None:
        while self.report_layout.count():
            item = self.report_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        for section_key, section_title in (
            ("models", tr("settings.local_model_resources.section.models", "模型文件")),
            ("dependencies", tr("settings.local_model_resources.section.dependencies", "运行依赖")),
        ):
            section_items = report.section_items(section_key)
            if not section_items:
                continue
            heading = CaptionLabel(section_title, self.scroll_content)
            self.report_layout.addWidget(heading)
            for resource in section_items:
                self.report_layout.addWidget(self._resource_card(resource))
        self.report_layout.addStretch(1)

    def _resource_card(self, item: LocalModelResourceItem) -> QFrame:
        card = QFrame(self.scroll_content)
        card.setObjectName("LocalModelResourceCard")
        card.setFrameShape(QFrame.Shape.NoFrame)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        header = QHBoxLayout()
        title = BodyLabel(self._resource_title(item), card)
        status = QLabel(self._status_text(item.status), card)
        status.setObjectName("LocalModelResourceStatus")
        status.setStyleSheet(self._status_label_style(item.status))
        header.addWidget(title, 1)
        header.addWidget(status, 0, Qt.AlignmentFlag.AlignRight)
        layout.addLayout(header)

        for line in self._resource_detail_lines(item):
            label = CaptionLabel(line, card)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            label.setWordWrap(True)
            layout.addWidget(label)

        card.setStyleSheet(self._card_style())
        return card

    @staticmethod
    def _card_style() -> str:
        background = "rgba(255,255,255,18)" if isDarkTheme() else "rgba(0,0,0,8)"
        border = "rgba(255,255,255,24)" if isDarkTheme() else "rgba(0,0,0,14)"
        return f"QFrame#LocalModelResourceCard {{ background: {background}; border: 1px solid {border}; border-radius: 8px; }}"

    @staticmethod
    def _status_label_style(status: str) -> str:
        color = {
            STATUS_READY: "#107C10",
            STATUS_MISSING: "#C50F1F",
            STATUS_DEPENDENCY_MISSING: "#C50F1F",
            STATUS_CONFIG_DISABLED: "#8A8886",
        }.get(status, "#8A8886")
        return f"QLabel#LocalModelResourceStatus {{ color: {color}; font-weight: 600; }}"

    @staticmethod
    def _status_text(status: str) -> str:
        mapping = {
            STATUS_READY: tr("settings.local_model_resources.status.ready", "正常"),
            STATUS_MISSING: tr("settings.local_model_resources.status.missing", "缺失"),
            STATUS_DEPENDENCY_MISSING: tr("settings.local_model_resources.status.dependency_missing", "依赖缺失"),
            STATUS_CONFIG_DISABLED: tr("settings.local_model_resources.status.config_disabled", "配置未启用"),
        }
        return mapping.get(str(status or "").strip(), str(status or "").strip())

    @staticmethod
    def _resource_title(item: LocalModelResourceItem) -> str:
        mapping = {
            "chat_model": tr("settings.local_model_resources.chat_model", "聊天模型"),
            "embedding_model": tr("settings.local_model_resources.embedding_model", "嵌入模型"),
            "voice_transcription_model": tr("settings.local_model_resources.voice_model", "语音转文字模型"),
            "dependency_llama_cpp": tr("settings.local_model_resources.llama_cpp", "llama-cpp-python"),
            "dependency_llama_cpp_embedding": tr("settings.local_model_resources.llama_cpp_embedding", "llama-cpp-python embedding"),
            "dependency_faster_whisper": tr("settings.local_model_resources.faster_whisper", "faster-whisper"),
            "dependency_cuda_12": tr("settings.local_model_resources.cuda", "CUDA 12 运行时"),
        }
        return mapping.get(item.key, item.title)

    def _resource_detail_lines(self, item: LocalModelResourceItem) -> list[str]:
        lines: list[str] = []
        if item.model_id:
            lines.append(f"ID: {item.model_id}")
        if item.path:
            lines.append(f"{tr('settings.local_model_resources.path', '路径')}: {item.path}")
        if item.size_bytes:
            lines.append(f"{tr('settings.local_model_resources.size', '大小')}: {self._format_bytes(item.size_bytes)}")
        if item.detail:
            lines.append(item.detail)
        for key, value in item.metadata.items():
            if value in (None, "", (), []):
                continue
            if key in {"missing_files"}:
                lines.append(f"missing_files: {', '.join(str(part) for part in value)}")
            elif key in {"gpu_name", "acceleration", "device", "compute_type", "cpu_threads", "allow_download"}:
                lines.append(f"{key}: {value}")
        return lines or [self._status_text(item.status)]

    @staticmethod
    def _format_bytes(size_bytes: int) -> str:
        size = float(max(0, int(size_bytes or 0)))
        units = ("B", "KB", "MB", "GB")
        index = 0
        while size >= 1024 and index < len(units) - 1:
            size /= 1024.0
            index += 1
        if index == 0:
            return f"{int(size)} {units[index]}"
        return f"{size:.1f} {units[index]}"


class SettingsInterface(ScrollArea):
    """Application settings page."""

    micaChanged = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("SettingsInterface")

        self.scroll_widget = QWidget(self)
        self.scroll_widget.setObjectName("settingsScrollWidget")
        self.expand_layout = ExpandLayout(self.scroll_widget)

        self.personal_group = SettingCardGroup(tr("settings.group.personalization", "Personalization"), self.scroll_widget)
        self.ai_group = SettingCardGroup(tr("settings.group.ai", "AI"), self.scroll_widget)
        self.notification_group = SettingCardGroup(tr("settings.group.notifications", "Notifications"), self.scroll_widget)
        self.app_group = SettingCardGroup(tr("settings.group.application", "Application"), self.scroll_widget)
        self.developer_group = SettingCardGroup(tr("settings.group.developer", "Developer"), self.scroll_widget)
        self._developer_settings_enabled = is_development_runtime()
        self._ai_capability = detect_local_ai_capabilities()
        self._ai_model_specs = installed_local_ai_model_specs()

        self.mica_card = SwitchSettingCard(
            AppIcon.TRANSPARENT,
            tr("settings.card.mica.title", "Mica Effect"),
            tr("settings.card.mica.content", "Enable the Windows 11 Mica background effect for the window surface."),
            configItem=cfg.micaEnabled,
            parent=self.personal_group,
        )
        self.theme_card = OptionsSettingCard(
            cfg.themeMode,
            AppIcon.PALETTE,
            tr("settings.card.theme.title", "Theme"),
            tr("settings.card.theme.content", "Switch between light, dark, or system theme."),
            texts=[
                tr("settings.card.theme.option.light", "Light"),
                tr("settings.card.theme.option.dark", "Dark"),
                tr("settings.card.theme.option.system", "Follow System"),
            ],
            parent=self.personal_group,
        )
        self.theme_color_card = CustomColorSettingCard(
            cfg.themeColor,
            AppIcon.BRUSH,
            tr("settings.card.theme_color.title", "Theme Color"),
            tr("settings.card.theme_color.content", "Change the application accent color."),
            parent=self.personal_group,
        )
        self.zoom_card = OptionsSettingCard(
            cfg.dpiScale,
            AppIcon.ZOOM,
            tr("settings.card.zoom.title", "Display Scale"),
            tr("settings.card.zoom.content", "Adjust the scale used for UI and text rendering."),
            texts=["100%", "125%", "150%", "175%", "200%", tr("settings.card.zoom.option.auto", "Follow System")],
            parent=self.personal_group,
        )
        self.language_card = ComboBoxSettingCard(
            cfg.language,
            AppIcon.LANGUAGE,
            tr("settings.card.language.title", "Language"),
            tr("settings.card.language.content", "Choose the language used by the application interface."),
            texts=[
                tr("settings.card.language.option.zh_cn", "Simplified Chinese"),
                tr("settings.card.language.option.en_us", "English"),
                tr("settings.card.language.option.ko_kr", "Korean"),
                tr("settings.card.language.option.auto", "Follow System"),
            ],
            parent=self.personal_group,
        )

        self.exit_confirm_card = SwitchSettingCard(
            AppIcon.CLOSE,
            tr("settings.card.exit_confirm.title", "Confirm Before Exit"),
            tr("settings.card.exit_confirm.content", "Show a confirmation dialog before quitting from the system tray."),
            configItem=cfg.exitConfirmEnabled,
            parent=self.app_group,
        )
        self.sound_enabled_card = SwitchSettingCard(
            CollectionIcon("speaker_2"),
            tr("settings.card.sound_enabled.title", "Enable Sound Effects"),
            tr("settings.card.sound_enabled.content", "Allow the desktop client to play notification sounds and future UI sound effects."),
            configItem=cfg.soundEnabled,
            parent=self.notification_group,
        )
        self.message_sound_card = SwitchSettingCard(
            CollectionIcon("alert"),
            tr("settings.card.message_sound.title", "Incoming Message Sound"),
            tr("settings.card.message_sound.content", "Play a prompt sound when a new real-time message arrives."),
            configItem=cfg.messageSoundEnabled,
            parent=self.notification_group,
        )
        self.ai_model_card = AIModelSettingCard(
            AppIcon.ROBOT,
            tr("settings.card.ai_model.title", "Local AI Model"),
            tr("settings.card.ai_model.content", "Choose which local GGUF model the desktop client should load after restart."),
            parent=self.ai_group,
        )
        self.ai_gpu_card = SwitchSettingCard(
            AppIcon.ROBOT,
            tr("settings.card.ai_gpu.title", "GPU Acceleration"),
            tr("settings.card.ai_gpu.content", "Enable GPU acceleration for the selected local AI model when the runtime and hardware support it."),
            configItem=cfg.aiGpuAccelerationEnabled,
            parent=self.ai_group,
        )
        self.ai_resources_card = LocalModelResourcesSettingCard(
            AppIcon.INFO,
            tr("settings.card.ai_resources.title", "本地模型资源"),
            tr("settings.card.ai_resources.content", "查看聊天模型、嵌入模型、语音转文字模型和运行依赖状态。"),
            parent=self.ai_group,
        )
        self.server_localhost_card = SwitchSettingCard(
            AppIcon.GLOBE,
            tr("settings.card.dev_server_localhost.title", "Use Local Server"),
            tr(
                "settings.card.dev_server_localhost.content",
                "Connect to localhost:8000 after restart while keeping the configured remote server address.",
            ),
            configItem=cfg.serverUseLocalhost,
            parent=self.developer_group,
        )

        self._init_widget()

    def _init_widget(self) -> None:
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setViewportMargins(0, 24, 0, 24)
        self.setWidget(self.scroll_widget)
        self.setWidgetResizable(True)

        self._init_layout()
        self._connect_signals()
        self._apply_initial_values()
        if self.viewport() is not None:
            self.viewport().setObjectName("settingsViewport")
            self.viewport().setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
            self.viewport().setAutoFillBackground(False)
            self.viewport().setStyleSheet("background: transparent; border: none;")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setAutoFillBackground(False)
        self.setStyleSheet("QAbstractScrollArea{background: transparent; border: none;} QScrollArea{background: transparent; border: none;}")
        self.scroll_widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.scroll_widget.setAutoFillBackground(False)
        self.scroll_widget.setStyleSheet("background: transparent; border: none;")
        if hasattr(self, "enableTransparentBackground"):
            self.enableTransparentBackground()
        StyleSheet.SETTINGS_INTERFACE.apply(self)

        if not is_win11():
            self.mica_card.setChecked(False)
            self.mica_card.setEnabled(False)
            self.mica_card.setContent(
                tr(
                    "settings.mica.unsupported",
                    "Mica is unavailable on this system. Windows 11 or newer is required.",
                )
            )

    def _init_layout(self) -> None:
        self.personal_group.addSettingCard(self.mica_card)
        self.personal_group.addSettingCard(self.theme_card)
        self.personal_group.addSettingCard(self.theme_color_card)
        self.personal_group.addSettingCard(self.zoom_card)
        self.personal_group.addSettingCard(self.language_card)

        self.ai_group.addSettingCard(self.ai_model_card)
        self.ai_group.addSettingCard(self.ai_gpu_card)
        self.ai_group.addSettingCard(self.ai_resources_card)

        self.notification_group.addSettingCard(self.sound_enabled_card)
        self.notification_group.addSettingCard(self.message_sound_card)

        self.app_group.addSettingCard(self.exit_confirm_card)

        if self._developer_settings_enabled:
            self.developer_group.addSettingCard(self.server_localhost_card)

        self.expand_layout.setSpacing(28)
        self.expand_layout.setContentsMargins(36, 0, 36, 0)
        self.expand_layout.addWidget(self.personal_group)
        self.expand_layout.addWidget(self.ai_group)
        self.expand_layout.addWidget(self.notification_group)
        self.expand_layout.addWidget(self.app_group)
        if self._developer_settings_enabled:
            self.expand_layout.addWidget(self.developer_group)

    def _connect_signals(self) -> None:
        cfg.themeChanged.connect(self._on_theme_changed)
        cfg.themeColorChanged.connect(setThemeColor)
        cfg.appRestartSig.connect(self._show_restart_tooltip)
        self.mica_card.checkedChanged.connect(self.micaChanged.emit)
        self.sound_enabled_card.checkedChanged.connect(self.message_sound_card.setEnabled)
        self.ai_model_card.modelChanged.connect(self._on_ai_model_changed)
        self.ai_gpu_card.checkedChanged.connect(lambda _checked: self._refresh_ai_gpu_card_state())
        self.ai_resources_card.clicked.connect(self._open_local_model_resources_dialog)

    def _apply_initial_values(self) -> None:
        setTheme(cfg.get(cfg.themeMode), lazy=True)
        setThemeColor(cfg.get(cfg.themeColor))
        self.message_sound_card.setEnabled(bool(cfg.get(cfg.soundEnabled)))
        self._sync_ai_model_card()
        self._refresh_ai_gpu_card_state()

    def _on_theme_changed(self, theme: Theme) -> None:
        setTheme(theme, lazy=True)

    def _show_restart_tooltip(self) -> None:
        InfoBar.info(
            tr("settings.restart.title", "Restart Required"),
            tr(
                "settings.restart.content",
                "Display scale, language, and AI setting changes will apply after restarting the app.",
            ),
            parent=self.window(),
            duration=2500,
        )

    def _open_local_model_resources_dialog(self) -> None:
        dialog = LocalModelResourcesDialog(parent=self.window() or self, on_imported=self._on_local_model_resource_imported)
        dialog.exec()

    def _on_local_model_resource_imported(self, result: LocalModelImportResult) -> None:
        self._ai_model_specs = installed_local_ai_model_specs()
        if result.kind == "chat" and result.model_id:
            cfg.set(cfg.aiModelId, result.model_id)
        self._sync_ai_model_card()
        self._refresh_ai_gpu_card_state()

    def _on_ai_model_changed(self, model_id: str) -> None:
        normalized_model_id = str(model_id or "").strip()
        if not normalized_model_id:
            return
        if cfg.get(cfg.aiModelId) == normalized_model_id:
            self._refresh_ai_gpu_card_state()
            return
        cfg.set(cfg.aiModelId, normalized_model_id)
        self._refresh_ai_gpu_card_state()

    def _sync_ai_model_card(self) -> None:
        options = [(spec.model_id, self._format_ai_model_label(spec)) for spec in self._ai_model_specs]
        if not options:
            self.ai_model_card.setEnabled(False)
            self.ai_model_card.setContent(
                tr(
                    "settings.card.ai_model.unavailable",
                    "No installed local GGUF models were found in client/resources/models.",
                )
            )
            return

        selected_model_id = str(cfg.get(cfg.aiModelId) or "").strip()
        if selected_model_id not in {model_id for model_id, _label in options}:
            selected_model_id = options[0][0]
        self.ai_model_card.setEnabled(True)
        self.ai_model_card.setContent(
            tr(
                "settings.card.ai_model.content",
                "Choose which local GGUF model the desktop client should load after restart.",
            )
        )
        self.ai_model_card.set_options(options, selected_model_id)

    def _refresh_ai_gpu_card_state(self) -> None:
        selected_spec = self._selected_ai_model_spec()
        if selected_spec is None:
            self.ai_gpu_card.setEnabled(False)
            self.ai_gpu_card.setContent(
                tr(
                    "settings.card.ai_gpu.unavailable_model",
                    "Select one installed local AI model before enabling GPU acceleration.",
                )
            )
            return

        cache_clear = getattr(detect_local_ai_capabilities, "cache_clear", None)
        if callable(cache_clear):
            cache_clear()
        capability = detect_local_ai_capabilities()
        self._ai_capability = capability
        available_vram_gb = capability.gpu_free_memory_gb if capability.gpu_free_memory_gb > 0 else capability.gpu_total_memory_gb
        if not capability.runtime_supports_gpu_offload:
            self.ai_gpu_card.setEnabled(False)
            if capability.missing_cuda_dependencies:
                deps = ", ".join(capability.missing_cuda_dependencies)
                self.ai_gpu_card.setContent(
                    tr(
                        "settings.card.ai_gpu.unavailable_cuda",
                        "GPU acceleration is unavailable because CUDA 12 runtime dependencies are missing: {deps}.",
                        deps=deps,
                    )
                )
            else:
                self.ai_gpu_card.setContent(
                    tr(
                        "settings.card.ai_gpu.unavailable_runtime",
                        "GPU acceleration is unavailable because the local runtime or GPU driver does not expose llama.cpp GPU offload support.",
                    )
                )
            return

        self.ai_gpu_card.setEnabled(True)
        gpu_label = capability.gpu_name or tr("settings.card.ai_gpu.gpu_unknown", "当前 GPU")
        if selected_spec.min_vram_gb > 0 and available_vram_gb > 0 and available_vram_gb < selected_spec.min_vram_gb:
            self.ai_gpu_card.setContent(
                tr(
                    "settings.card.ai_gpu.content_warning_vram",
                    "启动时会按 llama.cpp 尝试为 {model} 使用 GPU offload，并采用 RAM + VRAM 混合推理。当前 {gpu} 可用显存约 {available} GB，低于参考门槛 {required} GB，运行时可能回退到 CPU。",
                    model=self._format_ai_model_label(selected_spec),
                    gpu=gpu_label,
                    required=f"{selected_spec.min_vram_gb:.1f}",
                    available=f"{available_vram_gb:.2f}",
                )
            )
            return

        self.ai_gpu_card.setContent(
            tr(
                "settings.card.ai_gpu.content_ready",
                "Use GPU acceleration for {model} on {gpu}. Disable this if you prefer CPU-only inference.",
                model=self._format_ai_model_label(selected_spec),
                gpu=gpu_label,
            )
        )

    def _selected_ai_model_spec(self) -> LocalAIModelSpec | None:
        selected_model_id = self.ai_model_card.current_value() if self._ai_model_specs else ""
        if not selected_model_id:
            selected_model_id = str(cfg.get(cfg.aiModelId) or "").strip()
        for spec in self._ai_model_specs:
            if spec.model_id == selected_model_id:
                return spec
        return None

    @staticmethod
    def _format_ai_model_label(spec: LocalAIModelSpec) -> str:
        model_id = str(spec.model_id or "").strip()
        normalized = model_id.lower()
        if normalized.startswith("gemma-4-e2b-it-"):
            suffix = model_id.split("gemma-4-E2B-it-", 1)[-1]
            return f"Gemma 4 E2B-it ({suffix})"
        if normalized.startswith("qwen3.5-"):
            family = model_id.replace("-Q4_K_M", "").replace("-Q8_0", "")
            suffix = model_id.split(family + "-", 1)[-1] if model_id.startswith(family + "-") else spec.quantization or ""
            return f"{family} ({suffix})" if suffix else family
        return model_id
