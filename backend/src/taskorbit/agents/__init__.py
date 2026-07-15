"""Task-specific agents.

All agents live in this file. To add a new agent:
  1. Subclass BaseAgent and implement handle_message() + get_task_definitions()
  2. Register it in AgentRegistry._REGISTRY with the keyword(s) that appear in config.id

AgentRegistry.create() is the single constructor for all agent types.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import defaultdict
from typing import TYPE_CHECKING

from taskorbit.logging.setup import get_logger
from taskorbit.types import AgentConfig, ConversationRequest, ConversationResponse, ToolDefinition

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

# Tracks how many times each agent type has been invoked this process lifetime.
_agent_call_counts: dict[str, int] = defaultdict(int)

if TYPE_CHECKING:
    from taskorbit.orchestration import ConversationOrchestrator


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class BaseAgent(ABC):
    """Abstract base for all task-specific agents."""

    #: Short label shown in logs and ConversationResponse.selected_agent
    agent_name: str = "base"

    def __init__(self, config: AgentConfig, orchestrator: ConversationOrchestrator) -> None:
        self.config = config
        self.orchestrator = orchestrator

    @abstractmethod
    async def handle_message(self, request: ConversationRequest) -> ConversationResponse:
        """Process a user message and return an assistant response."""
        ...

    @abstractmethod
    def get_task_definitions(self) -> list[ToolDefinition]:
        """Return the tool definitions that define this agent's task scope."""
        ...


# ---------------------------------------------------------------------------
# Concrete agents — add new ones below this line
# ---------------------------------------------------------------------------


class SalesAgent(BaseAgent):
    """Lead qualification: discovery, data extraction, appointment scheduling.

    Owns the book_service_appointment workflow.
    """

    agent_name = "sales"

    async def handle_message(self, request: ConversationRequest) -> ConversationResponse:
        return await self.orchestrator.process_message(request)

    def get_task_definitions(self) -> list[ToolDefinition]:
        return self.config.tools


class TechnicalSupportAgent(BaseAgent):
    """Troubleshooting: problem diagnosis, data collection, escalation.

    Owns the customer_dissatisfaction_inquiry workflow.
    """

    agent_name = "technical_support"

    async def handle_message(self, request: ConversationRequest) -> ConversationResponse:
        return await self.orchestrator.process_message(request)

    def get_task_definitions(self) -> list[ToolDefinition]:
        return self.config.tools


class GeneralInquiryAgent(BaseAgent):
    """First-line agent for FAQs, product/service info, and policy questions.

    Handles callers whose intent is unclear or who have a simple question that
    doesn't require slot collection. Answers from the agent persona's knowledge
    and hands off to a specialist agent via AgentTransferTool when the topic
    warrants deeper handling.
    """

    agent_name = "general_inquiry"

    async def handle_message(self, request: ConversationRequest) -> ConversationResponse:
        return await self.orchestrator.process_message(request)

    def get_task_definitions(self) -> list[ToolDefinition]:
        return self.config.tools


class AppointmentManagementAgent(BaseAgent):
    """Manages existing bookings: reschedule, cancel, or check appointment status.

    Complements SalesAgent (which only creates new appointments). Collects the
    caller's booking reference or contact details, looks up the appointment, and
    processes the requested change — reschedule, cancellation, or status check.
    """

    agent_name = "appointment_management"

    async def handle_message(self, request: ConversationRequest) -> ConversationResponse:
        return await self.orchestrator.process_message(request)

    def get_task_definitions(self) -> list[ToolDefinition]:
        return self.config.tools


class CustomerDissatisfactionAgent(BaseAgent):
    """Handles complaints, negative experiences, and escalation requests.

    Focuses on emotional resolution: acknowledging the complaint, capturing
    the issue and preferred resolution channel, and logging a formal ticket.
    Can transfer to TechnicalSupportAgent when the root cause is technical.
    """

    agent_name = "customer_dissatisfaction"

    async def handle_message(self, request: ConversationRequest) -> ConversationResponse:
        return await self.orchestrator.process_message(request)

    def get_task_definitions(self) -> list[ToolDefinition]:
        return self.config.tools


class GenericAgent(BaseAgent):
    """Fallback agent for custom IDs that don't match any specialized class.

    Preserves the original config.id as its agent_name to ensure metrics
    and handoff logic correctly identify the specific custom agent.
    """

    def __init__(self, config: AgentConfig, orchestrator: ConversationOrchestrator) -> None:
        super().__init__(config, orchestrator)
        # AC #71: Use the actual config.id as the agent name instead of a hardcoded string.
        # This prevents silent fallbacks to 'sales' in logs and response status.
        self.agent_name = config.id

    async def handle_message(self, request: ConversationRequest) -> ConversationResponse:
        return await self.orchestrator.process_message(request)

    def get_task_definitions(self) -> list[ToolDefinition]:
        return self.config.tools


# ---------------------------------------------------------------------------
# Registry / constructor
# ---------------------------------------------------------------------------


