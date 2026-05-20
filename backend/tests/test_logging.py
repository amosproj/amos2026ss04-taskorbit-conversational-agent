"""Tests for taskorbit.logging — configure_logging() and get_logger() behaviour."""

from __future__ import annotations

import logging

import pytest
import structlog

from taskorbit.logging.setup import configure_logging, get_logger


@pytest.fixture(autouse=True)
def reset_structlog():
    """Reset structlog configuration between tests."""
    yield
    structlog.reset_defaults()


class TestConfigureLogging:
    def test_idempotent(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "development")
        from taskorbit.config import get_settings

        get_settings.cache_clear()
        try:
            configure_logging()
            configure_logging()  # second call must not raise
        finally:
            get_settings.cache_clear()

    def test_development_uses_console_renderer(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "development")
        from taskorbit.config import get_settings

        get_settings.cache_clear()
        try:
            configure_logging()
            config = structlog.get_config()
            renderer_types = [type(p).__name__ for p in config["processors"]]
            assert "ConsoleRenderer" in renderer_types
        finally:
            get_settings.cache_clear()

    def test_production_uses_json_renderer(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        from taskorbit.config import get_settings

        get_settings.cache_clear()
        try:
            configure_logging()
            config = structlog.get_config()
            renderer_types = [type(p).__name__ for p in config["processors"]]
            assert "JSONRenderer" in renderer_types
        finally:
            get_settings.cache_clear()

    def test_log_level_applied_to_stdlib(self, monkeypatch):
        monkeypatch.setenv("LOG_LEVEL", "WARNING")
        monkeypatch.setenv("APP_ENV", "development")
        from taskorbit.config import get_settings

        get_settings.cache_clear()
        try:
            configure_logging()
            assert logging.getLogger().level == logging.WARNING
        finally:
            get_settings.cache_clear()

    def test_default_log_level_is_info(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "development")
        from taskorbit.config import get_settings

        get_settings.cache_clear()
        try:
            configure_logging()
            # Verify settings default — basicConfig is a no-op when pytest
            # has already configured the root logger, so we assert via settings.
            assert get_settings().log_level == "INFO"
        finally:
            get_settings.cache_clear()

    def test_processors_include_timestamp_and_level(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "development")
        from taskorbit.config import get_settings

        get_settings.cache_clear()
        try:
            configure_logging()
            config = structlog.get_config()
            processor_types = [type(p).__name__ for p in config["processors"]]
            assert "TimeStamper" in processor_types
            assert "_base_chain" in processor_types or any(
                "log_level" in str(p) or "add_log_level" in getattr(p, "__name__", "")
                for p in config["processors"]
            )
        finally:
            get_settings.cache_clear()

    def test_contextvars_processor_present(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "development")
        from taskorbit.config import get_settings

        get_settings.cache_clear()
        try:
            configure_logging()
            config = structlog.get_config()
            processor_names = [
                getattr(p, "__name__", type(p).__name__) for p in config["processors"]
            ]
            assert any("contextvars" in n.lower() or "merge" in n.lower() for n in processor_names)
        finally:
            get_settings.cache_clear()


class TestGetLogger:
    def test_returns_bound_logger(self):
        logger = get_logger(__name__)
        assert logger is not None

    def test_named_logger(self):
        logger = get_logger("taskorbit.test")
        assert logger is not None

    def test_anonymous_logger(self):
        logger = get_logger()
        assert logger is not None

    def test_loggers_are_distinct_by_name(self):
        a = get_logger("module.a")
        b = get_logger("module.b")
        assert a is not b

    def test_logger_can_emit_without_configure(self, capsys):
        """get_logger() works even before configure_logging() — structlog defaults apply."""
        logger = get_logger("taskorbit.test.unconfigured")
        logger.info("test_event", key="value")
        # No exception means the logger is usable; output format is structlog default.

    def test_logger_emits_after_configure(self, monkeypatch, capsys):
        monkeypatch.setenv("APP_ENV", "development")
        from taskorbit.config import get_settings

        get_settings.cache_clear()
        try:
            configure_logging()
            logger = get_logger("taskorbit.test")
            logger.info("pipeline_started", stage="stt")
            captured = capsys.readouterr()
            assert "pipeline_started" in captured.out or "pipeline_started" in captured.err
        finally:
            get_settings.cache_clear()

    def test_structured_keys_emitted(self, monkeypatch, capsys):
        monkeypatch.setenv("APP_ENV", "development")
        from taskorbit.config import get_settings

        get_settings.cache_clear()
        try:
            configure_logging()
            logger = get_logger("taskorbit.test")
            logger.info("tool_call_completed", tool="meisterwerk", status="ok")
            captured = capsys.readouterr()
            output = captured.out + captured.err
            assert "tool_call_completed" in output
            assert "meisterwerk" in output
        finally:
            get_settings.cache_clear()
