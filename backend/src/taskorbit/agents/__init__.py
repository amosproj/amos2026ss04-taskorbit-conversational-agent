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


class CustomAgent(BaseAgent):
    """Thin wrapper for user-defined agents loaded from the database.

    Carries a user-supplied AgentConfig without any specialised class logic.
    All behaviour is driven by the config (persona, tools, etc.) through the
    shared orchestrator pipeline, exactly like the built-in agents.
    """

    agent_name = "custom"

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
    def create(
        cls,
        config: AgentConfig,
        orchestrator: ConversationOrchestrator,
    ) -> BaseAgent:
        """Construct and return the agent that matches *config.id*.

        Falls back to SalesAgent when no keyword matches.
        """
        agent_id = config.id.lower()
        for keywords, agent_cls in cls._REGISTRY:
            if any(kw in agent_id for kw in keywords):
                _agent_call_counts[agent_cls.agent_name] += 1
                count = _agent_call_counts[agent_cls.agent_name]
                print(f"[AgentRegistry] {agent_cls.agent_name} called (total: {count})", flush=True)
                logger.info("agent_selected", agent=agent_cls.agent_name, total_calls=count)
                return agent_cls(config, orchestrator)

        _agent_call_counts[cls._DEFAULT.agent_name] += 1
        count = _agent_call_counts[cls._DEFAULT.agent_name]
        print(
            f"[AgentRegistry] {cls._DEFAULT.agent_name} called (default) (total: {count})",
            flush=True,
        )
        logger.info(
            "agent_selected", agent=cls._DEFAULT.agent_name, total_calls=count, via="default"
        )
        return cls._DEFAULT(config, orchestrator)

    @classmethod
    def known_agent_names(cls) -> frozenset[str]:
        """Return the set of built-in agent_name strings."""
        return frozenset(agent_cls.agent_name for _, agent_cls in cls._REGISTRY)

    @classmethod
    def create_by_name(
        cls,
        agent_name: str,
        config: AgentConfig,
        orchestrator: ConversationOrchestrator,
    ) -> BaseAgent:
        """Construct an agent directly by agent_name (e.g. from an IntentResult).

        Falls back to the default agent if agent_name is empty or unrecognised.
        """
        for _, agent_cls in cls._REGISTRY:
            if agent_cls.agent_name == agent_name:
                _agent_call_counts[agent_cls.agent_name] += 1
                count = _agent_call_counts[agent_cls.agent_name]
                print(
                    f"[AgentRegistry] {agent_cls.agent_name} called via intent (total: {count})",
                    flush=True,
                )
                logger.info(
                    "agent_selected", agent=agent_cls.agent_name, total_calls=count, via="intent"
                )
                return agent_cls(config, orchestrator)
        return cls.create(config, orchestrator)

    @classmethod
    def create_custom(cls, config: AgentConfig, orchestrator: ConversationOrchestrator) -> BaseAgent:
        """Construct a CustomAgent from a DB-resolved AgentConfig.

        Called by the orchestrator after it has loaded the config from the
        agent_configurations table. Built-in routing is not consulted.
        """
        _agent_call_counts["custom"] += 1
        count = _agent_call_counts["custom"]
        logger.info("agent_selected", agent="custom", config_id=config.id, total_calls=count)
        return CustomAgent(config, orchestrator)

    # Keep the old name available so existing call sites don't break.
    @classmethod
    def get_agent(
        cls,
        config: AgentConfig,
        orchestrator: ConversationOrchestrator,
    ) -> BaseAgent:
        return cls.create(config, orchestrator)
