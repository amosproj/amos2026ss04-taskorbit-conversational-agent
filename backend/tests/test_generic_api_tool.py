"""Unit tests for GenericApiTool (#66).

Covers config parsing, template substitution with the env-var whitelist,
parameter validation, httpx execution (mocked), dot-path response
extraction, and the standardised error envelope / code taxonomy.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from taskorbit.tools.generic_api import (
    GenericApiConfigError,
    GenericApiTool,
    TemplateSubstitutionError,
    extract_arg_names,
    extract_path,
    extract_response,
    parse_config,
    substitute_string,
    substitute_tree,
)


def test_extract_arg_names_scans_all_request_sections() -> None:
    params = {
        "request": {
            "method": "POST",
            "url": "https://x/{{args.id}}",
            "headers": {"X-Trace": "{{args.trace}}", "X-Key": "{{env.SECRET}}"},
            "query": {"tz": "{{args.timeZone}}"},
            "body": {"nested": {"who": "{{args.user.name}}"}, "list": ["{{args.item}}", 5]},
        }
    }
    # First-seen order, top-level segment only, env refs excluded, deduped.
    assert extract_arg_names(params) == ["id", "trace", "timeZone", "user", "item"]


def test_extract_arg_names_empty_when_no_refs() -> None:
    assert (
        extract_arg_names({"request": {"method": "GET", "url": "https://x?tz=Europe/Berlin"}}) == []
    )
    assert extract_arg_names({}) == []
    assert extract_arg_names({"request": "nope"}) == []


@pytest.fixture
def tool() -> GenericApiTool:
    return GenericApiTool()


@pytest.fixture
def minimal_config() -> dict[str, object]:
    """Smallest config that passes parse_config validation."""
    return {
        "request": {"method": "GET", "url": "https://example.com/api"},
    }


@pytest.fixture
def full_config() -> dict[str, object]:
    """Realistic config exercising every supported field."""
    return {
        "request": {
            "method": "POST",
            "url": "https://api.example.com/v1/widgets/{{args.id}}",
            "headers": {"X-API-Key": "{{env.MY_TEST_KEY}}"},
            "query": {"verbose": "true"},
            "body": {"name": "{{args.name}}"},
            "timeout_seconds": 5,
        },
        "response": {
            "extract": {"result": "$.data.value"},
            "success_when": {"status_in": [200, 201]},
        },
        "auth": {"allowed_env": ["MY_TEST_KEY"]},
        "error_mapping": {"TIMEOUT": "Timed out."},
        "args_schema": {
            "type": "object",
            "required": ["id", "name"],
            "properties": {
                "id": {"type": "string"},
                "name": {"type": "string"},
            },
        },
    }


@pytest.fixture
def set_test_env() -> Iterator[None]:
    """Stash and restore MY_TEST_KEY so tests can run with it set."""
    old = os.environ.get("MY_TEST_KEY")
    os.environ["MY_TEST_KEY"] = "secret-value"
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("MY_TEST_KEY", None)
        else:
            os.environ["MY_TEST_KEY"] = old


# ---------------------------------------------------------------------------
# parse_config()
# ---------------------------------------------------------------------------


def test_parse_minimal_config_succeeds(minimal_config: dict[str, object]) -> None:
    config = parse_config(minimal_config)
    assert config.method == "GET"
    assert config.url == "https://example.com/api"
    assert config.timeout_seconds == 10.0  # default
    assert config.success_statuses == tuple(range(200, 300))
    assert config.allowed_env == frozenset()


def test_parse_full_config_preserves_every_field(full_config: dict[str, object]) -> None:
    config = parse_config(full_config)
    assert config.method == "POST"
    assert config.timeout_seconds == 5.0
    assert config.success_statuses == (200, 201)
    assert config.allowed_env == frozenset({"MY_TEST_KEY"})
    assert config.error_mapping == {"TIMEOUT": "Timed out."}
    assert config.extract == {"result": "$.data.value"}


def test_parse_method_normalises_case() -> None:
    config = parse_config({"request": {"method": "post", "url": "https://x"}})
    assert config.method == "POST"


def test_parse_rejects_unknown_method() -> None:
    with pytest.raises(GenericApiConfigError, match="method must be one of"):
        parse_config({"request": {"method": "TRACE", "url": "https://x"}})


def test_parse_rejects_missing_url() -> None:
    with pytest.raises(GenericApiConfigError, match="url is required"):
        parse_config({"request": {"method": "GET"}})


def test_parse_rejects_non_positive_timeout() -> None:
    with pytest.raises(GenericApiConfigError, match="timeout_seconds must be > 0"):
        parse_config({"request": {"method": "GET", "url": "https://x", "timeout_seconds": 0}})


def test_parse_rejects_non_dict_parameters() -> None:
    with pytest.raises(GenericApiConfigError, match="must be a JSON object"):
        parse_config("not-a-dict")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# substitute_string() + substitute_tree()
# ---------------------------------------------------------------------------


def test_substitute_args_only() -> None:
    result = substitute_string("/users/{{args.id}}", {"id": "42"}, frozenset())
    assert result == "/users/42"


def test_substitute_env_requires_whitelist(set_test_env: None) -> None:
    with pytest.raises(TemplateSubstitutionError, match="not in auth.allowed_env"):
        substitute_string("{{env.MY_TEST_KEY}}", {}, frozenset())


def test_substitute_env_allowed_resolves(set_test_env: None) -> None:
    result = substitute_string("Bearer {{env.MY_TEST_KEY}}", {}, frozenset({"MY_TEST_KEY"}))
    assert result == "Bearer secret-value"


def test_substitute_env_unset_raises() -> None:
    with pytest.raises(TemplateSubstitutionError, match="not set in the process environment"):
        substitute_string("{{env.DEFINITELY_UNSET_VAR}}", {}, frozenset({"DEFINITELY_UNSET_VAR"}))


def test_substitute_args_missing_raises() -> None:
    with pytest.raises(TemplateSubstitutionError, match="args key 'city' was not provided"):
        substitute_string("{{args.city}}", {}, frozenset())


def test_substitute_args_nested() -> None:
    result = substitute_string("{{args.user.id}}", {"user": {"id": "abc"}}, frozenset())
    assert result == "abc"


def test_substitute_tree_walks_dict_and_list(set_test_env: None) -> None:
    template = {
        "headers": {"X-Key": "{{env.MY_TEST_KEY}}"},
        "items": ["{{args.a}}", "{{args.b}}", 42],
        "number": 100,
    }
    result = substitute_tree(template, {"a": "x", "b": "y"}, frozenset({"MY_TEST_KEY"}))
    assert result == {
        "headers": {"X-Key": "secret-value"},
        "items": ["x", "y", 42],
        "number": 100,
    }


def test_substitute_tree_passes_non_string_scalars_through() -> None:
    assert substitute_tree(True, {}, frozenset()) is True
    assert substitute_tree(None, {}, frozenset()) is None
    assert substitute_tree(3.14, {}, frozenset()) == 3.14


# ---------------------------------------------------------------------------
# GenericApiTool.validate_parameters()
# ---------------------------------------------------------------------------


def test_validate_minimal_config_succeeds(
    tool: GenericApiTool, minimal_config: dict[str, object]
) -> None:
    assert tool.validate_parameters(minimal_config) is True


def test_validate_full_config_with_correct_args_succeeds(
    tool: GenericApiTool, full_config: dict[str, object]
) -> None:
    params = {**full_config, "args": {"id": "w1", "name": "Asad"}}
    assert tool.validate_parameters(params) is True


def test_validate_missing_required_arg_fails(
    tool: GenericApiTool, full_config: dict[str, object]
) -> None:
    params = {**full_config, "args": {"id": "w1"}}  # missing 'name'
    assert tool.validate_parameters(params) is False


def test_validate_wrong_arg_type_fails(
    tool: GenericApiTool, full_config: dict[str, object]
) -> None:
    params = {**full_config, "args": {"id": 1, "name": "Asad"}}  # id must be string
    assert tool.validate_parameters(params) is False


def test_validate_malformed_config_fails(tool: GenericApiTool) -> None:
    assert tool.validate_parameters({"request": {"method": "FOO", "url": "https://x"}}) is False


def test_validate_non_dict_args_fails(
    tool: GenericApiTool, minimal_config: dict[str, object]
) -> None:
    params = {**minimal_config, "args": "not-a-dict"}
    assert tool.validate_parameters(params) is False


# ---------------------------------------------------------------------------
# execute() — HTTP path (Stage 3)
# ---------------------------------------------------------------------------


def _mock_response(
    status_code: int = 200,
    json_body: object | None = None,
    text_body: str | None = None,
    headers: dict[str, str] | None = None,
) -> MagicMock:
    """Build a fake httpx.Response stand-in for AsyncClient.request mocking."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.headers = headers or {}
    if json_body is not None:
        resp.json = MagicMock(return_value=json_body)
        resp.text = ""
    else:
        resp.json = MagicMock(side_effect=ValueError("not json"))
        resp.text = text_body or ""
    return resp


