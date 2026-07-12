"""User agent routes.

Endpoints for loading default agent templates and customising per-user copies.

Route summary:
  - GET    /v1/user-agents       → merged list: user copies + untouched templates
  - POST   /v1/user-agents       → create a brand-new agent ("Save as new")
  - PUT    /v1/user-agents/{id}  → update an existing copy by PK, or clone a template
  - DELETE /v1/user-agents/{id}  → delete user's copy (agent reverts to template view)

Note: user_id is a query parameter until JWT auth is wired in.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from taskorbit.api.deps import get_current_user_id
from taskorbit.database import get_session
from taskorbit.database.crud import (
    DuplicateAgentIdError,
    copy_on_write_user_agent,
    delete_user_agent,
    get_user_agent,
    list_default_agent_templates,
    list_user_agents_merged,
)
from taskorbit.database.crud import (
    create_user_agent as create_user_agent_in_db,
)
from taskorbit.database.crud import (
    update_user_agent as update_user_agent_in_db,
)
from taskorbit.logging.setup import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/v1/user-agents", tags=["user-agents"])


class UserAgentCreateRequest(BaseModel):
    name: str
    config: dict[str, Any]


class UserAgentUpdateRequest(BaseModel):
    name: str | None = None
    config: dict[str, Any] | None = None


class UserAgentResponse(BaseModel):
    id: str
    template_id: str | None
    name: str
    config: dict[str, Any]
    is_default: bool
    is_customized: bool


# ---------------------------------------------------------------------------
# GET /v1/user-agents  — merged list for the frontend
# ---------------------------------------------------------------------------


@router.get("", response_model=list[UserAgentResponse])
async def get_user_agents(
    user_id: int = Depends(get_current_user_id),  # noqa: B008
    db: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[UserAgentResponse]:
    """Return all agents visible to a user.

    Customised copies appear with is_customized=True.
    Templates the user has never edited appear with is_customized=False.
    """
    merged = await list_user_agents_merged(db, user_id)
    return [UserAgentResponse(**entry) for entry in merged]


# ---------------------------------------------------------------------------
# GET /v1/user-agents/templates  — raw default templates (admin / debug view)
# ---------------------------------------------------------------------------


@router.get("/templates", response_model=list[UserAgentResponse])
async def get_default_templates(
    db: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[UserAgentResponse]:
    """Return the raw default agent templates (not user-specific)."""
    templates = await list_default_agent_templates(db, active_only=True)
    return [
        UserAgentResponse(
            id=t.id,
            template_id=t.id,
            name=t.name,
            config=t.config,
            is_default=False,
            is_customized=False,
        )
        for t in templates
    ]


# ---------------------------------------------------------------------------
# POST /v1/user-agents  — create a brand-new agent ("Save as new")
# ---------------------------------------------------------------------------


@router.post("", response_model=UserAgentResponse, status_code=201)
async def create_user_agent(
    body: UserAgentCreateRequest,
    user_id: int = Depends(get_current_user_id),  # noqa: B008
    db: AsyncSession = Depends(get_session),  # noqa: B008
) -> UserAgentResponse:
    """Create a brand-new user agent, independent of any template or currently loaded agent.

    This is the correct backend target for "Save as new": it always INSERTs a
    fresh row so the caller's currently-loaded agent is never touched.
    """
    try:
        agent = await create_user_agent_in_db(
            db, user_id=user_id, name=body.name, config=body.config
        )
    except DuplicateAgentIdError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    if not agent:
        raise HTTPException(status_code=500, detail="Could not create agent.")
    return UserAgentResponse(
        id=agent.id,
        template_id=agent.template_id,
        name=agent.name,
        config=agent.config,
        is_default=agent.is_default,
        is_customized=True,
    )


# ---------------------------------------------------------------------------
# PUT /v1/user-agents/{id}  — update an existing copy ("Update")
# ---------------------------------------------------------------------------


@router.put("/{agent_id}", response_model=UserAgentResponse)
async def update_user_agent(
    agent_id: str,
    body: UserAgentUpdateRequest,
    user_id: int = Depends(get_current_user_id),  # noqa: B008
    db: AsyncSession = Depends(get_session),  # noqa: B008
) -> UserAgentResponse:
    """Customise an agent.

    Two paths:
    - agent_id matches the DB primary key of a row the user already owns →
      update that exact row directly (prevents collision when a second agent
      shares the same base template).
    - agent_id is a template id → clone the template on first save, or update
      the user's existing copy of that template.
    """
    # If agent_id is the row's own PK, update it directly to avoid the
    # template_id-keyed lookup that would overwrite a sibling agent.
    existing = await get_user_agent(db, agent_id, user_id)
    try:
        if existing:
            agent = await update_user_agent_in_db(
                db,
                agent_id=agent_id,
                user_id=user_id,
                name=body.name,
                config=body.config,
            )
        else:
            agent = await copy_on_write_user_agent(
                db,
                user_id=user_id,
                template_id=agent_id,
                name=body.name,
                config_updates=body.config,
            )
    except DuplicateAgentIdError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    return UserAgentResponse(
        id=agent.id,
        template_id=agent.template_id,
        name=agent.name,
        config=agent.config,
        is_default=agent.is_default,
        is_customized=True,
    )


# ---------------------------------------------------------------------------
# DELETE /v1/user-agents/{id}  — remove user's copy (revert to template)
# ---------------------------------------------------------------------------


@router.delete("/{agent_id}", status_code=200)
async def delete_user_agent_endpoint(
    agent_id: str,
    user_id: int = Depends(get_current_user_id),  # noqa: B008
    db: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict:
    """Delete the user's customised copy.

    After deletion the agent reappears as the original template in GET /v1/user-agents.
    """
    existing = await get_user_agent(db, agent_id, user_id)
    if not existing:
        raise HTTPException(status_code=404, detail="User agent not found")

    deleted = await delete_user_agent(db, agent_id, user_id)
    if not deleted:
        raise HTTPException(status_code=500, detail="Failed to delete agent")
    return {"deleted": agent_id}
