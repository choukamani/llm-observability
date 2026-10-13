from __future__ import annotations

import asyncio
import threading

import pytest
from opentelemetry.trace import SpanKind, StatusCode

import llmobs
from llmobs import Instrumentor
from llmobs.events import CallFinished, CallStarted, EventBus
from llmobs.model import CallStatus, ErrorCategory, LLMCall
from llmobs.pipeline import Processor
from tests.conftest import RecordingSubscriber, Telemetry


def finished(recorder: RecordingSubscriber) -> list[LLMCall]:
    return [e.call for e in recorder.events if isinstance(e, CallFinished)]


def test_track_publishes_start_then_finish(
    instrumentor: Instrumentor, recorder: RecordingSubscriber
) -> None:
    with instrumentor.track("openai", "gpt-4o-mini", prompt="hi") as call:
        call.response = {"usage": {"prompt_tokens": 10, "completion_tokens": 5}}
    assert [type(e) for e in recorder.events] == [CallStarted, CallFinished]
    done = finished(recorder)[0]
    assert done.usage is not None
    assert done.usage.total_tokens == 15
    assert done.cost_usd is not None
    assert done.duration_s >= 0
    assert done.ended_at_ns >= done.started_at_ns
    assert done.prompt is None  # content is dropped by default


def test_track_records_errors_and_reraises(
    instrumentor: Instrumentor, recorder: RecordingSubscriber, telemetry: Telemetry
) -> None:
    with pytest.raises(TimeoutError), instrumentor.track("openai", "gpt-4o"):
        raise TimeoutError
    call = finished(recorder)[0]
    assert call.status is CallStatus.ERROR
    assert call.error_category is ErrorCategory.TIMEOUT
    span = telemetry.finished_spans()[0]
    assert span.status.status_code is StatusCode.ERROR
    assert span.attributes is not None
    assert span.attributes["error.type"] == "timeout"
    assert telemetry.counter_total("llm.client.errors") == 1


def test_span_follows_genai_conventions(instrumentor: Instrumentor, telemetry: Telemetry) -> None:
    with (
        llmobs.attributes(tenant="acme", feature="summarize"),
        instrumentor.track("openai", "gpt-4o-mini") as call,
    ):
        call.response = {
            "model": "gpt-4o-mini-2024-07-18",
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        }
    span = telemetry.finished_spans()[0]
    assert span.name == "chat gpt-4o-mini"
    assert span.kind is SpanKind.CLIENT
    attrs = dict(span.attributes or {})
    assert attrs["gen_ai.provider.name"] == "openai"
    assert attrs["gen_ai.request.model"] == "gpt-4o-mini"
    assert attrs["gen_ai.response.model"] == "gpt-4o-mini-2024-07-18"
    assert attrs["gen_ai.usage.input_tokens"] == 100
    assert attrs["gen_ai.usage.output_tokens"] == 50
    assert attrs["llm.tenant"] == "acme"
    assert attrs["llm.feature"] == "summarize"
    assert "llm.prompt" not in attrs


def test_captured_content_reaches_span_redacted(telemetry: Telemetry) -> None:
    obs = Instrumentor.create(
        tracer_provider=telemetry.tracer_provider,
        meter_provider=telemetry.meter_provider,
        capture_content=True,
    )
    with obs.track("fake", "fake-small", prompt="contact me at a@b.io") as call:
        call.response = "sure"
    attrs = dict(telemetry.finished_spans()[0].attributes or {})
    assert attrs["llm.prompt"] == "contact me at [EMAIL]"
    assert attrs["llm.completion"] == "sure"
    assert attrs["llm.usage.estimated"] is True


def test_metrics_recorded(instrumentor: Instrumentor, telemetry: Telemetry) -> None:
    for _ in range(3):
        with instrumentor.track("fake", "fake-small") as call:
            call.response = {"input_tokens": 10, "output_tokens": 20}
    durations = telemetry.metric_points("gen_ai.client.operation.duration")
    assert sum(p.count for p in durations) == 3  # type: ignore[attr-defined]
    tokens = telemetry.metric_points("gen_ai.client.token.usage")
    assert {p.attributes["gen_ai.token.type"] for p in tokens} == {"input", "output"}  # type: ignore[attr-defined]
    assert telemetry.counter_total("llm.client.cost") == pytest.approx(
        3 * (10 * 0.2 + 20 * 0.8) / 1e6
    )
    assert telemetry.counter_total("llm.client.in_flight") == 0


