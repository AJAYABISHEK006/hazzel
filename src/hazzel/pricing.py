PRICING_LAST_UPDATED = "2026-09-17"

# Rates in USD per 1M tokens. Dated snapshot — use `custom_pricing` override
# in config for newer rates. Models absent here price as `unknown`, never guessed.
# Sources (Sep 2026): GroqCloud docs, Anthropic pricing page, Mistral La Plateforme,
# Gemini API pricing guides, DeepSeek API docs (V3 rates applied to V4 family).
PRICING = {
    "groq": {
        "llama-3.1-8b-instant": {"input": 0.05, "output": 0.08},
        "llama-3.3-70b-versatile": {"input": 0.59, "output": 0.99},
        "openai/gpt-oss-120b": {"input": 0.15, "output": 0.60},
        "openai/gpt-oss-20b": {"input": 0.075, "output": 0.30},
        "openai/gpt-oss-safeguard-20b": {"input": 0.075, "output": 0.30},
        "qwen/qwen3.6-27b": {"input": 0.60, "output": 3.00},
        "qwen/qwen3.8-27b": {"input": 0.80, "output": 4.00},
    },
    "anthropic": {
        "claude-haiku-4-5": {"input": 1.00, "output": 5.00, "cached_input": 0.10},
        "claude-haiku-4-5-20251001": {"input": 1.00, "output": 5.00, "cached_input": 0.10},
        "claude-sonnet-4-5": {"input": 3.00, "output": 15.00, "cached_input": 0.30},
        "claude-opus-4-5": {"input": 5.00, "output": 25.00, "cached_input": 0.50},
        "claude-opus-4-5-20251101": {"input": 5.00, "output": 25.00, "cached_input": 0.50},
        "claude-opus-4-6": {"input": 5.00, "output": 25.00, "cached_input": 0.50},
        "claude-opus-4-7": {"input": 5.00, "output": 25.00, "cached_input": 0.50},
        "claude-opus-4-8": {"input": 5.00, "output": 25.00, "cached_input": 0.50},
        "claude-opus-5": {"input": 5.00, "output": 25.00, "cached_input": 0.50},
        "claude-fable-5": {"input": 10.00, "output": 50.00, "cached_input": 1.00},
    },
    "mistral": {
        "mistral-medium-3.5": {"input": 1.50, "output": 7.50},
        "mistral-small-4": {"input": 0.15, "output": 0.60},
        "mistral-large-3": {"input": 0.50, "output": 1.50},
        "codestral": {"input": 0.30, "output": 0.90},
    },
    "gemini": {
        "gemini-2.5-pro": {"input": 1.25, "output": 10.00},
        "gemini-3.1-pro-preview": {"input": 2.00, "output": 12.00},
        "gemini-3.8-flash": {"input": 0.50, "output": 3.00},
        "gemini-3.7-flash": {"input": 0.50, "output": 3.00},
    },
    "deepseek": {
        "deepseek-v4-flash": {"input": 0.27, "output": 1.10, "cached_input": 0.028},
        "deepseek-v4-pro": {"input": 0.27, "output": 1.10, "cached_input": 0.028},
    },
    "openrouter": {
        "google/gemini-3.8-flash": {"input": 0.50, "output": 3.00},
    },
}

FREE_PROVIDERS = frozenset({"ollama"})


def get_price(provider, model, custom=None):
    if custom:
        try:
            entry = (custom.get(provider) or {}).get(model)
        except AttributeError:
            entry = None
        if isinstance(entry, dict):
            return entry
    try:
        return PRICING.get(provider, {}).get(model)
    except AttributeError:
        return None


def cost_usd(provider, model, input_tokens, output_tokens, cached_tokens=0, custom=None):
    if provider in FREE_PROVIDERS:
        return 0.0
    entry = get_price(provider, model, custom)
    if not isinstance(entry, dict):
        return None
    try:
        rate_in = float(entry.get("input", 0) or 0)
        rate_out = float(entry.get("output", 0) or 0)
        rate_cached = entry.get("cached_input", rate_in)
        rate_cached = float(rate_cached or 0)
    except (TypeError, ValueError):
        return None
    fresh_in = max(0, int(input_tokens or 0) - int(cached_tokens or 0))
    total = (fresh_in * rate_in + int(output_tokens or 0) * rate_out + int(cached_tokens or 0) * rate_cached) / 1_000_000
    return round(total, 6)


def format_usd(value):
    if value is None:
        return "unknown"
    return f"${float(value):,.2f}"
