import json
import queue

import pytest

from hazzel import agent, config
from hazzel import mcp as mcp_mod


class FakeStdout:
    def __init__(self):
        self.q = queue.Queue()

    def readline(self):
        try:
            return self.q.get(timeout=5)
        except queue.Empty:
            return ""

    def close(self):
        pass


class FakeStdin:
    def __init__(self, stdout, behavior):
        self._stdout = stdout
        self._behavior = behavior
        self._buf = ""

    def write(self, text):
        self._buf += text
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self._respond(line)
        return len(text)

    def flush(self):
        pass

    def close(self):
        pass

    def _respond(self, line):
        if self._behavior == "silent":
            return
        try:
            req = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            return
        rid = req.get("id")
        if rid is None:
            return  # notification
        method = req.get("method")
        if method == "initialize":
            result = {"protocolVersion": "2024-11-05", "serverInfo": {"name": "fake"}}
        elif method == "tools/list":
            result = {"tools": [
                {"name": "read", "description": "Read things."},
                {"name": "odd tool!", "description": "Skipped: bad name."},
                {"name": "long", "description": "x" * 200},
            ]}
        elif method == "tools/call":
            name = (req.get("params") or {}).get("name")
            if name == "boom":
                result = {"content": [{"type": "text", "text": "it broke"}], "isError": True}
            elif name == "rich":
                result = {"content": [
                    {"type": "text", "text": "hello"},
                    {"type": "image", "data": "…"},
                    {"type": "resource", "uri": "x"},
                ]}
            else:
                result = {"content": [{"type": "text", "text": "hello from fake"}]}
        else:
            self._stdout.q.put(json.dumps({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "Method not found"}}) + "\n")
            return
        self._stdout.q.put(json.dumps({"jsonrpc": "2.0", "id": rid, "result": result}) + "\n")


class FakePopen:
    behavior = "ok"

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self._stdout = FakeStdout()
        self.stdin = FakeStdin(self._stdout, FakePopen.behavior)
        self.stdout = self._stdout
        self.pid = 1234
        self._killed = False

    def poll(self):
        return None if not self._killed else 1

    def kill(self):
        self._killed = True

    def wait(self, timeout=None):
        return 1


