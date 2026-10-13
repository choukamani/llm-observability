"""End-to-end: HTTP request → instrumented client → chain → OpenTelemetry SDK (global providers)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from opentelemetry import metrics, trace

from demo_app.main import create_app
from llmobs.clients import FakeChatClient
from tests.conftest import Telemetry

pytestmark = pytest.mark.integration


@pytest.fixture
def global_telemetry(telemetry: Telemetry, monkeypatch: pytest.MonkeyPatch) -> Telemetry:
    # The demo uses the global providers, as a real application would.
    monkeypatch.setattr(
        trace, "get_tracer", lambda *a, **k: telemetry.tracer_provider.get_tracer("t")
    )
    monkeypatch.setattr(
        metrics, "get_meter", lambda *a, **k: telemetry.meter_provider.get_meter("m")
    )
    return telemetry


@pytest.fixture
def client(global_telemetry: Telemetry) -> Iterator[TestClient]:
    with TestClient(create_app(fail_ratio=0.0, seed=1)) as test_client:
        yield test_client


def test_chat_request_produces_tenant_labelled_span(
    client: TestClient, global_telemetry: Telemetry
) -> None:
    response = client.post(
        "/v1/chat",
        json={"prompt": "summarize this", "model": "fake-large", "feature": "summarize"},
        headers={"x-tenant": "acme"},
    )
    assert response.status_code == 200
    assert response.json()["model"] == "fake-large"
    span = global_telemetry.finished_spans()[0]
    attrs = dict(span.attributes or {})
    assert attrs["llm.tenant"] == "acme"
    assert attrs["llm.feature"] == "summarize"
    output_tokens = attrs["gen_ai.usage.output_tokens"]
    assert isinstance(output_tokens, int)
    assert output_tokens > 0
    assert global_telemetry.counter_total("llm.client.cost") > 0


def test_unknown_model_is_rejected_without_llm_call(
    client: TestClient, global_telemetry: Telemetry
) -> None:
    response = client.post("/v1/chat", json={"prompt": "x", "model": "gpt-9"})
    assert response.status_code == 422
    assert global_telemetry.finished_spans() == []


@pytest.mark.parametrize(("ratio_kwarg", "status"), [("rate", 429), ("timeout", 504)])
def test_llm_failures_map_to_http_errors(
    global_telemetry: Telemetry, monkeypatch: pytest.MonkeyPatch, ratio_kwarg: str, status: int
) -> None:
    original = FakeChatClient

    def failing(**kwargs: float) -> object:
        kwargs = {**kwargs, "base_latency_s": 0}
        if ratio_kwarg == "rate":
            kwargs["rate_limit_ratio"] = 1.0
        else:
            kwargs["timeout_ratio"] = 1.0
        return original(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("demo_app.main.FakeChatClient", failing)
    with TestClient(create_app(fail_ratio=0.0, seed=1)) as test_client:
        response = test_client.post("/v1/chat", json={"prompt": "x"}, headers={"x-tenant": "a"})
    assert response.status_code == status
    assert global_telemetry.counter_total("llm.client.errors") == 1


def test_healthz(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}
