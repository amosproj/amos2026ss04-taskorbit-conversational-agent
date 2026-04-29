"""FastAPI application.

Creates the HTTP service that exposes the `/health` liveness endpoint
today, and will host orchestration / chat-history / confirmation
endpoints as downstream tickets land.

Run with `poetry run taskorbit-api` (defined in pyproject.toml scripts).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from taskorbit import __version__
from taskorbit.api import health
from taskorbit.api.routes import conversations, livekit
from taskorbit.config import get_settings
from taskorbit.logging.setup import configure_logging, get_logger


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Run once on startup, once on shutdown."""
    configure_logging()
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

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(conversations.router)
    app.include_router(livekit.router)

    return app


# uvicorn target — `uvicorn taskorbit.api.main:app` works too.
app = create_app()
