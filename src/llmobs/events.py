"""Observer: the instrumentor publishes call events, sinks subscribe to them.

A failing subscriber is logged and skipped: observability must never break
the application call it observes.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Protocol

from llmobs.model import LLMCall

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CallStarted:
    call: LLMCall


@dataclass(frozen=True, slots=True)
class CallFinished:
    call: LLMCall


type Event = CallStarted | CallFinished


class Subscriber(Protocol):
    def notify(self, event: Event) -> None: ...


class EventBus:
    def __init__(self) -> None:
        self._subscribers: tuple[Subscriber, ...] = ()
        self._lock = threading.Lock()

    def subscribe(self, subscriber: Subscriber) -> None:
        with self._lock:
            self._subscribers = (*self._subscribers, subscriber)

    def unsubscribe(self, subscriber: Subscriber) -> None:
        with self._lock:
            self._subscribers = tuple(s for s in self._subscribers if s is not subscriber)

    @property
    def subscribers(self) -> tuple[Subscriber, ...]:
        return self._subscribers

    def publish(self, event: Event) -> None:
        # Copy-on-write tuple: iteration needs no lock and never sees a half-updated list.
        for subscriber in self._subscribers:
            try:
                subscriber.notify(event)
            except Exception:
                logger.exception("llmobs subscriber %r failed", subscriber)
