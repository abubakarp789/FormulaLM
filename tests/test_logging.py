import logging

from formulalm.logging_utils import get_logger


def test_logger_writes_to_file_without_duplicate_handlers(tmp_path):
    log_file = tmp_path / "logs" / "run.log"
    log = get_logger("formulalm.test", log_file=log_file)
    log = get_logger("formulalm.test", log_file=log_file)  # second call must not add handlers
    log.info("hello %s", "world")
    for h in log.handlers:
        h.flush()

    assert len(log.handlers) == 2  # one console + one file
    assert "hello world" in log_file.read_text(encoding="utf-8")
    assert log.level == logging.INFO
