from client.ui.common.emoji_names import emoji_display_name


def test_emoji_display_name_uses_zh_resource() -> None:
    assert emoji_display_name("😀", language_code="zh-CN") == "嘿嘿"


def test_emoji_display_name_uses_ko_resource() -> None:
    assert emoji_display_name("😀", language_code="ko-KR") == "활짝 웃는 얼굴"


def test_emoji_display_name_falls_back_to_index_name_for_en() -> None:
    assert emoji_display_name("😀", language_code="en-US") == "grinning face"
