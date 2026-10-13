"""llmobs: OpenTelemetry instrumentation for LLM calls."""

from llmobs.context import attributes
from llmobs.events import CallFinished, CallStarted, EventBus, Subscriber
from llmobs.instrumentor import Instrumentor
from llmobs.model import CallStatus, ErrorCategory, LLMCall, TokenUsage
from llmobs.pricing import ModelPrice, PriceTable

__all__ = [
    "CallFinished",
    "CallStarted",
    "CallStatus",
    "ErrorCategory",
    "EventBus",
    "Instrumentor",
    "LLMCall",
    "ModelPrice",
    "PriceTable",
    "Subscriber",
    "TokenUsage",
    "attributes",
]
__version__ = "0.1.0"
