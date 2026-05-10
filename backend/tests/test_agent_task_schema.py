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
