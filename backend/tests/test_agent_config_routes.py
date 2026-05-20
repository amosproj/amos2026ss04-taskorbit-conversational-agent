"""Tests for the /v1/agent-configs routes.

Covers the POST endpoint introduced by #47 (save). The GET endpoints
(load list / load detail) have CRUD-level coverage in
``test_agent_config_crud.py``; here we additionally exercise the
round-trip via HTTP so the load endpoint returns exactly what the save
endpoint persisted (proves the ``config: dict[str, Any]`` change preserves
the full FE contract).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from taskorbit.api.main import create_app
from taskorbit.api.routes.agent_configs import get_sync_session
from taskorbit.database.models import Base

TEST_DATABASE_URL = "sqlite:///:memory:"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client() -> Iterator[TestClient]:
    """A FastAPI TestClient with an in-memory SQLite DB wired in.

    Overrides the ``get_sync_session`` dependency so the route uses a
    test session instead of the real psycopg engine. Drops + recreates
    the schema for each test so rows don't leak across tests.
    """
    # StaticPool keeps a single SQLite connection alive across all sessions
    # so create_all() and the route's session see the same in-memory DB.
    # Without it, sqlite:///:memory: creates a fresh empty DB per connection
    # and the route raises "no such table: agent_configurations".
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_session() -> Iterator[Session]:
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app = create_app()
    app.dependency_overrides[get_sync_session] = override_session

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


# Full FE contract (Preet's reference shape) — verbatim from
# ``frontend/src/lib/mockAgents.ts`` so the test fails loudly if the FE
# schema is widened on its side and the backend silently drops fields.
_FULL_FE_CONFIG = {
    "agent_id": "preet-agent",
    "name": "John Doe",
    "instructions": "You are John Doe, customer support for TechStore.",
    "first_message": {
        "type": "text",
        "message": "Hi there!",
        "prompt": "",
    },
    "variables": {"name": "John Doe"},
    "stt": {"provider": "deepgram", "model": "nova-3"},
    "tts": {
        "provider": "elevenlabs",
        "model": "eleven_multilingual_v2",
        "voice_id": "21m00Tcm4TlvDq8ikWAM",
    },
    "llm": {"provider": "openai", "model": "gpt-4.1-mini"},
    "tools": [
        {
            "type": "data_extraction",
            "name": "collect_user_info",
            "description": "Save customer info.",
            "params": [
                {
                    "variable_name": "full_name",
                    "description": "Customer's full name",
                    "type": "string",
                    "required": False,
                },
            ],
        },
    ],
    "engine": {},
}


# ---------------------------------------------------------------------------
# POST /v1/agent-configs
# ---------------------------------------------------------------------------


def test_save_config_happy_path(client: TestClient) -> None:
    """Minimal valid payload persists and returns a 201 with the saved row."""
    payload = {"name": "test-config", "config": {"model": "gpt-4"}}

    response = client.post("/v1/agent-configs", json=payload)

    assert response.status_code == 201
    body = response.json()
    assert isinstance(body["id"], str) and len(body["id"]) > 0
    assert body["name"] == "test-config"
    assert body["config"] == {"model": "gpt-4"}
    assert body["created_at"] is not None
    assert body["updated_at"] is None


def test_save_config_empty_name_rejected(client: TestClient) -> None:
    """name="" violates min_length=1 on AgentConfigurationCreate."""
    response = client.post("/v1/agent-configs", json={"name": "", "config": {}})
    assert response.status_code == 422


def test_save_config_missing_config_rejected(client: TestClient) -> None:
    """Missing required ``config`` field fails Pydantic validation."""
    response = client.post("/v1/agent-configs", json={"name": "x"})
    assert response.status_code == 422


def test_save_config_accepts_full_fe_contract(client: TestClient) -> None:
    """The full Preet/FE shape round-trips intact — no field stripping.

    This is the critical regression test for the ``config: dict[str, Any]``
    type change. If someone reverts ``AgentConfigurationDetail.config`` to
    the narrow ``AgentConfig`` Pydantic model, this test will fail because
    Pydantic will reject ``agent_id``, ``instructions``, ``first_message``,
    ``variables``, ``engine`` (none of which exist on the orchestrator
    wire shape).
    """
    response = client.post(
        "/v1/agent-configs",
        json={"name": "john-doe-preset", "config": _FULL_FE_CONFIG},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["config"] == _FULL_FE_CONFIG


def test_save_then_load_round_trip(client: TestClient) -> None:
    """A POSTed config is fetchable via GET /v1/agent-configs/{id} unchanged."""
    create_response = client.post(
        "/v1/agent-configs",
        json={"name": "round-trip", "config": _FULL_FE_CONFIG},
    )
    assert create_response.status_code == 201
    saved_id = create_response.json()["id"]

    load_response = client.get(f"/v1/agent-configs/{saved_id}")

    assert load_response.status_code == 200
    body = load_response.json()
    assert body["id"] == saved_id
    assert body["name"] == "round-trip"
    assert body["config"] == _FULL_FE_CONFIG


# ---------------------------------------------------------------------------
# PUT /v1/agent-configs/{config_id}
# ---------------------------------------------------------------------------


def test_update_config_happy_path(client: TestClient) -> None:
    """Updating both name and config returns 200 and reflects changes."""
    create_response = client.post("/v1/agent-configs", json={"name": "old", "config": {"a": 1}})
    config_id = create_response.json()["id"]

    update_payload = {"name": "new", "config": {"b": 2}}
    update_response = client.put(f"/v1/agent-configs/{config_id}", json=update_payload)

    assert update_response.status_code == 200
    body = update_response.json()
    assert body["name"] == "new"
    assert body["config"] == {"b": 2}
    assert body["updated_at"] is not None


def test_update_config_partial_name(client: TestClient) -> None:
    """Updating only the name keeps the old config intact."""
    create_response = client.post("/v1/agent-configs", json={"name": "old", "config": {"a": 1}})
    config_id = create_response.json()["id"]

    update_response = client.put(f"/v1/agent-configs/{config_id}", json={"name": "new"})

    assert update_response.status_code == 200
    body = update_response.json()
    assert body["name"] == "new"
    assert body["config"] == {"a": 1}


def test_update_config_partial_config(client: TestClient) -> None:
    """Updating only the config keeps the old name intact."""
    create_response = client.post("/v1/agent-configs", json={"name": "old", "config": {"a": 1}})
    config_id = create_response.json()["id"]

    update_response = client.put(f"/v1/agent-configs/{config_id}", json={"config": {"b": 2}})

    assert update_response.status_code == 200
    body = update_response.json()
    assert body["name"] == "old"
    assert body["config"] == {"b": 2}


def test_update_nonexistent_config_returns_404(client: TestClient) -> None:
    """PUT to a missing ID returns 404."""
    response = client.put("/v1/agent-configs/missing", json={"name": "x"})
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /v1/agent-configs/{config_id}
# ---------------------------------------------------------------------------


def test_delete_config_happy_path(client: TestClient) -> None:
    """DELETE returns 204 and the config is no longer fetchable."""
    create_response = client.post("/v1/agent-configs", json={"name": "to-delete", "config": {}})
    config_id = create_response.json()["id"]

    delete_response = client.delete(f"/v1/agent-configs/{config_id}")
    assert delete_response.status_code == 204

    load_response = client.get(f"/v1/agent-configs/{config_id}")
    assert load_response.status_code == 404


def test_delete_nonexistent_config_returns_404(client: TestClient) -> None:
    """DELETE for a missing ID returns 404."""
    response = client.delete("/v1/agent-configs/missing")
    assert response.status_code == 404
