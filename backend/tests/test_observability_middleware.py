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
