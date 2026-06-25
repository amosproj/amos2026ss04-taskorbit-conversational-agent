import json
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema import ValidationError, validate

# Resolve paths relative to project root
ROOT = Path(__file__).parent.parent.parent
SCHEMA_PATH = ROOT / "schemas" / "agent-task.schema.json"
EXAMPLE_PATH = ROOT / "schemas" / "examples" / "agent-task.example.json"


@pytest.fixture
def schema() -> dict[str, Any]:
    with open(SCHEMA_PATH) as f:
        return cast(dict[str, Any], json.load(f))


@pytest.fixture
def valid_example() -> dict[str, Any]:
    with open(EXAMPLE_PATH) as f:
        return cast(dict[str, Any], json.load(f))


def test_schema_validation_success(schema: dict[str, Any], valid_example: dict[str, Any]) -> None:
    """Verifies that the canonical example passes the schema."""
    try:
        validate(instance=valid_example, schema=schema)
    except ValidationError as e:
        pytest.fail(f"Validation failed unexpectedly: {e.message}")


def test_schema_validation_fails_missing_field(
    schema: dict[str, Any], valid_example: dict[str, Any]
) -> None:
    """Verifies that missing a mandatory field (e.g., first_message) raises an error."""
    invalid_data = valid_example.copy()
    # Remove a mandatory field from the agent definition
    del invalid_data["agent"]["first_message"]

    with pytest.raises(ValidationError) as excinfo:
        validate(instance=invalid_data, schema=schema)
    assert "'first_message' is a required property" in str(excinfo.value)


def test_schema_validation_fails_invalid_id(
    schema: dict[str, Any], valid_example: dict[str, Any]
) -> None:
    """Verifies that invalid ID patterns (e.g. spaces in agent_id) are rejected."""
    invalid_data = valid_example.copy()
    invalid_data["agent"]["agent_id"] = "Invalid ID With Spaces"

    with pytest.raises(ValidationError):
        validate(instance=invalid_data, schema=schema)


def test_schema_rejects_params_on_end_call(
    schema: dict[str, Any], valid_example: dict[str, Any]
) -> None:
    """end_call tools must not carry params (additionalProperties=false)."""
    invalid_data = deepcopy(valid_example)
    for tool in invalid_data["agent"]["tools"]:
        if tool.get("type") == "end_call":
            tool["params"] = []
            break
    else:
        pytest.fail("example must include an end_call tool")

    with pytest.raises(ValidationError):
        validate(instance=invalid_data, schema=schema)


# ---------------------------------------------------------------------------
# persona_constraints (ticket #69)
# ---------------------------------------------------------------------------


def test_schema_accepts_persona_constraints(
    schema: dict[str, Any], valid_example: dict[str, Any]
) -> None:
    """Adding a fully populated persona_constraints block validates."""
    data = deepcopy(valid_example)
    data["agent"]["persona_constraints"] = {
        "scope": "TechStore customer service.",
        "out_of_scope": ["therapy", "legal advice"],
        "refusal_template": "I can only help with TechStore questions.",
    }
    validate(instance=data, schema=schema)


def test_schema_accepts_missing_persona_constraints(
    schema: dict[str, Any], valid_example: dict[str, Any]
) -> None:
    """The canonical example has no persona_constraints — must still validate.

    Backward-compatibility guarantee: existing saved agent configs continue
    to pass schema validation after the persona_constraints field is added.
    """
    assert "persona_constraints" not in valid_example["agent"]
    validate(instance=valid_example, schema=schema)


def test_schema_accepts_empty_persona_constraints(
    schema: dict[str, Any], valid_example: dict[str, Any]
) -> None:
    """A persona_constraints object with zero fields is allowed (every
    sub-field is optional)."""
    data = deepcopy(valid_example)
    data["agent"]["persona_constraints"] = {}
    validate(instance=data, schema=schema)


