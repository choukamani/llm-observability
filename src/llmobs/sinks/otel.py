"""OpenTelemetry sinks, following the GenAI semantic conventions where they exist.

See https://opentelemetry.io/docs/specs/semconv/gen-ai/ . Attributes that have
no convention yet (estimated cost, estimated tokens) use the `llm.` namespace.
"""

from __future__ import annotations

from typing import Final

from opentelemetry import metrics, trace
from opentelemetry.trace import SpanKind, Status, StatusCode
from opentelemetry.util.types import AttributeValue

from llmobs.events import CallFinished, CallStarted, Event
from llmobs.model import LLMCall

# Bucket boundaries recommended by the GenAI semantic conventions.
DURATION_BUCKETS: Final = (
    0.01, 0.02, 0.04, 0.08, 0.16, 0.32, 0.64, 1.28, 2.56, 5.12, 10.24, 20.48, 40.96, 81.92,
)  # fmt: skip
TOKEN_BUCKETS: Final = (
    1, 4, 16, 64, 256, 1024, 4096, 16384, 65536, 262144, 1048576, 4194304, 16777216, 67108864,
)  # fmt: skip


def common_attributes(call: LLMCall) -> dict[str, AttributeValue]:
    attrs: dict[str, AttributeValue] = {
        "gen_ai.operation.name": call.operation,
        "gen_ai.provider.name": call.provider,
        "gen_ai.request.model": call.model,
    }
    attrs.update({f"llm.{key}": value for key, value in call.attributes.items()})
    if call.error_category is not None:
        attrs["error.type"] = call.error_category.value
    return attrs


class OTelSpanSink:
    """Emits one CLIENT span per call, timestamped with the call's real start and end."""

    def __init__(self, tracer_provider: trace.TracerProvider | None = None) -> None:
        self._tracer = trace.get_tracer("llmobs", tracer_provider=tracer_provider)

    def notify(self, event: Event) -> None:
        if not isinstance(event, CallFinished):
            return
        call = event.call
        attrs = common_attributes(call)
        if call.response_model:
            attrs["gen_ai.response.model"] = call.response_model
        if call.usage is not None:
            attrs["gen_ai.usage.input_tokens"] = call.usage.input_tokens
            attrs["gen_ai.usage.output_tokens"] = call.usage.output_tokens
            attrs["llm.usage.estimated"] = call.usage.estimated
        if call.cost_usd is not None:
            attrs["llm.cost.usd"] = call.cost_usd
        if call.prompt is not None:
            attrs["llm.prompt"] = call.prompt
        if call.completion is not None:
            attrs["llm.completion"] = call.completion

        span = self._tracer.start_span(
            f"{call.operation} {call.model}",
            kind=SpanKind.CLIENT,
            start_time=call.started_at_ns,
            attributes=attrs,
        )
        if call.error is not None:
            span.record_exception(call.error)
            span.set_status(Status(StatusCode.ERROR, type(call.error).__name__))
        span.end(end_time=call.ended_at_ns)


class OTelMetricsSink:
    """Duration/token histograms (GenAI conventions), cost and error counters, in-flight gauge."""

    def __init__(self, meter_provider: metrics.MeterProvider | None = None) -> None:
        meter = metrics.get_meter("llmobs", meter_provider=meter_provider)
        self._duration = meter.create_histogram(
            "gen_ai.client.operation.duration",
            unit="s",
            description="Duration of LLM client operations",
            explicit_bucket_boundaries_advisory=list(DURATION_BUCKETS),
        )
        self._tokens = meter.create_histogram(
            "gen_ai.client.token.usage",
            unit="{token}",
            description="Tokens used per LLM call, by token type",
            explicit_bucket_boundaries_advisory=list(TOKEN_BUCKETS),
        )
        self._cost = meter.create_counter(
            "llm.client.cost", unit="USD", description="Estimated cost of LLM calls"
        )
        self._errors = meter.create_counter(
            "llm.client.errors", unit="{error}", description="Failed LLM calls by error type"
        )
        self._in_flight = meter.create_up_down_counter(
            "llm.client.in_flight", unit="{call}", description="LLM calls currently running"
        )

    def notify(self, event: Event) -> None:
        call = event.call
        base = {
            "gen_ai.provider.name": call.provider,
            "gen_ai.request.model": call.model,
        }
        if isinstance(event, CallStarted):
            self._in_flight.add(1, base)
            return
        self._in_flight.add(-1, base)
        attrs = common_attributes(call)
        self._duration.record(call.duration_s, attrs)
        if call.usage is not None:
            self._tokens.record(call.usage.input_tokens, {**attrs, "gen_ai.token.type": "input"})
            self._tokens.record(call.usage.output_tokens, {**attrs, "gen_ai.token.type": "output"})
        if call.cost_usd is not None:
            self._cost.add(call.cost_usd, attrs)
        if call.failed:
            self._errors.add(1, attrs)