def _patch_async_client(response: MagicMock | None = None, side_effect: object = None):
    """Patch httpx.AsyncClient with a context-manager that returns a request mock.

    Either `response` (a single fake Response) or `side_effect` (e.g.
    httpx.TimeoutException) drives the mocked behaviour.
    """
    request_mock = AsyncMock()
    if side_effect is not None:
        request_mock.side_effect = side_effect
    else:
        request_mock.return_value = response

    client_instance = MagicMock()
    client_instance.request = request_mock
    client_instance.__aenter__ = AsyncMock(return_value=client_instance)
    client_instance.__aexit__ = AsyncMock(return_value=None)
    return patch(
        "taskorbit.tools.generic_api.httpx.AsyncClient",
        return_value=client_instance,
    ), request_mock


async def test_execute_get_returns_json_body_on_2xx(tool: GenericApiTool) -> None:
    config = {
        "request": {"method": "GET", "url": "https://api.example.com/v1/echo"},
        "args_schema": {"type": "object", "properties": {}},
    }
    response = _mock_response(status_code=200, json_body={"result": "ok"})
    patcher, request_mock = _patch_async_client(response=response)

    with patcher:
        result = await tool.execute(config)

    assert result.success is True
    assert result.data["status"] == 200
    assert result.data["data"] == {"result": "ok"}
    request_mock.assert_awaited_once()
    call_kwargs = request_mock.call_args.kwargs
    assert call_kwargs["method"] == "GET"
    assert call_kwargs["url"] == "https://api.example.com/v1/echo"
    assert call_kwargs["json"] is None


