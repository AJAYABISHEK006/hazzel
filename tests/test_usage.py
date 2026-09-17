from hazzel import config, pricing, usage_store
from hazzel.providers import anthropic, groq, mistral, ollama, openai
from hazzel.providers.base import Usage


class _Usage:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _Resp:
    def __init__(self, usage):
        self.usage = usage


def _use_file(monkeypatch, tmp_path):
    monkeypatch.setenv("HAZZEL_USAGE_FILE", str(tmp_path / "usage.jsonl"))


def test_parse_usage_openai_shape():
    rec = openai.parse_usage(_Resp(_Usage(prompt_tokens=100, completion_tokens=50)), "gpt-4o", "openai")
    assert (rec.provider, rec.model) == ("openai", "gpt-4o")
    assert (rec.input_tokens, rec.output_tokens) == (100, 50)
    assert rec.estimated is False


def test_parse_usage_anthropic_cached():
    rec = anthropic.parse_usage(
        _Resp(_Usage(input_tokens=1000, output_tokens=10, cache_read_input_tokens=800, cache_creation_input_tokens=0)),
        "claude-haiku-4-5",
    )
    assert rec.provider == "anthropic"
    assert rec.cached_tokens == 800


def test_parse_usage_groq_mistral_ollama():
    assert groq.parse_usage(_Resp(_Usage(prompt_tokens=7, completion_tokens=3)), "m").input_tokens == 7
    assert mistral.parse_usage(_Resp({"prompt_tokens": 9, "completion_tokens": 1}), "m").output_tokens == 1
    assert ollama.parse_usage(_Resp(_Usage(prompt_tokens=5, completion_tokens=5)), "m").provider == "ollama"
    assert openai.parse_usage(_Resp(None), "m") is None


def test_parse_usage_chat_response_shape():
    from hazzel.providers.base import ChatResponse

    resp = ChatResponse(content="hi", usage=Usage(input_tokens=40, output_tokens=20, cached_tokens=5))
    rec = groq.parse_usage(resp, "llama-3.3-70b-versatile", "groq")
    assert (rec.input_tokens, rec.output_tokens, rec.cached_tokens) == (40, 20, 5)
    assert rec.provider == "groq"


def test_pricing_golden():
    assert pricing.cost_usd("groq", "llama-3.1-8b-instant", 1_000_000, 1_000_000) == 0.13
    assert pricing.cost_usd("ollama", "anything", 10**9, 10**9) == 0.0
    assert pricing.cost_usd("groq", "no-such-model", 100, 100) is None
    assert pricing.cost_usd("anthropic", "claude-haiku-4-5", 1_000_000, 0, cached_tokens=1_000_000) == 0.10
    assert pricing.format_usd(None) == "unknown"
    assert pricing.format_usd(0.424) == "$0.42"


def test_custom_pricing_override():
    custom = {"groq": {"no-such-model": {"input": 1.0, "output": 2.0}}}
    assert pricing.cost_usd("groq", "no-such-model", 1_000_000, 1_000_000, custom=custom) == 3.0


def test_store_roundtrip_and_ranges(monkeypatch, tmp_path):
    _use_file(monkeypatch, tmp_path)
    usage_store.append({"provider": "groq", "model": "m", "input_tokens": 100, "output_tokens": 50, "cost_usd": 0.01})
    usage_store.append({"provider": "groq", "model": "m", "input_tokens": 200, "output_tokens": 0, "cost_usd": None})
    assert len(usage_store.query()) == 2
    total = usage_store.summarize(usage_store.query())
    assert (total["input"], total["output"], total["calls"]) == (300, 50, 2)
    assert total["cost"] == 0.01 and total["unknown"] == 1
    assert usage_store.range_totals("today")["calls"] == 2
    assert usage_store.range_totals("week")["calls"] == 2
    assert usage_store.range_totals("month")["calls"] == 2
    groups = usage_store.by_model(usage_store.query())
    assert groups[("groq", "m")]["calls"] == 2
    ok, _ = usage_store.export_json(tmp_path / "u.json")
    assert ok
    ok, _ = usage_store.export_csv(tmp_path / "u.csv")
    assert ok
    assert usage_store.clear() == 2
    assert usage_store.query() == []


def test_record_usage_invariant(monkeypatch, tmp_path):
    from hazzel.agent.state import _record_usage, get_session_usage, reset_usage
    from hazzel.providers.base import ChatResponse

    _use_file(monkeypatch, tmp_path)
    monkeypatch.setattr(config, "_provider", "groq")
    monkeypatch.setattr(config, "_model", "llama-3.1-8b-instant")
    monkeypatch.setattr(config, "_custom_pricing", {})
    reset_usage()
    try:
        for _ in range(2):
            resp = ChatResponse(content="hi", usage=Usage(input_tokens=1000, output_tokens=500))
            _record_usage(resp, [])
        sess = get_session_usage()
        logged = [r for r in usage_store.query() if r.get("session_id") == usage_store.session_id()]
        assert sess["input"] == sum(r["input_tokens"] for r in logged) == 2000
        assert sess["output"] == sum(r["output_tokens"] for r in logged) == 1000
        assert sess["cost"] == round(sum(r["cost_usd"] for r in logged), 6)
        assert sess["cost"] == pricing.cost_usd("groq", "llama-3.1-8b-instant", 2000, 1000)
    finally:
        reset_usage()


def test_budget_warns_never_blocks(monkeypatch):
    monkeypatch.setattr(config, "_budget", {"session_usd": 1.0, "daily_usd": None, "warn_at_pct": 80})
    assert usage_store.budget_warnings(0.5, 0.0) == []
    assert len(usage_store.budget_warnings(0.9, 0.0)) == 1
