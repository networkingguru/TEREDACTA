"""Tests for logging configuration wiring."""
import logging
import sys
import pytest
from teredacta.config import TeredactaConfig


def test_setup_logging_configures_file_handler(tmp_path):
    from teredacta.__main__ import setup_logging
    log_file = tmp_path / "test.log"
    cfg = TeredactaConfig(log_path=str(log_file), log_level="debug")
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    try:
        setup_logging(cfg)
        handler_types = [type(h).__name__ for h in root.handlers]
        assert "RotatingFileHandler" in handler_types
        assert root.level == logging.DEBUG
    finally:
        root.handlers = original_handlers


def test_setup_logging_no_file_handler_when_empty_path():
    from teredacta.__main__ import setup_logging
    cfg = TeredactaConfig(log_path="", log_level="info")
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    try:
        setup_logging(cfg)
        handler_types = [type(h).__name__ for h in root.handlers]
        assert "RotatingFileHandler" not in handler_types
    finally:
        root.handlers = original_handlers


def test_setup_logging_stderr_handler_present():
    from teredacta.__main__ import setup_logging
    cfg = TeredactaConfig(log_path="", log_level="warning")
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    try:
        setup_logging(cfg)
        stream_handlers = [h for h in root.handlers if isinstance(h, logging.StreamHandler)
                          and not isinstance(h, logging.FileHandler)]
        assert len(stream_handlers) >= 1
        assert root.level == logging.WARNING
    finally:
        root.handlers = original_handlers


def test_setup_logging_writes_to_file(tmp_path):
    from teredacta.__main__ import setup_logging
    log_file = tmp_path / "app.log"
    cfg = TeredactaConfig(log_path=str(log_file), log_level="info")
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    try:
        setup_logging(cfg)
        test_logger = logging.getLogger("teredacta.test")
        test_logger.info("stability test message")
        for h in root.handlers:
            h.flush()
        content = log_file.read_text()
        assert "stability test message" in content
    finally:
        root.handlers = original_handlers


def test_uncaught_exception_is_logged(tmp_path):
    from teredacta.__main__ import setup_logging
    log_file = tmp_path / "crash.log"
    cfg = TeredactaConfig(log_path=str(log_file), log_level="info")
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_excepthook = sys.excepthook
    try:
        setup_logging(cfg)
        assert sys.excepthook is not original_excepthook
    finally:
        root.handlers = original_handlers
        sys.excepthook = original_excepthook
