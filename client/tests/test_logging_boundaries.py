from pathlib import Path
import sys

from client.core import logging as app_logging


def test_logging_respects_configured_level_and_suppresses_qasync_debug() -> None:
    logging_source = Path("client/core/logging.py").read_text(encoding="utf-8")

    assert "root_logger.setLevel(logging.DEBUG)" not in logging_source
    assert "queue_handler.setLevel(logging.DEBUG)" not in logging_source
    assert "handler.setLevel(logging.DEBUG)" not in logging_source
    assert 'logging.getLogger("qasync").setLevel(logging.WARNING)' in logging_source


def test_console_stream_write_failure_does_not_emit_logging_error(tmp_path, monkeypatch, capsys) -> None:
    class BrokenConsoleStream:
        closed = False

        def write(self, value: str) -> int:
            raise OSError("console stream is unavailable")

        def flush(self) -> None:
            return None

    log_file = tmp_path / "assistim.log"
    monkeypatch.setattr(sys, "stdout", BrokenConsoleStream())
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
        logger.info("console failure should not break file logging")
        app_logging._queue.join()

        captured = capsys.readouterr()
        assert "--- Logging error ---" not in captured.err
        assert "console failure should not break file logging" in log_file.read_text(encoding="utf-8")
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
