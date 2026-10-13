"""Measure the per-call overhead added by llmobs.

The instrumented function itself does no work (it returns a canned provider
response), so the measured time is the instrumentation cost alone: event
publishing, the processing chain, span creation and metric recording.

    uv run python benchmarks/overhead.py --iterations 20000
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult

from llmobs import Instrumentor, attributes
from llmobs.events import EventBus
from llmobs.instrumentor import default_chain

RESPONSE: dict[str, Any] = {
    "model": "gpt-4o-mini-2024-07-18",
    "usage": {"prompt_tokens": 120, "completion_tokens": 80},
    "choices": [{"message": {"content": "ok"}}],
}


class DiscardingExporter(SpanExporter):
    """Stands in for the network: measures SDK cost without measuring a collector."""

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:  # noqa: ARG002
        return SpanExportResult.SUCCESS


def bare() -> dict[str, Any]:
    return RESPONSE


def make_instrumented(obs: Instrumentor) -> Callable[[], dict[str, Any]]:
    @obs.observe("openai", "gpt-4o-mini")
    def call() -> dict[str, Any]:
        return RESPONSE

    return call


def sample(func: Callable[[], object], iterations: int, warmup: int) -> list[float]:
    for _ in range(warmup):
        func()
    timings: list[float] = []
    clock = time.perf_counter_ns
    with attributes(tenant="bench", feature="overhead"):
        for _ in range(iterations):
            start = clock()
            func()
            timings.append((clock() - start) / 1_000)  # microseconds
    return timings


def percentile(values: list[float], pct: float) -> float:
    return statistics.quantiles(values, n=100, method="inclusive")[int(pct) - 1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=20_000)
    parser.add_argument("--warmup", type=int, default=2_000)
    parser.add_argument("--out", type=Path, default=Path("benchmarks/results/overhead.json"))
    args = parser.parse_args()

    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(BatchSpanProcessor(DiscardingExporter()))
    meter_provider = MeterProvider(metric_readers=[InMemoryMetricReader()])

    scenarios: dict[str, Callable[[], object]] = {
        "no instrumentation": bare,
        "llmobs, chain only (no sinks)": make_instrumented(
            Instrumentor(default_chain(), EventBus())
        ),
        "llmobs + OTel SDK (spans + metrics)": make_instrumented(
            Instrumentor.create(tracer_provider=tracer_provider, meter_provider=meter_provider)
        ),
    }

    results = []
    for name, func in scenarios.items():
        timings = sample(func, args.iterations, args.warmup)
        results.append(
            {
                "scenario": name,
                "p50_us": round(percentile(timings, 50), 2),
                "p95_us": round(percentile(timings, 95), 2),
                "p99_us": round(percentile(timings, 99), 2),
                "mean_us": round(statistics.fmean(timings), 2),
            }
        )
    tracer_provider.shutdown()
    meter_provider.shutdown()

    environment = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "processor": platform.processor(),
        "iterations": args.iterations,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps({"environment": environment, "results": results}, indent=2), encoding="utf-8"
    )

    print(f"Environment: {environment}\n")
    print("| Scenario | p50 (µs) | p95 (µs) | p99 (µs) | mean (µs) |")
    print("|---|---:|---:|---:|---:|")
    for r in results:
        print(
            f"| {r['scenario']} | {r['p50_us']} | {r['p95_us']} | {r['p99_us']} | {r['mean_us']} |"
        )


if __name__ == "__main__":
    main()
