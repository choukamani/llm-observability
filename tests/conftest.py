from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader, NumberDataPoint
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from llmobs import Instrumentor
from llmobs.events import Event


@dataclass
class Telemetry:
    spans: InMemorySpanExporter
    reader: InMemoryMetricReader
    tracer_provider: TracerProvider
    meter_provider: MeterProvider

    def finished_spans(self) -> list[ReadableSpan]:
        return list(self.spans.get_finished_spans())

    def metric_points(self, name: str) -> list[object]:
        data = self.reader.get_metrics_data()
        if data is None:
            return []
        return [
            point
            for resource in data.resource_metrics
            for scope in resource.scope_metrics
            for metric in scope.metrics
            if metric.name == name
            for point in metric.data.data_points
        ]

    def counter_total(self, name: str) -> float:
        return sum(p.value for p in self.metric_points(name) if isinstance(p, NumberDataPoint))


@pytest.fixture
def telemetry() -> Iterator[Telemetry]:
    spans = InMemorySpanExporter()
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(spans))
    reader = InMemoryMetricReader()
    meter_provider = MeterProvider(metric_readers=[reader])
    yield Telemetry(spans, reader, tracer_provider, meter_provider)
    tracer_provider.shutdown()
    meter_provider.shutdown()


@dataclass
class RecordingSubscriber:
    events: list[Event] = field(default_factory=list)

    def notify(self, event: Event) -> None:
        self.events.append(event)


@pytest.fixture
def recorder() -> RecordingSubscriber:
    return RecordingSubscriber()


@pytest.fixture
def instrumentor(telemetry: Telemetry, recorder: RecordingSubscriber) -> Instrumentor:
    return Instrumentor.create(
        tracer_provider=telemetry.tracer_provider,
        meter_provider=telemetry.meter_provider,
        subscribers=[recorder],
    )
