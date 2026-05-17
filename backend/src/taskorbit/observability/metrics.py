"""Custom Prometheus metrics for TaskOrbit.

Usage:
    from taskorbit.observability.metrics import configure_default_metrics, get_metrics

    configure_default_metrics()   # call once at process startup

    m = get_metrics()
    m.llm_requests_total.labels(provider="openai", model="gpt-4o-mini", status="success").inc()
    m.llm_response_chars.labels(provider="openai", model="gpt-4o-mini").observe(len(text))
    m.pipeline_latency_seconds.labels(stage="llm_call").observe(elapsed)
    m.tokens_used_total.labels(provider="openai", model="gpt-4o-mini", token_type="prompt").inc(150)
    m.tokens_used_total.labels(provider="openai", model="gpt-4o-mini", token_type="completion").inc(42)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

from prometheus_client import Counter, Histogram

from taskorbit.logging.setup import get_logger

_log = get_logger(__name__)


def configure_default_metrics() -> None:
    """Register default process, GC, and platform collectors.

    Python equivalent of Node.js prom-client's collectDefaultMetrics({ timeout: 5000 }).

    In Python's pull model, metrics are collected on-demand at scrape time rather
    than on a timer, so there is no timeout parameter. These collectors provide:
      - ProcessCollector: CPU, RSS/virtual memory, open file descriptors, start time
      - GCCollector:      garbage collection counts and durations by generation
      - PlatformCollector: Python version info

    Safe to call multiple times — already-registered collectors are silently skipped.
    ProcessCollector metrics are only available on Linux (requires /proc/).
    """
    from prometheus_client import (
        GC_COLLECTOR,
        PLATFORM_COLLECTOR,
        PROCESS_COLLECTOR,
        REGISTRY,
    )

    registered: list[str] = []
    for collector, name in (
        (PROCESS_COLLECTOR, "ProcessCollector"),
        (GC_COLLECTOR, "GCCollector"),
        (PLATFORM_COLLECTOR, "PlatformCollector"),
    ):
        try:
            REGISTRY.register(collector)
            registered.append(name)
        except ValueError:
            pass  # Already registered — default prometheus_client behaviour

    if registered:
        _log.debug("default_metrics_registered", collectors=registered)
    else:
        _log.debug("default_metrics_already_registered")


@dataclass
class MetricsRegistry:
    llm_requests_total: Counter = field(
        default_factory=lambda: Counter(
            "taskorbit_llm_requests_total",
            "Total LLM API calls",
            ["provider", "model", "status"],
        )
    )
    llm_response_chars: Histogram = field(
        default_factory=lambda: Histogram(
            "taskorbit_llm_response_chars",
            "LLM response size in characters",
            ["provider", "model"],
            buckets=[64, 256, 512, 1024, 2048, 4096, 8192],
        )
    )
    pipeline_latency_seconds: Histogram = field(
        default_factory=lambda: Histogram(
            "taskorbit_pipeline_latency_seconds",
            "Latency in seconds for named pipeline stages",
            ["stage"],
            buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
        )
    )
    conversation_errors_total: Counter = field(
        default_factory=lambda: Counter(
            "taskorbit_conversation_errors_total",
            "Conversation processing errors by type",
            ["error_type"],
        )
    )
    tokens_used_total: Counter = field(
        default_factory=lambda: Counter(
            "taskorbit_tokens_used_total",
            "LLM tokens consumed, split by prompt and completion",
            ["provider", "model", "token_type"],  # token_type: prompt | completion
        )
    )


@lru_cache(maxsize=1)
def get_metrics() -> MetricsRegistry:
    """Singleton accessor — mirrors get_settings() pattern. One registry per process."""
    return MetricsRegistry()
