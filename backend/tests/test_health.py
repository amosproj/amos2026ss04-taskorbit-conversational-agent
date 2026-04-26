"""Smoke tests that verify the API boots and the health endpoint is wired.

Run with: `poetry run pytest`
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from taskorbit.api.main import create_app


def test_health_endpoint_returns_ok() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "taskorbit-backend"
    assert "version" in body
