"""CLI entry point wired into pyproject.toml's `[tool.poetry.scripts]`.

After `poetry install` you get:

    poetry run taskorbit-api      # FastAPI HTTP server (uvicorn)

The voice-agent worker entry point will be added by the downstream
ticket that implements `livekit_agent/`.
"""

from __future__ import annotations

import argparse

import uvicorn

from taskorbit.config import get_settings
from taskorbit.logging.setup import configure_logging


def run_api() -> None:
    """Start the FastAPI server.

    Forwards arbitrary uvicorn flags so `poetry run taskorbit-api --reload`
    or `--port 9000` works as expected.
    """
    configure_logging()
    settings = get_settings()

    parser = argparse.ArgumentParser(description="Run the TaskOrbit FastAPI server.")
    parser.add_argument("--host", default=settings.api_host)
    parser.add_argument("--port", type=int, default=settings.api_port)
    parser.add_argument(
        "--reload",
        action="store_true",
        default=settings.is_development,
        help="Enable auto-reload (default: on in development).",
    )
    args = parser.parse_args()

    uvicorn.run(
        "taskorbit.api.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_config=None,  # logging is configured separately via structlog
    )
