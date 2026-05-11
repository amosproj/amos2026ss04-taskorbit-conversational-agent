"""
LLM error taxonomy: LLMError is the base; subclasses narrow the failure mode
so callers can catch only what they can handle.
"""


class LLMError(Exception):
    """Base class for all LLM-related errors."""


class LLMConfigError(LLMError):
    """Raised when provider config or API key is missing or invalid."""


class LLMTimeoutError(LLMError):
    """Raised when an LLM call exceeds its configured timeout."""


class LLMAPIError(LLMError):
    """Raised when the provider API returns an error response."""
