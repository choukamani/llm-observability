"""Chain of Responsibility: each processor enriches the call, then hands it to the next.

Every handler decides by itself whether it applies (e.g. the token estimator
skips calls whose provider already reported usage), so the chain can be
re-ordered or extended without touching the existing handlers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from llmobs.model import LLMCall


class Processor(ABC):
    def __init__(self) -> None:
        self._next: Processor | None = None

    def set_next(self, processor: Processor) -> Processor:
        """Link `processor` after this one and return it, so links can be chained fluently."""
        self._next = processor
        return processor

    def handle(self, call: LLMCall) -> None:
        if self.applies_to(call):
            self.process(call)
        if self._next is not None:
            self._next.handle(call)

    def applies_to(self, call: LLMCall) -> bool:  # noqa: ARG002 - hook for subclasses
        return True

    @abstractmethod
    def process(self, call: LLMCall) -> None: ...


def build_chain(processors: Sequence[Processor]) -> Processor | None:
    """Link processors in order and return the head of the chain."""
    if not processors:
        return None
    head = processors[0]
    current = head
    for nxt in processors[1:]:
        current = current.set_next(nxt)
    return head
