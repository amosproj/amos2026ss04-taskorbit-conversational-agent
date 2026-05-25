"""Intent detection — maps a user prompt to a task workflow.

MockIntentDetector uses keyword-based routing across two predefined intents.
Real NLP-based routing lands in a later sprint.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class IntentResult:
    name: str
    description: str
    required_inputs: list[dict[str, Any]] = field(default_factory=list)
    workflow_steps: list[dict[str, Any]] = field(default_factory=list)


# Mirrors schemas/examples/agent-task.example.json — task section.
_BOOK_SERVICE_APPOINTMENT = IntentResult(
    name="book_service_appointment",
    description="Collect caller details and request a preferred appointment date for a plumbing service.",
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


class MockIntentDetector:
    """Keyword-based intent detector used until real NLP routing is implemented."""

    def detect(self, prompt: str) -> IntentResult:
        lowered = prompt.lower()
        if any(kw in lowered for kw in _DISSATISFACTION_KEYWORDS):
            return _CUSTOMER_DISSATISFACTION_INQUIRY
        return _BOOK_SERVICE_APPOINTMENT
