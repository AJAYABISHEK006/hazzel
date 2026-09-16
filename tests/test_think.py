from hazzel import config
from hazzel.providers.base import ChatResponse, extract_reasoning
from hazzel.providers.anthropic import AnthropicProvider, THINK_BUDGET_TOKENS, THINK_MAX_TOKENS
from hazzel.providers.openai import OpenAIProvider, _reasoning_rejected
from hazzel.providers.groq import GroqProvider


def _tmp_config(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(config, "LEGACY_FILE", tmp_path / "legacy.json")
    monkeypatch.setattr(config, "_think_enabled", False)


def test_think_roundtrip(monkeypatch, tmp_path):
    _tmp_config(monkeypatch, tmp_path)
    try:
        assert config.is_think_enabled() is False
        config.set_think_enabled(True)
        assert config.is_think_enabled() is True
        config.set_think_enabled(False)
        assert config.is_think_enabled() is False
    finally:
        config._think_enabled = False


def test_think_persists(monkeypatch, tmp_path):
    _tmp_config(monkeypatch, tmp_path)
    try:
        config.set_think_enabled(True)
        config._think_enabled = False
        config._load_config()
        assert config.is_think_enabled() is True
    finally:
        config._think_enabled = False


def test_think_runs_provider_flag(monkeypatch, tmp_path):
    from hazzel import agent
    _tmp_config(monkeypatch, tmp_path)
    seen = {}

    class FakeProvider:
        provider_name = "Fake"

        def stream(self, messages, tools, on_token=None, think=False, on_reason=None):
            seen["think"] = think
            seen["on_reason"] = on_reason
            return ChatResponse(content="ok")

    monkeypatch.setattr(agent.core, "get_provider", lambda: FakeProvider())
    messages = [{"role": "system", "content": "test"}]

    config.set_think_enabled(False)
    agent.run(messages, "say hi")
    assert seen["think"] is False
    assert seen["on_reason"] is not None

    config.set_think_enabled(True)
    agent.run(messages, "say hi")
    assert seen["think"] is True


def test_anthropic_thinking_kwargs():
    import inspect
    provider = AnthropicProvider.__new__(AnthropicProvider)
    provider.model = "claude-sonnet-4-5"
    assert THINK_BUDGET_TOKENS < THINK_MAX_TOKENS
    sig = inspect.signature(AnthropicProvider.chat)
    assert "think" in sig.parameters
    assert sig.parameters["think"].default is False


def test_openai_reasoning_effort():
    provider = OpenAIProvider.__new__(OpenAIProvider)
    provider.provider_name = "OpenAI"
    provider.model = "gpt-5.6-sol"
    assert provider._create_kwargs([], [], think=False).get("reasoning_effort") is None
    assert provider._create_kwargs([], [], think=True).get("reasoning_effort") == "high"

    compat = OpenAIProvider.__new__(OpenAIProvider)
    compat.provider_name = "DeepSeek"
    compat.model = "deepseek-v4-pro"
    assert "reasoning_effort" not in compat._create_kwargs([], [], think=True)


def test_reasoning_rejected_hints():
    assert _reasoning_rejected("extra_forbidden: reasoning_effort")
    assert _reasoning_rejected("model does not support reasoning")
    assert not _reasoning_rejected("rate limit exceeded")
    assert not _reasoning_rejected("")


def test_extract_reasoning_attrs():
    class Delta:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    assert extract_reasoning(Delta(reasoning_content="think step")) == "think step"
    assert extract_reasoning(Delta(reasoning="groq think step")) == "groq think step"
    assert extract_reasoning(Delta(reasoning_content=" ")) is None
    assert extract_reasoning(Delta(content="plain")) is None


def test_live_reasoning_streams_and_clears(capsys):
    from hazzel import ui

    ui.begin_stream()
    assert ui.was_thinking_streamed() is False
    ui.push_reasoning_token("step one ")
    ui.push_reasoning_token("step two")
    assert ui.was_thinking_streamed() is True
    assert "".join(ui._reason_buffer) == "step one step two"
    ui.push_stream_token("Hello!")
    assert ui._thinking_streamed is False
    assert "".join(ui._reason_buffer) == ""
    assert ui.was_thinking_streamed() is True
    assert ui.end_stream() == "Hello!"

    ui.show_reasoning("should be skipped when streamed live")
    out = capsys.readouterr().out
    assert "should be skipped" not in out

    ui.show_reasoning("shown when not streamed live")
    out = capsys.readouterr().out
    assert "shown when not streamed live" in out


def test_groq_supports_reasoning():
    oss = GroqProvider.__new__(GroqProvider)
    oss.model = "openai/gpt-oss-120b"
    assert oss._supports_reasoning()
    llama = GroqProvider.__new__(GroqProvider)
    llama.model = "llama-3.3-70b-versatile"
    assert not llama._supports_reasoning()