async def test_execute_post_sends_substituted_body(
    tool: GenericApiTool, full_config: dict[str, object], set_test_env: None
) -> None:
    params = {**full_config, "args": {"id": "w1", "name": "Asad"}}
    response = _mock_response(status_code=201, json_body={"created": True})
    patcher, request_mock = _patch_async_client(response=response)

    with patcher:
        result = await tool.execute(params)

    assert result.success is True
    assert result.data["status"] == 201
    call_kwargs = request_mock.call_args.kwargs
    assert call_kwargs["method"] == "POST"
    assert call_kwargs["url"] == "https://api.example.com/v1/widgets/w1"
    assert call_kwargs["headers"] == {"X-API-Key": "secret-value"}
    assert call_kwargs["params"] == {"verbose": "true"}
    assert call_kwargs["json"] == {"name": "Asad"}


async def test_execute_non_success_status_returns_failure_with_body(
    tool: GenericApiTool, minimal_config: dict[str, object]
) -> None:
    response = _mock_response(status_code=404, json_body={"error": "not found"})
    patcher, _ = _patch_async_client(response=response)

    with patcher:
        result = await tool.execute(minimal_config)

    assert result.success is False
    assert result.data["status"] == 404
    assert result.data["data"] == {"error": "not found"}
    assert result.data["error_code"] == "HTTP_4XX"


async def test_execute_timeout_returns_timeout_error(
    tool: GenericApiTool, minimal_config: dict[str, object]
) -> None:
    patcher, _ = _patch_async_client(side_effect=httpx.TimeoutException("boom"))

    with patcher:
        result = await tool.execute(minimal_config)

    assert result.success is False
    assert result.data["error_code"] == "TIMEOUT"


async def test_execute_unparseable_response_falls_back_to_text(
    tool: GenericApiTool, minimal_config: dict[str, object]
) -> None:
    response = _mock_response(status_code=200, json_body=None, text_body="plain text body")
    patcher, _ = _patch_async_client(response=response)

    with patcher:
        result = await tool.execute(minimal_config)

    assert result.success is True
    assert result.data["data"] == "plain text body"


async def test_execute_short_circuits_on_invalid_config(tool: GenericApiTool) -> None:
    # Bad method should be rejected BEFORE httpx is touched.
    patcher, request_mock = _patch_async_client(response=_mock_response())

    with patcher:
        result = await tool.execute({"request": {"method": "TRACE", "url": "https://x"}})

    assert result.success is False
    assert result.data["error_code"] == "CONFIG_INVALID"
    assert "method must be one of" in result.data["error_detail"]
    request_mock.assert_not_awaited()


