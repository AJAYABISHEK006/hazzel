import json
import urllib.request

from .openai import OpenAIProvider


def _tags_url():
    import os
    host = os.getenv("OLLAMA_HOST", "http://localhost:11434/v1").rstrip("/")
    if host.endswith("/v1"):
        host = host[: -len("/v1")]
    return host + "/api/tags"


def fetch_local_models(timeout=2):
    try:
        with urllib.request.urlopen(_tags_url(), timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8") or "{}")
    except Exception:
        return []
    names = []
    for m in data.get("models", None) or []:
        name = m.get("name") if isinstance(m, dict) else None
        if name and name not in names:
            names.append(name)
    return names


class OllamaProvider(OpenAIProvider):
    provider_name = "Ollama"

    def _create_kwargs(self, messages, tools, stream=False, think=False):
        kwargs = super()._create_kwargs(messages, tools, stream=stream, think=think)
        kwargs.pop("prompt_cache_key", None)
        try:
            kwargs["extra_body"] = {"options": {"num_ctx": 65536, "keep_alive": "30m"}}
        except (TypeError, ValueError):
            pass
        return kwargs

    def _connect_error(self, e):
        msg = str(e).lower()
        if "connection" in msg or "refused" in msg or "no response" in msg:
            raise RuntimeError(f"Unable to connect to Ollama — is it running? Start with `ollama serve`, then `ollama pull {self.model}`.") from e
        if "model" in msg and ("not found" in msg or "invalid" in msg or "does not exist" in msg):
            raise RuntimeError(f"Ollama model not found: {self.model} — run `ollama pull {self.model}` first.") from e
        return super()._connect_error(e)
