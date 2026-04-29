"""Task-specific agents.

BaseAgent defines the interface every agent must implement. Concrete agents
(TechnicalSupportAgent, SalesAgent) encapsulate the task definitions for
their domain and delegate message processing to the shared orchestrator.

AgentRegistry maps an AgentConfig to the right BaseAgent subclass so the
API layer doesn't need to know which agent type it's dealing with.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from taskorbit.orchestration import ConversationOrchestrator
from taskorbit.types import AgentConfig, ConversationRequest, ConversationResponse, ToolDefinition


class BaseAgent(ABC):
    """Abstract base for all task-specific agents."""

    def __init__(
        self,
        config: AgentConfig,
        orchestrator: ConversationOrchestrator,
    ) -> None:
        self.config = config
        self.orchestrator = orchestrator

    @abstractmethod
    async def handle_message(
        self, request: ConversationRequest
    ) -> ConversationResponse:
        """Process a user message and return an assistant response."""
        ...

    @abstractmethod
    def get_task_definitions(self) -> list[ToolDefinition]:
        """Return the tool definitions that define this agent's task scope."""
        ...


class AgentRegistry:
    """Maps an AgentConfig to the correct BaseAgent subclass at runtime."""

    @staticmethod
    def get_agent(
        config: AgentConfig,
        orchestrator: ConversationOrchestrator,
    ) -> BaseAgent:
        """Instantiate the right agent for the given config.

        Selection logic (e.g. based on config.id prefix or a type field)
        is implemented in downstream tickets.
        """
        raise NotImplementedError
