"""Tests for TraceIDMiddleware — trace-id header injection and structlog binding."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from taskorbit.api.main import create_app


def test_trace_id_header_present_in_response() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/health")
    assert "x-trace-id" in response.headers


def test_trace_id_is_valid_uuid() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/health")
    trace_id = response.headers.get("x-trace-id", "")
    uuid.UUID(trace_id)


def test_upstream_trace_id_is_echoed() -> None:
    app = create_app()
    upstream_id = "my-custom-trace-id-abc123"
    with TestClient(app) as client:
        response = client.get("/health", headers={"X-Trace-Id": upstream_id})
    assert response.headers.get("x-trace-id") == upstream_id


def test_different_requests_get_different_trace_ids() -> None:
    app = create_app()
    with TestClient(app) as client:
        r1 = client.get("/health")
        r2 = client.get("/health")
    assert r1.headers.get("x-trace-id") != r2.headers.get("x-trace-id")


def test_trace_id_bound_into_structlog_contextvars() -> None:
    """TraceIDMiddleware must call bind_contextvars with the request trace_id."""
    from unittest.mock import patch

    app = create_app()
    upstream_id = "test-trace-abc123"
    bound_calls: list[dict] = []

    original_bind = __import__("structlog").contextvars.bind_contextvars

    def capturing_bind(**kwargs: object) -> None:
        bound_calls.append(dict(kwargs))
        return original_bind(**kwargs)

    with patch("structlog.contextvars.bind_contextvars", side_effect=capturing_bind):
        with TestClient(app) as client:
            client.get("/health", headers={"X-Trace-Id": upstream_id})

    trace_ids_bound = [c.get("trace_id") for c in bound_calls if "trace_id" in c]
    assert upstream_id in trace_ids_bound, (
        f"Expected trace_id={upstream_id!r} to be bound into structlog contextvars, "
        f"got: {trace_ids_bound}"
    )
