"""Unit tests for GenericApiTool config parsing, template substitution,
and parameter validation (#66 Stage 2).

HTTP execution and response extraction are covered in later stages and
their tests will land alongside that code.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from taskorbit.tools.generic_api import (
    GenericApiConfigError,
    GenericApiTool,
    TemplateSubstitutionError,
    parse_config,
    substitute_string,
    substitute_tree,
)


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
# execute() — still a stub in Stage 2
# ---------------------------------------------------------------------------


async def test_execute_stub_returns_not_implemented(
    tool: GenericApiTool, minimal_config: dict[str, object]
) -> None:
    result = await tool.execute(minimal_config)
    assert result.success is False
    assert "not implemented" in result.error.lower()
