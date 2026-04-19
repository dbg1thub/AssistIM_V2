# coding: utf-8
"""Settings interface built with qfluentwidgets."""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import QWidget
from qfluentwidgets import (
    ComboBox,
    ComboBoxSettingCard,
    CustomColorSettingCard,
    ExpandLayout,
    InfoBar,
    OptionsSettingCard,
    ScrollArea,
    SettingCard,
    SettingCardGroup,
    SwitchSettingCard,
    Theme,
    setTheme,
    setThemeColor,
)

from client.core.app_icons import AppIcon, CollectionIcon
from client.core.config import cfg, is_win11
from client.core.i18n import tr
from client.services.local_ai_selection import LocalAIModelSpec, detect_local_ai_capabilities, installed_local_ai_model_specs
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

        self.notification_group.addSettingCard(self.sound_enabled_card)
        self.notification_group.addSettingCard(self.message_sound_card)

        self.app_group.addSettingCard(self.exit_confirm_card)

        self.expand_layout.setSpacing(28)
        self.expand_layout.setContentsMargins(36, 0, 36, 0)
        self.expand_layout.addWidget(self.personal_group)
        self.expand_layout.addWidget(self.ai_group)
        self.expand_layout.addWidget(self.notification_group)
        self.expand_layout.addWidget(self.app_group)

    def _connect_signals(self) -> None:
        cfg.themeChanged.connect(self._on_theme_changed)
        cfg.themeColorChanged.connect(setThemeColor)
        cfg.appRestartSig.connect(self._show_restart_tooltip)
        self.mica_card.checkedChanged.connect(self.micaChanged.emit)
        self.sound_enabled_card.checkedChanged.connect(self.message_sound_card.setEnabled)
        self.ai_model_card.modelChanged.connect(self._on_ai_model_changed)
        self.ai_gpu_card.checkedChanged.connect(lambda _checked: self._refresh_ai_gpu_card_state())

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
