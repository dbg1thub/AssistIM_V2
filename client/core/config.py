# coding:utf-8
"""
应用配置文件 - 遵循 PyQt-Fluent-Widgets 模式
用于定义所有设置项的序列化和反序列化

添加新设置的步骤：
1. 在 Config 类中添加新的 ConfigItem/OptionsConfigItem 等
2. 在 settings_interface.qss.qss.py 中添加对应的 SettingCard
3. 使用 cfg.get(cfg.xxx) 读取设置，cfg.set(cfg.xxx, value) 写入设置
"""

import os
import sys
from enum import Enum

from qfluentwidgets import (
    qconfig, QConfig, ConfigItem, OptionsConfigItem, BoolValidator,
    ColorConfigItem, OptionsValidator, RangeConfigItem, RangeValidator,
    FolderListValidator, EnumSerializer, FolderValidator, ConfigSerializer,
    Theme
)
from PySide6.QtCore import Qt, QLocale


class Language(Enum):
    """ Language enumeration """

    CHINESE_SIMPLIFIED = QLocale(QLocale.Language.Chinese, QLocale.Country.China)
    ENGLISH = QLocale(QLocale.Language.English, QLocale.Country.UnitedStates)
    KOREA = QLocale(QLocale.Language.Korean, QLocale.Country.SouthKorea)
    AUTO = QLocale()


class LanguageSerializer(ConfigSerializer):
    """ Language serializer """

    def serialize(self, language):
        return language.value.name() if language != Language.AUTO else "Auto"

    def deserialize(self, value: str):
        return Language(QLocale(value)) if value != "Auto" else Language.AUTO


def isWin11():
    """判断是否为 Windows 11"""
    return sys.platform == 'win32' and sys.getwindowsversion().build >= 22000


# ============ 序列化器 ============

class ThemeModeSerializer(ConfigSerializer):
    """主题模式序列化器"""

    def serialize(self, mode):
        return mode.value

    def deserialize(self, value: str):
        return Theme(value)


class RecallTime(Enum):
    """消息撤回时间枚举"""
    TWO_MINUTES = 2
    FIVE_MINUTES = 5
    UNLIMITED = 0


class RecallTimeSerializer(ConfigSerializer):
    """消息撤回时间序列化器"""

    def serialize(self, time):
        return time.value

    def deserialize(self, value: int):
        return RecallTime(value)


class AIModel(Enum):
    """AI模型枚举"""
    GPT_4 = "GPT-4"
    GPT_35 = "GPT-3.5"
    GPT_4O = "GPT-4o"
    CLAUDE_3 = "Claude-3"
    LOCAL = "本地模型"


class AIProvider(Enum):
    """AI服务提供商枚举"""
    OPENAI = "OpenAI"
    ANTHROPIC = "Anthropic"
    CUSTOM = "自定义"


class AIModelSerializer(ConfigSerializer):
    """AI模型序列化器"""

    def serialize(self, model):
        return model.value

    def deserialize(self, value: str):
        return AIModel(value)


class AIProviderSerializer(ConfigSerializer):
    """AI提供商序列化器"""

    def serialize(self, provider):
        return provider.value

    def deserialize(self, value: str):
        return AIProvider(value)


class Config(QConfig):
    """应用配置类 - 所有设置项定义在这里"""

    # ============ 窗口设置 (Window) ============
    micaEnabled = ConfigItem(
        "Window", "MicaEnabled", isWin11(), BoolValidator())
    dpiScale = OptionsConfigItem(
        "MainWindow", "DpiScale", "Auto", OptionsValidator([1, 1.25, 1.5, 1.75, 2, "Auto"]), restart=True)
    language = OptionsConfigItem(
        "MainWindow", "Language", Language.AUTO, OptionsValidator(Language), LanguageSerializer(), restart=True)

    # ============ 主题设置 (Theme) ============
    themeMode = OptionsConfigItem(
        "Theme", "ThemeMode", Theme.AUTO,
        OptionsValidator(Theme), ThemeModeSerializer())
    themeColor = ColorConfigItem("Theme", "ThemeColor", "#07c160")

    # ============ 服务器设置 (Server) ============
    serverHost = ConfigItem(
        "Server", "ServerHost", "localhost")
    serverPort = ConfigItem(
        "Server", "ServerPort", 8000, RangeValidator(1, 65535))
    wsPort = ConfigItem(
        "Server", "WsPort", 8000, RangeValidator(1, 65535))

    # ============ 通知设置 (Notification) ============
    enableMessageNotification = ConfigItem(
        "Notification", "EnableMessageNotification", True, BoolValidator())
    enableMessageSound = ConfigItem(
        "Notification", "EnableMessageSound", True, BoolValidator())
    enableDesktopNotification = ConfigItem(
        "Notification", "EnableDesktopNotification", True, BoolValidator())

    # ============ 聊天设置 (Chat) ============
    enableQuickReply = ConfigItem(
        "Chat", "EnableQuickReply", True, BoolValidator())
    enableReadReceipt = ConfigItem(
        "Chat", "EnableReadReceipt", True, BoolValidator())
    enableTypingIndicator = ConfigItem(
        "Chat", "EnableTypingIndicator", True, BoolValidator())
    messageRecallTime = OptionsConfigItem(
        "Chat", "MessageRecallTime", RecallTime.FIVE_MINUTES,
        OptionsValidator(RecallTime), RecallTimeSerializer())

    # ============ AI 设置 (AI) ============
    enableAIAutoReply = ConfigItem(
        "AI", "EnableAIAutoReply", False, BoolValidator())
    aiModel = OptionsConfigItem(
        "AI", "AIModel", AIModel.GPT_35,
        OptionsValidator(AIModel), AIModelSerializer())
    aiProvider = OptionsConfigItem(
        "AI", "AIProvider", AIProvider.OPENAI,
        OptionsValidator(AIProvider), AIProviderSerializer())
    aiApiKey = ConfigItem(
        "AI", "AIApiKey", "")
    aiBaseUrl = ConfigItem(
        "AI", "AIBaseUrl", "https://api.openai.com/v1")
    aiMaxTokens = ConfigItem(
        "AI", "AIMaxTokens", 2048, RangeValidator(1, 128000))
    aiTemperature = ConfigItem(
        "AI", "AITemperature", 0.7)

    # ============ 更新设置 (Update) ============
    checkUpdateAtStartUp = ConfigItem(
        "Update", "CheckUpdateAtStartUp", True, BoolValidator())

    # ============ 关于 (About) ============
    @property
    def appVersion(self):
        """获取应用版本"""
        return "v1.0.0"

    @property
    def appName(self):
        """获取应用名称"""
        return "AssistIM"


# 创建全局配置实例
cfg = Config()

# 使用 qfluentwidgets 提供的 qconfig 管理配置文件
# 配置将会被序列化到 `data/config.json` 中
qconfig.load("data/config.json", cfg)


def save_config():
    """保存配置到文件"""
    # 保存到通过 qconfig.load 绑定的同一路径
    cfg.save()


def get_config_value(key: str, default=None):
    """
    获取配置值（便捷方法）

    Args:
        key: 配置项名称（不含cfg.前缀）
        default: 默认值

    Returns:
        配置值
    """
    if hasattr(cfg, key):
        return cfg.get(getattr(cfg, key))
    return default


def set_config_value(key: str, value):
    """
    设置配置值（便捷方法）

    Args:
        key: 配置项名称（不含cfg.前缀）
        value: 要设置的值
    """
    if hasattr(cfg, key):
        cfg.set(getattr(cfg, key), value)
        save_config()
