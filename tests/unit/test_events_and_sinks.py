from __future__ import annotations

import json
import logging

import pytest

from llmobs.events import CallFinished, CallStarted, Event, EventBus
from llmobs.model import CallStatus, ErrorCategory, LLMCall, TokenUsage
from llmobs.sinks import BudgetAlertSink, BudgetExceeded, LoggingSink
from tests.conftest import RecordingSubscriber


class Exploding:
    def notify(self, event: Event) -> None:
        raise RuntimeError("sink down")


def test_bus_delivers_in_subscription_order() -> None:
    bus = EventBus()
    first, second = RecordingSubscriber(), RecordingSubscriber()
    bus.subscribe(first)
    bus.subscribe(second)
    event = CallStarted(LLMCall("p", "m"))
    bus.publish(event)
    assert first.events == [event]
    assert second.events == [event]
    assert bus.subscribers == (first, second)


def test_failing_subscriber_is_isolated(caplog: pytest.LogCaptureFixture) -> None:
    bus = EventBus()
    healthy = RecordingSubscriber()
    bus.subscribe(Exploding())
    bus.subscribe(healthy)
    bus.publish(CallStarted(LLMCall("p", "m")))
    assert len(healthy.events) == 1
    assert "subscriber" in caplog.text


def test_unsubscribe() -> None:
    bus = EventBus()
    sub = RecordingSubscriber()
    bus.subscribe(sub)
    bus.unsubscribe(sub)
    bus.publish(CallStarted(LLMCall("p", "m")))
    assert sub.events == []


def test_logging_sink_writes_one_json_line(caplog: pytest.LogCaptureFixture) -> None:
    call = LLMCall("openai", "gpt-4o", usage=TokenUsage(1, 2), cost_usd=0.1)
    call.attributes["tenant"] = "acme"
    caplog.set_level(logging.INFO, logger="llmobs.calls")
    sink = LoggingSink()
    sink.notify(CallStarted(call))  # ignored
    sink.notify(CallFinished(call))
    assert len(caplog.records) == 1
    record = json.loads(caplog.records[0].getMessage())
    assert record["tenant"] == "acme"
    assert record["input_tokens"] == 1
    assert record["status"] == "ok"


def test_logging_sink_warns_on_failure(caplog: pytest.LogCaptureFixture) -> None:
    call = LLMCall("p", "m", status=CallStatus.ERROR, error_category=ErrorCategory.RATE_LIMIT)
    LoggingSink().notify(CallFinished(call))
    assert caplog.records[0].levelno == logging.WARNING
    assert json.loads(caplog.records[0].getMessage())["error_type"] == "rate_limit"


def _finished(tenant: str | None, cost: float | None) -> CallFinished:
    call = LLMCall("p", "m", cost_usd=cost)
    if tenant is not None:
        call.attributes["tenant"] = tenant
    return CallFinished(call)


def test_budget_alerts_once_when_crossed() -> None:
    alerts: list[BudgetExceeded] = []
    sink = BudgetAlertSink({"acme": 1.0}, alerts.append)
    sink.notify(_finished("acme", 0.6))
    assert alerts == []
    sink.notify(_finished("acme", 0.6))
    sink.notify(_finished("acme", 0.6))
    assert len(alerts) == 1
    assert alerts[0].key == "acme"
    assert alerts[0].spent_usd == pytest.approx(1.2)
    assert sink.spent("acme") == pytest.approx(1.8)


def test_budget_ignores_unbudgeted_or_uncosted_calls() -> None:
    alerts: list[BudgetExceeded] = []
    sink = BudgetAlertSink({"acme": 0.0}, alerts.append)
    sink.notify(_finished("other", 5.0))
    sink.notify(_finished(None, 5.0))
    sink.notify(_finished("acme", None))
    sink.notify(CallStarted(LLMCall("p", "m")))
    assert alerts == []
