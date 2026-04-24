from pathlib import Path
import sys

from client.core import logging as app_logging


def test_logging_respects_configured_level_and_suppresses_qasync_debug() -> None:
    logging_source = Path("client/core/logging.py").read_text(encoding="utf-8")

    assert "root_logger.setLevel(logging.DEBUG)" not in logging_source
    assert "queue_handler.setLevel(logging.DEBUG)" not in logging_source
    assert "handler.setLevel(logging.DEBUG)" not in logging_source
    assert 'logging.getLogger("qasync").setLevel(logging.WARNING)' in logging_source


def test_console_stream_write_failure_does_not_disable_future_console_output(tmp_path, monkeypatch, capsys) -> None:
    class FlakyConsoleStream:
        closed = False

        def __init__(self) -> None:
            self.fail_next_write = True
            self.written: list[str] = []

        def write(self, value: str) -> int:
            if self.fail_next_write:
                self.fail_next_write = False
                raise OSError("console stream is temporarily unavailable")
            self.written.append(value)
            return len(value)

        def flush(self) -> None:
            return None

    log_file = tmp_path / "assistim.log"
    flaky_stream = FlakyConsoleStream()
    monkeypatch.setattr(sys, "stdout", flaky_stream)
    try:
        app_logging.setup_logging(
            app_logging.LogConfig(
                level="INFO",
                file_path=str(log_file),
                max_bytes=1024 * 1024,
                backup_count=1,
                enable_console=True,
                enable_file=True,
            )
        )

        logger = app_logging.get_logger("client.tests.logging")
        logger.info("first console write may fail")
        logger.info("second console write should be visible")
        app_logging._queue.join()

        captured = capsys.readouterr()
        assert "--- Logging error ---" not in captured.err
        assert "first console write may fail" in log_file.read_text(encoding="utf-8")
        assert "second console write should be visible" in log_file.read_text(encoding="utf-8")
        assert any("second console write should be visible" in value for value in flaky_stream.written)
    finally:
        app_logging.setup_logging(
            app_logging.LogConfig(
                level="INFO",
                file_path=str(tmp_path / "disabled.log"),
                max_bytes=1024 * 1024,
                backup_count=1,
                enable_console=False,
                enable_file=False,
            )
        )
