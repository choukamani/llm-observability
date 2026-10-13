"""Request-scoped attributes (tenant, feature, ...) propagated with `contextvars`.

They work across threads started with `contextvars.copy_context()` and across
`await` points, so a FastAPI middleware can set the tenant once per request.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from types import MappingProxyType
from typing import Final

_EMPTY: Final[MappingProxyType[str, str]] = MappingProxyType({})
_attributes: ContextVar[MappingProxyType[str, str]] = ContextVar(
    "llmobs_attributes", default=_EMPTY
)


@contextmanager
def attributes(**values: str) -> Iterator[None]:
    """Attach attributes to every LLM call made inside the block. Nested blocks merge."""
    merged = MappingProxyType({**_attributes.get(), **values})
    token = _attributes.set(merged)
    try:
        yield
    finally:
        _attributes.reset(token)


def current_attributes() -> dict[str, str]:
    return dict(_attributes.get())
