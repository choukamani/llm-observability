from llmobs.providers.adapters import GenericAdapter, MistralAdapter, OllamaAdapter, OpenAIAdapter
from llmobs.providers.base import Normalized, ProviderAdapter

DEFAULT_ADAPTERS: dict[str, ProviderAdapter] = {
    "openai": OpenAIAdapter(),
    "azure_openai": OpenAIAdapter(),
    "mistral": MistralAdapter(),
    "ollama": OllamaAdapter(),
}

__all__ = [
    "DEFAULT_ADAPTERS",
    "GenericAdapter",
    "MistralAdapter",
    "Normalized",
    "OllamaAdapter",
    "OpenAIAdapter",
    "ProviderAdapter",
]