class AgentRegistry:
    """Factory that constructs the right agent for a given AgentConfig.

    _REGISTRY maps a set of keywords (matched against config.id) to an agent
    class. Keywords are checked in definition order; first match wins.
    Add a new row here whenever a new agent type is introduced.
    """

    _REGISTRY: list[tuple[tuple[str, ...], type[BaseAgent]]] = [
        (("support", "technical", "tech", "helpdesk", "troubleshoot"), TechnicalSupportAgent),
        (("sales", "lead", "qualification", "onboard", "new-customer"), SalesAgent),
        (("inquiry", "faq", "general", "info", "question"), GeneralInquiryAgent),
        (
            ("appointment", "reschedule", "cancel", "booking", "schedule", "rebook"),
            AppointmentManagementAgent,
        ),
        (
            ("dissatisfaction", "complaint", "unhappy", "frustrated", "refund", "escalat"),
            CustomerDissatisfactionAgent,
        ),
    ]

    _DEFAULT: type[BaseAgent] = SalesAgent

    @classmethod
    def get_agent_name_for_id(cls, config_id: str) -> str:
        """Map a logical config.id (e.g. from allowed_handoffs) to a registry agent_name."""
        agent_id = config_id.lower()
        for keywords, agent_cls in cls._REGISTRY:
            if any(kw in agent_id for kw in keywords):
                return agent_cls.agent_name.lower()
        # AC #71: Return the ID itself if no keyword matches, instead of falling back to 'sales'.
        return agent_id

    @classmethod
    def create(
        cls,
        config: AgentConfig,
        orchestrator: ConversationOrchestrator,
    ) -> BaseAgent:
        """Construct and return the agent that matches *config.id*.

        Falls back to GenericAgent (preserving the ID) when no keyword matches.
        """
        agent_id = config.id.lower()
        for keywords, agent_cls in cls._REGISTRY:
            if any(kw in agent_id for kw in keywords):
                normalized_name = agent_cls.agent_name.lower()
                _agent_call_counts[normalized_name] += 1
                count = _agent_call_counts[normalized_name]
                logger.info("agent_selected", agent=normalized_name, total_calls=count)
                return agent_cls(config, orchestrator)

        # AC #71: Explicitly use GenericAgent for custom IDs to avoid silent 'sales' fallback.
        normalized_id = config.id.lower()
        _agent_call_counts[normalized_id] += 1
        count = _agent_call_counts[normalized_id]
        logger.info("agent_selected", agent=normalized_id, total_calls=count, via="generic")
        return GenericAgent(config, orchestrator)

    @classmethod
    def known_agent_names(cls) -> frozenset[str]:
        """Return the set of built-in agent_name strings."""
        return frozenset(agent_cls.agent_name for _, agent_cls in cls._REGISTRY)

    @classmethod
    async def create_by_name(
        cls,
        agent_name: str,
        config: AgentConfig,
        orchestrator: ConversationOrchestrator,
        db: AsyncSession | None = None,
        user_id: int | None = None,
    ) -> BaseAgent:
        """Construct an agent by agent_name (e.g. from an IntentResult).

        Resolution order:
          1. Built-in agents matched by agent_name.
          2. Custom agents looked up by name in agent_configurations (when db given).
          3. Default agent fallback (via config.id).
        """
        target_name = agent_name.lower()
        for _, agent_cls in cls._REGISTRY:
            if agent_cls.agent_name.lower() == target_name:
                normalized_name = agent_cls.agent_name.lower()
                _agent_call_counts[normalized_name] += 1
                count = _agent_call_counts[normalized_name]
                logger.info(
                    "agent_selected", agent=normalized_name, total_calls=count, via="intent"
                )
                return agent_cls(config, orchestrator)

        # Fall back to DB for custom agents — scope by user_id to prevent cross-user leakage.
        if db is not None:
            from pydantic import ValidationError

            from taskorbit.database.crud import (
                _find_agent_config_by_logical_id,
                get_agent_configuration_by_name,
            )
            from taskorbit.types import AgentConfig as AgentConfigType

            # Intent routing hands us an agent_id ("chris"), but the DB name column
            # holds the display name ("Chris") and the lookup is case-sensitive, so
            # by-name misses custom agents and silently falls back to the default
            # (#8 / the "custom agent not found" symptom). Resolve by logical
            # agent_id (config.agent_id / config.id) when the name lookup misses.
            record = await get_agent_configuration_by_name(db, agent_name, user_id=user_id)
            if record is None:
                record = await _find_agent_config_by_logical_id(db, agent_name, user_id)
            if record is not None:
                try:
                    from taskorbit.agent_config_util import agent_config_from_stored_blob

                    # record.config is the stored (frontend-shaped) blob using
                    # instructions/first_message; map it the way the text path does
                    # rather than validating it raw as AgentConfig, which is missing
                    # persona/greeting and silently falls back to the default agent
                    # (that's why a transferred-to custom agent behaved like Maya).
                    custom_config = agent_config_from_stored_blob(record.config)
                except (ValidationError, Exception) as exc:
                    logger.error(
                        "custom_agent_invalid_config",
                        agent_name=agent_name,
                        error=str(exc),
                    )
                    logger.warning("agent_not_found", agent_name=agent_name, fallback="default")
                    return cls.create(config, orchestrator)
                logger.info(
                    "agent_selected",
                    agent=custom_config.id,
                    config_name=agent_name,
                    via="db_fallback",
                )
                return cls.create_custom(custom_config, orchestrator)

        logger.warning("agent_not_found", agent_name=agent_name, fallback="default")
        return cls.create(config, orchestrator)

    @classmethod
    def create_custom(
        cls, config: AgentConfig, orchestrator: ConversationOrchestrator
    ) -> BaseAgent:
        """Construct a GenericAgent from a DB-resolved AgentConfig.

        Called by the orchestrator after it has loaded the config from the
        agent_configurations table. Built-in routing is not consulted.
        """
        normalized_id = config.id.lower()
        _agent_call_counts[normalized_id] += 1
        count = _agent_call_counts[normalized_id]
        logger.info("agent_selected", agent=normalized_id, config_id=config.id, total_calls=count)
        return GenericAgent(config, orchestrator)

    # Keep the old name available so existing call sites don't break.
    @classmethod
    def get_agent(
        cls,
        config: AgentConfig,
        orchestrator: ConversationOrchestrator,
    ) -> BaseAgent:
        return cls.create(config, orchestrator)
