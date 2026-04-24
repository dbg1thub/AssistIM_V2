from pathlib import Path

from client.core.file_text_extraction import (
    FILE_SUMMARY_EXTRA_KEY,
    FILE_TEXT_EXTRACT_EXTRA_KEY,
    FileTextExtractionConfig,
    FileTextExtractionError,
    LocalFileTextExtractor,
    file_summary_display_text,
)


def test_local_file_text_extractor_reads_text_and_markdown(tmp_path) -> None:
    text_file = tmp_path / "notes.md"
    text_file.write_text("# 周会\n\n明天下午三点确认方案。", encoding="utf-8")
    extractor = LocalFileTextExtractor(FileTextExtractionConfig(max_text_chars=200))

    result = extractor.extract_sync(str(text_file), display_name="notes.md")

    assert result.text == "# 周会\n\n明天下午三点确认方案。"
    assert result.file_name == "notes.md"
    assert result.file_ext == ".md"
    assert result.truncated is False


def test_local_file_text_extractor_rejects_unsupported_and_oversized_files(tmp_path) -> None:
    unsupported = tmp_path / "archive.zip"
    unsupported.write_bytes(b"zip")
    extractor = LocalFileTextExtractor(FileTextExtractionConfig(max_file_bytes=4))

    try:
        extractor.extract_sync(str(unsupported), display_name="archive.zip")
    except FileTextExtractionError as exc:
        assert exc.code == "FILE_TEXT_UNSUPPORTED_TYPE"
    else:
        raise AssertionError("unsupported file should fail")

    oversized = tmp_path / "large.txt"
    oversized.write_text("12345", encoding="utf-8")
    try:
        extractor.extract_sync(str(oversized), display_name="large.txt")
    except FileTextExtractionError as exc:
        assert exc.code == "FILE_TEXT_FILE_TOO_LARGE"
    else:
        raise AssertionError("oversized file should fail")


def test_file_summary_display_text_maps_local_statuses() -> None:
    assert file_summary_display_text({FILE_SUMMARY_EXTRA_KEY: {"status": "pending"}}) == "正在总结文件内容..."
    assert file_summary_display_text({FILE_SUMMARY_EXTRA_KEY: {"status": "ready", "text": "这是总结"}}) == "这是总结"
    assert file_summary_display_text({FILE_SUMMARY_EXTRA_KEY: {"status": "failed"}}) == "文件总结失败"
    assert file_summary_display_text(
        {FILE_TEXT_EXTRACT_EXTRA_KEY: {"status": "skipped", "reason": "unsupported_type"}}
    ) == "暂不支持总结该文件类型"
