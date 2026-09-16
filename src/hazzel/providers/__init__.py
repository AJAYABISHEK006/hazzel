import os
from .base import BaseProvider, ChatResponse, ToolCall, Usage, call_with_backoff, extract_reasoning, is_rate_limit_error, rate_limit_message


def _ollama_base_url():
    return os.getenv("OLLAMA_HOST", "http://localhost:11434/v1")


COMPAT_PROVIDERS = {
    "openai": ("OpenAI", "https://api.openai.com/v1"),
    "openrouter": ("OpenRouter", "https://openrouter.ai/api/v1"),
    "deepseek": ("DeepSeek", "https://api.deepseek.com/v1"),
    "gemini": ("Gemini", "https://generativelanguage.googleapis.com/v1beta/openai/"),
}


def create_provider(provider_name: str, api_key: str | None, model: str, base_url: str | None = None) -> BaseProvider:
    provider_name = provider_name.lower()
    if provider_name == "openai":
        from .openai import OpenAIProvider
        return OpenAIProvider(api_key, model, base_url=base_url or "https://api.openai.com/v1")
    if provider_name == "anthropic":
        from .anthropic import AnthropicProvider
        return AnthropicProvider(api_key, model)
    if provider_name == "groq":
        from .groq import GroqProvider
        return GroqProvider(api_key, model)
    if provider_name == "mistral":
        from .mistral import MistralProvider
        return MistralProvider(api_key, model)
    if provider_name == "ollama":
        from .ollama import OllamaProvider
        return OllamaProvider(api_key, model, base_url=base_url or _ollama_base_url())
    if provider_name == "openrouter":
        from .openai import OpenAIProvider
        return OpenAIProvider(api_key, model, base_url=base_url or "https://openrouter.ai/api/v1", provider_name="OpenRouter")
    if provider_name == "deepseek":
        from .openai import OpenAIProvider
        return OpenAIProvider(api_key, model, base_url=base_url or "https://api.deepseek.com/v1", provider_name="DeepSeek")
    if provider_name == "gemini":
        from .openai import OpenAIProvider
        return OpenAIProvider(api_key, model, base_url=base_url or "https://generativelanguage.googleapis.com/v1beta/openai/", provider_name="Gemini")
    raise RuntimeError(f"Unknown provider: {provider_name}")


def get_provider() -> BaseProvider:
    from hazzel import config as _config
    provider_name = _config.get_current_provider()
    api_key = _config.get_api_key(provider_name)
    model = _config.get_current_model()
    return create_provider(provider_name, api_key, model)


__all__ = [
    "BaseProvider",
    "ChatResponse",
    "ToolCall",
    "Usage",
    "call_with_backoff",
    "extract_reasoning",
    "is_rate_limit_error",
    "rate_limit_message",
    "get_provider",
    "create_provider",
    "COMPAT_PROVIDERS",
    "_ollama_base_url",
]