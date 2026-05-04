"""Tests for POST /v1/livekit/token."""

from __future__ import annotations

from fastapi.testclient import TestClient

from taskorbit.api.main import create_app


def test_livekit_token_returns_503_when_keys_missing() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.post(
            "/v1/livekit/token",
            json={"room_name": "test-room", "participant_name": "user-1"},
        )
    # Keys are empty strings in test env → 503
    assert response.status_code == 503


def test_livekit_token_rejects_invalid_payload() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.post("/v1/livekit/token", json={})
    assert response.status_code == 422
