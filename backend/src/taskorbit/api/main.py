"""FastAPI application.

Creates the HTTP service that exposes the `/health` liveness endpoint
today, and will host orchestration / chat-history / confirmation
endpoints as downstream tickets land.

Run with `poetry run taskorbit-api` (defined in pyproject.toml scripts).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from taskorbit import __version__
from taskorbit.api import health
from taskorbit.api.routes import conversations, livekit, tts
from taskorbit.config import get_settings
from taskorbit.logging.setup import configure_logging, get_logger
from taskorbit.observability.metrics import configure_default_metrics, get_metrics
from taskorbit.observability.middleware import TraceIDMiddleware
from taskorbit.observability.tracing import configure_tracing

_log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Run once on startup, once on shutdown."""
    configure_logging()
    configure_tracing()
    log = get_logger(__name__)
    settings = get_settings()
    log.info(
        "api_starting",
        env=settings.app_env,
        version=__version__,
        host=settings.api_host,
        port=settings.api_port,
    )
    yield
    log.info("api_shutdown")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="TaskOrbit Backend",
        description=(
            "HTTP API for the TaskOrbit Conversational Agent. "
            "Hosts the dev-environment health endpoint today; "
            "orchestration and admin endpoints arrive in downstream tickets."
        ),
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs" if settings.is_development else None,
        redoc_url=None,
    )

    if settings.metrics_enabled:
        from prometheus_fastapi_instrumentator import Instrumentator

        configure_default_metrics()
        Instrumentator(
            should_group_status_codes=True,
            excluded_handlers=["/health"],
        ).instrument(app).expose(app, endpoint="/metrics")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(TraceIDMiddleware)

    # Add routers here as we build more apis
    app.include_router(health.router)
    app.include_router(conversations.router)  # /v1/conversations/process
    app.include_router(livekit.router)  # /v1/livekit/token
    app.include_router(tts.router)  # /v1/tts/synthesize

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """Catch-all for unhandled exceptions: log with structlog + increment error counter."""
        _log.exception(
            "unhandled_error",
            path=str(request.url.path),
            method=request.method,
            error=str(exc),
            exc_info=exc,
        )
        get_metrics().conversation_errors_total.labels(error_type="unhandled").inc()
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    return app


# uvicorn target — `uvicorn taskorbit.api.main:app` works too.
app = create_app()
