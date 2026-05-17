"""HTTP middleware: inject trace_id and span_id into structlog contextvars.

Every structlog call within a request coroutine automatically carries
trace_id and span_id after this middleware runs — no manual passing needed.

Note: structlog contextvars do NOT propagate into asyncio.create_task() children.
Manually copy context when spawning background tasks.
"""

from __future__ import annotations

import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

_TRACE_HEADER = "X-Trace-Id"


class TraceIDMiddleware(BaseHTTPMiddleware):
    """Binds trace_id into structlog contextvars for every HTTP request."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        trace_id = request.headers.get(_TRACE_HEADER) or str(uuid.uuid4())
        span_id = _get_otel_span_id()

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(trace_id=trace_id, span_id=span_id)

        response = await call_next(request)
        response.headers[_TRACE_HEADER] = trace_id
        return response


def _get_otel_span_id() -> str:
    """Return the active OTel span id as hex, or empty string when OTel is off."""
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        ctx = span.get_span_context()
        if ctx and ctx.is_valid:
            return format(ctx.span_id, "016x")
    except Exception:
        pass
    return ""
