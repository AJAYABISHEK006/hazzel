"""Minimal MCP (Model Context Protocol) stdio transport — stdlib only.

A configured server is a command Hazzel spawns over JSON-RPC 2.0 on stdio::

    {"mcpServers": {"myserver": {"command": "npx", "args": ["-y", "..."],
                                 "env": {"KEY": "val"}, "timeout": 30}}}

Config files (project wins on name clash):

- ``<project>/.hazzel/mcp.json``
- ``~/.config/hazzel/mcp.json`` (``XDG_CONFIG_HOME`` aware)

The agent sees a single ``mcp`` tool (skill-like): ``list`` discovers
servers/tools read-only, ``call`` runs one remote tool. Processes spawn
lazily on first use — never at startup — and are reaped on exit.
"""

from __future__ import annotations

import atexit
import json
import os
import queue
import re
import subprocess
import threading
import time
from pathlib import Path

MCP_FILENAME = "mcp.json"
PROTOCOL_VERSION = "2024-11-05"

DEFAULT_TIMEOUT = 30.0
MAX_TIMEOUT = 120.0
MIN_TIMEOUT = 1.0

MAX_SERVERS = 32
MAX_TOOLS_PER_SERVER = 64
MAX_CATALOG_TOOLS = 40
MAX_DESC_CHARS = 100
MAX_RESULT_CHARS = 5000

_CATALOG_TTL = 30.0

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_TOOL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def _coerce_timeout(value):
    try:
        timeout = float(value)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT
    if timeout != timeout:  # NaN
        return DEFAULT_TIMEOUT
    if timeout < MIN_TIMEOUT:
        return MIN_TIMEOUT
    if timeout > MAX_TIMEOUT:
        return MAX_TIMEOUT
    return timeout


def _config_paths():
    from . import config as _cfg

    return [
        (_cfg.PROJECT_ROOT / ".hazzel" / MCP_FILENAME, "project"),
        (_cfg.CONFIG_DIR / MCP_FILENAME, "global"),
    ]


def _read_config_file(path):
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    # Accept both {"mcpServers": {...}} and a bare {"name": {...}} map.
    servers = data.get("mcpServers", data)
    if not isinstance(servers, dict):
        return {}
    return servers


