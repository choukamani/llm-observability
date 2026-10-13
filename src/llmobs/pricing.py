"""Price table loaded from TOML (USD per million tokens), with longest-prefix model matching."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

from llmobs.model import TokenUsage

_PER_MILLION = 1_000_000
_MAX_CACHED_MODELS = 1_024


@dataclass(frozen=True, slots=True)
class ModelPrice:
    input_per_million: float
    output_per_million: float

    def cost(self, usage: TokenUsage) -> float:
        return (
            usage.input_tokens * self.input_per_million
            + usage.output_tokens * self.output_per_million
        ) / _PER_MILLION


class PriceTable:
    """Resolves `provider/model` to a price.

    Matching order: exact key, then the longest key that is a prefix of the model
    (so `openai/gpt-4o-mini-2024-07-18` resolves to `openai/gpt-4o-mini`), then a
    `provider/*` wildcard. Unknown models resolve to `None`: no cost is reported
    rather than a wrong one.
    """

    def __init__(self, prices: dict[str, ModelPrice], as_of: str | None = None) -> None:
        self._prices = prices
        self._prefixes = sorted(prices, key=len, reverse=True)
        self._resolved: dict[str, ModelPrice | None] = {}
        self.as_of = as_of

    @classmethod
    def from_toml(cls, path: str | Path) -> PriceTable:
        return cls._from_mapping(tomllib.loads(Path(path).read_text(encoding="utf-8")))

    @classmethod
    def default(cls) -> PriceTable:
        text = resources.files("llmobs").joinpath("pricing.toml").read_text(encoding="utf-8")
        return cls._from_mapping(tomllib.loads(text))

    @classmethod
    def _from_mapping(cls, data: dict[str, Any]) -> PriceTable:
        prices = {
            key: ModelPrice(float(entry["input"]), float(entry["output"]))
            for key, entry in data.get("models", {}).items()
        }
        as_of = data.get("meta", {}).get("as_of")
        return cls(prices, as_of=str(as_of) if as_of is not None else None)

    def lookup(self, provider: str, model: str) -> ModelPrice | None:
        key = f"{provider}/{model}"
        try:
            return self._resolved[key]
        except KeyError:
            if len(self._resolved) >= _MAX_CACHED_MODELS:
                self._resolved.clear()
            price = self._resolved[key] = self._resolve(provider, key)
            return price

    def _resolve(self, provider: str, key: str) -> ModelPrice | None:
        if key in self._prices:
            return self._prices[key]
        for prefix in self._prefixes:
            if not prefix.endswith("/*") and key.startswith(prefix):
                return self._prices[prefix]
        return self._prices.get(f"{provider}/*")
