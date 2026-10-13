"""The built-in handlers of the processing chain, in their default order."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Final

from llmobs.model import ErrorCategory, LLMCall, TokenUsage
from llmobs.pipeline.base import Processor
from llmobs.pricing import PriceTable
from llmobs.providers import DEFAULT_ADAPTERS, GenericAdapter, ProviderAdapter


class ResponseNormalizer(Processor):
    """Extracts usage and completion text from the raw provider response."""

    def __init__(self, adapters: Mapping[str, ProviderAdapter] | None = None) -> None:
        super().__init__()
        self._adapters = dict(DEFAULT_ADAPTERS if adapters is None else adapters)
        self._fallback = GenericAdapter()

    def applies_to(self, call: LLMCall) -> bool:
        return call.response is not None

    def process(self, call: LLMCall) -> None:
        normalized = self._adapters.get(call.provider, self._fallback).normalize(call.response)
        if call.usage is None:
            call.usage = normalized.usage
        if call.completion is None:
            call.completion = normalized.completion
        if normalized.model:
            call.response_model = normalized.model


class TokenEstimator(Processor):
    """Estimates tokens from text length when the provider reported none.

    Uses a characters-per-token ratio (about 4 for English with BPE tokenizers).
    The result is flagged `estimated=True` so dashboards can tell it apart.
    """

    def __init__(self, chars_per_token: float = 4.0) -> None:
        super().__init__()
        if chars_per_token <= 0:
            raise ValueError("chars_per_token must be positive")
        self._ratio = chars_per_token

    def applies_to(self, call: LLMCall) -> bool:
        return call.usage is None and (call.prompt is not None or call.completion is not None)

    def _estimate(self, text: str | None) -> int:
        return math.ceil(len(text) / self._ratio) if text else 0

    def process(self, call: LLMCall) -> None:
        call.usage = TokenUsage(
            input_tokens=self._estimate(call.prompt),
            output_tokens=self._estimate(call.completion),
            estimated=True,
        )


class CostEstimator(Processor):
    def __init__(self, prices: PriceTable | None = None) -> None:
        super().__init__()
        self._prices = prices or PriceTable.default()

    def applies_to(self, call: LLMCall) -> bool:
        return call.usage is not None

    def process(self, call: LLMCall) -> None:
        assert call.usage is not None  # noqa: S101 - guaranteed by applies_to
        price = self._prices.lookup(call.provider, call.response_model or call.model)
        if price is not None:
            call.cost_usd = price.cost(call.usage)


class ErrorClassifier(Processor):
    """Maps any exception to an `ErrorCategory` using its HTTP status or its class name.

    Works with the OpenAI/Mistral SDK exceptions and `httpx.HTTPStatusError`
    without importing them.
    """

    _BY_NAME: Final = (
        ("ratelimit", ErrorCategory.RATE_LIMIT),
        ("timeout", ErrorCategory.TIMEOUT),
        ("authentication", ErrorCategory.AUTHENTICATION),
        ("permissiondenied", ErrorCategory.AUTHENTICATION),
        ("badrequest", ErrorCategory.INVALID_REQUEST),
        ("unprocessable", ErrorCategory.INVALID_REQUEST),
    )

    def applies_to(self, call: LLMCall) -> bool:
        return call.error is not None and call.error_category is None

    def process(self, call: LLMCall) -> None:
        assert call.error is not None  # noqa: S101 - guaranteed by applies_to
        call.error_category = self.classify(call.error)

    @classmethod
    def classify(cls, error: BaseException) -> ErrorCategory:
        if isinstance(error, TimeoutError):
            return ErrorCategory.TIMEOUT
        status = cls._status_code(error)
        if status is not None:
            return cls._from_status(status)
        name = type(error).__name__.lower()
        for needle, category in cls._BY_NAME:
            if needle in name:
                return category
        return ErrorCategory.UNKNOWN

    @staticmethod
    def _status_code(error: BaseException) -> int | None:
        status = getattr(error, "status_code", None)
        if status is None:
            status = getattr(getattr(error, "response", None), "status_code", None)
        return status if isinstance(status, int) else None

    @staticmethod
    def _from_status(status: int) -> ErrorCategory:
        if status == 429:  # noqa: PLR2004
            return ErrorCategory.RATE_LIMIT
        if status in (401, 403):
            return ErrorCategory.AUTHENTICATION
        if status in (408, 504):
            return ErrorCategory.TIMEOUT
        if status >= 500:  # noqa: PLR2004
            return ErrorCategory.PROVIDER
        if status >= 400:  # noqa: PLR2004
            return ErrorCategory.INVALID_REQUEST
        return ErrorCategory.UNKNOWN


class ContentPolicy(Processor):
    """Last link: decides what prompt/completion text leaves the process.

    By default content is dropped entirely (prompts often contain personal
    data). With `capture=True`, emails, phone numbers and card-like numbers are
    redacted and the text is truncated.
    """

    _PATTERNS: Final = (
        (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[EMAIL]"),
        (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "[CARD]"),
        (re.compile(r"(?<!\w)\+?\d[\d .-]{7,}\d\b"), "[PHONE]"),
    )

    def __init__(self, *, capture: bool = False, max_chars: int = 1_000) -> None:
        super().__init__()
        self._capture = capture
        self._max_chars = max_chars

    def process(self, call: LLMCall) -> None:
        call.prompt = self._sanitize(call.prompt)
        call.completion = self._sanitize(call.completion)

    def _sanitize(self, text: str | None) -> str | None:
        if text is None or not self._capture:
            return None
        return self.redact(text)[: self._max_chars]

    @classmethod
    def redact(cls, text: str) -> str:
        for pattern, replacement in cls._PATTERNS:
            text = pattern.sub(replacement, text)
        return text
