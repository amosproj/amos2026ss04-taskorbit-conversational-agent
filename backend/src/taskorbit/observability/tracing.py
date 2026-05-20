"""OpenTelemetry TracerProvider initialisation.

No-op unless OTEL_ENABLED=true. When disabled the OTel API stays in its
default no-op provider state — zero overhead, no imports beyond the API stub.
"""

from __future__ import annotations

from opentelemetry import trace as _otel_trace

from taskorbit.config import get_settings
from taskorbit.logging.setup import get_logger

_log = get_logger(__name__)


def configure_tracing() -> None:
    """Initialise the OTel TracerProvider. Idempotent — safe to call on every startup."""
    settings = get_settings()
    if not settings.otel_enabled:
        return

    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

    if isinstance(trace.get_tracer_provider(), TracerProvider):
        return

    resource = Resource.create({"service.name": "taskorbit-backend"})
    provider = TracerProvider(resource=resource)

    if settings.otel_exporter_otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        exporter: object = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint)
        _log.info(
            "otel_configured",
            exporter="otlp",
            endpoint=settings.otel_exporter_otlp_endpoint,
        )
    else:
        exporter = ConsoleSpanExporter()
        _log.info("otel_configured", exporter="console")

    provider.add_span_processor(BatchSpanProcessor(exporter))  # type: ignore[arg-type]
    trace.set_tracer_provider(provider)


def get_tracer(name: str) -> _otel_trace.Tracer:
    """Return a tracer. Silently no-ops when OTel is disabled."""
    return _otel_trace.get_tracer(name)