def test_broken_processor_never_breaks_the_call(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class Broken(Processor):
        def process(self, call: LLMCall) -> None:
            raise RuntimeError("bug in a processor")

    recorder = RecordingSubscriber()
    bus = EventBus()
    bus.subscribe(recorder)
    obs = Instrumentor(Broken(), bus)
    with obs.track("p", "m") as call:
        call.response = "ok"
    assert len(finished(recorder)) == 1
    assert "processing chain failed" in caplog.text


def test_instrumentor_without_chain() -> None:
    recorder = RecordingSubscriber()
    bus = EventBus()
    bus.subscribe(recorder)
    with Instrumentor(None, bus).track("p", "m"):
        pass
    assert finished(recorder)[0].usage is None


def test_observe_sync_function(instrumentor: Instrumentor, recorder: RecordingSubscriber) -> None:
    @instrumentor.observe("ollama", "llama3", prompt_arg="prompt")
    def ask(prompt: str, temperature: float = 0.0) -> dict[str, object]:
        return {"prompt_eval_count": 4, "eval_count": 8, "message": {"content": "pong"}}

    assert ask("ping")["eval_count"] == 8
    assert ask.__name__ == "ask"
    call = finished(recorder)[0]
    assert call.usage is not None
    assert call.usage.input_tokens == 4
    assert call.cost_usd == 0.0


async def test_observe_async_function(
    instrumentor: Instrumentor, recorder: RecordingSubscriber
) -> None:
    @instrumentor.observe("fake", "fake-small", prompt_arg="prompt")
    async def ask(prompt: str) -> str:
        await asyncio.sleep(0.01)
        return "answer text"

    assert await ask(prompt="question") == "answer text"
    call = finished(recorder)[0]
    assert call.duration_s >= 0.01
    assert call.usage is not None
    assert call.usage.estimated


async def test_observe_async_error(
    instrumentor: Instrumentor, recorder: RecordingSubscriber
) -> None:
    class RateLimitError(Exception):
        pass

    @instrumentor.observe("openai", "gpt-4o")
    async def ask() -> str:
        raise RateLimitError

    with pytest.raises(RateLimitError):
        await ask()
    assert finished(recorder)[0].error_category is ErrorCategory.RATE_LIMIT


def test_observe_ignores_non_string_prompt(
    instrumentor: Instrumentor, recorder: RecordingSubscriber
) -> None:
    @instrumentor.observe("fake", "fake-small", prompt_arg="messages")
    def ask(messages: list[str]) -> str:
        return "abcd"

    ask(["a" * 400])
    usage = finished(recorder)[0].usage
    assert usage is not None
    assert usage.input_tokens == 0  # the list was not mistaken for a prompt
    assert usage.output_tokens == 1


async def test_attributes_are_isolated_between_concurrent_tasks(
    instrumentor: Instrumentor, recorder: RecordingSubscriber
) -> None:
    async def run(tenant: str) -> None:
        with llmobs.attributes(tenant=tenant):
            await asyncio.sleep(0.01)
            with instrumentor.track("fake", "fake-small"):
                await asyncio.sleep(0.01)

    await asyncio.gather(*(run(t) for t in ("a", "b", "c")))
    assert sorted(c.attributes["tenant"] for c in finished(recorder)) == ["a", "b", "c"]


def test_nested_attributes_merge_and_restore() -> None:
    with llmobs.attributes(tenant="a"):
        with llmobs.attributes(feature="f"):
            assert llmobs.context.current_attributes() == {"tenant": "a", "feature": "f"}
        assert llmobs.context.current_attributes() == {"tenant": "a"}
    assert llmobs.context.current_attributes() == {}


def test_thread_safety_of_bus(instrumentor: Instrumentor, recorder: RecordingSubscriber) -> None:
    def work() -> None:
        for _ in range(50):
            with instrumentor.track("fake", "fake-small") as call:
                call.response = {"input_tokens": 1, "output_tokens": 1}

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(finished(recorder)) == 400
