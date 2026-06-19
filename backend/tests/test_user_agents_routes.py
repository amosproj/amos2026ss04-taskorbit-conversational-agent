"""Regression tests for /v1/user-agents — covers the save-collision fix.

Root cause of the original bug
-------------------------------
"Save as new" sent PUT /v1/user-agents/{activeUserAgentId}, which always updated
the currently-loaded row instead of creating a fresh one.  This caused Step B Agent
to silently overwrite Step C Agent's row.

How the fix works
-----------------
POST /v1/user-agents  →  always INSERTs a new row (the "Save as new" path).
PUT  /v1/user-agents/{id}  →  updates an existing row by PK (the "Update" path),
     with a fallback to copy-on-write clone when agent_id is a template id.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from taskorbit.api.deps import get_current_user_id
from taskorbit.api.main import create_app
from taskorbit.database import get_session
from taskorbit.database.crud import create_user
from taskorbit.database.models import Base, DefaultAgentTemplate

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

_AGENT_CONFIG = {
    "id": "technical-support-agent",
    "name": "Technical Support Agent",
    "persona": "You are a helpful support agent.",
    "greeting": "Hello! How can I help?",
    "stt": {"provider": "deepgram", "model": "nova-3"},
    "llm": {"provider": "openai", "model": "gpt-4o-mini"},
    "tts": {"provider": "elevenlabs", "voice_id": "abc", "model": "eleven_multilingual_v2"},
    "tools": [],
}


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine(
        TEST_DB_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def async_session_factory(db_engine):
    return async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def seeded_client(async_session_factory):
    """TestClient with an in-memory async DB, a seeded template, and a dev user."""
    async with async_session_factory() as session:
        template = DefaultAgentTemplate(
            id="technical-support-agent",
            name="Technical Support Agent",
            config=_AGENT_CONFIG,
            is_active=True,
        )
        session.add(template)
        await session.commit()

        user = await create_user(
            session,
            username="dev",
            email="dev@taskorbit.local",
            hashed_password="x",
        )
        user_id = user.id

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with async_session_factory() as s:
            yield s

    async def override_user_id() -> int:
        return user_id

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_current_user_id] = override_user_id

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_STEP_C_BODY = {
    "name": "Step C Agent",
    "config": {**_AGENT_CONFIG, "id": "agent-c", "name": "Step C Agent"},
}

_STEP_B_BODY = {
    "name": "Step B Agent",
    "config": {**_AGENT_CONFIG, "id": "agent-b", "name": "Step B Agent"},
}


# ---------------------------------------------------------------------------
# POST /v1/user-agents — "Save as new" path
# ---------------------------------------------------------------------------


def test_post_creates_new_independent_row(seeded_client: TestClient) -> None:
    """POST always inserts a fresh row with no template linkage."""
    resp = seeded_client.post("/v1/user-agents", json=_STEP_C_BODY)
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Step C Agent"
    assert body["is_customized"] is True
    assert body["template_id"] is None
    assert isinstance(body["id"], str) and len(body["id"]) > 0


def test_two_posts_create_two_independent_rows(seeded_client: TestClient) -> None:
    """Regression: "Save as new" twice must create two separate rows.

    This is the exact scenario that triggered the original data-loss bug:
    1. Save Step C Agent  → creates UUID_C
    2. Save Step B Agent  → must create UUID_B, leaving UUID_C untouched
    """
    r1 = seeded_client.post("/v1/user-agents", json=_STEP_C_BODY)
    assert r1.status_code == 201
    uuid_c = r1.json()["id"]

    r2 = seeded_client.post("/v1/user-agents", json=_STEP_B_BODY)
    assert r2.status_code == 201
    uuid_b = r2.json()["id"]

    assert uuid_c != uuid_b, "each POST must produce a distinct row"
    assert r2.json()["name"] == "Step B Agent"

    # Confirm Step C still exists as its own row.
    agents = seeded_client.get("/v1/user-agents").json()
    customized_names = {a["name"] for a in agents if a["is_customized"]}
    assert "Step C Agent" in customized_names
    assert "Step B Agent" in customized_names


def test_post_missing_name_rejected(seeded_client: TestClient) -> None:
    """POST without a name fails Pydantic validation."""
    resp = seeded_client.post("/v1/user-agents", json={"config": _AGENT_CONFIG})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# PUT /v1/user-agents/{id} — "Update" path
# ---------------------------------------------------------------------------


def test_put_template_id_clones_a_new_row(seeded_client: TestClient) -> None:
    """PUT with a template id when the user has no copy → creates a new row."""
    resp = seeded_client.put("/v1/user-agents/technical-support-agent", json=_STEP_C_BODY)
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Step C Agent"
    assert body["is_customized"] is True
    assert body["template_id"] == "technical-support-agent"
    assert body["id"] != "technical-support-agent"


def test_put_row_id_updates_exact_row_without_touching_others(seeded_client: TestClient) -> None:
    """PUT /v1/user-agents/{uuid} updates that exact row by primary key.

    This is the "Update" button path after the frontend fix:
    1. POST → creates Step C (UUID_C), frontend stores activeUserAgentId = UUID_C
    2. PUT UUID_C → correctly updates Step C in place (does not create a new row)
    """
    r1 = seeded_client.post("/v1/user-agents", json=_STEP_C_BODY)
    assert r1.status_code == 201
    uuid_c = r1.json()["id"]

    r2 = seeded_client.put(f"/v1/user-agents/{uuid_c}", json=_STEP_B_BODY)
    assert r2.status_code == 200
    assert r2.json()["id"] == uuid_c, "row id must not change on update"
    assert r2.json()["name"] == "Step B Agent"


def test_put_with_unknown_id_returns_404(seeded_client: TestClient) -> None:
    """PUT with an id that is neither a known template nor a user-owned row → 404."""
    resp = seeded_client.put("/v1/user-agents/nonexistent-id", json=_STEP_C_BODY)
    assert resp.status_code == 404


def test_put_template_id_twice_updates_existing_copy(seeded_client: TestClient) -> None:
    """Two PUT calls with the same template id update a single row (copy-on-write contract).

    Documented behaviour: PUT is the "Update" path.  Creating a second independent
    agent from the same template requires POST, not PUT.
    """
    r1 = seeded_client.put("/v1/user-agents/technical-support-agent", json=_STEP_C_BODY)
    assert r1.status_code == 200
    uuid_c = r1.json()["id"]

    r2 = seeded_client.put("/v1/user-agents/technical-support-agent", json=_STEP_B_BODY)
    assert r2.status_code == 200
    uuid_b = r2.json()["id"]

    assert uuid_b == uuid_c, "copy_on_write updates the existing row when called twice"
    assert r2.json()["name"] == "Step B Agent"
