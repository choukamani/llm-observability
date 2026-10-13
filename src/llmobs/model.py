"""Core data model: one mutable record per LLM call, enriched by the processing chain."""

from __future__ import annotations

import enum
import random
from dataclasses import dataclass, field
from typing import Any


class CallStatus(enum.StrEnum):
    OK = "ok"
    ERROR = "error"


class ErrorCategory(enum.StrEnum):
    """Provider-agnostic error taxonomy, used as the `error.type` attribute."""

    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    AUTHENTICATION = "authentication"
    INVALID_REQUEST = "invalid_request"
    PROVIDER = "provider_error"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int
    estimated: bool = False
    """True when the provider did not report usage and tokens were estimated locally."""

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(slots=True)
class LLMCall:
    """Everything known about a single LLM call.

    Created by the `Instrumentor` when the call starts, completed when it ends,
    then enriched in place by each `Processor` of the chain before being
    published to subscribers.
    """

    provider: str
    model: str
    """Requested model."""
    operation: str = "chat"
    call_id: str = field(default_factory=lambda: f"{random.getrandbits(64):016x}")
    """Correlation id for logs. Not security-sensitive, so a fast non-crypto RNG is enough."""
    attributes: dict[str, str] = field(default_factory=dict)
    prompt: str | None = None
    completion: str | None = None
    response: Any = None
    response_model: str | None = None
    """Model reported by the provider (often a dated snapshot of `model`)."""
    usage: TokenUsage | None = None
    cost_usd: float | None = None
    status: CallStatus = CallStatus.OK
    error: BaseException | None = None
    error_category: ErrorCategory | None = None
    started_at_ns: int = 0
    ended_at_ns: int = 0
    duration_s: float = 0.0

    @property
    def failed(self) -> bool:
        return self.status is CallStatus.ERROR
