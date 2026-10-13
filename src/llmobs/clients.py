"""A minimal chat-client interface, an instrumenting Decorator for it, and a fake client.

`InstrumentedChatClient` is the object form of the Decorator pattern: same
interface as the client it wraps, observability added transparently.
`FakeChatClient` lets the demo, tests and benchmarks run without any API key.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from typing import Protocol

from llmobs.instrumentor import Instrumentor


@dataclass(frozen=True, slots=True)
class Completion:
    text: str
    model: str
    input_tokens: int
    output_tokens: int


class ChatClient(Protocol):
    provider: str

    async def complete(self, prompt: str, *, model: str) -> Completion: ...


class InstrumentedChatClient:
    def __init__(self, inner: ChatClient, instrumentor: Instrumentor) -> None:
        self._inner = inner
        self._obs = instrumentor
        self.provider = inner.provider

    async def complete(self, prompt: str, *, model: str) -> Completion:
        with self._obs.track(self.provider, model, prompt=prompt) as call:
            completion = await self._inner.complete(prompt, model=model)
            call.response = completion
            return completion


class RateLimitError(Exception):
    status_code = 429


class ProviderUnavailableError(Exception):
    status_code = 503


class FakeChatClient:
    """Deterministic (seeded) simulation of an LLM API: latency, token counts and failures.

    Latency grows with output length, as with real autoregressive decoding.
    """

    provider = "fake"

    def __init__(
        self,
        *,
        seed: int | None = None,
        base_latency_s: float = 0.05,
        per_token_latency_s: float = 0.002,
        rate_limit_ratio: float = 0.0,
        unavailable_ratio: float = 0.0,
        timeout_ratio: float = 0.0,
    ) -> None:
        self._rng = random.Random(seed)  # noqa: S311 - simulation, not cryptography
        self._base = base_latency_s
        self._per_token = per_token_latency_s
        self._failures = (
            (rate_limit_ratio, RateLimitError("rate limit exceeded")),
            (unavailable_ratio, ProviderUnavailableError("upstream unavailable")),
            (timeout_ratio, TimeoutError("request timed out")),
        )

    async def complete(self, prompt: str, *, model: str) -> Completion:
        roll = self._rng.random()
        threshold = 0.0
        for ratio, error in self._failures:
            threshold += ratio
            if roll < threshold:
                await asyncio.sleep(self._base)
                raise error
        input_tokens = max(1, len(prompt) // 4)
        output_tokens = self._rng.randint(20, 400 if model.endswith("large") else 150)
        await asyncio.sleep(self._base + output_tokens * self._per_token)
        text = f"[{model}] simulated answer of {output_tokens} tokens"
        return Completion(text, model, input_tokens, output_tokens)
