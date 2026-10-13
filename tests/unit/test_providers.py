from __future__ import annotations

from types import SimpleNamespace

from llmobs.model import TokenUsage
from llmobs.providers import GenericAdapter, MistralAdapter, OllamaAdapter, OpenAIAdapter
from llmobs.providers.base import field


def test_openai_chat_completions_object() -> None:
    response = SimpleNamespace(
        model="gpt-4o-mini-2024-07-18",
        usage=SimpleNamespace(prompt_tokens=12, completion_tokens=30),
        choices=[SimpleNamespace(message=SimpleNamespace(content="Bonjour"))],
    )
    normalized = OpenAIAdapter().normalize(response)
    assert normalized.usage == TokenUsage(12, 30)
    assert normalized.completion == "Bonjour"
    assert normalized.model == "gpt-4o-mini-2024-07-18"


def test_openai_responses_api_dict() -> None:
    response = {"usage": {"input_tokens": 5, "output_tokens": 7}, "output_text": "ok"}
    normalized = OpenAIAdapter().normalize(response)
    assert normalized.usage == TokenUsage(5, 7)
    assert normalized.completion == "ok"


def test_mistral_payload() -> None:
    response = {
        "model": "mistral-large-2411",
        "usage": {"prompt_tokens": 3, "completion_tokens": 4},
        "choices": [{"message": {"content": "salut"}}],
    }
    normalized = MistralAdapter().normalize(response)
    assert normalized.usage == TokenUsage(3, 4)
    assert normalized.completion == "salut"


def test_ollama_chat_and_generate() -> None:
    chat = {"model": "llama3", "prompt_eval_count": 9, "eval_count": 2, "message": {"content": "a"}}
    generate = {"prompt_eval_count": 1, "response": "b"}
    assert OllamaAdapter().normalize(chat).usage == TokenUsage(9, 2)
    gen = OllamaAdapter().normalize(generate)
    assert gen.completion == "b"
    assert gen.usage == TokenUsage(1, 0)


def test_missing_usage_gives_none() -> None:
    assert OpenAIAdapter().normalize({"choices": []}).usage is None


def test_generic_adapter_handles_plain_strings_and_objects() -> None:
    assert GenericAdapter().normalize("hello").completion == "hello"
    obj = SimpleNamespace(text="t", input_tokens=1, output_tokens=2, model="m")
    assert GenericAdapter().normalize(obj).usage == TokenUsage(1, 2)


def test_field_walks_mixed_paths_and_tolerates_gaps() -> None:
    data = {"a": [SimpleNamespace(b={"c": 1})]}
    assert field(data, "a", 0, "b", "c") == 1
    assert field(data, "a", 5, "b") is None
    assert field(data, "x", "y") is None
    assert field(None, "a") is None


def test_booleans_are_not_token_counts() -> None:
    assert OpenAIAdapter().normalize({"usage": {"prompt_tokens": True}}).usage is None
