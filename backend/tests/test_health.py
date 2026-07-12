"""Smoke tests that verify the API boots and the health endpoint is wired.

Run with: `poetry run pytest`
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from taskorbit.api.main import create_app
from taskorbit.config import get_settings


def test_health_endpoint_returns_ok() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "taskorbit-backend"
    assert "version" in body
    assert "livekit_configured" in body


def test_health_endpoint_reports_livekit_configured(monkeypatch) -> None:
    monkeypatch.setenv("LIVEKIT_URL", "wss://example.livekit.cloud")
    monkeypatch.setenv("LIVEKIT_API_KEY", "test-key")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "test-secret")
    get_settings.cache_clear()
    try:
        app = create_app()
        with TestClient(app) as client:
            response = client.get("/health")
        assert response.json()["livekit_configured"] is True
    finally:
        get_settings.cache_clear()


def test_health_endpoint_reports_livekit_not_configured(monkeypatch) -> None:
    monkeypatch.setenv("LIVEKIT_URL", "")
    monkeypatch.setenv("LIVEKIT_API_KEY", "")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "")
    get_settings.cache_clear()
    try:
        app = create_app()
        with TestClient(app) as client:
            response = client.get("/health")
        assert response.json()["livekit_configured"] is False
    finally:
        get_settings.cache_clear()
