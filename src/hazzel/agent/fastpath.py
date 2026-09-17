import re
import shlex

from hazzel import config
from hazzel import ui
from hazzel.config import resolve_project_path
from hazzel.tools.search_files import missing_file_message

from .dispatch import is_print_readonly, run_tool
from .history import _build_summary, _commit_history
from .state import _LAST_TARGET, _looks_like_path, _note_target


def _fast_reply(messages, user_input, reply, trace):
    _commit_history(messages, user_input, reply)
    return reply, trace, _build_summary(trace, reply, user_input)


def _fast_trace(tool, detail, result, success):
    return [{"tool": tool, "args": {}, "detail": detail, "result": result, "success": success, "exit_code": None}]


def _plan_defers():
    try:
        return config.is_plan_enabled()
    except Exception:
        return False


def _mutating_defers():
    # Plan mode and read-only print mode both keep zero-LLM mutating shortcuts off,
    # so the model turn (with its reduced tool set) handles them instead.
    if _plan_defers():
        return True
    try:
        return is_print_readonly()
    except Exception:
        return False


def _fast_delete(messages, user_input, target):
    if _mutating_defers():
        return None
    try:
        resolved = resolve_project_path(target)
    except ValueError as error:
        return _fast_reply(messages, user_input, str(error), [])
    if not resolved.exists():
        reply = f"No such file: {target}."
        return _fast_reply(messages, user_input, reply, _fast_trace("run_command", f"rm {target}", reply, False))
    result = run_tool("run_command", {"command": f"rm {shlex.quote(target)}"})
    success = not result.lower().startswith(("command failed", "command cancelled", "command timed out", "tool error"))
    reply = f"{target} has been removed." if success else result
    if success:
        _note_target(target)
    return _fast_reply(messages, user_input, reply, _fast_trace("run_command", f"rm {target}", result, success))


def _fast_create(messages, user_input, target):
    if _mutating_defers():
        return None
    try:
        if resolve_project_path(target).exists():
            reply = f"{target} already exists."
            return _fast_reply(messages, user_input, reply, _fast_trace("write_file", target, reply, False))
    except ValueError as error:
        return _fast_reply(messages, user_input, str(error), [])
    result = run_tool("write_file", {"path": target, "content": ""})
    success = not result.lower().startswith(("tool error", "content too large"))
    reply = f"Created {target}." if success else result
    if success:
        _note_target(target)
    return _fast_reply(messages, user_input, reply, _fast_trace("write_file", target, result, success))


def _fast_read(messages, user_input, target):
    try:
        resolved = resolve_project_path(target)
    except ValueError as error:
        reply = str(error)
        return _fast_reply(messages, user_input, reply, _fast_trace("read_file", target, reply, False))
    if not resolved.exists():
        reply = missing_file_message(target)
        return _fast_reply(messages, user_input, reply, _fast_trace("read_file", target, reply, False))
    if not resolved.is_file():
        reply = "Path is not a file"
        return _fast_reply(messages, user_input, reply, _fast_trace("read_file", target, reply, False))
    try:
        text = resolved.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError, ValueError):
        reply = "File is binary; preview not supported"
        return _fast_reply(messages, user_input, reply, _fast_trace("read_file", target, reply, False))
    lines = text.splitlines()
    total = len(lines)
    if total == 0:
        return _fast_reply(messages, user_input, f"`{target}` is empty.", _fast_trace("read_file", target, "(empty file)", True))
    shown = lines[:ui.VIEW_MAX_LINES] if len(lines) > ui.VIEW_MAX_LINES else lines
    if ui.is_print_mode():
        # No file viewer on a pipe — hand the content back as the reply instead.
        content = run_tool("read_file", {"path": target})
        return _fast_reply(messages, user_input, f"`{target}`:\n\n{content}", _fast_trace("read_file", target, f"({total} lines via print mode)", True))
    ui.show_file_viewer(target, "\n".join(shown), total, len(shown))
    _note_target(target)
    reply = f"Showed `{target}` ({total} lines) above — ask me anything about it."
    return _fast_reply(messages, user_input, reply, _fast_trace("read_file", target, f"({total} lines shown via viewer)", True))


def _fast_list(messages, user_input, target):
    result = run_tool("list_files", {"path": target})
    if isinstance(result, list):
        result = "\n".join(result) or "(empty directory)"
    success = not str(result).lower().startswith(("path does not exist", "path is not", "path is outside"))
    return _fast_reply(messages, user_input, str(result), _fast_trace("list_files", target, str(result), success))


