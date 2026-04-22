from pathlib import Path


def test_logging_respects_configured_level_and_suppresses_qasync_debug() -> None:
    logging_source = Path("client/core/logging.py").read_text(encoding="utf-8")

    assert "root_logger.setLevel(logging.DEBUG)" not in logging_source
    assert "queue_handler.setLevel(logging.DEBUG)" not in logging_source
    assert "handler.setLevel(logging.DEBUG)" not in logging_source
    assert 'logging.getLogger("qasync").setLevel(logging.WARNING)' in logging_source
