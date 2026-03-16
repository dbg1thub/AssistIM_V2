# coding: utf-8
"""
设置界面 - 遵循 PyQt-Fluent-Widgets 设置界面模式

添加新设置项的步骤：
1. 在 client/core/config.py 的 Config 类中添加新的 ConfigItem
2. 在对应的 _setupXXX 方法中添加 SettingCard
3. 在 __init_layout 方法中将 SettingCard 添加到 SettingCardGroup
4. 在 __connect_signal_to_slot 方法中连接信号和槽
"""

from qfluentwidgets import (
    ScrollArea, FluentIcon, SettingCardGroup, SwitchSettingCard,
    PushSettingCard, PrimaryPushSettingCard, ComboBoxSettingCard,
    OptionsSettingCard, ExpandLayout, Theme, InfoBar,
    setTheme, setThemeColor, isDarkTheme, CustomColorSettingCard,
    HyperlinkCard
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFileDialog

from client.core.config import cfg, save_config


class SettingsInterface(ScrollArea):
    """设置界面 - 遵循 PyQt-Fluent-Widgets 模式"""

    # Signal 定义
    check_update_sig = Signal()
    acrylic_enable_changed = Signal(bool)
    theme_changed = Signal(str)
    language_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("SettingsInterface")

        self.scroll_widget = QWidget(self)
        self.scroll_widget.setObjectName("scrollWidget")
        self.expand_layout = ExpandLayout(self.scroll_widget)

        # ============ 个性化设置组 ============
        self.personal_group = SettingCardGroup(self.tr('Personalization'), self.scroll_widget)

        # 透明效果
        self.acrylic_card = SwitchSettingCard(
            FluentIcon.TRANSPARENT,
            self.tr('Mica effect'),
            self.tr('Apply semi transparent to windows and surfaces'),
            configItem=cfg.micaEnabled,
            parent=self.personal_group
        )

        # 主题模式
        self.theme_card = OptionsSettingCard(
            cfg.themeMode,
            FluentIcon.PALETTE,
            self.tr('Application theme'),
            self.tr("Change the appearance of your application"),
            texts=[self.tr('Light'), self.tr('Dark'), self.tr('Use system setting')],
            parent=self.personal_group
        )

        # 主题颜色
        self.theme_color_card = CustomColorSettingCard(
            cfg.themeColor,
            FluentIcon.BRUSH,
            self.tr('Theme color'),
            self.tr('Change the theme color of you application'),
            parent=self.personal_group
        )
        # 窗口缩放
        self.zoom_card = OptionsSettingCard(
            cfg.dpiScale,
            FluentIcon.ZOOM,
            self.tr("Interface zoom"),
            self.tr("Change the size of widgets and fonts"),
            texts=["100%", "125%", "150%", "175%", "200%",
                   self.tr("Use system setting")
                   ],
            parent=self.personal_group
        )

        self.language_card = ComboBoxSettingCard(
            cfg.language,
            FluentIcon.LANGUAGE,
            self.tr('Language'),
            self.tr('Set your preferred language for UI'),
            texts=['简体中文', 'English', '한국인', self.tr('Use system setting')],
            parent=self.personal_group
        )

        # ============ 通知设置组 ============
        self.notify_group = SettingCardGroup("通知", self.scroll_widget)

        # 新消息通知
        self.msg_notify_card = SwitchSettingCard(
            FluentIcon.MESSAGE,
            "新消息通知",
            "收到新消息时显示通知",
            configItem=cfg.enableMessageNotification,
            parent=self.notify_group
        )

        # 消息声音
        self.msg_sound_card = SwitchSettingCard(
            FluentIcon.VOLUME,
            "消息提示音",
            "收到新消息时播放提示音",
            configItem=cfg.enableMessageSound,
            parent=self.notify_group
        )

        # 桌面通知
        self.desktop_notify_card = SwitchSettingCard(
            FluentIcon.INFO,
            "桌面通知",
            "在桌面显示通知横幅",
            configItem=cfg.enableDesktopNotification,
            parent=self.notify_group
        )

        # ============ 聊天设置组 ============
        self.chat_group = SettingCardGroup("聊天", self.scroll_widget)

        # 快捷回复
        self.quick_reply_card = SwitchSettingCard(
            FluentIcon.CHAT,
            "快捷回复",
            "启用快捷回复功能",
            configItem=cfg.enableQuickReply,
            parent=self.chat_group
        )

        # 已读回执
        self.read_receipt_card = SwitchSettingCard(
            FluentIcon.CHECKBOX,
            "已读回执",
            "发送已读回执给对方",
            configItem=cfg.enableReadReceipt,
            parent=self.chat_group
        )

        # 正在输入
        self.typing_indicator_card = SwitchSettingCard(
            FluentIcon.SEND,
            "正在输入",
            "显示正在输入状态",
            configItem=cfg.enableTypingIndicator,
            parent=self.chat_group
        )

        # 消息撤回时间
        self.recall_time_card = OptionsSettingCard(
            cfg.messageRecallTime,
            FluentIcon.HISTORY,
            "消息撤回时间",
            "可以选择撤回消息的时间限制",
            texts=["2分钟", "5分钟", "无限制"],
            parent=self.chat_group
        )

        # ============ AI 设置组 ============
        self.ai_group = SettingCardGroup("AI 助手", self.scroll_widget)

        # AI 自动回复
        self.ai_auto_reply_card = SwitchSettingCard(
            FluentIcon.ROBOT,
            "AI 自动回复",
            "启用 AI 自动回复功能",
            configItem=cfg.enableAIAutoReply,
            parent=self.ai_group
        )

        # AI 模型选择
        self.ai_model_card = OptionsSettingCard(
            cfg.aiModel,
            FluentIcon.AIRPLANE,
            "AI 模型",
            "选择使用的 AI 模型",
            texts=["GPT-4", "GPT-3.5", "本地模型"],
            parent=self.ai_group
        )

        # 清空 AI 上下文
        self.clear_context_card = PrimaryPushSettingCard(
            "清空上下文",
            FluentIcon.DELETE,
            "清空 AI 对话上下文",
            "清除所有 AI 对话历史",
            parent=self.ai_group
        )

        # ============ 更新设置组 ============
        self.update_group = SettingCardGroup("软件更新", self.scroll_widget)

        # 启动时检查更新
        self.check_update_card = SwitchSettingCard(
            FluentIcon.UPDATE,
            "启动时检查更新",
            "新版本会更稳定并包含更多功能",
            configItem=cfg.checkUpdateAtStartUp,
            parent=self.update_group
        )

        # ============ 关于设置组 ============
        self.about_group = SettingCardGroup("关于", self.scroll_widget)

        # 检查更新
        self.update_check_card = PushSettingCard(
            "检查更新",
            FluentIcon.UPDATE,
            "检查更新",
            f"当前版本: {cfg.appVersion}",
            parent=self.about_group
        )

        # 反馈问题
        self.feedback_card = PushSettingCard(
            "反馈问题",
            FluentIcon.FEEDBACK,
            "反馈问题",
            "报告问题或提出建议",
            parent=self.about_group
        )

        # 隐私政策
        self.privacy_card = PushSettingCard(
            "查看",
            FluentIcon.INFO,
            "隐私政策",
            "了解我们如何保护您的隐私",
            parent=self.about_group
        )

        self.__init_widget()

    def __init_widget(self):
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setViewportMargins(0, 30, 0, 30)
        self.setWidget(self.scroll_widget)
        self.setWidgetResizable(True)

        # 初始化布局
        self.__init_layout()

        # 连接信号槽
        self.__connect_signal_to_slot()

    def __init_layout(self):
        # ============ 添加设置卡片到分组 ============

        # 个性化设置组
        self.personal_group.addSettingCard(self.acrylic_card)
        self.personal_group.addSettingCard(self.theme_card)
        self.personal_group.addSettingCard(self.theme_color_card)
        self.personal_group.addSettingCard(self.zoom_card)
        self.personal_group.addSettingCard(self.language_card)

        # 通知设置组
        self.notify_group.addSettingCard(self.msg_notify_card)
        self.notify_group.addSettingCard(self.msg_sound_card)
        self.notify_group.addSettingCard(self.desktop_notify_card)

        # 聊天设置组
        self.chat_group.addSettingCard(self.quick_reply_card)
        self.chat_group.addSettingCard(self.read_receipt_card)
        self.chat_group.addSettingCard(self.typing_indicator_card)
        self.chat_group.addSettingCard(self.recall_time_card)

        # AI 设置组
        self.ai_group.addSettingCard(self.ai_auto_reply_card)
        self.ai_group.addSettingCard(self.ai_model_card)
        self.ai_group.addSettingCard(self.clear_context_card)

        # 更新设置组
        self.update_group.addSettingCard(self.check_update_card)

        # 关于设置组
        self.about_group.addSettingCard(self.update_check_card)
        self.about_group.addSettingCard(self.feedback_card)
        self.about_group.addSettingCard(self.privacy_card)

        # ============ 添加分组到布局 ============
        self.expand_layout.setSpacing(30)
        self.expand_layout.setContentsMargins(36, 0, 36, 0)
        self.expand_layout.addWidget(self.personal_group)
        self.expand_layout.addWidget(self.notify_group)
        self.expand_layout.addWidget(self.chat_group)
        self.expand_layout.addWidget(self.ai_group)
        self.expand_layout.addWidget(self.update_group)
        self.expand_layout.addWidget(self.about_group)

    def __connect_signal_to_slot(self):
        """连接信号和槽"""

        # 主题相关
        cfg.themeChanged.connect(self.__on_theme_changed)
        self.theme_color_card.colorChanged.connect(setThemeColor)

        # 透明效果
        self.acrylic_card.checkedChanged.connect(
            lambda checked: self.acrylic_enable_changed.emit(checked))

        # 清空上下文
        self.clear_context_card.clicked.connect(self.__on_clear_context_clicked)

        # 关于 - 检查更新
        self.update_check_card.clicked.connect(self.check_update_sig.emit)

        # 所有开关设置项自动保存
        self._connect_switch_cards()

    def _connect_switch_cards(self):
        """连接所有开关设置卡的信号到保存函数"""
        switch_cards = [
            self.acrylic_card,
            self.msg_notify_card,
            self.msg_sound_card,
            self.desktop_notify_card,
            self.quick_reply_card,
            self.read_receipt_card,
            self.typing_indicator_card,
            self.ai_auto_reply_card,
            self.check_update_card
        ]

        for card in switch_cards:
            if hasattr(card, 'checkedChanged'):
                card.checkedChanged.connect(lambda checked, c=card: save_config())

    def __on_theme_changed(self, theme: Theme):
        """主题改变槽函数"""
        setTheme(theme)

    def __on_clear_context_clicked(self):
        """清空 AI 上下文"""
        InfoBar.success(
            "",
            "AI 对话上下文已清空",
            parent=self.window()
        )

    def __show_restart_tooltip(self):
        """显示重启提示"""
        InfoBar.warning(
            "",
            "配置将在重启后生效",
            parent=self.window()
        )