_PKG_RE = re.compile(r"^[A-Za-z0-9_.\-]+(\[[A-Za-z0-9_,.\-]+\])?(==[A-Za-z0-9_.\-]+)?$")
_PKG_CONNECTORS = frozenset({"and", "with", "plus", "&", "+", "package", "packages", "library", "libraries", "module", "modules"})


def _parse_package_names(raw):
    pkgs = []
    for tok in re.split(r"[\s,]+", (raw or "").strip()):
        cleaned = tok.strip("'\"").rstrip(".,!?;:)}\"'")
        if not cleaned:
            continue
        if cleaned.lower() in _PKG_CONNECTORS:
            continue
        if not _PKG_RE.match(cleaned):
            return None
        if cleaned.lower() in {"a", "an", "the", "for", "me", "it", "them", "this", "that", "two", "three", "both", "all", "everything", "dependencies", "requirements", "latest", "version"}:
            return None
        pkgs.append(cleaned)
    return pkgs or None


def _fast_install(messages, user_input, pkgs):
    if _mutating_defers():
        return None
    command = "pip install " + " ".join(shlex.quote(p) for p in pkgs)
    result = run_tool("run_command", {"command": command})
    success = not str(result).lower().startswith(("command failed", "command cancelled", "command timed out", "tool error"))
    if success:
        reply = f"Installed {', '.join(pkgs)}."
    else:
        reply = str(result)
    return _fast_reply(messages, user_input, reply, _fast_trace("run_command", command, str(result), success))


def _fast_run(messages, user_input, command):
    if _mutating_defers():
        return None
    result = run_tool("run_command", {"command": command})
    if isinstance(result, list):
        result = "\n".join(result) or "(empty directory)"
    success = not str(result).lower().startswith(("command failed", "command cancelled", "command timed out", "tool error"))
    return _fast_reply(messages, user_input, str(result), _fast_trace("run_command", command, str(result), success))