@pytest.fixture()
def mcp_env(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    (proj / ".hazzel").mkdir(parents=True)
    gconf = tmp_path / "global"
    gconf.mkdir()
    monkeypatch.setattr(config, "PROJECT_ROOT", proj)
    monkeypatch.setattr(config, "CONFIG_DIR", gconf)
    monkeypatch.setattr(mcp_mod.subprocess, "Popen", FakePopen)
    FakePopen.behavior = "ok"
    mcp_mod.clear_mcp_cache()
    try:
        agent.set_print_approvals(None)
    except Exception:
        pass
    yield proj, gconf
    FakePopen.behavior = "ok"
    mcp_mod.clear_mcp_cache()
    try:
        agent.set_print_approvals(None)
    except Exception:
        pass


def _write(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


def _with_server(proj, name="demo", timeout=30, extra=None):
    entry = {"command": "fake-mcp", "args": ["--x"], "timeout": timeout}
    if extra:
        entry.update(extra)
    _write(proj / ".hazzel" / "mcp.json", {"mcpServers": {name: entry}})


def test_discover_project_wins(mcp_env):
    proj, gconf = mcp_env
    _write(gconf / "mcp.json", {"mcpServers": {"demo": {"command": "global-cmd"}}})
    _with_server(proj)
    servers = mcp_mod.discover_servers()
    assert [s["name"] for s in servers] == ["demo"]
    assert servers[0]["command"] == "fake-mcp"
    assert servers[0]["source"] == "project"


def test_discover_skips_invalid(mcp_env):
    proj, _ = mcp_env
    _write(proj / ".hazzel" / "mcp.json", {"mcpServers": {
        "good": {"command": "cmd"},
        "bad name!": {"command": "cmd"},
        "nocmd": {"args": []},
        "badargs": {"command": "cmd", "args": "nope"},
        "badenv": {"command": "cmd", "env": {"K": 1}},
        "notdict": "nope",
    }})
    assert [s["name"] for s in mcp_mod.discover_servers()] == ["good"]


def test_discover_bare_map_and_bad_json(mcp_env):
    proj, _ = mcp_env
    _write(proj / ".hazzel" / "mcp.json", {"demo": {"command": "cmd"}})
    assert [s["name"] for s in mcp_mod.discover_servers()] == ["demo"]
    (proj / ".hazzel" / "mcp.json").write_text("{not json", encoding="utf-8")
    mcp_mod.clear_mcp_cache()
    assert mcp_mod.discover_servers() == []
    assert mcp_mod.mcp_prompt() == ""


def test_list_no_servers(mcp_env):
    out = agent.run_tool("mcp", {"action": "list"})
    assert "No MCP servers" in out
    assert ".hazzel/mcp.json" in out


def test_list_ok_and_name_filter(mcp_env):
    proj, _ = mcp_env
    _with_server(proj)
    out = agent.run_tool("mcp", {"action": "list"})
    assert "demo" in out and "read" in out
    assert "odd tool!" not in out  # invalid remote name skipped
    assert "…" in out  # long description truncated
    single = agent.run_tool("mcp", {"action": "list", "server": "demo"})
    assert "read" in single
    assert agent.run_tool("mcp", {"action": "list", "server": "nope_xyz"}).startswith("MCP server not found")


def test_list_unknown_suggests_close(mcp_env):
    proj, _ = mcp_env
    _with_server(proj, name="helper-srv")
    assert "helper-srv" in agent.run_tool("mcp", {"action": "list", "server": "help"})


def test_call_ok_and_variants(mcp_env):
    proj, _ = mcp_env
    _with_server(proj)
    assert "hello from fake" in agent.run_tool("mcp", {"action": "call", "server": "demo", "tool": "read", "arguments": {}})
    rich = agent.run_tool("mcp", {"action": "call", "server": "demo", "tool": "rich", "arguments": {}})
    assert "hello" in rich and "image" in rich
    err = agent.run_tool("mcp", {"action": "call", "server": "demo", "tool": "boom", "arguments": {}})
    assert err.startswith("Tool error: MCP")


def test_call_validation(mcp_env):
    proj, _ = mcp_env
    _with_server(proj)
    assert agent.run_tool("mcp", {"action": "call", "server": "nope_xyz", "tool": "read"}).startswith("MCP server not found")
    assert agent.run_tool("mcp", {"action": "call", "server": "demo", "tool": "bad name!"}).startswith("Invalid MCP tool name")
    assert agent.run_tool("mcp", {"action": "call", "server": "demo"}).startswith("Usage:")
    assert agent.run_tool("mcp", {"action": "call"}).startswith("Usage:")
    assert agent.run_tool("mcp", {"action": "frobnicate"}).startswith("Usage:")


def test_spawn_failure_is_stable(mcp_env, monkeypatch):
    proj, _ = mcp_env
    _with_server(proj)

    def _boom(*args, **kwargs):
        raise OSError("no such binary")

    monkeypatch.setattr(mcp_mod.subprocess, "Popen", _boom)
    out = agent.run_tool("mcp", {"action": "call", "server": "demo", "tool": "read", "arguments": {}})
    assert out.startswith("Tool error: MCP")
    assert "no such binary" in out


def test_call_timeout(mcp_env):
    proj, _ = mcp_env
    _with_server(proj, timeout=1)
    FakePopen.behavior = "silent"
    out = agent.run_tool("mcp", {"action": "call", "server": "demo", "tool": "read", "arguments": {}})
    assert "timed out" in out


def test_plan_blocks_call_not_list(mcp_env, monkeypatch):
    proj, _ = mcp_env
    _with_server(proj)
    monkeypatch.setattr(config, "is_plan_enabled", lambda: True)
    assert "Blocked: plan mode" in agent.run_tool("mcp", {"action": "call", "server": "demo", "tool": "read", "arguments": {}})
    assert "demo" in agent.run_tool("mcp", {"action": "list"})
    assert any(t["function"]["name"] == "mcp" for t in agent._active_tools())


def test_print_readonly_blocks_call(mcp_env):
    proj, _ = mcp_env
    _with_server(proj)
    agent.set_print_approvals(False)
    try:
        assert "read-only" in agent.run_tool("mcp", {"action": "call", "server": "demo", "tool": "read", "arguments": {}})
        assert "demo" in agent.run_tool("mcp", {"action": "list"})
    finally:
        agent.set_print_approvals(None)


def test_agent_registers_mcp_tool():
    assert "mcp" in agent.TOOL_NAMES
    assert "mcp" in agent.PLAN_TOOL_NAMES
    assert "mcp" not in agent.PARALLEL_SAFE  # sequential: third-party side effects
    assert agent._normalize_tool_name("mcplist") == "mcp"
    schema = next(t for t in agent.TOOLS if t["function"]["name"] == "mcp")
    assert "mcp" in schema["function"]["description"].lower()
    coerced = agent._coerce_tool_args("mcp", {"op": "call", "name": "s", "tool_name": "t", "args": {"a": 1}})
    assert (coerced["action"], coerced["server"], coerced["tool"], coerced["arguments"]) == ("call", "s", "t", {"a": 1})
    detail = agent._tool_detail("mcp", {"action": "call", "server": "s", "tool": "t"})
    assert detail == "call s/t"
    assert agent._tool_cache_key("mcp", {"action": "list", "server": "s"}, "list s") is not None
    assert agent._tool_cache_key("mcp", {"action": "call", "server": "s"}, "call s") is None


def test_prompt_needs_no_spawn(mcp_env, monkeypatch):
    proj, _ = mcp_env
    _with_server(proj)

    def _boom(*args, **kwargs):
        raise AssertionError("must not spawn for prompt")

    monkeypatch.setattr(mcp_mod.subprocess, "Popen", _boom)
    prompt = mcp_mod.mcp_prompt()
    assert "demo" in prompt and "mcp(action=list)" in prompt
