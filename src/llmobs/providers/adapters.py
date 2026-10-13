"""Concrete adapters for the response shapes of common providers."""

from __future__ import annotations

from typing import Any

from llmobs.providers.base import Normalized, as_text, field, usage_from


class OpenAIAdapter:
    """OpenAI Chat Completions *and* Responses API (also Azure OpenAI, same payloads)."""

    def normalize(self, response: Any) -> Normalized:
        usage = usage_from(
            field(response, "usage", "prompt_tokens"), field(response, "usage", "completion_tokens")
        ) or usage_from(
            field(response, "usage", "input_tokens"), field(response, "usage", "output_tokens")
        )
        completion = as_text(field(response, "choices", 0, "message", "content")) or as_text(
            field(response, "output_text")
        )
        return Normalized(usage, completion, as_text(field(response, "model")))


class MistralAdapter:
    """Mistral chat completions follow the OpenAI-compatible shape."""

    def normalize(self, response: Any) -> Normalized:
        usage = usage_from(
            field(response, "usage", "prompt_tokens"), field(response, "usage", "completion_tokens")
        )
        completion = as_text(field(response, "choices", 0, "message", "content"))
        return Normalized(usage, completion, as_text(field(response, "model")))


class OllamaAdapter:
    """Ollama `/api/chat` and `/api/generate` responses."""

    def normalize(self, response: Any) -> Normalized:
        usage = usage_from(field(response, "prompt_eval_count"), field(response, "eval_count"))
        completion = as_text(field(response, "message", "content")) or as_text(
            field(response, "response")
        )
        return Normalized(usage, completion, as_text(field(response, "model")))


class GenericAdapter:
    """Fallback for unknown providers and test doubles: `text`, `input_tokens`, `output_tokens`."""

    def normalize(self, response: Any) -> Normalized:
        if isinstance(response, str):
            return Normalized(usage=None, completion=response)
        usage = usage_from(field(response, "input_tokens"), field(response, "output_tokens"))
        return Normalized(
            usage, as_text(field(response, "text")), as_text(field(response, "model"))
        )