def try_fast_path(messages, user_input):
    # Trivial turns are handled locally with zero LLM calls. Anything ambiguous
    # returns None and falls through to the model.
    text = (user_input or "").strip()
    text = re.sub(r'@(?:"([^"]+)"|\'([^\']+)\'|`([^`]+)`|(\S+))', lambda m: (m.group(1) or m.group(2) or m.group(3) or m.group(4) or "").rstrip(".,!?;:)]"), text).strip()
    if not text or text.startswith("/"):
        return None
    low = text.lower().strip(" .!?")
    if low in ("hi", "hello", "hey", "yo", "sup", "howdy", "hiya", "greetings"):
        return _fast_reply(messages, user_input, "Hello! How can I help you today?", [])
    if low in ("thanks", "thank you", "thx"):
        return _fast_reply(messages, user_input, "You're welcome.", [])
    if len(low) <= 1:
        return _fast_reply(messages, user_input, "I'm Hazzel — tell me what to do (e.g. `read @path`, `run pytest -q`).", [])

    if re.search(r"who\s+(developed|created|built|made|designed)\s+(you|hazzel|this)(\s+(agent|app|tool|program))?\b", low) or re.search(
        r"who'?s\s+your\s+(developer|creator|maker|author|owner|father|dad)\b", low
    ) or re.search(r"\b(your\s+developer|your\s+creator|developed\s+by\s+whom)\b", low):
        return _fast_reply(messages, user_input, "I am Hazzel, developed by Mukund Jha.", [])
    if re.search(r"who\s+is\s+mukund(\s+jha)?\b", low):
        return _fast_reply(messages, user_input, "Mukund Jha is the developer of Hazzel.", [])
    if re.search(r"\b(what\s+is\s+hazzel|is\s+hazzel|tell\s+me\s+about\s+hazzel|about\s+hazzel)\b", low):
        return _fast_reply(
            messages,
            user_input,
            "Hazzel is a small terminal coding agent, not a code editor. It lives in your shell, "
            "inspects your project, edits code, and runs commands through explicit tools.",
            [],
        )
    if re.search(r"^(who\s+are\s+you|what\s+are\s+you|your\s+name|about\s+yourself|introduce\s+yourself)\b", low):
        return _fast_reply(
            messages, user_input, "I am Hazzel, a terminal coding agent developed by Mukund Jha.", []
        )
    if re.search(r"what\s+model\s+are\s+you(\s+on|\s+using|\s+running)?\b", low):
        from hazzel.config import PROVIDER_DISPLAY, get_current_display_name, get_current_provider
        model = get_current_display_name()
        provider = PROVIDER_DISPLAY.get(get_current_provider(), get_current_provider())
        return _fast_reply(
            messages,
            user_input,
            f"I am Hazzel by Mukund Jha, currently running on {model} ({provider}).",
            [],
        )

    match = re.match(r"^(?:(?:now|please)\s+)?(delete|delet|remove|rm|del)\s+(\S+?)[.!?]*\s*$", text, re.IGNORECASE)
    if match:
        target = match.group(2)
        if target.lower() in ("it", "this", "that", "them"):
            target = _LAST_TARGET
            if not target:
                return None
        if not _looks_like_path(target):
            try:
                if not resolve_project_path(target).exists():
                    return None
            except ValueError:
                return None
        return _fast_delete(messages, user_input, target)

    match = re.match(r"^(?:(?:now|please)\s+)?create\s+(?:a\s+)?(?:new\s+)?(?:file\s+)?(?:named\s+|called\s+)?(\S+?)[.!?]*\s*$", text, re.IGNORECASE)
    if match:
        target = match.group(1)
        if target.lower() in ("it", "this", "that") or not _looks_like_path(target):
            return None
        return _fast_create(messages, user_input, target)

    match = re.match(r"^(?:(?:now|please|get|give|show|display)\s+)?context\s+(?:of\s+|for\s+)?(\S+?)[.!?]*\s*$", text, re.IGNORECASE)
    if match:
        if match.group(1).lower().startswith(("http://", "https://")):
            return None
        target = match.group(1)
        if target.lower() in ("it", "this", "that"):
            target = _LAST_TARGET
            if not target:
                return None
        return _fast_read(messages, user_input, target)

    match = re.match(r"^(?:(?:now|please)\s+)?(read|show|open|cat|view)\s+(?:me\s+)?(\S+?)[.!?]*\s*$", text, re.IGNORECASE)
    if match:
        if match.group(2).lower().startswith(("http://", "https://")):
            return None
        if match.group(2).lower() == "files" and match.group(1).lower() == "show":
            return _fast_list(messages, user_input, ".")
        target = match.group(2)
        if target.lower() in ("it", "this", "that"):
            target = _LAST_TARGET
            if not target:
                return None
        return _fast_read(messages, user_input, target)

    match = re.match(r"^(?:(?:now|please)\s+)?(?:list|ls)(?:\s+files)?(?:\s+(\S+?))?[.!?]*\s*$", text, re.IGNORECASE)
    if match:
        return _fast_list(messages, user_input, match.group(1) or ".")

    match = re.match(r"^(?:(?:now|please)\s+)?(?:download|install|pip\s+install)\s+(.+?)[.!?]*\s*$", text, re.IGNORECASE)
    if match:
        pkgs = _parse_package_names(match.group(1))
        if pkgs:
            return _fast_install(messages, user_input, pkgs)

    if re.match(r"^(?:git\s+)?status[.!?]*$", low):
        result = run_tool("git_status", {})
        return _fast_reply(messages, user_input, str(result), _fast_trace("git_status", "status", str(result), True))
    if re.match(r"^(?:git\s+)?diff(?:\s+staged)?[.!?]*$", low):
        staged = "staged" in low
        result = run_tool("git_diff", {"staged": staged})
        return _fast_reply(messages, user_input, str(result), _fast_trace("git_diff", "staged" if staged else "", str(result), True))
    if re.match(r"^(?:git\s+)?log(?:\s+\S+)?[.!?]*$", low):
        from hazzel import git as _git

        ok, out = _git.log_entries(10)
        result = out if ok else "Not a git repo here."
        return _fast_reply(messages, user_input, str(result), _fast_trace("git_log", "log", str(result), True))

    match = re.match(r"^(?:(?:now|please)\s+)?(?:run|execute)\s+(.+?)\s*$", text, re.IGNORECASE)
    if match:
        command = match.group(1).strip().rstrip(".!?")
        if command:
            first = command.split()[0].lower() if command.split() else ""
            if first in ("python", "python3", "pytest", "pip", "npm", "npx", "node", "cargo", "go", "make", "git", "ls", "ruff"):
                return _fast_run(messages, user_input, command)
    return None
