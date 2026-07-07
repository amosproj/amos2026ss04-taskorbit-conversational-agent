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

logger = get_logger(__name__)


def configure_default_metrics() -> None:
    """Register default process, GC, and platform collectors, and pre-initialize
    LLM metric label combinations.

    Python equivalent of Node.js prom-client's collectDefaultMetrics({ timeout: 5000 }).

    In Python's pull model, metrics are collected on-demand at scrape time rather
    than on a timer, so there is no timeout parameter. These collectors provide:
      - ProcessCollector: CPU, RSS/virtual memory, open file descriptors, start time
      - GCCollector:      garbage collection counts and durations by generation
      - PlatformCollector: Python version info

    Safe to call multiple times — already-registered collectors are silently skipped.
    ProcessCollector metrics are only available on Linux (requires /proc/).

    Label pre-initialization: prometheus_client only emits a labeled counter in
    /metrics output after the first .labels(...).inc() call. Without this, Grafana
    shows "No data" until the first successful LLM call. Calling .labels(...) here
    (without .inc()) registers each child with value 0 so the series is visible from
    the first Prometheus scrape.
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
        logger.debug("default_metrics_registered", collectors=registered)
    else:
        logger.debug("default_metrics_already_registered")

    # Pre-initialize known label combinations so counters appear as 0 in /metrics
    # from startup rather than being absent until the first LLM call completes.
    m = get_metrics()
    _providers = [
        ("openai", "gpt-4o-mini"),
        ("google", "gemini-2.5-flash"),
        # Open-source providers — pre-initialize with representative default models
        # so Grafana shows 0 from startup rather than "No data" until first request.
        # Add a new tuple here when onboarding a new OS provider.
        ("openrouter", "qwen/qwen3-next-80b-a3b-instruct:free"),
        ("ollama", "gemma4:26b"),
    ]
    _llm_statuses = ["success", "auth", "rate_limit", "timeout", "api", "empty_response", "client"]
    for provider, model in _providers:
        for token_type in ("prompt", "completion"):
            m.tokens_used_total.labels(provider=provider, model=model, token_type=token_type)
        for status in _llm_statuses:
            m.llm_requests_total.labels(provider=provider, model=model, status=status)
        m.llm_response_chars.labels(provider=provider, model=model)
    for stage in (
        "llm_call",
        "llm_api_openai",
        "llm_api_google",
        "llm_api_openrouter",
        "llm_api_ollama",
        "tts_synthesis",
        "tts_ttfb",
        "worker_turn",
        "total",
        "stt_processing",
        "tool_call",
    ):
        m.pipeline_latency_seconds.labels(stage=stage)
    for error_type in (
        "llm_timeout",
        "encoding_error",
        "invalid_input",
        "runtime_error",
        "llm_config",
        "llm_provider_error",
        "unhandled",
    ):
        m.conversation_errors_total.labels(error_type=error_type)
    for handler in ("/v1/conversations/process", "/v1/tts/synthesize"):
        for status in ("success", "error"):
            m.voice_pipeline_requests_total.labels(handler=handler, status=status)
    logger.debug("metrics_labels_initialized")


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
    voice_turn_latency_seconds: Histogram = field(
        default_factory=lambda: Histogram(
            "taskorbit_voice_turn_latency_seconds",
            "End-to-end voice turn latency from commit_turn received to reply text ready",
            buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 15.0],
        )
    )
    voice_pipeline_requests_total: Counter = field(
        default_factory=lambda: Counter(
            "taskorbit_voice_pipeline_requests_total",
            "Requests processed through the voice pipeline (equivalent REST handler shown as label)",
            ["handler", "status"],
        )
    )


@lru_cache(maxsize=1)
def get_metrics() -> MetricsRegistry:
    """Singleton accessor — mirrors get_settings() pattern. One registry per process."""
    return MetricsRegistry()
