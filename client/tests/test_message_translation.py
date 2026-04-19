from client.core.message_translation import (
    detect_text_language_code,
    language_name_for_code,
    should_auto_translate_text,
)


def test_detect_text_language_code_for_supported_languages() -> None:
    assert detect_text_language_code("你好，明天见。") == "zh-CN"
    assert detect_text_language_code("내일 같이 갈래요?") == "ko-KR"
    assert detect_text_language_code("Would you like dinner tomorrow?") == "en-US"


def test_should_auto_translate_text_skips_current_language() -> None:
    assert should_auto_translate_text("Would you like dinner tomorrow?", "zh-CN") is True
    assert should_auto_translate_text("你好，明天见。", "zh-CN") is False
    assert should_auto_translate_text("12345?!", "zh-CN") is False


def test_language_name_for_code_fallbacks_to_english() -> None:
    assert language_name_for_code("zh-CN") == "中文"
    assert language_name_for_code("ko-KR") == "韩文"
    assert language_name_for_code("en-US") == "英文"
    assert language_name_for_code("fr-FR") == "英文"