def _clean_entry(name, raw):
    if not isinstance(raw, dict):
        return None
    command = raw.get("command")
    if not isinstance(command, str) or not command.strip():
        return None
    args = raw.get("args", [])
    if args is None:
        args = []
    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        return None
    env = raw.get("env", {})
    if env is None:
        env = {}
    if not isinstance(env, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
        return None
    return {
        "name": name,
        "command": command.strip(),
        "args": list(args),
        "env": dict(env),
        "timeout": _coerce_timeout(raw.get("timeout", DEFAULT_TIMEOUT)),
    }


_config_cache = {"ts": 0.0, "servers": []}


def discover_servers():
    """Configured MCP servers (project wins on clash). Never spawns."""
    now = time.monotonic()
    if _config_cache["servers"] and now - _config_cache["ts"] < _CATALOG_TTL:
        return list(_config_cache["servers"])
    seen = {}
    for path, source in _config_paths():
        for name, raw in _read_config_file(path).items():
            if not isinstance(name, str) or not _NAME_RE.match(name):
                continue
            if name in seen:
                continue
            entry = _clean_entry(name, raw)
            if entry is None:
                continue
            entry["source"] = source
            seen[name] = entry
            if len(seen) >= MAX_SERVERS:
                break
        if len(seen) >= MAX_SERVERS:
            break
    servers = sorted(seen.values(), key=lambda s: s["name"].lower())
    _config_cache.update({"ts": now, "servers": servers})
    return list(servers)


def find_server(name):
    clean = (name or "").strip().strip("'\"")
    if not clean:
        return None
    return next((s for s in discover_servers() if s["name"] == clean), None)


def _client_version():
    try:
        from importlib.metadata import version as _pkg_version

        return _pkg_version("hazzel")
    except Exception:
        try:
            from hazzel import __version__ as _ver

            return _ver
        except Exception:
            return "0.0.0"


class _ServerConn:
    """One lazily-spawned MCP stdio process. Single-flight via _lock."""

    def __init__(self, spec):
        self.spec = spec
        self._lock = threading.RLock()
        self._proc = None
        self._reader = None
        self._lines: queue.Queue[str] = queue.Queue()
        self._next_id = 0
        self._tools = None
        self._tools_ts = 0.0

    def _alive(self):
        return self._proc is not None and self._proc.poll() is None

    def _kill(self):
        proc = self._proc
        self._proc = None
        self._reader = None
        self._tools = None
        if proc is not None:
            try:
                proc.kill()
            except Exception:
                pass
            try:
                for stream in (getattr(proc, "stdin", None), getattr(proc, "stdout", None)):
                    try:
                        if stream is not None:
                            stream.close()
                    except Exception:
                        pass
            except Exception:
                pass

    def _read_loop(self, proc):
        try:
            while True:
                try:
                    line = proc.stdout.readline()
                except Exception:
                    break
                if not line:
                    break
                self._lines.put(line)
        except Exception:
            pass

    def _spawn(self):
        from . import config as _cfg
        from . import wincompat as _win

        self._kill()
        # Drain stale responses from a previous process.
        try:
            while True:
                self._lines.get_nowait()
        except queue.Empty:
            pass
        env = dict(os.environ)
        env.update(self.spec["env"])
        try:
            proc = subprocess.Popen(
                [self.spec["command"]] + self.spec["args"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
                cwd=str(_cfg.PROJECT_ROOT),
                env=env,
                **_win.popen_kwargs(),
            )
        except (OSError, ValueError) as error:
            raise RuntimeError(f"could not start `{self.spec['command']}` ({error})")
        self._proc = proc
        reader = threading.Thread(target=self._read_loop, args=(proc,), daemon=True)
        self._reader = reader
        reader.start()
        # initialize handshake (tolerant: any result is accepted).
        try:
            self._request_locked(
                "initialize",
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "hazzel", "version": _client_version()},
                },
                timeout=self.spec["timeout"],
                _handshake=True,
            )
        except Exception:
            self._kill()
            raise
        try:
            note = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
            proc.stdin.write(note)
            proc.stdin.flush()
        except Exception:
            self._kill()
            raise RuntimeError("handshake failed (initialized not accepted)")

    def _request_locked(self, method, params, timeout, _handshake=False):
        if not self._alive():
            if _handshake:
                pass  # already in _spawn; proc exists but handshake uses it directly
            else:
                self._spawn()
        proc = self._proc
        if proc is None:
            raise RuntimeError("server is not running")
        self._next_id += 1
        rid = self._next_id
        try:
            proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}) + "\n")
            proc.stdin.flush()
        except Exception:
            self._kill()
            raise RuntimeError("server write failed (crashed or closed stdin)")
        deadline = time.monotonic() + max(MIN_TIMEOUT, float(timeout))
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._kill()
                raise TimeoutError(f"timed out after {timeout:g} seconds")
            try:
                line = self._lines.get(timeout=remaining)
            except queue.Empty:
                self._kill()
                raise TimeoutError(f"timed out after {timeout:g} seconds")
            if not isinstance(line, str) or not line.strip():
                continue
            try:
                msg = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue  # ignore non-JSON stdout chatter
            if not isinstance(msg, dict) or msg.get("id") != rid:
                continue  # notification or another call; single-flight so skip
            if "error" in msg and msg["error"] is not None:
                err = msg["error"]
                detail = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                raise RuntimeError(detail or "server error")
            return msg.get("result")

    def request(self, method, params=None, timeout=None):
        with self._lock:
            if not self._alive():
                self._spawn()
            try:
                return self._request_locked(method, params or {}, timeout or self.spec["timeout"])
            except (TimeoutError, RuntimeError):
                raise
            except Exception as error:
                self._kill()
                raise RuntimeError(str(error) or "request failed")


_registry_lock = threading.Lock()
_registry: dict[str, _ServerConn] = {}


