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

from taskorbit.api.deps import get_current_user_id
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
    monkeypatch.setenv("LIVEKIT_AGENT_DISPATCH_NAME", "")
    monkeypatch.setenv("LIVEKIT_AGENT_NAME", "")
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
    app = create_app()
    app.dependency_overrides[get_current_user_id] = lambda: 1
    return TestClient(app)


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


def test_token_with_metadata_attaches_json_to_jwt(configured_settings: None) -> None:
    """When metadata is provided, it is JSON-serialised onto the AccessToken."""
    with patch("taskorbit.api.routes.livekit.lk_api.AccessToken") as mock_access_token:
        instance = mock_access_token.return_value
        instance.with_identity.return_value = instance
        instance.with_grants.return_value = instance
        instance.with_metadata.return_value = instance
        instance.to_jwt.return_value = _FAKE_JWT

        with _client() as client:
            response = client.post(
                "/v1/livekit/token",
                json={
                    "identity": "dev-user",
                    "room": "taskorbit-dev-room",
                    "metadata": {"agent_id": "abc-123", "greeting": "Hi!"},
                },
            )

    assert response.status_code == 200
    instance.with_metadata.assert_called_once()
    metadata_arg = instance.with_metadata.call_args.args[0]
    assert isinstance(metadata_arg, str)
    import json

    assert json.loads(metadata_arg) == {"agent_id": "abc-123", "greeting": "Hi!"}


def test_token_without_metadata_does_not_call_with_metadata(
    configured_settings: None,
) -> None:
    """Backwards compatibility: omitting metadata leaves the JWT clean."""
    with patch("taskorbit.api.routes.livekit.lk_api.AccessToken") as mock_access_token:
        instance = mock_access_token.return_value
        instance.with_identity.return_value = instance
        instance.with_grants.return_value = instance
        instance.with_metadata.return_value = instance
        instance.to_jwt.return_value = _FAKE_JWT

        with _client() as client:
            response = client.post(
                "/v1/livekit/token",
                json={"identity": "dev-user", "room": "taskorbit-dev-room"},
            )

    assert response.status_code == 200
    instance.with_metadata.assert_not_called()


def test_token_metadata_too_large_returns_413(configured_settings: None) -> None:
    """A metadata payload larger than the cap is rejected before signing."""
    big_payload = {"persona": "x" * 5000}
    with _client() as client:
        response = client.post(
            "/v1/livekit/token",
            json={
                "identity": "dev-user",
                "room": "taskorbit-dev-room",
                "metadata": big_payload,
            },
        )

    assert response.status_code == 413


def test_token_with_env_agent_dispatch_calls_with_room_config(
    configured_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cloud agent id in LIVEKIT_AGENT_DISPATCH_NAME embeds RoomAgentDispatch."""
    monkeypatch.setenv("LIVEKIT_AGENT_DISPATCH_NAME", "CA_nBrjReA5YgFE")
    get_settings.cache_clear()
    try:
        with patch("taskorbit.api.routes.livekit.lk_api.AccessToken") as mock_access_token:
            instance = mock_access_token.return_value
            instance.with_identity.return_value = instance
            instance.with_grants.return_value = instance
            instance.with_room_config.return_value = instance
            instance.to_jwt.return_value = _FAKE_JWT

            with _client() as client:
                response = client.post(
                    "/v1/livekit/token",
                    json={"identity": "dev-user", "room": "taskorbit-new-room"},
                )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 200
    instance.with_room_config.assert_called_once()


def test_token_agent_dispatch_name_in_body_overrides_env(
    configured_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LIVEKIT_AGENT_DISPATCH_NAME", "CA_from_env")
    get_settings.cache_clear()
    try:
        with patch("taskorbit.api.routes.livekit.lk_api.AccessToken") as mock_access_token:
            with patch("taskorbit.api.routes.livekit.lk_api.RoomConfiguration") as mock_rc:
                with patch(
                    "taskorbit.api.routes.livekit.lk_api.RoomAgentDispatch",
                ) as mock_rad:
                    instance = mock_access_token.return_value
                    instance.with_identity.return_value = instance
                    instance.with_grants.return_value = instance
                    instance.with_room_config.return_value = instance
                    instance.to_jwt.return_value = _FAKE_JWT
                    mock_rc.return_value = object()

                    with _client() as client:
                        response = client.post(
                            "/v1/livekit/token",
                            json={
                                "identity": "dev-user",
                                "room": "r1",
                                "agent_dispatch_name": "CA_from_body",
                            },
                        )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 200
    mock_rad.assert_called_once_with(
        agent_name="CA_from_body",
        metadata="",
    )


def test_token_with_env_livekit_agent_name_alias_calls_with_room_config(
    configured_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LIVEKIT_AGENT_NAME is an alias for the cloud agent dispatch target."""
    monkeypatch.setenv("LIVEKIT_AGENT_NAME", "CA_nBrjReA5YgFE")
    get_settings.cache_clear()
    try:
        with patch("taskorbit.api.routes.livekit.lk_api.AccessToken") as mock_access_token:
            instance = mock_access_token.return_value
            instance.with_identity.return_value = instance
            instance.with_grants.return_value = instance
            instance.with_room_config.return_value = instance
            instance.to_jwt.return_value = _FAKE_JWT

            with _client() as client:
                response = client.post(
                    "/v1/livekit/token",
                    json={"identity": "dev-user", "room": "taskorbit-room-alias"},
                )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 200
    instance.with_room_config.assert_called_once()
