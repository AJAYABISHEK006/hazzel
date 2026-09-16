import hashlib
import json
import os
import tempfile
from pathlib import Path


MAX_MESSAGES = 100
MAX_TRACE = 20
MAX_TEXT = 20000


def _session_dir():
    from . import config

    return config.CONFIG_DIR / "sessions"


def session_path(root=None):
    from . import config

    base = Path(root) if root is not None else config.PROJECT_ROOT
    try:
        key = str(base.resolve())
    except OSError:
        key = str(base)
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    return _session_dir() / f"{digest}.json"


def _clean_text(value, limit=MAX_TEXT):
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if len(value) > limit:
        return value[:limit].rstrip()
    return value


def _clean_message(msg):
    if not isinstance(msg, dict):
        return None
    role = msg.get("role")
    if role not in ("user", "assistant", "tool"):
        return None
    out = {"role": role}
    content = msg.get("content")
    if isinstance(content, str):
        out["content"] = _clean_text(content)
    elif isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(_clean_text(part, limit=4000))
            elif isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(_clean_text(part["text"], limit=4000))
        out["content"] = "\n".join(p for p in parts if p)[:MAX_TEXT]
    else:
        out["content"] = ""
    for key in ("tool_calls", "name", "tool_call_id"):
        if key in msg and isinstance(msg[key], (list, str)):
            try:
                json.dumps(msg[key])
                out[key] = msg[key]
            except (TypeError, ValueError):
                pass
    return out


def _clean_trace(trace):
    cleaned = []
    for item in (trace or [])[:MAX_TRACE]:
        if not isinstance(item, dict):
            continue
        entry = {}
        if isinstance(item.get("tool"), str):
            entry["tool"] = item["tool"][:80]
        if isinstance(item.get("detail"), str):
            entry["detail"] = item["detail"][:500]
        if isinstance(item.get("success"), bool):
            entry["success"] = item["success"]
        cleaned.append(entry)
    return cleaned


def save(messages, summary=None, trace=None, user_input=None, response=None, root=None):
    kept = []
    for msg in (messages or [])[1:]:
        cleaned = _clean_message(msg)
        if cleaned is not None:
            kept.append(cleaned)
    kept = kept[-MAX_MESSAGES:]
    data = {
        "messages": kept,
        "summary": _clean_text(summary or ""),
        "trace": _clean_trace(trace),
        "user_input": _clean_text(user_input or "", limit=4000),
        "response": _clean_text(response or ""),
    }
    path = session_path(root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(path.parent, 0o700)
        except OSError:
            pass
        fd, tmp_path = tempfile.mkstemp(dir=str(path.parent))
        os.close(fd)
        tmp = Path(tmp_path)
        try:
            tmp.write_text(json.dumps(data) + "\n", encoding="utf-8")
            os.chmod(tmp, 0o600)
            tmp.replace(path)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        finally:
            if tmp.exists() and tmp != path:
                try:
                    tmp.unlink()
                except OSError:
                    pass
    except OSError:
        return False
    return True


def backup_path(root=None):
    path = session_path(root)
    return path.with_name(path.stem + ".prev.json")


def backup(root=None):
    try:
        raw = session_path(root).read_bytes()
    except OSError:
        return False
    dst = backup_path(root)
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(dst.parent, 0o700)
        except OSError:
            pass
        fd, tmp_path = tempfile.mkstemp(dir=str(dst.parent))
        os.close(fd)
        tmp = Path(tmp_path)
        try:
            tmp.write_bytes(raw)
            os.chmod(tmp, 0o600)
            tmp.replace(dst)
            try:
                os.chmod(dst, 0o600)
            except OSError:
                pass
        finally:
            if tmp.exists() and tmp != dst:
                try:
                    tmp.unlink()
                except OSError:
                    pass
    except OSError:
        return False
    return True


def _read(path):
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    kept = []
    for msg in data.get("messages") or []:
        cleaned = _clean_message(msg)
        if cleaned is not None:
            kept.append(cleaned)
    if not kept:
        return None
    return {
        "messages": kept[-MAX_MESSAGES:],
        "summary": data.get("summary") if isinstance(data.get("summary"), str) else "",
        "trace": _clean_trace(data.get("trace")),
        "user_input": data.get("user_input") if isinstance(data.get("user_input"), str) else "",
        "response": data.get("response") if isinstance(data.get("response"), str) else "",
    }


def load(root=None):
    return _read(session_path(root))


def load_backup(root=None):
    return _read(backup_path(root))


def clear(root=None):
    try:
        session_path(root).unlink()
    except OSError:
        pass


def clear_backup(root=None):
    try:
        backup_path(root).unlink()
    except OSError:
        pass
