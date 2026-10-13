"""Optional helper: configure global OpenTelemetry providers exporting over OTLP/HTTP.

Applications that already configure OpenTelemetry should skip this and let
`Instrumentor.create()` use their global providers.
"""

from __future__ import annotations

from dataclasses import dataclass

from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


@dataclass(frozen=True, slots=True)
class Providers:
    tracer_provider: TracerProvider
    meter_provider: MeterProvider

    def shutdown(self) -> None:
        self.tracer_provider.shutdown()
        self.meter_provider.shutdown()


def configure(
    service_name: str, endpoint: str, *, export_interval_ms: int = 5_000
) -> Providers:  # pragma: no cover - exercised by the docker-compose demo, needs a collector
    """Install OTLP/HTTP exporters (requires the `otlp` extra) as the global providers."""
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    resource = Resource.create({"service.name": service_name})
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces"))
    )
    reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=f"{endpoint}/v1/metrics"),
        export_interval_millis=export_interval_ms,
    )
    meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
    trace.set_tracer_provider(tracer_provider)
    metrics.set_meter_provider(meter_provider)
    return Providers(tracer_provider, meter_provider)
