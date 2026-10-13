"""Non-OpenTelemetry sinks: structured logging and per-key budget alerts."""

from __future__ import annotations

import json
import logging
import threading
from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from llmobs.events import CallFinished, Event


class LoggingSink:
    """One JSON log line per finished call (WARNING level for failures)."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger("llmobs.calls")

    def notify(self, event: Event) -> None:
        if not isinstance(event, CallFinished):
            return
        call = event.call
        record = {
            "call_id": call.call_id,
            "provider": call.provider,
            "model": call.model,
            "operation": call.operation,
            "status": call.status.value,
            "duration_ms": round(call.duration_s * 1000, 3),
            "input_tokens": call.usage.input_tokens if call.usage else None,
            "output_tokens": call.usage.output_tokens if call.usage else None,
            "tokens_estimated": call.usage.estimated if call.usage else None,
            "cost_usd": call.cost_usd,
            "error_type": call.error_category.value if call.error_category else None,
            **call.attributes,
        }
        level = logging.WARNING if call.failed else logging.INFO
        self._logger.log(level, json.dumps(record, sort_keys=True))


@dataclass(frozen=True, slots=True)
class BudgetExceeded:
    key: str
    budget_usd: float
    spent_usd: float


class BudgetAlertSink:
    """Accumulates estimated cost per attribute value (e.g. per tenant) and alerts once on overrun.

    Totals live in memory for the lifetime of the process: this is an early
    warning, not an accounting system (see the README's known limitations).
    """

    def __init__(
        self,
        budgets_usd: Mapping[str, float],
        on_exceeded: Callable[[BudgetExceeded], None],
        *,
        key_attribute: str = "tenant",
    ) -> None:
        self._budgets = dict(budgets_usd)
        self._on_exceeded = on_exceeded
        self._key_attribute = key_attribute
        self._spent: defaultdict[str, float] = defaultdict(float)
        self._alerted: set[str] = set()
        self._lock = threading.Lock()

    def notify(self, event: Event) -> None:
        if not isinstance(event, CallFinished) or event.call.cost_usd is None:
            return
        key = event.call.attributes.get(self._key_attribute)
        if key is None or key not in self._budgets:
            return
        with self._lock:
            self._spent[key] += event.call.cost_usd
            spent = self._spent[key]
            should_alert = spent > self._budgets[key] and key not in self._alerted
            if should_alert:
                self._alerted.add(key)
        if should_alert:
            self._on_exceeded(BudgetExceeded(key, self._budgets[key], spent))

    def spent(self, key: str) -> float:
        with self._lock:
            return self._spent[key]
