"""Tests for POST /v1/livekit/token.

Covers the full validation matrix called out in ticket #26:

1. Successful token generation.
2. Missing `identity` (422).
3. Missing `room` (422).
4. Missing LiveKit credentials (503).
5. The configured API secret never appears in the response body.
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from taskorbit.api.main import create_app
from taskorbit.config import get_settings

_FAKE_KEY = "test-api-key"
_FAKE_SECRET = "test-api-secret-DO-NOT-LEAK"
_FAKE_URL = "wss://test.livekit.cloud"
_FAKE_JWT = "header.payload.signature"


@pytest.fixture
def configured_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Inject valid LiveKit credentials into the cached Settings instance."""
    monkeypatch.setenv("LIVEKIT_URL", _FAKE_URL)
    monkeypatch.setenv("LIVEKIT_API_KEY", _FAKE_KEY)
    monkeypatch.setenv("LIVEKIT_API_SECRET", _FAKE_SECRET)
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


@pytest.fixture
def empty_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Force LiveKit credentials to be unset for the duration of a test."""
    monkeypatch.setenv("LIVEKIT_URL", "")
    monkeypatch.setenv("LIVEKIT_API_KEY", "")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "")
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


def _client() -> TestClient:
    return TestClient(create_app())


def test_token_success_returns_jwt_url_room_identity(
    configured_settings: None,
) -> None:
    with patch("taskorbit.api.routes.livekit.lk_api.AccessToken") as mock_access_token:
        instance = mock_access_token.return_value
        instance.with_identity.return_value = instance
        instance.with_grants.return_value = instance
        instance.to_jwt.return_value = _FAKE_JWT

        with _client() as client:
            response = client.post(
                "/v1/livekit/token",
                json={"identity": "dev-user", "room": "taskorbit-dev-room"},
            )

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "token": _FAKE_JWT,
        "url": _FAKE_URL,
        "room": "taskorbit-dev-room",
        "identity": "dev-user",
    }
    mock_access_token.assert_called_once_with(_FAKE_KEY, _FAKE_SECRET)


def test_token_missing_identity_returns_422(configured_settings: None) -> None:
    with _client() as client:
        response = client.post("/v1/livekit/token", json={"room": "taskorbit-dev-room"})
    assert response.status_code == 422


def test_token_missing_room_returns_422(configured_settings: None) -> None:
    with _client() as client:
        response = client.post("/v1/livekit/token", json={"identity": "dev-user"})
    assert response.status_code == 422


def test_token_empty_strings_return_422(configured_settings: None) -> None:
    with _client() as client:
        response = client.post(
            "/v1/livekit/token",
            json={"identity": "", "room": ""},
        )
    assert response.status_code == 422


def test_token_missing_credentials_returns_503(empty_settings: None) -> None:
    with _client() as client:
        response = client.post(
            "/v1/livekit/token",
            json={"identity": "dev-user", "room": "taskorbit-dev-room"},
        )
    assert response.status_code == 503
    detail = response.json().get("detail", "")
    assert "configured" in detail.lower()
    assert _FAKE_SECRET not in response.text


def test_token_response_does_not_leak_secret(configured_settings: None) -> None:
    with patch("taskorbit.api.routes.livekit.lk_api.AccessToken") as mock_access_token:
        instance = mock_access_token.return_value
        instance.with_identity.return_value = instance
        instance.with_grants.return_value = instance
        instance.to_jwt.return_value = _FAKE_JWT

        with _client() as client:
            response = client.post(
                "/v1/livekit/token",
                json={"identity": "dev-user", "room": "taskorbit-dev-room"},
            )

    assert response.status_code == 200
    assert _FAKE_SECRET not in response.text
    assert _FAKE_KEY not in response.text
