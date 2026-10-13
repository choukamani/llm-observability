"""Adapters normalising heterogeneous provider responses into `TokenUsage` + completion text.

Adapters are duck-typed on purpose: they read attributes *or* dict keys, so the
library works with the official SDK objects, raw JSON payloads and test doubles
without importing any provider SDK.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from llmobs.model import TokenUsage


@dataclass(frozen=True, slots=True)
class Normalized:
    usage: TokenUsage | None
    completion: str | None
    model: str | None = None


class ProviderAdapter(Protocol):
    def normalize(self, response: Any) -> Normalized: ...


_MISSING = object()


def field(obj: Any, *path: str | int) -> Any:
    """Walk `path` through attributes, dict keys or list indexes; None if any step is missing."""
    current = obj
    for step in path:
        if current is None:
            return None
        if isinstance(step, int):
            try:
                current = current[step]
            except (IndexError, KeyError, TypeError):
                return None
            continue
        if isinstance(current, dict):
            current = current.get(step)
        else:
            value = getattr(current, step, _MISSING)
            current = None if value is _MISSING else value
    return current


def as_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def usage_from(input_tokens: Any, output_tokens: Any) -> TokenUsage | None:
    inp, out = as_int(input_tokens), as_int(output_tokens)
    if inp is None and out is None:
        return None
    return TokenUsage(input_tokens=inp or 0, output_tokens=out or 0)


def as_text(value: Any) -> str | None:
    return value if isinstance(value, str) else None
