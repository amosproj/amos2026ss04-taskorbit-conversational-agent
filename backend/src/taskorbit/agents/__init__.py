"""Task-specific agents.

All agents live in this file. To add a new agent:
  1. Subclass BaseAgent and implement handle_message() + get_task_definitions()
  2. Register it in AgentRegistry._REGISTRY with the keyword(s) that appear in config.id

AgentRegistry.create() is the single constructor for all agent types.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from taskorbit.types import AgentConfig, ConversationRequest, ConversationResponse, ToolDefinition

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
        (("support", "technical", "tech"), TechnicalSupportAgent),
        (("sales", "lead", "qualification"), SalesAgent),
        (("inquiry", "faq", "general"), GeneralInquiryAgent),
        (("appointment", "reschedule", "cancel", "booking"), AppointmentManagementAgent),
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
                return agent_cls(config, orchestrator)
        return cls._DEFAULT(config, orchestrator)

    # Keep the old name available so existing call sites don't break.
    @classmethod
    def get_agent(
        cls,
        config: AgentConfig,
        orchestrator: ConversationOrchestrator,
    ) -> BaseAgent:
        return cls.create(config, orchestrator)
