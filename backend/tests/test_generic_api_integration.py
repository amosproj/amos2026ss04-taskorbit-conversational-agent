"""End-to-end integration tests for GenericApiTool (#66 AC5).

Proves the adapter can configure-and-call a real external HTTP service
without any tool-specific Python code: we point a single config at
httpbin.org/get, supply runtime args, and assert the response makes it
back through substitution + extraction + the standardised envelope.

Each test is marked ``integration`` and skipped on network failures so
the suite stays useful in offline / restricted-CI environments. Run the
integration tests explicitly with::

    poetry run pytest -m integration
"""

from __future__ import annotations

import httpx
import pytest

from taskorbit.tools.generic_api import GenericApiTool

pytestmark = pytest.mark.integration


@pytest.fixture
def tool() -> GenericApiTool:
    return GenericApiTool()


async def test_httpbin_get_round_trip_with_substitution_and_extraction(
    tool: GenericApiTool,
) -> None:
    """A single config + caller args, against a real public HTTP service.

    httpbin echoes everything back, which lets us assert that:
      - the URL template substituted args.path correctly
      - the query template substituted args.q
      - the response extraction pulled the echoed values out of the
        standardised httpbin shape
      - the result envelope mirrors the documented success contract
    """
    config: dict[str, object] = {
        "request": {
            "method": "GET",
            "url": "https://httpbin.org/anything/{{args.path}}",
            "query": {"q": "{{args.q}}"},
            "timeout_seconds": 15,
        },
        "response": {
            "extract": {
                "echoed_path": "url",
                "echoed_q": "args.q",
                "echoed_method": "method",
            }
        },
        "args_schema": {
            "type": "object",
            "required": ["path", "q"],
            "properties": {
                "path": {"type": "string"},
                "q": {"type": "string"},
            },
        },
        "args": {"path": "taskorbit-66", "q": "hello"},
    }

    try:
        result = await tool.execute(config)
    except (httpx.RequestError, httpx.TimeoutException) as exc:
        pytest.skip(f"network unavailable for integration test: {exc}")

    assert result.success is True, result.error
    assert result.data["status"] == 200

    extracted = result.data["data"]
    assert extracted["echoed_method"] == "GET"
    assert "taskorbit-66" in str(extracted["echoed_path"])
    assert extracted["echoed_q"] == "hello"

    # Raw payload is preserved alongside extracted view so reviewers /
    # operators can still inspect what httpbin actually returned.
    assert result.data["raw"]["url"].endswith("?q=hello") or "?q=hello" in result.data["raw"]["url"]


async def test_httpbin_404_returns_http_4xx_envelope(tool: GenericApiTool) -> None:
    """A real 404 must surface the standardised HTTP_4XX code, not a string."""
    config: dict[str, object] = {
        "request": {
            "method": "GET",
            "url": "https://httpbin.org/status/404",
            "timeout_seconds": 15,
        },
    }

    try:
        result = await tool.execute(config)
    except (httpx.RequestError, httpx.TimeoutException) as exc:
        pytest.skip(f"network unavailable for integration test: {exc}")

    assert result.success is False
    assert result.data["error_code"] == "HTTP_4XX"
    assert result.data["status"] == 404
