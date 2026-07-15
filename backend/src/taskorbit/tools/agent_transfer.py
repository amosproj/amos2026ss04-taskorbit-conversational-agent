"""Agent transfer tool — hands the conversation off to a different agent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from taskorbit.tools import BaseTool, ToolResult
from taskorbit.types import ToolType

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def _get_known_agent_names() -> frozenset[str]:
    from taskorbit.agents import AgentRegistry

    return AgentRegistry.known_agent_names()


def _logical_agent_id(config: Any) -> str | None:
    """Logical routing id from a stored config blob (config.agent_id / config.id)."""
    if isinstance(config, dict):
        aid = config.get("agent_id") or config.get("id")
        if aid:
            return str(aid)
    return None


@dataclass(frozen=True)
class ResolvedTransferTarget:
    """Outcome of resolving a configured transfer target to a real agent.

    ``canonical_id`` is the identifier every downstream consumer should use:
    the registry agent_name for built-ins (e.g. "general_inquiry"), or the DB
    row id for saved configs and templates (UUID hex / template slug). The
    frontend handoff swap matches on exactly these forms (useAgentHandoff).
    """

    canonical_id: str
    kind: str  # "builtin" | "config" | "template"
    display_name: str | None = None
    # Logical routing id (config.agent_id, e.g. "chris") for saved configs.
    # intent.agent_name is this logical id, NOT the DB-row canonical_id, so tool
    # selection must compare against agent_id to fire a transfer to a custom
    # agent (#4). Falls back to canonical_id for built-ins/templates.
    agent_id: str | None = None


def resolve_builtin_transfer_target(target: str) -> str | None:
    """Resolve a configured target to a built-in agent_name, without DB access.

    Sync subset of resolve_transfer_target for callers that only need the
    built-in destination (tool selection compares against intent.agent_name,
    which is always a registry agent). Kept separate from the async resolver
    so its keyword fallback cannot jump ahead of the deterministic DB matches
    there (#212).
    """
    raw = (target or "").strip()
    if not raw:
        return None
    if raw in _get_known_agent_names():
        return raw

    from taskorbit.agents import AgentRegistry

    mapped = AgentRegistry.get_agent_name_for_id(raw)
    if mapped in _get_known_agent_names():
        return mapped
    return None


async def resolve_transfer_target(
    target: str,
    db: AsyncSession | None = None,
    user_id: int | None = None,
) -> ResolvedTransferTarget | None:
    """Resolve a configured transfer target to a canonical agent identifier.

    Transfer targets are free text in the config UI today (#203 adds a
    dropdown), so real configs contain UUID hex ids, template slugs
    ("general-inquiry-agent"), registry names ("general_inquiry"), display
    names ("General Inquiry Agent"), or near-misses ("inquiry-agent", the
    #212 prod value). Deterministic matches run first; the registry keyword
    map runs last so an exact match can never be shadowed by a fuzzy hit.
    Returns None when nothing matches; callers own the error reporting.
    """
    raw = (target or "").strip()
    if not raw:
        return None

    # 1. Exact built-in registry name, no DB needed.
    if raw in _get_known_agent_names():
        return ResolvedTransferTarget(canonical_id=raw, kind="builtin")

    if db is not None:
        from taskorbit.database.crud import (
            get_agent_configuration_by_id,
            get_agent_configuration_by_name,
            get_default_agent_template,
        )

        # 2. Saved config by primary key (UUID hex, or slug id on old rows).
        #    A PK hit means record.id == raw, so raw IS the canonical id.
        record = await get_agent_configuration_by_id(db, raw, user_id=user_id)
        if record is not None:
            return ResolvedTransferTarget(
                canonical_id=raw,
                kind="config",
                display_name=record.name,
                agent_id=_logical_agent_id(record.config),
            )

        # 3. Un-customized built-in template by slug id ("general-inquiry-agent").
        #    The manual-transfer path checks this table too; the tool must match it.
        template = await get_default_agent_template(db, raw)
        if template is not None:
            return ResolvedTransferTarget(
                canonical_id=raw, kind="template", display_name=template.name
            )

        # 4. Saved config by exact display name, user-scoped (fails closed
        #    without a user, same contract as the manual-transfer path).
        record = await get_agent_configuration_by_name(db, raw, user_id=user_id)
        if record is not None:
            return ResolvedTransferTarget(
                canonical_id=record.id,
                kind="config",
                display_name=record.name,
                agent_id=_logical_agent_id(record.config),
            )

    # 5. Registry keyword mapping, fuzzy last resort ("inquiry-agent" ->
    #    general_inquiry). get_agent_name_for_id echoes its input when nothing
    #    matches, so only accept results that are real registry names.
    from taskorbit.agents import AgentRegistry

    mapped = AgentRegistry.get_agent_name_for_id(raw)
    if mapped in _get_known_agent_names():
        return ResolvedTransferTarget(canonical_id=mapped, kind="builtin")

    return None


class AgentTransferTool(BaseTool):
    tool_type = ToolType.AGENT_TRANSFER

    def __init__(self, db: AsyncSession | None = None, user_id: int | None = None) -> None:
        self._db = db
        self._user_id = user_id

    async def execute(self, parameters: dict[str, Any]) -> ToolResult:
        """Transfer the conversation to another agent, preserving full history.

        Expected parameters:
            target_agent_id (str): built-in agent_name (e.g. "technical_support"),
                the UUID hex ID or template slug of a saved agent, its display
                name, or a keyword near-miss; resolved via resolve_transfer_target.
            conversation_history (list[dict]): full message list — passed through
                so the new agent has full context.
        """
        target_agent_id = parameters.get("target_agent_id", "").strip()
        if not target_agent_id:
            return ToolResult(success=False, error="target_agent_id is required")

        resolved = await resolve_transfer_target(
            target_agent_id, db=self._db, user_id=self._user_id
        )
        if resolved is None:
            known = sorted(_get_known_agent_names())
            return ToolResult(
                success=False,
                error=f"Unknown agent '{target_agent_id}'. Valid built-in agents: {known}",
            )

        conversation_history = parameters.get("conversation_history", [])

        return ToolResult(
            success=True,
            data={
                "transferred_to": resolved.canonical_id,
                "target_kind": resolved.kind,
                "requested_target": target_agent_id,
                "history_preserved": True,
                "message_count": len(conversation_history),
            },
        )

    def validate_parameters(self, parameters: dict[str, Any]) -> bool:
        # Synchronous check against built-ins only (used for pre-flight validation).
        # Full validation including custom agents happens async in execute().
        target = parameters.get("target_agent_id", "").strip()
        return bool(target) and target in _get_known_agent_names()
