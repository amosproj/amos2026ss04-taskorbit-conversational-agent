"""Intent detection — maps a user prompt to a task workflow.

MockIntentDetector always returns the predefined book_service_appointment
workflow from schemas/examples/agent-task.example.json. Real NLP-based
routing lands in a later sprint.
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
        {"name": "phone_number", "type": "string", "required": True},
        {"name": "preferred_date", "type": "date", "required": True},
    ],
    workflow_steps=[
        {"id": "greet", "action": "send_first_message"},
        {"id": "collect-data", "action": "extract_required_fields", "tool": "extract_data"},
        {"id": "confirm", "action": "confirm_booking_details"},
        {"id": "end", "action": "end_call", "tool": "end_call"},
    ],
)


class MockIntentDetector:
    """Hardwired intent detector used until real NLP routing is implemented."""

    def detect(self, prompt: str) -> IntentResult:  # noqa: ARG002
        return _BOOK_SERVICE_APPOINTMENT
