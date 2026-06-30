"""Settings tests for the persona guardrails scope short-circuit flag."""

from __future__ import annotations

from taskorbit.config import Settings, get_settings


def test_scope_shortcircuit_defaults_on_in_development() -> None:
    settings = Settings(app_env="development")
    assert settings.enable_scope_shortcircuit is True


def test_scope_shortcircuit_defaults_off_in_production() -> None:
    settings = Settings(app_env="production")
    assert settings.enable_scope_shortcircuit is False


def test_scope_shortcircuit_env_override_true(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("ENABLE_SCOPE_SHORTCIRCUIT", "true")
    try:
        settings = Settings(app_env="production")
        assert settings.enable_scope_shortcircuit is True
    finally:
        get_settings.cache_clear()


def test_scope_shortcircuit_env_override_false(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("ENABLE_SCOPE_SHORTCIRCUIT", "false")
    try:
        settings = Settings(app_env="development")
        assert settings.enable_scope_shortcircuit is False
    finally:
        get_settings.cache_clear()
