import time

from hazzel.providers.base import Usage, UsageRecord
from hazzel.tokens import estimate_messages, estimate_text

from .toolspec import TOOLS

_session_usage = {"input": 0, "output": 0, "cached": 0, "calls": 0, "estimated": 0, "cost": 0.0, "unknown": 0}
_last_turn_usage = {"input": 0, "output": 0, "cached": 0, "calls": 0, "estimated": False, "cost": 0.0, "unknown": 0}


def get_session_usage():
    return dict(_session_usage)


def get_last_turn_usage():
    return dict(_last_turn_usage)


def get_last_reasoning():
    joined = "\n\n".join(_turn_reasoning).strip()
    return joined or None


def reset_usage():
    _session_usage.update({"input": 0, "output": 0, "cached": 0, "calls": 0, "estimated": 0, "cost": 0.0, "unknown": 0})
    _last_turn_usage.update({"input": 0, "output": 0, "cached": 0, "calls": 0, "estimated": False, "cost": 0.0, "unknown": 0})


def _parse_response(provider, model, response):
    try:
        import importlib
        name = {"openrouter": "openai", "deepseek": "openai", "gemini": "openai"}.get(provider, provider)
        mod = importlib.import_module(f"hazzel.providers.{name}")
        parse = getattr(mod, "parse_usage", None)
        if parse is None:
            return None
        return parse(response, model, provider)
    except Exception:
        return None


def _record_usage(response, task_messages):
    global _last_turn_usage
    from hazzel import pricing, usage_store
    try:
        from hazzel import config
        provider = config.get_current_provider()
        model = config.get_current_model()
        custom = config.get_custom_pricing()
    except Exception:
        provider, model, custom = "unknown", "unknown", None
    record = _parse_response(provider, model, response)
    if record is not None:
        delta = {"input": record.input_tokens, "output": record.output_tokens, "cached": record.cached_tokens}
        estimated = False
        response.usage = Usage(input_tokens=delta["input"], output_tokens=delta["output"], cached_tokens=delta["cached"])
    else:
        usage = getattr(response, "usage", None)
        if usage and (usage.input_tokens or usage.output_tokens):
            delta = {"input": usage.input_tokens, "output": usage.output_tokens, "cached": usage.cached_tokens}
            estimated = False
        else:
            delta = {"input": estimate_messages(task_messages, TOOLS), "output": estimate_text(getattr(response, "content", None))}
            delta["cached"] = 0
            usage = Usage(input_tokens=delta["input"], output_tokens=delta["output"], estimated=True)
            response.usage = usage
            estimated = True
    try:
        if estimated:
            cost = None
        else:
            cost = pricing.cost_usd(provider, model, delta["input"], delta["output"], delta["cached"], custom)
    except Exception:
        cost = None
    try:
        if record is None:
            record = UsageRecord(provider=provider, model=model, estimated=estimated)
            record.input_tokens = delta["input"]
            record.output_tokens = delta["output"]
            record.cached_tokens = delta["cached"]
        record.timestamp = time.time()
        record.session_id = usage_store.session_id()
        record.cost_usd = cost
        usage_store.append(record.to_dict())
    except Exception:
        pass
    for key in ("input", "output", "cached"):
        _session_usage[key] += delta[key]
        _last_turn_usage[key] += delta[key]
    _session_usage["calls"] += 1
    _last_turn_usage["calls"] += 1
    if cost is None:
        _session_usage["unknown"] += 1
        _last_turn_usage["unknown"] += 1
    else:
        _session_usage["cost"] = round(_session_usage["cost"] + cost, 6)
        _last_turn_usage["cost"] = round(_last_turn_usage["cost"] + cost, 6)
    if estimated:
        _session_usage["estimated"] += 1
        _last_turn_usage["estimated"] = True
    delta["cost"] = cost
    return delta


# Last file the user touched, so pronouns like "delete it" resolve without an LLM call.
_LAST_TARGET = None


def reset_conversation_state():
    reset_usage()
    global _LAST_TARGET
    _LAST_TARGET = None
    _turn_reasoning.clear()


def _note_target(target):
    global _LAST_TARGET
    if target:
        _LAST_TARGET = target


def _looks_like_path(target):
    return "." in target or "/" in target


_turn_reasoning = []


def _note_reasoning(text):
    if (text or "").strip():
        _turn_reasoning.append(text.strip())


def _update_last_target(trace):
    for t in reversed(trace or []):
        if t.get("tool") in ("read_file", "write_file", "edit_file") and t.get("detail"):
            _note_target(t["detail"])
            return
        if t.get("tool") == "run_command":
            detail = (t.get("detail") or "").strip()
            if detail.startswith("rm ") and t.get("success"):
                parts = detail[3:].strip().split()
                if parts:
                    _note_target(parts[-1].strip("'\""))
                    return