def _conn(spec):
    with _registry_lock:
        conn = _registry.get(spec["name"])
        if conn is None or conn.spec != spec:
            old = _registry.pop(spec["name"], None)
            if old is not None:
                try:
                    with old._lock:
                        old._kill()
                except Exception:
                    pass
            conn = _ServerConn(spec)
            _registry[spec["name"]] = conn
        return conn


def _clean_tools(result):
    tools = []
    items = []
    if isinstance(result, dict):
        items = result.get("tools", [])
    if not isinstance(items, list):
        return []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not isinstance(name, str) or not _TOOL_RE.match(name):
            continue
        desc = item.get("description", "")
        if not isinstance(desc, str):
            desc = ""
        desc = " ".join(desc.split())
        if len(desc) > MAX_DESC_CHARS:
            desc = desc[: MAX_DESC_CHARS - 1].rstrip() + "…"
        tools.append({"name": name, "description": desc})
        if len(tools) >= MAX_TOOLS_PER_SERVER:
            break
    return tools


def list_server_tools(server_name):
    """(tools, error) for one server; spawns it on first use."""
    spec = find_server(server_name)
    if spec is None:
        return None, f"MCP server not found: {server_name}."
    conn = _conn(spec)
    now = time.monotonic()
    if conn._tools is not None and now - conn._tools_ts < _CATALOG_TTL:
        return list(conn._tools), None
    try:
        result = conn.request("tools/list", {}, timeout=spec["timeout"])
    except (TimeoutError, RuntimeError) as error:
        return None, f"MCP server `{spec['name']}` failed: {error}."
    except Exception as error:
        return None, f"MCP server `{spec['name']}` failed: {error}."
    tools = _clean_tools(result)
    conn._tools = tools
    conn._tools_ts = now
    return list(tools), None


def _flatten_call_result(result):
    if isinstance(result, dict) and isinstance(result.get("content"), list):
        parts = []
        for block in result["content"]:
            if not isinstance(block, dict):
                continue
            kind = block.get("type")
            if kind == "text" and isinstance(block.get("text"), str):
                parts.append(block["text"])
            elif kind == "image":
                parts.append("[image content omitted]")
            elif kind == "resource":
                parts.append("[resource content omitted]")
        text = "\n".join(p for p in parts if p.strip()).strip()
        if isinstance(result.get("isError"), bool) and result["isError"]:
            return (text or "(empty error result)", True)
        return (text or "(empty result)", False)
    if isinstance(result, dict):
        try:
            return json.dumps(result)[:MAX_RESULT_CHARS], False
        except (TypeError, ValueError):
            return str(result)[:MAX_RESULT_CHARS], False
    return str(result or "(empty result)")[:MAX_RESULT_CHARS], False


def call_server_tool(server_name, tool_name, arguments=None):
    spec = find_server(server_name)
    if spec is None:
        return f"MCP server not found: {server_name}."
    if not isinstance(tool_name, str) or not _TOOL_RE.match(tool_name.strip()):
        return f"Invalid MCP tool name: {tool_name}."
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        return "Invalid MCP arguments: pass an object."
    conn = _conn(spec)
    try:
        result = conn.request("tools/call", {"name": tool_name.strip(), "arguments": arguments}, timeout=spec["timeout"])
    except (TimeoutError, RuntimeError) as error:
        return f"Tool error: MCP `{spec['name']}` failed ({error})."
    except Exception as error:
        return f"Tool error: MCP `{spec['name']}` failed ({error})."
    text, is_error = _flatten_call_result(result)
    if len(text) > MAX_RESULT_CHARS:
        text = text[: MAX_RESULT_CHARS - 700] + f"\n[…{len(text) - MAX_RESULT_CHARS} chars skipped…]\n" + text[-700:]
    if is_error:
        return f"Tool error: MCP `{tool_name.strip()}` reported an error:\n{text}"
    return text or "(empty result)"


