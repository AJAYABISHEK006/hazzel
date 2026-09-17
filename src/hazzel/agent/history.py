from hazzel import config
from hazzel.tokens import estimate_messages

from .dispatch import _active_tools
from .state import get_session_usage
from .toolspec import HISTORY_REPLY_CHARS, HISTORY_TOKEN_BUDGET

# In-turn working copy is distilled once it grows past this (~tokens).
TURN_TOKEN_BUDGET = 12000


def _build_summary(trace, response_content, user_input):
    try:
        return _build_summary_inner(trace, response_content, user_input)
    except Exception:
        return "Done."


def _build_summary_inner(trace, response_content, user_input):
    inspected = []
    created = []
    changed = []
    deleted = []
    actions = []
    verifs = []
    warnings = []
    for t in trace:
        name = t["tool"]
        detail = t["detail"]
        success = t["success"]
        result = t["result"]
        if name == "read_file" and success and not t.get("cached"):
            inspected.append(detail)
        elif name in ("list_files", "search_files", "web_search", "fetch_url", "skill") and success and not t.get("cached"):
            inspected.append(detail or name)
        elif name == "write_file" and success:
            created.append(detail)
            actions.append(f"{name} {detail}".strip())
        elif name in ("edit_file", "apply_edits") and success:
            changed.append(detail)
            actions.append(f"{name} {detail}".strip())
        elif name == "run_command":
            actions.append(f"run_command {detail}".strip())
            if any(k in detail for k in ["pytest", "test", "build", "lint", "typecheck", "ruff", "mypy", "tsc", "npm", "cargo"]):
                if t["exit_code"] is not None:
                    verifs.append(f"{detail} — {'passed' if success else 'failed'} (exit {t['exit_code']})")
                else:
                    verifs.append(f"{detail} — {'passed' if success else 'failed'}")
            if not success:
                warnings.append(f"{detail} — {result[:140].replace(chr(10), ' ')}")
            if "rm " in detail or "unlink" in detail:
                deleted.append(detail)
        elif not success:
            warnings.append(f"{name} {detail} — {result[:140].replace(chr(10), ' ')}")

    def _clean(items):
        seen = []
        for x in items:
            x = (x or "").strip()
            if not x or x in seen or x == "." or x == "/":
                continue
            seen.append(x)
        return seen

    inspected = _clean(inspected)
    created = _clean(created)
    changed = _clean(changed)

    def _fmt(items):
        return ", ".join(f"`{x}`" for x in items[:4]) if items else ""

    paras = []

    clean_input = user_input.strip().lstrip("/").strip().rstrip(".")
    is_slash = user_input.strip().startswith("/") and len(clean_input) < 3

    if inspected and not created and not changed and len(inspected) <= 3:
        paras.append(f"You asked Hazzel to read `{inspected[0]}` and re-edit it.")
        paras.append(f"Hazzel inspected {_fmt(inspected)}.")
        if response_content and "empty" in response_content.lower():
            paras.append(f"`{inspected[0]}` is currently empty.")
        else:
            snippet = response_content.strip().splitlines()[0][:180] if response_content else ""
            if snippet and len(snippet) > 12:
                paras.append(snippet)
    elif trace:
        if not is_slash and clean_input:
            paras.append(f"You asked Hazzel to {clean_input}.")
        parts = []
        if inspected:
            parts.append(f"inspected {_fmt(inspected)}")
        if created:
            parts.append(f"created {_fmt(created)}")
        if changed:
            parts.append(f"updated {_fmt(changed)}")
        if parts:
            paras.append("Hazzel " + ", ".join(parts) + ".")
        if verifs:
            paras.append("Verified via " + ", ".join(verifs[:2]) + ".")
        elif created or changed:
            paras.append("No automated verification was run in this turn.")
        if response_content and response_content.strip() and "empty" not in response_content.lower():
            snippet = response_content.strip().splitlines()[0][:200]
            if snippet and snippet not in paras and len(snippet) > 15:
                paras.append(snippet)
    else:
        if not is_slash and clean_input:
            paras.append(f"You asked: {clean_input}")
        paras.append("Hazzel answered directly — no file changes were needed.")

    if warnings:
        warn = warnings[0].replace("Command cancelled", "Cancelled").replace(" — ", " — ")
        paras.append(f"Note: `{warn[:120]}`")

    return "\n\n".join(p for p in paras if p.strip())


def _compact_reply(content):
    content = (content or "Done.").strip()
    if len(content) > HISTORY_REPLY_CHARS:
        content = content[:HISTORY_REPLY_CHARS] + "…"
    return content


def _commit_history(messages, user_input, content):
    # Only the user request and the compact final answer are kept between turns.
    # Tool calls and tool results stay inside the turn so history stays small.
    user_input = user_input.strip()[:500]
    messages.append({"role": "user", "content": user_input})
    messages.append({"role": "assistant", "content": _compact_reply(content)})

    # Drop the oldest user/assistant pairs together to keep role alternation intact.
    while len(messages) > 3 and sum(len(m.get("content") or "") for m in messages[1:]) // 4 > HISTORY_TOKEN_BUDGET:
        del messages[1:3]


def context_usage(messages=None):
    try:
        live = estimate_messages(messages or [], _active_tools())
    except Exception:
        live = 0
    try:
        burned = int(get_session_usage().get("input") or 0)
    except Exception:
        burned = 0
    try:
        window = config.get_context_window()
    except Exception:
        window = 131072
    try:
        window = int(window or 131072)
    except (TypeError, ValueError):
        window = 131072
    if window <= 0:
        window = 131072
    return max(int(live or 0), burned, 0), window


def _enforce_turn_budget(task_messages):
    def _msg_len(m):
        try:
            from hazzel.mentions import content_text_len

            return content_text_len(m.get("content"))
        except Exception:
            c = m.get("content") or ""
            return len(c) if isinstance(c, str) else len(str(c))
    while sum(_msg_len(m) for m in task_messages) // 4 > TURN_TOKEN_BUDGET:
        distilled = False
        for m in task_messages:
            if m.get("role") == "tool":
                content = m.get("content") or ""
                if len(content) > 350 and "…distilled…" not in content:
                    m["content"] = content[:280] + "\n[…distilled…]"
                    distilled = True
                    break
        if not distilled:
            break


def _session_goal_note():
    try:
        goal = config.get_goal()
    except Exception:
        return ""
    if not isinstance(goal, dict):
        return ""
    objective = (goal.get("objective") or "").strip()
    if not objective:
        return ""
    note = f"\n\nSession goal: {objective}."
    criteria = (goal.get("criteria") or "").strip()
    if criteria:
        note += f" Acceptance: {criteria}."
    note += " Steer toward it and briefly note progress."
    return note


def goal_run_task():
    try:
        goal = config.get_goal()
    except Exception:
        return None
    if not isinstance(goal, dict):
        return None
    objective = (goal.get("objective") or "").strip()
    if not objective:
        return None
    criteria = (goal.get("criteria") or "").strip() or "use your best judgment"
    return f"Work toward this session goal: {objective}. Acceptance: {criteria}. Start with the first concrete step."
