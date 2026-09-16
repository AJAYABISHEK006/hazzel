from hazzel.providers.base import Usage
from hazzel.tokens import estimate_messages, estimate_text

from .toolspec import TOOLS

_session_usage = {"input": 0, "output": 0, "cached": 0, "calls": 0, "estimated": 0}
_last_turn_usage = {"input": 0, "output": 0, "cached": 0, "calls": 0, "estimated": False}


def get_session_usage():
    return dict(_session_usage)


def get_last_turn_usage():
    return dict(_last_turn_usage)


def get_last_reasoning():
    joined = "\n\n".join(_turn_reasoning).strip()
    return joined or None


def reset_usage():
    _session_usage.update({"input": 0, "output": 0, "cached": 0, "calls": 0, "estimated": 0})
    _last_turn_usage.update({"input": 0, "output": 0, "cached": 0, "calls": 0, "estimated": False})


def _record_usage(response, task_messages):
    global _last_turn_usage
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
    for key in ("input", "output", "cached"):
        _session_usage[key] += delta[key]
        _last_turn_usage[key] += delta[key]
    _session_usage["calls"] += 1
    _last_turn_usage["calls"] += 1
    if estimated:
        _session_usage["estimated"] += 1
        _last_turn_usage["estimated"] = True
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