def list_all():
    servers = discover_servers()
    if not servers:
        return (
            "No MCP servers configured. Add one in .hazzel/mcp.json:\n"
            '{"mcpServers": {"myserver": {"command": "npx", "args": ["-y", "pkg"], "timeout": 30}}}'
        )
    out = [f"MCP servers ({len(servers)}): " + ", ".join(s["name"] for s in servers)]
    shown = 0
    for spec in servers:
        tools, error = list_server_tools(spec["name"])
        if error is not None:
            out.append(f"- {spec['name']}: ({error})")
            continue
        if not tools:
            out.append(f"- {spec['name']}: no tools")
            continue
        out.append(f"- {spec['name']} ({len(tools)} tool{'s' if len(tools) != 1 else ''}):")
        for tool in tools:
            if shown >= MAX_CATALOG_TOOLS:
                break
            desc = f": {tool['description']}" if tool["description"] else ""
            out.append(f"  - {tool['name']}{desc}")
            shown += 1
        if shown >= MAX_CATALOG_TOOLS:
            out.append(f"  […{sum(1 for _ in servers)} servers capped at {MAX_CATALOG_TOOLS} tools…]")
            break
    return "\n".join(out)


def mcp_tool(action="list", server="", tool="", arguments=None):
    act = (action or "list").strip().lower()
    if act in ("servers", "ls", "tools"):
        act = "list"
    if act not in ("list", "call"):
        return "Usage: mcp(action=list|call, server=<name>, tool=<name>, arguments={}). List first, then call."
    if act == "list":
        if (server or "").strip():
            spec = find_server(server)
            if spec is None:
                close = [s["name"] for s in discover_servers() if server.strip().lower() in s["name"].lower()]
                hint = f" Did you mean: {', '.join(close[:3])}?" if close else ""
                return f"MCP server not found: {server.strip()}.{hint}"
            tools, error = list_server_tools(spec["name"])
            if error is not None:
                return f"MCP server `{spec['name']}` failed: {error}."
            if not tools:
                return f"MCP server `{spec['name']}`: no tools."
            rows = [f"MCP `{spec['name']}` tools ({len(tools)}):"]
            for t in tools:
                desc = f": {t['description']}" if t["description"] else ""
                rows.append(f"- {t['name']}{desc}")
            return "\n".join(rows)
        return list_all()
    if not (server or "").strip():
        return "Usage: mcp(action=call, server=<name>, tool=<name>, arguments={})."
    if not (tool or "").strip():
        return "Usage: mcp(action=call, server=<name>, tool=<name>, arguments={})."
    return call_server_tool(server.strip(), tool.strip(), arguments if isinstance(arguments, dict) else {})


def mcp_prompt():
    """Catalog note for the system prompt. Never spawns servers."""
    servers = discover_servers()
    if not servers:
        return ""
    names = ", ".join(s["name"] for s in servers)
    lines = [
        "\n\nMCP (external servers, configured): " + names + ".",
        "Call mcp(action=list) to see their tools (read-only), "
        "mcp(action=call, server, tool, arguments) to run one. "
        "Prefer local read/search tools for repo files; use MCP for what they provide.",
    ]
    # Include freshly cached tool names only — no spawning here.
    cached = []
    for spec in servers:
        conn = _registry.get(spec["name"])
        if conn is None or conn._tools is None:
            continue
        if time.monotonic() - conn._tools_ts >= _CATALOG_TTL:
            continue
        for tool in conn._tools[:8]:
            cached.append(f"{spec['name']}/{tool['name']}")
        if len(cached) >= MAX_CATALOG_TOOLS:
            break
    if cached:
        lines.append("Known MCP tools: " + ", ".join(cached) + ".")
    return "\n".join(lines)


def clear_mcp_cache():
    _config_cache.update({"ts": 0.0, "servers": []})
    with _registry_lock:
        conns = list(_registry.values())
        _registry.clear()
    for conn in conns:
        try:
            with conn._lock:
                conn._kill()
        except Exception:
            pass


def shutdown():
    with _registry_lock:
        conns = list(_registry.values())
        _registry.clear()
    for conn in conns:
        try:
            with conn._lock:
                conn._kill()
        except Exception:
            pass


try:
    atexit.register(shutdown)
except Exception:
    pass
