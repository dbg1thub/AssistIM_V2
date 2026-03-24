from client.models.message import MessageType
from client.ui.widgets.composer_clipboard import (
    clipboard_file_paths,
    clipboard_plain_text,
    deserialize_clipboard_segments,
    serialize_clipboard_segments,
)


def test_clipboard_segments_roundtrip_preserves_mixed_content():
    segments = [
        {"type": MessageType.TEXT, "content": "hello "},
        {
            "type": MessageType.IMAGE,
            "file_path": "C:/tmp/demo.png",
            "display_name": "demo.png",
        },
        {"type": MessageType.TEXT, "content": "🙂 world"},
    ]

    restored = deserialize_clipboard_segments(serialize_clipboard_segments(segments))

    assert restored == [
        {"type": MessageType.TEXT.value, "content": "hello "},
        {
            "type": MessageType.IMAGE.value,
            "file_path": "C:/tmp/demo.png",
            "display_name": "demo.png",
        },
        {"type": MessageType.TEXT.value, "content": "🙂 world"},
    ]


def test_clipboard_plain_text_keeps_text_emoji_and_attachment_hint():
    segments = [
        {"type": MessageType.TEXT, "content": "A🙂"},
        {
            "type": MessageType.FILE,
            "file_path": "C:/tmp/report.pdf",
            "display_name": "report.pdf",
        },
        {"type": MessageType.TEXT, "content": "B"},
    ]

    assert clipboard_plain_text(segments) == "A🙂[File: report.pdf]B"


def test_clipboard_file_paths_only_returns_attachment_entries():
    segments = [
        {"type": MessageType.TEXT, "content": "draft"},
        {"type": MessageType.IMAGE, "file_path": "C:/tmp/demo.png"},
        {"type": MessageType.FILE, "file_path": "C:/tmp/report.pdf"},
    ]

    assert clipboard_file_paths(segments) == [
        "C:/tmp/demo.png",
        "C:/tmp/report.pdf",
    ]


def test_clipboard_segments_preserve_whitespace_only_text_runs():
    segments = [
        {"type": MessageType.TEXT, "content": "  "},
        {"type": MessageType.IMAGE, "file_path": "C:/tmp/demo.png"},
        {"type": MessageType.TEXT, "content": "\n🙂"},
    ]

    restored = deserialize_clipboard_segments(serialize_clipboard_segments(segments))

    assert restored[0] == {"type": MessageType.TEXT.value, "content": "  "}
    assert restored[2] == {"type": MessageType.TEXT.value, "content": "\n🙂"}