def test_schema_rejects_unknown_field_inside_persona_constraints(
    schema: dict[str, Any], valid_example: dict[str, Any]
) -> None:
    """personaConstraints has additionalProperties=false — unknown keys fail."""
    data = deepcopy(valid_example)
    data["agent"]["persona_constraints"] = {
        "scope": "ok",
        "unknown_field": "should fail",
    }
    with pytest.raises(ValidationError):
        validate(instance=data, schema=schema)


# ---------------------------------------------------------------------------
# workflow_rules (Issue #71)
# ---------------------------------------------------------------------------


def test_schema_accepts_workflow_rules(
    schema: dict[str, Any], valid_example: dict[str, Any]
) -> None:
    """Conditional workflow branches validate against workflowRule defs."""
    data = deepcopy(valid_example)
    data["agent"]["workflow_rules"] = [
        {
            "when": {"intent": "technical_support_request"},
            "dependencies": ["identity-verification"],
        },
        {
            "when": {"else": True},
            "dependencies": ["customer-entry"],
        },
    ]
    validate(instance=data, schema=schema)


def test_schema_rejects_unknown_workflow_rule_field(
    schema: dict[str, Any], valid_example: dict[str, Any]
) -> None:
    """workflowRule has additionalProperties=false — unknown keys fail."""
    data = deepcopy(valid_example)
    data["agent"]["workflow_rules"] = [
        {
            "when": {"intent": "technical_support_request"},
            "dependencies": ["identity-verification"],
            "priority": 1,
        }
    ]
    with pytest.raises(ValidationError):
        validate(instance=data, schema=schema)


# ---------------------------------------------------------------------------
# external_api tool (ticket #66)
# ---------------------------------------------------------------------------


def _example_external_api_tool() -> dict[str, Any]:
    return {
        "type": "external_api",
        "name": "lookup_thing",
        "description": "Look something up.",
        "parameters": {
            "request": {
                "method": "GET",
                "url": "https://api.example.com/things/{{args.id}}",
                "headers": {"X-API-Key": "{{env.MY_KEY}}"},
                "timeout_seconds": 5,
            },
            "response": {
                "extract": {"name": "data.name"},
                "success_when": {"status_in": [200]},
            },
            "auth": {"allowed_env": ["MY_KEY"]},
            "error_mapping": {"HTTP_4XX": "Not found."},
            "args_schema": {
                "type": "object",
                "required": ["id"],
                "properties": {"id": {"type": "string"}},
            },
        },
    }


def test_schema_accepts_external_api_tool(
    schema: dict[str, Any], valid_example: dict[str, Any]
) -> None:
    """A fully populated external_api tool validates."""
    data = deepcopy(valid_example)
    data["agent"]["tools"].append(_example_external_api_tool())
    validate(instance=data, schema=schema)


def test_schema_external_api_requires_request(
    schema: dict[str, Any], valid_example: dict[str, Any]
) -> None:
    """parameters.request is the only required block; dropping it must fail."""
    tool = _example_external_api_tool()
    del tool["parameters"]["request"]
    data = deepcopy(valid_example)
    data["agent"]["tools"].append(tool)
    with pytest.raises(ValidationError):
        validate(instance=data, schema=schema)


def test_schema_external_api_rejects_unknown_method(
    schema: dict[str, Any], valid_example: dict[str, Any]
) -> None:
    """Method enum is constrained to GET/POST/PUT/PATCH/DELETE."""
    tool = _example_external_api_tool()
    tool["parameters"]["request"]["method"] = "TRACE"
    data = deepcopy(valid_example)
    data["agent"]["tools"].append(tool)
    with pytest.raises(ValidationError):
        validate(instance=data, schema=schema)


def test_schema_external_api_rejects_unknown_parameters_key(
    schema: dict[str, Any], valid_example: dict[str, Any]
) -> None:
    """externalApiParameters has additionalProperties=false — unknown keys fail."""
    tool = _example_external_api_tool()
    tool["parameters"]["bogus_top_level"] = "nope"
    data = deepcopy(valid_example)
    data["agent"]["tools"].append(tool)
    with pytest.raises(ValidationError):
        validate(instance=data, schema=schema)
