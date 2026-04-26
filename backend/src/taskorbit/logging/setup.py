"""Configure stdlib logging + structlog.

Use `configure_logging()` once at process start. Then anywhere:

    from taskorbit.logging.setup import get_logger
    log = get_logger(__name__)
    log.info("agent_started", task="greeting", room="abc")

Structured logs carry key/value context (room id, task id, …) — the
architecture document calls this out explicitly under "Quality:
structured logging".
"""

from __future__ import annotations

# Absolute imports — these resolve to the stdlib, not to `taskorbit.logging`.
# See the package docstring in __init__.py.
import logging
import sys

import structlog

from taskorbit.config import get_settings


def configure_logging() -> None:
    """Configure stdlib logging + structlog. Idempotent."""
    settings = get_settings()
    level = getattr(logging, settings.log_level)

    # Stdlib root logger — used by FastAPI / uvicorn / livekit internals.
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )

    # JSON renderer in production for log aggregation; pretty console
    # output in development for human eyes.
    renderer: structlog.types.Processor
    if settings.is_development:
        renderer = structlog.dev.ConsoleRenderer(colors=True)
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Get a bound structlog logger."""
    return structlog.get_logger(name)
