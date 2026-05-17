"""Tests for the /metrics Prometheus endpoint and custom metric registration."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from taskorbit.api.main import create_app
from taskorbit.config import get_settings
from taskorbit.observability.metrics import configure_default_metrics, get_metrics


@pytest.fixture(scope="module", autouse=True)
def _isolate_prometheus_registry() -> Iterator[None]:
    """Unregister any collectors added by this module to avoid duplicate-registration
    errors when other test modules also call create_app()."""
    from prometheus_client import REGISTRY

    before = set(REGISTRY._names_to_collectors.keys())
    yield
    for name in set(REGISTRY._names_to_collectors.keys()) - before:
        try:
            REGISTRY.unregister(REGISTRY._names_to_collectors[name])
        except Exception:
            pass


def test_metrics_endpoint_returns_200() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/metrics")
    assert response.status_code == 200


def test_metrics_endpoint_content_type_is_prometheus_text() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/metrics")
    assert "text/plain" in response.headers["content-type"]


def test_metrics_endpoint_contains_http_requests_total() -> None:
    app = create_app()
    with TestClient(app) as client:
        client.get("/health")
        response = client.get("/metrics")
    assert "http_requests_total" in response.text


def test_metrics_endpoint_contains_custom_llm_counter() -> None:
    get_metrics()
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/metrics")
    assert "taskorbit_llm_requests_total" in response.text


def test_metrics_endpoint_contains_pipeline_latency_histogram() -> None:
    get_metrics()
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/metrics")
    assert "taskorbit_pipeline_latency_seconds" in response.text


def test_metrics_endpoint_contains_tokens_used_counter() -> None:
    get_metrics()
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/metrics")
    assert "taskorbit_tokens_used_total" in response.text


def test_default_metrics_idempotent() -> None:
    """configure_default_metrics() is safe to call multiple times without error."""
    configure_default_metrics()
    configure_default_metrics()


def test_default_metrics_gc_collector_present() -> None:
    """GC collector metrics appear in /metrics output after configure_default_metrics()."""
    configure_default_metrics()
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/metrics")
    assert "python_gc_collections_total" in response.text


def test_default_metrics_python_info_present() -> None:
    """Platform collector python_info gauge appears in /metrics output."""
    configure_default_metrics()
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/metrics")
    assert "python_info" in response.text


def test_tokens_used_counter_increments_correctly() -> None:
    """Verify tokens_used_total increments by the exact token count supplied."""
    from prometheus_client import REGISTRY

    m = get_metrics()
    # Read current value before increment (label combo unique to this test)
    before = _read_counter(
        REGISTRY,
        "taskorbit_tokens_used_total",
        {"provider": "test_provider", "model": "test_model", "token_type": "prompt"},
    )
    m.tokens_used_total.labels(
        provider="test_provider", model="test_model", token_type="prompt"
    ).inc(77)
    after = _read_counter(
        REGISTRY,
        "taskorbit_tokens_used_total",
        {"provider": "test_provider", "model": "test_model", "token_type": "prompt"},
    )
    assert after - before == pytest.approx(77)


def test_tokens_used_counter_tracks_prompt_and_completion_separately() -> None:
    """prompt and completion token_type labels are independent counters."""
    m = get_metrics()
    m.tokens_used_total.labels(provider="openai", model="gpt-4o-mini", token_type="prompt").inc(100)
    m.tokens_used_total.labels(provider="openai", model="gpt-4o-mini", token_type="completion").inc(
        25
    )
    # Just verify no exception is raised and both labels are accepted.


def _read_counter(registry: object, metric_name: str, labels: dict[str, str]) -> float:
    """Helper: read a single labelled counter value from the Prometheus registry.

    prometheus_client strips the _total suffix from Counter metric family names,
    so Counter("foo_total") is stored with metric.name == "foo". We search both
    the full name and the base name, then filter samples to the _total entry.
    """
    base_name = metric_name.removesuffix("_total")
    for metric in registry.collect():  # type: ignore[attr-defined]
        if metric.name in (metric_name, base_name):
            for sample in metric.samples:
                if sample.labels == labels and sample.name == metric_name:
                    return sample.value
    return 0.0


def test_metrics_disabled_returns_404(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("METRICS_ENABLED", "false")
    get_settings.cache_clear()
    try:
        app = create_app()
        with TestClient(app) as client:
            response = client.get("/metrics")
        assert response.status_code == 404
    finally:
        get_settings.cache_clear()
