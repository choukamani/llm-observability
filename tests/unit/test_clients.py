from __future__ import annotations

import pytest

from llmobs import Instrumentor
from llmobs.clients import (
    FakeChatClient,
    InstrumentedChatClient,
    ProviderUnavailableError,
    RateLimitError,
)
from llmobs.events import CallFinished
from llmobs.model import ErrorCategory
from tests.conftest import RecordingSubscriber


async def test_fake_client_is_deterministic_with_seed() -> None:
    a = FakeChatClient(seed=7, base_latency_s=0, per_token_latency_s=0)
    b = FakeChatClient(seed=7, base_latency_s=0, per_token_latency_s=0)
    results_a = [await a.complete("hello", model="fake-small") for _ in range(5)]
    results_b = [await b.complete("hello", model="fake-small") for _ in range(5)]
    assert results_a == results_b


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"rate_limit_ratio": 1.0}, RateLimitError),
        ({"unavailable_ratio": 1.0}, ProviderUnavailableError),
        ({"timeout_ratio": 1.0}, TimeoutError),
    ],
)
async def test_fake_client_failure_modes(kwargs: dict[str, float], error: type[Exception]) -> None:
    client = FakeChatClient(seed=1, base_latency_s=0, **kwargs)
    with pytest.raises(error):
        await client.complete("x", model="fake-small")


async def test_instrumented_client_is_transparent(
    instrumentor: Instrumentor, recorder: RecordingSubscriber
) -> None:
    inner = FakeChatClient(seed=3, base_latency_s=0, per_token_latency_s=0)
    client = InstrumentedChatClient(inner, instrumentor)
    completion = await client.complete("bonjour", model="fake-large")
    assert client.provider == "fake"
    call = next(e.call for e in recorder.events if isinstance(e, CallFinished))
    assert call.usage is not None
    assert call.usage.output_tokens == completion.output_tokens
    assert not call.usage.estimated
    assert call.cost_usd is not None


async def test_instrumented_client_classifies_failures(
    instrumentor: Instrumentor, recorder: RecordingSubscriber
) -> None:
    client = InstrumentedChatClient(
        FakeChatClient(seed=1, base_latency_s=0, unavailable_ratio=1.0), instrumentor
    )
    with pytest.raises(ProviderUnavailableError):
        await client.complete("x", model="fake-small")
    call = next(e.call for e in recorder.events if isinstance(e, CallFinished))
    assert call.error_category is ErrorCategory.PROVIDER
