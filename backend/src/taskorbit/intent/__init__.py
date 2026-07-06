"""Intent detection — maps a user prompt to a task workflow.

MockIntentDetector uses keyword-based routing across two predefined intents.
IntentRouter replaces it with LLM-based classification and a confidence gate.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

from taskorbit.integrations.llm.errors import LLMError
from taskorbit.logging.setup import get_logger

if TYPE_CHECKING:
    from taskorbit.types import LLMConfig, Message

logger = get_logger(__name__)

CONFIDENCE_THRESHOLD = 0.7

_ROUTING_SYSTEM_PROMPT = """\
You are an intent classifier for a voice assistant. Given a user message, pick the \
best-matching intent from the list below and rate your confidence.

Available intents:
{intents_list}

Respond ONLY with valid JSON: {{"intent": "<name>", "confidence": <0.0-1.0>}}
If nothing matches, return: {{"intent": null, "confidence": 0.0}}\
"""


@dataclass
class IntentResult:
    name: str
    description: str
    agent_name: str = ""  # maps to BaseAgent.agent_name in AgentRegistry
    required_inputs: list[dict[str, Any]] = field(default_factory=list)
    workflow_steps: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 1.0
    requires_clarification: bool = False


# Mirrors schemas/examples/agent-task.example.json — task section.
_BOOK_SERVICE_APPOINTMENT = IntentResult(
    name="book_service_appointment",
    description="Collect caller details and request a preferred appointment date for a plumbing service.",
    agent_name="sales",
    required_inputs=[
        {"name": "caller_name", "type": "string", "required": True},
        {"name": "email_address", "type": "email", "required": True},
        {"name": "phone_number", "type": "phone", "required": True},
        {"name": "preferred_date", "type": "date", "required": True},
        {"name": "service_location", "type": "location", "required": False},
    ],
    workflow_steps=[
        {"id": "greet", "action": "send_first_message"},
        {"id": "collect-data", "action": "extract_required_fields", "tool": "extract_data"},
        {"id": "confirm", "action": "confirm_booking_details"},
        {"id": "end", "action": "end_call", "tool": "end_call"},
    ],
)

_CUSTOMER_DISSATISFACTION_INQUIRY = IntentResult(
    name="customer_dissatisfaction_inquiry",
    description="Capture a customer complaint, affected service, and preferred resolution channel.",
    agent_name="customer_dissatisfaction",
    required_inputs=[
        {"name": "caller_name", "type": "string", "required": True},
        {"name": "email_address", "type": "email", "required": True},
        {"name": "complaint_description", "type": "string", "required": True},
        {"name": "preferred_contact", "type": "string", "required": True},
    ],
    workflow_steps=[
        {"id": "greet", "action": "send_first_message"},
        {"id": "collect-data", "action": "extract_required_fields", "tool": "extract_data"},
        {"id": "confirm", "action": "confirm_complaint_details"},
        {"id": "end", "action": "end_call", "tool": "end_call"},
    ],
)

_DISSATISFACTION_KEYWORDS = frozenset(
    [
        "complaint",
        "unhappy",
        "dissatisfied",
        "frustrated",
        "disappointed",
        "problem",
        "issue",
        "broken",
        "wrong",
        "bad",
        "terrible",
        "awful",
        "refund",
        "cancel",
    ]
)

_TECHNICAL_SUPPORT_KEYWORDS = frozenset(
    [
        "technical",
        "tech support",
        "support",
        "not working",
        "error",
        "bug",
        "crash",
        "fix",
        "troubleshoot",
        "help with",
        "device",
        "software",
        "hardware",
        "install",
        "setup",
    ]
)

_GENERAL_INQUIRY_KEYWORDS = frozenset(
    [
        "question",
        "info",
        "information",
        "how does",
        "what is",
        "tell me",
        "explain",
        "faq",
        "policy",
        "price",
        "pricing",
        "hours",
        "contact",
    ]
)

_APPOINTMENT_MANAGEMENT_KEYWORDS = frozenset(
    [
        "reschedule",
        "rebook",
        "cancel appointment",
        "cancel booking",
        "change appointment",
        "move appointment",
        "check appointment",
        "appointment status",
        "existing booking",
        "my booking",
    ]
)

_TECHNICAL_SUPPORT_REQUEST = IntentResult(
    name="technical_support_request",
    description="Help a caller troubleshoot a technical issue or get direct technical assistance.",
    agent_name="technical_support",
    required_inputs=[
        {"name": "caller_name", "type": "string", "required": True},
        {"name": "issue_description", "type": "string", "required": True},
    ],
    workflow_steps=[
        {"id": "greet", "action": "send_first_message"},
        {"id": "collect-data", "action": "extract_required_fields", "tool": "extract_data"},
        {"id": "diagnose", "action": "troubleshoot_issue"},
        {"id": "end", "action": "end_call", "tool": "end_call"},
    ],
)


class MockIntentDetector:
    """Keyword-based intent detector kept for tests and local fallback."""

    def detect(self, prompt: str) -> IntentResult:
        """Return a fresh IntentResult copy — never mutates shared module-level objects.

        Keyword priority order (first match wins — add new checks carefully):
          1. Appointment management — checked first because its keywords
             (reschedule, rebook) are specific and don't overlap with others.
          2. Technical support — broad but distinct from complaint language.
          3. Customer dissatisfaction — shares some words with technical (e.g.
             "problem") so must come after technical to avoid mis-routing.
          4. General inquiry — catch-all for info/FAQ requests.
          5. Book service appointment — default when nothing else matches.
        """
        lowered = prompt.lower()
        # if any(kw in lowered for kw in _APPOINTMENT_MANAGEMENT_KEYWORDS):
        #     return replace(_KNOWN_INTENTS["appointment_management"])
        if any(kw in lowered for kw in _TECHNICAL_SUPPORT_KEYWORDS):
            return replace(_TECHNICAL_SUPPORT_REQUEST)
        if any(kw in lowered for kw in _DISSATISFACTION_KEYWORDS):
            return replace(_CUSTOMER_DISSATISFACTION_INQUIRY)
        if any(kw in lowered for kw in _GENERAL_INQUIRY_KEYWORDS):
            return replace(_KNOWN_INTENTS["general_inquiry"])
        return replace(_BOOK_SERVICE_APPOINTMENT)


# ---------------------------------------------------------------------------
# LLM-based intent router
# ---------------------------------------------------------------------------

LLMCallable = Callable[
    [str, list[Any], Any],
    Coroutine[Any, Any, str],
]

# Add new intents here — IntentRouter picks them up automatically.
_KNOWN_INTENTS: dict[str, IntentResult] = {
    _BOOK_SERVICE_APPOINTMENT.name: _BOOK_SERVICE_APPOINTMENT,
    _CUSTOMER_DISSATISFACTION_INQUIRY.name: _CUSTOMER_DISSATISFACTION_INQUIRY,
    _TECHNICAL_SUPPORT_REQUEST.name: _TECHNICAL_SUPPORT_REQUEST,
    "general_inquiry": IntentResult(
        name="general_inquiry",
        description="Answer general questions about products, services, or policies without collecting structured data.",
        agent_name="general_inquiry",
        workflow_steps=[
            {"id": "greet", "action": "send_first_message"},
            {"id": "answer", "action": "respond_to_query"},
            {"id": "handoff_or_end", "action": "transfer_or_end_call"},
        ],
    ),
    # "appointment_management": IntentResult(
    #     name="appointment_management",
    #     description="Reschedule, cancel, or check the status of an existing appointment.",
    #     agent_name="appointment_management",
    #     required_inputs=[
    #         {"name": "caller_name", "type": "string", "required": True},
    #         {"name": "booking_reference", "type": "string", "required": True},
    #         {"name": "requested_action", "type": "string", "required": True},
    #     ],
    #     workflow_steps=[
    #         {"id": "greet", "action": "send_first_message"},
    #         {"id": "collect-data", "action": "extract_required_fields", "tool": "extract_data"},
    #         {"id": "confirm", "action": "confirm_action"},
    #         {"id": "end", "action": "end_call", "tool": "end_call"},
    #     ],
    # ),
}

_CLARIFICATION_REPLY = (
    "I want to make sure I help you with the right thing — could you tell me a bit more "
    "about what you're looking for?"
)

_FALLBACK_RESULT = IntentResult(
    name="unknown",
    description="No matching intent found.",
    confidence=0.0,
    requires_clarification=True,
)


class IntentRouter:
    """LLM-based intent router with confidence gating.

    Replaces MockIntentDetector in the orchestration pipeline. Coworkers can
    extend _KNOWN_INTENTS above to add new routing targets without touching
    this class.
    """

    def __init__(self, threshold: float = CONFIDENCE_THRESHOLD) -> None:
        self._threshold = threshold
        self._fallback = MockIntentDetector()

    async def detect(
        self,
        prompt: str,
        messages: list[Message],
        llm_fn: LLMCallable,
        llm_config: LLMConfig,
    ) -> IntentResult:
        """Classify *prompt* and return an IntentResult.

        Sets ``requires_clarification=True`` when confidence is below the
        threshold or when the LLM returns no matching intent.
        """
        intents_list = "\n".join(
            f"- {name}: {result.description}" for name, result in _KNOWN_INTENTS.items()
        )

        history_block = ""
        if len(messages) >= 2:
            recent = messages[-3:] if len(messages) >= 3 else messages[:-1]
            lines = [
                f"{m.role.value}: {m.content}"
                for m in recent
                if m.role.value in ("user", "assistant")
            ]
            if lines:
                history_block = "\n\nConversation so far:\n" + "\n".join(lines)

        system_prompt = _ROUTING_SYSTEM_PROMPT.format(intents_list=intents_list) + history_block

        # Send only the current user turn so the classifier stays focused.
        from taskorbit.types import Message as Msg
        from taskorbit.types import MessageRole

        classification_messages: list[Msg] = [Msg(role=MessageRole.USER, content=prompt)]

        raw = ""
        try:
            raw = await llm_fn(system_prompt, classification_messages, llm_config)
            # Extract the first JSON object from the response — handles markdown
            # fences (Gemini), preamble text, and partial thinking output (Ollama).
            match = re.search(r"\{[^{}]*\}", raw, re.DOTALL)
            if match:
                cleaned = match.group(0)
            else:
                cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.IGNORECASE)
                cleaned = re.sub(r"\s*```$", "", cleaned)
            parsed = json.loads(cleaned)
            intent_name: str | None = parsed.get("intent")
            confidence: float = float(parsed.get("confidence", 0.0))
        except LLMError:
            # Provider failures (auth, quota, timeout, API error) must surface to
            # the caller so the orchestration error handlers can return a clear
            # message and the correct metric label. Masking them as a low-confidence
            # clarification made a real outage (e.g. an exhausted OpenAI quota, #197)
            # look identical to a genuine "please clarify", hiding the problem.
            raise
        except Exception as exc:
            logger.warning("intent_router_parse_error", error=str(exc))
            # Genuine parse/format issues (malformed JSON, etc.) fall back to keyword
            # matching so the call never silently drops. confidence=0.5 is below the
            # threshold so requires_clarification is set consistently.
            return replace(
                self._fallback.detect(prompt),
                confidence=0.5,
                requires_clarification=0.5 < self._threshold,
            )

        if not intent_name or intent_name not in _KNOWN_INTENTS:
            return replace(_FALLBACK_RESULT, confidence=0.0, requires_clarification=True)

        return replace(
            _KNOWN_INTENTS[intent_name],
            confidence=confidence,
            requires_clarification=confidence < self._threshold,
        )
