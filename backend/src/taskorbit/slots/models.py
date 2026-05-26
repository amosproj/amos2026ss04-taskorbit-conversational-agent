"""Slot extraction data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SlotValue:
    """A single extracted slot with its name, value, and declared type."""

    name: str
    value: Any
    slot_type: str


@dataclass
class SlotExtractionResult:
    """Result of a slot extraction pass over the conversation history."""

    filled: dict[str, SlotValue] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        """True when all required slots have been filled."""
        return len(self.missing) == 0

    def to_dict(self) -> dict[str, Any]:
        """Return filled slot values keyed by slot name."""
        return {name: sv.value for name, sv in self.filled.items()}
