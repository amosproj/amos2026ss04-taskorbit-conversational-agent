import json
import pytest
from pathlib import Path
from jsonschema import validate, ValidationError

# Resolve paths relative to project root
ROOT = Path(__file__).parent.parent.parent
SCHEMA_PATH = ROOT / "schemas" / "agent-task.schema.json"
EXAMPLE_PATH = ROOT / "schemas" / "examples" / "agent-task.example.json"

@pytest.fixture
def schema():
    with open(SCHEMA_PATH, "r") as f:
        return json.load(f)

@pytest.fixture
def valid_example():
    with open(EXAMPLE_PATH, "r") as f:
        return json.load(f)

def test_schema_validation_success(schema, valid_example):
    """Verifies that the canonical example passes the schema."""
    try:
        validate(instance=valid_example, schema=schema)
    except ValidationError as e:
        pytest.fail(f"Validation failed unexpectedly: {e.message}")

def test_schema_validation_fails_missing_field(schema, valid_example):
    """Verifies that missing a mandatory field (e.g., first_message) raises an error."""
    invalid_data = valid_example.copy()
    # Remove a mandatory field from the agent definition
    del invalid_data["agent"]["first_message"]
    
    with pytest.raises(ValidationError) as excinfo:
        validate(instance=invalid_data, schema=schema)
    assert "'first_message' is a required property" in str(excinfo.value)

def test_schema_validation_fails_invalid_id(schema, valid_example):
    """Verifies that invalid ID patterns (e.g. spaces in agent_id) are rejected."""
    invalid_data = valid_example.copy()
    invalid_data["agent"]["agent_id"] = "Invalid ID With Spaces"
    
    with pytest.raises(ValidationError):
        validate(instance=invalid_data, schema=schema)