async def test_execute_short_circuits_on_missing_required_arg(
    tool: GenericApiTool, full_config: dict[str, object]
) -> None:
    # full_config requires id + name; provide only id.
    params = {**full_config, "args": {"id": "w1"}}
    patcher, request_mock = _patch_async_client(response=_mock_response())

    with patcher:
        result = await tool.execute(params)

    assert result.success is False
    assert result.data["error_code"] == "ARGS_INVALID"
    assert "name" in result.data["error_detail"]
    request_mock.assert_not_awaited()


async def test_execute_short_circuits_on_unwhitelisted_env(
    tool: GenericApiTool,
) -> None:
    # Config references {{env.SECRET}} but auth.allowed_env is empty,
    # so the template substitution step must reject before httpx fires.
    config = {
        "request": {
            "method": "GET",
            "url": "https://api.example.com",
            "headers": {"Authorization": "Bearer {{env.SECRET}}"},
        },
        "auth": {"allowed_env": []},
    }
    patcher, request_mock = _patch_async_client(response=_mock_response())

    with patcher:
        result = await tool.execute(config)

    assert result.success is False
    assert result.data["error_code"] == "TEMPLATE_INVALID"
    assert "allowed_env" in result.data["error_detail"]
    request_mock.assert_not_awaited()


# ---------------------------------------------------------------------------
# Response extraction (Stage 4)
# ---------------------------------------------------------------------------


def test_extract_path_walks_nested_dict() -> None:
    body = {"data": {"current": {"temp_c": 22.5}}}
    assert extract_path(body, "data.current.temp_c") == 22.5


def test_extract_path_returns_none_for_missing_segment() -> None:
    body = {"data": {"current": {}}}
    assert extract_path(body, "data.current.temp_c") is None


def test_extract_path_returns_none_when_traversing_through_non_dict() -> None:
    body = {"data": "not-a-dict"}
    assert extract_path(body, "data.current") is None


def test_extract_path_accepts_jsonpath_dollar_prefix() -> None:
    body = {"items": {"first": "a"}}
    assert extract_path(body, "$.items.first") == "a"


def test_extract_path_dollar_alone_returns_whole_body() -> None:
    body = {"any": "thing"}
    assert extract_path(body, "$") == body


def test_extract_response_builds_standardised_shape() -> None:
    body = {"data": {"current": {"temp_c": 22.5, "humidity": 80}}, "status": "ok"}
    result = extract_response(
        body,
        {
            "temperature": "data.current.temp_c",
            "humidity": "data.current.humidity",
            "status_text": "status",
        },
    )
    assert result == {"temperature": 22.5, "humidity": 80, "status_text": "ok"}


def test_extract_response_missing_paths_become_none() -> None:
    body = {"data": {"current": {"temp_c": 22.5}}}
    result = extract_response(
        body, {"temperature": "data.current.temp_c", "wind": "data.current.wind_kph"}
    )
    assert result == {"temperature": 22.5, "wind": None}


async def test_execute_applies_extract_and_keeps_raw(tool: GenericApiTool) -> None:
    config = {
        "request": {"method": "GET", "url": "https://api.example.com/weather"},
        "response": {
            "extract": {
                "temperature": "data.current.temp_c",
                "condition": "data.current.condition.text",
            }
        },
    }
    upstream_body = {
        "data": {"current": {"temp_c": 18.3, "condition": {"text": "Cloudy"}}},
        "meta": {"source": "weatherapi"},
    }
    response = _mock_response(status_code=200, json_body=upstream_body)
    patcher, _ = _patch_async_client(response=response)

    with patcher:
        result = await tool.execute(config)

    assert result.success is True
    assert result.data["data"] == {"temperature": 18.3, "condition": "Cloudy"}
    assert result.data["raw"] == upstream_body


async def test_execute_without_extract_returns_raw_as_data(
    tool: GenericApiTool, minimal_config: dict[str, object]
) -> None:
    upstream_body = {"any": "shape"}
    response = _mock_response(status_code=200, json_body=upstream_body)
    patcher, _ = _patch_async_client(response=response)

    with patcher:
        result = await tool.execute(minimal_config)

    assert result.success is True
    assert result.data["data"] == upstream_body
    assert "raw" not in result.data


