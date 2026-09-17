import time
from dataclasses import dataclass, field
from abc import ABC, abstractmethod


RATE_LIMIT_ATTEMPTS = 3
RATE_LIMIT_DELAYS = (2.0, 4.0)


def is_rate_limit_error(error):
    text = str(error).lower()
    if "429" in text:
        return True
    return any(k in text for k in [
        "rate limit",
        "rate_limit",
        "ratelimit",
        "too many requests",
        "quota",
        "capacity",
        "overloaded",
        "server is busy",
        "try again later",
    ])


def rate_limit_message(provider_name):
    return (
        f"Rate limit reached on {provider_name} — requests are throttled, nothing is broken. "
        "Wait a minute and retry, or switch model with /model."
    )


def call_with_backoff(provider_name, fn, attempts=RATE_LIMIT_ATTEMPTS):
    last = None
    for i in range(max(1, attempts)):
        try:
            return fn()
        except Exception as error:
            if not is_rate_limit_error(error):
                raise
            last = error
            if i < attempts - 1:
                try:
                    time.sleep(RATE_LIMIT_DELAYS[min(i, len(RATE_LIMIT_DELAYS) - 1)])
                except Exception:
                    pass
    raise RuntimeError(rate_limit_message(provider_name)) from last


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    estimated: bool = False


@dataclass
class UsageRecord:
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0
    estimated: bool = False
    timestamp: float = 0.0
    session_id: str = ""
    cost_usd: float | None = None

    def to_dict(self):
        return {
            "provider": self.provider,
            "model": self.model,
            "input_tokens": int(self.input_tokens or 0),
            "output_tokens": int(self.output_tokens or 0),
            "cached_input_tokens": int(self.cached_tokens or 0),
            "reasoning_tokens": int(self.reasoning_tokens or 0),
            "estimated": bool(self.estimated),
            "ts": float(self.timestamp or 0),
            "session_id": self.session_id or "",
            "cost_usd": self.cost_usd,
        }


def record_from_usage(provider, model, usage):
    if isinstance(usage, UsageRecord):
        usage.provider = provider
        usage.model = model
        return usage
    if not isinstance(usage, Usage):
        return None
    if not usage.input_tokens and not usage.output_tokens:
        return None
    return UsageRecord(
        provider=provider,
        model=model,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cached_tokens=usage.cached_tokens,
        timestamp=time.time(),
    )


@dataclass
class ChatResponse:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage | None = None
    reasoning: str | None = None


def extract_reasoning(obj):
    try:
        for attr in ("reasoning_content", "reasoning"):
            text = getattr(obj, attr, None)
            if isinstance(text, str) and text.strip():
                return text
        parts = []
        for block in getattr(obj, "content", None) or []:
            if getattr(block, "type", None) in ("thinking", "redacted_thinking"):
                parts.append(getattr(block, "thinking", "") or "")
        joined = "\n".join(p for p in parts if p).strip()
        return joined or None
    except Exception:
        return None


class BaseProvider(ABC):
    @abstractmethod
    def chat(self, messages, tools, think=False) -> ChatResponse:
        ...

    def stream(self, messages, tools, on_token=None, think=False, on_reason=None) -> ChatResponse:
        response = self.chat(messages, tools, think=think)
        if on_reason and response.reasoning:
            try:
                on_reason(response.reasoning)
            except Exception:
                pass
        if on_token and response.content:
            try:
                on_token(response.content)
            except Exception:
                pass
        return response
