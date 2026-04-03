from client.models.message import normalize_message_mentions
from client.ui.widgets.composer_clipboard import deserialize_clipboard_segments, serialize_clipboard_segments


def test_normalize_message_mentions_keeps_valid_ranges_only():
    mentions = normalize_message_mentions(
        [
            {"start": 8, "end": 11, "display_name": "张三", "mention_type": "member", "member_id": "u-1"},
            {"start": 0, "end": 4, "display_name": "所有人", "mention_type": "all"},
            {"start": 2, "end": 3, "display_name": "坏数据", "mention_type": "member"},
            {"start": 99, "end": 120, "display_name": "越界", "mention_type": "member", "member_id": "u-2"},
        ],
        content="@所有人 hi @张三",
    )

    assert mentions == [
        {"start": 0, "end": 4, "display_name": "所有人", "mention_type": "all"},
        {"start": 8, "end": 11, "display_name": "张三", "mention_type": "member", "member_id": "u-1"},
    ]


def test_clipboard_segments_roundtrip_preserves_text_mentions():
    payload = [
        {
            "type": "text",
            "content": "@所有人 hi @张三",
            "extra": {
                "mentions": [
                    {"start": 0, "end": 4, "display_name": "所有人", "mention_type": "all"},
                    {"start": 8, "end": 11, "display_name": "张三", "mention_type": "member", "member_id": "u-1"},
                ]
            },
        }
    ]

    restored = deserialize_clipboard_segments(serialize_clipboard_segments(payload))

    assert restored == payload
