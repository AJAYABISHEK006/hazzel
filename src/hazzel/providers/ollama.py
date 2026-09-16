import json
import urllib.request
from .base import BaseProvider, ChatResponse, ToolCall, Usage, call_with_backoff, extract_reasoning


def _extract_usage(resp):
    try:
        u = getattr(resp, "usage", None)
        if not u:
            return None
        prompt = int(getattr(u, "prompt_tokens", 0) or 0)
        completion = int(getattr(u, "completion_tokens", 0) or 0)
        return Usage(input_tokens=prompt, output_tokens=completion)
    except (TypeError, ValueError):
        return None


def _tags_url() -> str:
    import os
    host = os.getenv("OLLAMA_HOST", "http://localhost:11434/v1")
    if host.endswith("/v1"):
        host = host[:-3]
    return f"{host}/api/tags"


def fetch_local_models() -> list[str]:
    try:
        with urllib.request.urlopen(_tags_url(), timeout=2) as resp:
            data = json.loads(resp.read().decode())
        return [m["name"] for m in data.get("models", []) if isinstance(m.get("name"), str)]
    except Exception:
        return []


class OllamaProvider(BaseProvider):
    def __init__(self, api_key, model, base_url=None):
        from openai import OpenAI
        self.model = model
        self.provider_name = "Ollama"
        kwargs = {"api_key": "ollama", "base_url": base_url or "http://localhost:11434/v1"}
        self.client = OpenAI(**kwargs)

    def chat(self, messages, tools, think=False):
        try:
            resp = call_with_backoff(
                self.provider_name,
                lambda: self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=tools,
                    max_tokens=10000,
                ),
            )
        except RuntimeError:
            raise
        except Exception as e:
            msg = str(e).lower()
            if "connection" in msg or "refused" in msg:
                raise RuntimeError("Unable to connect to Ollama\n\nIs Ollama running? Start it with `ollama serve`.") from e
            if "model" in msg and ("not found" in msg or "invalid" in msg):
                raise RuntimeError(f"Invalid model: {self.model}") from e
            raise RuntimeError(f"Unable to connect to Ollama: {e}") from e
        choice = resp.choices[0].message
        tool_calls = []
        if getattr(choice, "tool_calls", None):
            for tc in choice.tool_calls:
                tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=tc.function.arguments or "{}"))
        content = getattr(choice, "content", None)
        return ChatResponse(content=content, tool_calls=tool_calls, usage=_extract_usage(resp), reasoning=extract_reasoning(choice))

    def stream(self, messages, tools, on_token=None, think=False, on_reason=None):
        try:
            chunks = call_with_backoff(
                self.provider_name,
                lambda: self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=tools,
                    max_tokens=10000,
                    stream=True,
                    stream_options={"include_usage": True},
                ),
            )
        except Exception as first_error:
            if "stream_options" in str(first_error).lower():
                try:
                    chunks = call_with_backoff(
                        self.provider_name,
                        lambda: self.client.chat.completions.create(
                            model=self.model,
                            messages=messages,
                            tools=tools,
                            max_tokens=10000,
                            stream=True,
                        ),
                    )
                except Exception:
                    return super().stream(messages, tools, on_token, think=think, on_reason=on_reason)
            else:
                return super().stream(messages, tools, on_token, think=think, on_reason=on_reason)
        parts = []
        reason_parts = []
        acc = {}
        usage = None
        try:
            for chunk in chunks:
                try:
                    u = _extract_usage(chunk)
                    if u and (u.input_tokens or u.output_tokens):
                        usage = u
                except Exception:
                    pass
                choices = getattr(chunk, "choices", None) or []
                if not choices:
                    continue
                delta = getattr(choices[0], "delta", None)
                if delta is None:
                    continue
                reason = extract_reasoning(delta)
                if reason:
                    reason_parts.append(reason)
                    if on_reason:
                        try:
                            on_reason(reason)
                        except Exception:
                            pass
                text = getattr(delta, "content", None)
                if text:
                    parts.append(text)
                    if on_token:
                        try:
                            on_token(text)
                        except Exception:
                            pass
                for tc in getattr(delta, "tool_calls", None) or []:
                    idx = getattr(tc, "index", 0) or 0
                    entry = acc.setdefault(idx, {"id": "", "name": "", "args": ""})
                    if getattr(tc, "id", None):
                        entry["id"] = tc.id
                    fn = getattr(tc, "function", None)
                    if fn is not None:
                        if getattr(fn, "name", None):
                            entry["name"] = fn.name
                        if getattr(fn, "arguments", None):
                            entry["args"] += fn.arguments
        except Exception as error:
            if not parts and not acc:
                raise
            msg = str(error).lower()
            if "connection" in msg or "refused" in msg:
                raise RuntimeError("Unable to connect to Ollama\n\nIs Ollama running? Start it with `ollama serve`.") from error
        tool_calls = []
        for idx in sorted(acc):
            entry = acc[idx]
            if entry["name"]:
                tool_calls.append(ToolCall(id=entry["id"] or f"call_{idx}", name=entry["name"], arguments=entry["args"] or "{}"))
        reasoning = "".join(reason_parts).strip() or None
        return ChatResponse(content="".join(parts) or None, tool_calls=tool_calls, usage=usage, reasoning=reasoning)