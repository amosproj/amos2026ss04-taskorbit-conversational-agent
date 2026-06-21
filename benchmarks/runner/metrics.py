"""Metrics helpers for the TaskOrbit benchmarking environment.

Provides three capabilities:
  1. System metrics  — CPU, memory, optional GPU via psutil / pynvml
  2. Component latencies — named timing context manager for STT/LLM/TTS stages
  3. OTel export — push a benchmark summary to an OpenTelemetry OTLP endpoint

Designed to integrate with runner.py:_execute_trial() and with the backend's
existing Prometheus observability (taskorbit.observability.metrics) without
creating a hard dependency on it from the standalone benchmark process.
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Any, Generator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# System metrics
# ---------------------------------------------------------------------------


def capture_system_metrics() -> dict[str, Any]:
    """Capture a point-in-time snapshot of CPU, memory, and GPU utilization.

    GPU metrics require the pynvml package and an NVIDIA GPU. Missing pynvml
    or a non-NVIDIA system silently sets both GPU fields to None rather than
    raising — benchmarks should still run on CPU-only machines.

    Returns:
        Dict with keys: cpu_percent, memory_rss_mb, memory_percent,
        gpu_percent (or None), gpu_memory_percent (or None).
    """
    try:
        import psutil
    except ImportError:
        logger.warning("psutil not installed; system metrics unavailable")
        return {}

    process = psutil.Process()
    metrics: dict[str, Any] = {
        "cpu_percent": psutil.cpu_percent(interval=0.1),
        "memory_rss_mb": round(process.memory_info().rss / (1024 * 1024), 2),
        "memory_percent": psutil.virtual_memory().percent,
        "gpu_percent": None,
        "gpu_memory_percent": None,
    }

    try:
        import pynvml  # type: ignore[import]

        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        util = pynvml.nvmlDeviceGetUtilizationRates(handle)
        metrics["gpu_percent"] = util.gpu
        metrics["gpu_memory_percent"] = util.memory
    except Exception:
        pass  # GPU info is optional — CPU-only machines skip silently

    return metrics


# ---------------------------------------------------------------------------
# Component latency tracking
# ---------------------------------------------------------------------------


class ComponentTimer:
    """Accumulates named wall-clock timings for pipeline stages (STT, LLM, TTS).

    Usage::

        timer = ComponentTimer()
        with timer.measure("llm"):
            result = await call_llm(...)
        print(timer.timings())  # {"llm": 312.4}
    """

    def __init__(self) -> None:
        self._timings: dict[str, float] = {}

    @contextmanager
    def measure(self, component: str) -> Generator[None, None, None]:
        """Context manager that records wall-clock ms for *component*."""
        t0 = time.perf_counter()
        try:
            yield
        finally:
            self._timings[component] = (time.perf_counter() - t0) * 1000

    def timings(self) -> dict[str, float]:
        """Return a copy of all recorded timings in milliseconds."""
        return dict(self._timings)


def capture_component_latencies(
    stt_ms: float = 0.0,
    llm_ms: float = 0.0,
    tts_ms: float = 0.0,
) -> dict[str, float]:
    """Build a component latency dict from pre-measured stage durations.

    Convenience wrapper for callers that already have individual timings and
    don't need the ComponentTimer context manager.

    Args:
        stt_ms: Speech-to-text stage latency in milliseconds.
        llm_ms: LLM inference stage latency in milliseconds.
        tts_ms: Text-to-speech synthesis latency in milliseconds.

    Returns:
        Dict matching the TrialMetrics.component_latencies schema.
    """
    return {
        "stt": stt_ms,
        "llm": llm_ms,
        "tts": tts_ms,
    }


# ---------------------------------------------------------------------------
# OpenTelemetry export
# ---------------------------------------------------------------------------


def export_to_otel(
    run_id: str,
    config_name: str,
    summary: dict[str, Any],
    endpoint: str | None = None,
) -> bool:
    """Push benchmark summary metrics to an OpenTelemetry OTLP endpoint.

    Requires the opentelemetry-exporter-otlp package. When the package is
    absent or no endpoint is configured the function logs a warning and
    returns False so callers can decide whether to treat this as an error.

    Args:
        run_id: Unique identifier for the benchmark run.
        config_name: Name of the experiment configuration.
        summary: Dict produced by BenchmarkRunner._compute_summary().
        endpoint: OTLP HTTP endpoint URL. Falls back to the
            OTEL_EXPORTER_OTLP_ENDPOINT environment variable when None.

    Returns:
        True on successful export, False if export was skipped or failed.
    """
    import os

    resolved_endpoint = endpoint or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not resolved_endpoint:
        logger.warning(
            "export_to_otel: no endpoint configured; set OTEL_EXPORTER_OTLP_ENDPOINT "
            "or pass endpoint= to enable metric upload"
        )
        return False

    try:
        from opentelemetry import metrics as otel_metrics  # type: ignore[import]
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import (  # type: ignore[import]
            OTLPMetricExporter,
        )
        from opentelemetry.sdk.metrics import MeterProvider  # type: ignore[import]
        from opentelemetry.sdk.metrics.export import (  # type: ignore[import]
            PeriodicExportingMetricReader,
        )
    except ImportError:
        logger.warning(
            "export_to_otel: opentelemetry-exporter-otlp not installed; "
            "run: pip install opentelemetry-exporter-otlp"
        )
        return False

    try:
        exporter = OTLPMetricExporter(endpoint=resolved_endpoint)
        reader = PeriodicExportingMetricReader(exporter, export_interval_millis=1000)
        provider = MeterProvider(metric_readers=[reader])
        otel_metrics.set_meter_provider(provider)

        meter = otel_metrics.get_meter("taskorbit.benchmark")

        avg_latency = meter.create_gauge(
            "benchmark_avg_latency_ms",
            description="Average end-to-end latency across all trials",
        )
        success_rate = meter.create_gauge(
            "benchmark_success_rate",
            description="Fraction of trials that succeeded",
        )

        labels = {"run_id": run_id, "config_name": config_name}
        avg_latency.set(summary.get("avg_latency_ms", 0.0), labels)
        success_rate.set(summary.get("success_rate", 0.0), labels)

        provider.force_flush()
        logger.info("export_to_otel: metrics pushed", extra={"run_id": run_id, "endpoint": resolved_endpoint})
        return True

    except Exception as exc:
        logger.error("export_to_otel: export failed", exc_info=exc)
        return False
