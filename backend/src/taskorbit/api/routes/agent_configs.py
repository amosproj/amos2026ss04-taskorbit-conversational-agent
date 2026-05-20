"""Routes for /v1/agent-configs — save, load, list agent configurations."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from taskorbit.config import get_settings
from taskorbit.database.crud import (
    create_agent_configuration,
    delete_agent_configuration,
    get_agent_configuration,
    list_agent_configurations,
    update_agent_configuration,
)
from taskorbit.logging.setup import get_logger
from taskorbit.types import (
    AgentConfigurationCreate,
    AgentConfigurationDetail,
    AgentConfigurationSummary,
    AgentConfigurationUpdate,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/v1/agent-configs", tags=["agent-configs"])

_engine = create_engine(
    str(get_settings().database_url).replace("postgresql://", "postgresql+psycopg://"),
    pool_pre_ping=True,
)
_SessionLocal = sessionmaker(bind=_engine, autocommit=False, autoflush=False)


def get_sync_session() -> Iterator[Session]:
    session = _SessionLocal()
    try:
        yield session
    finally:
        session.close()


@router.get("", response_model=list[AgentConfigurationSummary])
def list_configs(
    db: Session = Depends(get_sync_session),  # noqa: B008
) -> list[AgentConfigurationSummary]:
    """Return a summary list of all saved agent configurations."""
    return list_agent_configurations(db)


@router.get("/{config_id}", response_model=AgentConfigurationDetail)
def get_config(
    config_id: str,
    db: Session = Depends(get_sync_session),  # noqa: B008
) -> AgentConfigurationDetail:
    """Return the full detail of a single agent configuration."""
    result = get_agent_configuration(db, config_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Agent configuration '{config_id}' not found.")
    return result


@router.post("", response_model=AgentConfigurationDetail, status_code=201)
def save_config(
    body: AgentConfigurationCreate,
    db: Session = Depends(get_sync_session),  # noqa: B008
) -> AgentConfigurationDetail:
    """Persist a new agent configuration and return its DB-assigned id."""
    result = create_agent_configuration(db, name=body.name, config=body.config)
    if result is None:
        logger.error("agent_config_create_failed", name=body.name)
        raise HTTPException(status_code=500, detail="Could not save configuration.")
    logger.info("agent_config_created", config_id=result.id, name=result.name)
    return result


@router.put("/{config_id}", response_model=AgentConfigurationDetail)
def update_config(
    config_id: str,
    body: AgentConfigurationUpdate,
    db: Session = Depends(get_sync_session),  # noqa: B008
) -> AgentConfigurationDetail:
    """Update an existing agent configuration."""
    result = update_agent_configuration(db, config_id=config_id, name=body.name, config=body.config)
    if result is None:
        logger.warning("agent_config_update_not_found", config_id=config_id)
        raise HTTPException(status_code=404, detail=f"Agent configuration '{config_id}' not found.")
    logger.info("agent_config_updated", config_id=config_id)
    return result


@router.delete("/{config_id}", status_code=204)
def delete_config(
    config_id: str,
    db: Session = Depends(get_sync_session),  # noqa: B008
) -> Response:
    """Delete an agent configuration."""
    success = delete_agent_configuration(db, config_id=config_id)
    if not success:
        logger.warning("agent_config_delete_not_found", config_id=config_id)
        raise HTTPException(status_code=404, detail=f"Agent configuration '{config_id}' not found.")
    logger.info("agent_config_deleted", config_id=config_id)
    return Response(status_code=204)
