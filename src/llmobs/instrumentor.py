"""Facade tying together the processing chain and the event bus.

Three ways to instrument a call, from most to least explicit:

* ``with obs.track("openai", "gpt-4o-mini", prompt=p) as call: call.response = ...``
* ``@obs.observe("openai", "gpt-4o-mini", prompt_arg="prompt")`` on a sync or async function
* ``InstrumentedChatClient(client, obs)`` wrapping a whole client (see `llmobs.clients`)
"""

from __future__ import annotations

import functools
import inspect
import logging
import time
from collections.abc import Awaitable, Callable, Iterable, Iterator
from contextlib import contextmanager
from typing import Any, cast

from opentelemetry import metrics, trace

from llmobs.context import current_attributes
from llmobs.events import CallFinished, CallStarted, EventBus, Subscriber
from llmobs.model import CallStatus, LLMCall
from llmobs.pipeline import (
    ContentPolicy,
    CostEstimator,
    ErrorClassifier,
    Processor,
    ResponseNormalizer,
    TokenEstimator,
    build_chain,
)
from llmobs.pricing import PriceTable
from llmobs.sinks import OTelMetricsSink, OTelSpanSink

logger = logging.getLogger(__name__)


def default_chain(
    *, prices: PriceTable | None = None, capture_content: bool = False
) -> Processor | None:
    """The default processing order: normalise, estimate tokens, price, classify, sanitise."""
    return build_chain(
        [
            ResponseNormalizer(),
            TokenEstimator(),
            CostEstimator(prices),
            ErrorClassifier(),
            ContentPolicy(capture=capture_content),
        ]
    )


class Instrumentor:
    def __init__(self, chain: Processor | None, bus: EventBus) -> None:
        self._chain = chain
        self.bus = bus

    @classmethod
    def create(
        cls,
        *,
        tracer_provider: trace.TracerProvider | None = None,
        meter_provider: metrics.MeterProvider | None = None,
        prices: PriceTable | None = None,
        capture_content: bool = False,
        subscribers: Iterable[Subscriber] = (),
    ) -> Instrumentor:
        """Factory with the default chain and OpenTelemetry sinks.

        Providers default to the global OpenTelemetry ones, so the library
        follows whatever the application (or `llmobs.otel.configure`) set up.
        """
        chain = default_chain(prices=prices, capture_content=capture_content)
        bus = EventBus()
        bus.subscribe(OTelSpanSink(tracer_provider))
        bus.subscribe(OTelMetricsSink(meter_provider))
        for subscriber in subscribers:
            bus.subscribe(subscriber)
        return cls(chain, bus)

    @contextmanager
    def track(
        self,
        provider: str,
        model: str,
        *,
        operation: str = "chat",
        prompt: str | None = None,
    ) -> Iterator[LLMCall]:
        """Measure the enclosed block as one LLM call; set `call.response` inside it."""
        call = LLMCall(
            provider=provider,
            model=model,
            operation=operation,
            prompt=prompt,
            attributes=current_attributes(),
        )
        self.bus.publish(CallStarted(call))
        call.started_at_ns = time.time_ns()
        started = time.perf_counter()
        try:
            yield call
        except BaseException as exc:
            call.status = CallStatus.ERROR
            call.error = exc
            raise
        finally:
            call.duration_s = time.perf_counter() - started
            call.ended_at_ns = call.started_at_ns + int(call.duration_s * 1e9)
            self._finish(call)

    def _finish(self, call: LLMCall) -> None:
        try:
            if self._chain is not None:
                self._chain.handle(call)
        except Exception:
            logger.exception("llmobs processing chain failed for call %s", call.call_id)
        self.bus.publish(CallFinished(call))

    def observe[**P, R](
        self,
        provider: str,
        model: str,
        *,
        operation: str = "chat",
        prompt_arg: str | None = None,
    ) -> Callable[[Callable[P, R]], Callable[P, R]]:
        """Decorator: the wrapped function's return value is treated as the provider response."""

        def decorator(func: Callable[P, R]) -> Callable[P, R]:
            signature = inspect.signature(func)

            def prompt_of(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str | None:
                if prompt_arg is None:
                    return None
                bound = signature.bind_partial(*args, **kwargs)
                value = bound.arguments.get(prompt_arg)
                return value if isinstance(value, str) else None

            if inspect.iscoroutinefunction(func):
                async_func = cast(Callable[P, Awaitable[Any]], func)

                @functools.wraps(func)
                async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
                    with self.track(
                        provider, model, operation=operation, prompt=prompt_of(args, kwargs)
                    ) as call:
                        result = await async_func(*args, **kwargs)
                        call.response = result
                        return result

                return cast(Callable[P, R], async_wrapper)

            @functools.wraps(func)
            def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                with self.track(
                    provider, model, operation=operation, prompt=prompt_of(args, kwargs)
                ) as call:
                    result = func(*args, **kwargs)
                    call.response = result
                    return result

            return wrapper

        return decorator
