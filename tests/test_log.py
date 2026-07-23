"""Tests for logging setup."""

from __future__ import annotations

import io
import logging

from mcp_common.log import setup_logging


def _reset_root():
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)


def test_returns_the_named_logger():
    _reset_root()
    assert setup_logging("brain", stream=io.StringIO()).name == "brain"


def test_default_level_is_info():
    _reset_root()
    assert setup_logging("svc-a", stream=io.StringIO()).level == logging.INFO


def test_explicit_level_wins():
    _reset_root()
    logger = setup_logging("svc-b", level="warning", stream=io.StringIO())
    assert logger.level == logging.WARNING


def test_env_level_is_honoured(monkeypatch):
    _reset_root()
    monkeypatch.setenv("LOG_LEVEL", "debug")
    assert setup_logging("svc-c", stream=io.StringIO()).level == logging.DEBUG


def test_argument_beats_env(monkeypatch):
    _reset_root()
    monkeypatch.setenv("LOG_LEVEL", "debug")
    assert setup_logging("svc-d", level="ERROR", stream=io.StringIO()).level == logging.ERROR


def test_noisy_loggers_are_quieted():
    _reset_root()
    setup_logging("svc-e", stream=io.StringIO())
    assert logging.getLogger("mcp").level == logging.WARNING


def test_writes_to_the_given_stream():
    _reset_root()
    stream = io.StringIO()
    logger = setup_logging("svc-f", stream=stream)
    logger.info("hello from the service")
    assert "hello from the service" in stream.getvalue()