async def test_execute_extract_applied_even_on_non_success_status(
    tool: GenericApiTool,
) -> None:
    config = {
        "request": {"method": "GET", "url": "https://api.example.com/get"},
        "response": {"extract": {"err": "error.message"}},
    }
    upstream_body = {"error": {"message": "not found"}}
    response = _mock_response(status_code=404, json_body=upstream_body)
    patcher, _ = _patch_async_client(response=response)

    with patcher:
        result = await tool.execute(config)

    assert result.success is False
    assert result.data["data"] == {"err": "not found"}
    assert result.data["raw"] == upstream_body


# ---------------------------------------------------------------------------
# Error normalisation (Stage 5)
# ---------------------------------------------------------------------------


async def test_execute_5xx_returns_http_5xx_code(
    tool: GenericApiTool, minimal_config: dict[str, object]
) -> None:
    response = _mock_response(status_code=503, json_body={"err": "down"})
    patcher, _ = _patch_async_client(response=response)

    with patcher:
        result = await tool.execute(minimal_config)

    assert result.success is False
    assert result.data["error_code"] == "HTTP_5XX"
    assert result.data["status"] == 503


async def test_execute_unexpected_status_returns_http_unexpected_code(
    tool: GenericApiTool,
) -> None:
    # success_when restricted to 200; a 201 is neither 4xx/5xx nor success.
    config = {
        "request": {"method": "GET", "url": "https://api.example.com"},
        "response": {"success_when": {"status_in": [200]}},
    }
    response = _mock_response(status_code=201, json_body={"created": True})
    patcher, _ = _patch_async_client(response=response)

    with patcher:
        result = await tool.execute(config)

    assert result.success is False
    assert result.data["error_code"] == "HTTP_UNEXPECTED"
    assert result.data["status"] == 201


async def test_execute_network_error_returns_network_code(
    tool: GenericApiTool, minimal_config: dict[str, object]
) -> None:
    patcher, _ = _patch_async_client(side_effect=httpx.ConnectError("DNS lookup failed"))

    with patcher:
        result = await tool.execute(minimal_config)

    assert result.success is False
    assert result.data["error_code"] == "NETWORK"
    assert "ConnectError" in result.data["error_detail"]


async def test_execute_invalid_response_when_extract_configured(
    tool: GenericApiTool,
) -> None:
    # extract is configured but the upstream returns plain text, so we
    # cannot apply the dot-paths. That must surface as INVALID_RESPONSE
    # rather than masquerading as a success.
    config = {
        "request": {"method": "GET", "url": "https://api.example.com"},
        "response": {"extract": {"x": "y.z"}},
    }
    response = _mock_response(status_code=200, json_body=None, text_body="oops")
    patcher, _ = _patch_async_client(response=response)

    with patcher:
        result = await tool.execute(config)

    assert result.success is False
    assert result.data["error_code"] == "INVALID_RESPONSE"
    assert result.data["raw"] == "oops"


async def test_execute_uses_error_mapping_for_human_message(
    tool: GenericApiTool,
) -> None:
    config = {
        "request": {"method": "GET", "url": "https://api.example.com"},
        "error_mapping": {
            "HTTP_4XX": "We could not find that record.",
            "TIMEOUT": "The CRM is slow today.",
        },
    }
    response = _mock_response(status_code=404, json_body={"err": "missing"})
    patcher, _ = _patch_async_client(response=response)

    with patcher:
        result = await tool.execute(config)

    assert result.success is False
    assert result.data["error_code"] == "HTTP_4XX"
    assert result.data["error_message"] == "We could not find that record."
    # ToolResult.error tracks "<code>: <message>" so the orchestrator log
    # line stays informative even without inspecting the data payload.
    assert result.error == "HTTP_4XX: We could not find that record."


async def test_execute_default_error_message_when_mapping_absent(
    tool: GenericApiTool, minimal_config: dict[str, object]
) -> None:
    response = _mock_response(status_code=500, json_body={"err": "boom"})
    patcher, _ = _patch_async_client(response=response)

    with patcher:
        result = await tool.execute(minimal_config)

    assert result.success is False
    assert result.data["error_code"] == "HTTP_5XX"
    # Falls back to the module default since no mapping override exists.
    assert result.data["error_message"] == "The external service is unavailable."
