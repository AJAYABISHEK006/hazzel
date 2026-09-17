import shutil
import subprocess

import pytest

from hazzel import agent, config
from hazzel import git as git_mod
from hazzel import ui as ui_mod
from hazzel.git_suggest import heuristic_message
from hazzel.tools import run_command as rc
from hazzel.tools.git_commit import git_commit
from hazzel.tools.git_diff import git_diff
from hazzel.tools.git_status import git_status

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git binary required")


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    env = {"GIT_CONFIG_NOSYSTEM": "1", "HOME": str(tmp_path)}
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True, env={**dict(__import__("os").environ), **env})
    subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True, capture_output=True)
    (root / "a.txt").write_text("one\n")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=root, check=True, capture_output=True)
    monkeypatch.setattr(git_mod, "PROJECT_ROOT", root)
    monkeypatch.setattr(config, "PROJECT_ROOT", root)
    yield root


def test_status_clean_and_dirty(repo):
    out = git_status()
    assert "a.txt" not in out
    (repo / "a.txt").write_text("one\ntwo\n")
    ok, out, branch = git_mod.status_porcelain()
    assert ok and "a.txt" in out and branch == git_mod.branch_current()


def test_status_outside_repo(tmp_path, monkeypatch):
    monkeypatch.setattr(git_mod, "PROJECT_ROOT", tmp_path / "plain")
    (tmp_path / "plain").mkdir()
    assert "Not a git repo" in git_status()


def test_diff_unstaged_staged_and_clean(repo):
    assert git_diff() == "No changes."
    (repo / "a.txt").write_text("one\ntwo\n")
    out = git_diff()
    assert "1 files changed" in out and "+two" in out
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    assert git_diff() == "No changes."
    assert "1 files changed" in git_diff(staged=True)


def test_changed_files_tracks_untracked(repo):
    (repo / "new.txt").write_text("hello\n")
    ok, files, err = git_mod.changed_files(False)
    assert ok and err == ""
    hit = next(f for f in files if f["key"] == "new.txt")
    assert hit["status"] == "?" and hit["added"] == 1


def test_diff_file_tracked_and_untracked(repo):
    (repo / "a.txt").write_text("one\ntwo\n")
    ok, body = git_mod.diff_file("a.txt")
    assert ok and "+two" in body
    (repo / "fresh.txt").write_text("hi\n")
    ok, body = git_mod.diff_file("fresh.txt")
    assert ok and "+++ b/fresh.txt" in body and "+hi" in body
    assert git_mod.diff_file("../escape")[0] is False


def test_log_shows_history(repo):
    ok, out = git_mod.log_entries(5)
    assert ok and "init" in out


def test_commit_tool_explicit_message(repo, monkeypatch):
    monkeypatch.setattr(ui_mod, "confirm", lambda *a: True)
    monkeypatch.setattr(ui_mod, "show_diff", lambda *a: None)
    (repo / "a.txt").write_text("one\ntwo\n")
    out = git_commit("feat: add two")
    assert out.startswith("[") and "feat" in out
    assert git_diff() == "No changes."
    assert git_commit("x") == "Nothing to commit — working tree clean."


def test_commit_tool_validates(repo, monkeypatch):
    monkeypatch.setattr(ui_mod, "confirm", lambda *a: True)
    monkeypatch.setattr(ui_mod, "show_diff", lambda *a: None)
    (repo / "a.txt").write_text("dirty\n")
    assert git_commit("x" * 501).startswith("Tool error: commit message too long")
    assert git_commit("msg", files="../outside").startswith("Path is outside the project root: ../outside.")
    assert "did not match" in git_commit("msg", files="nope")


def test_commit_suggest_flow_cancel_and_accept(repo, monkeypatch):
    from hazzel import git_suggest as gs

    monkeypatch.setattr(gs, "suggest_message", lambda *a: ("feat: mocked", False))
    monkeypatch.setattr(ui_mod, "show_loader", lambda *a: None)
    monkeypatch.setattr(ui_mod, "end_turn", lambda: None)
    monkeypatch.setattr(ui_mod, "show_git_suggest", lambda *a: None)
    (repo / "a.txt").write_text("change\n")
    monkeypatch.setattr(ui_mod, "prompt_suggest_action", lambda: "n")
    assert git_commit(None) == "Commit cancelled by user"
    monkeypatch.setattr(ui_mod, "prompt_suggest_action", lambda: "y")
    out = git_commit("suggest")
    assert "mocked" in out


def test_heuristic_message():
    assert heuristic_message("", "") == "chore: update working tree"
    assert heuristic_message(" M a.txt", "diff --git a/a.txt") == "chore(a): update a.txt"
    assert "2 files" in heuristic_message(" M a.txt\n M b.py", "")


def test_agent_registers_git_tools():
    for name in ("git_status", "git_diff", "git_commit"):
        assert name in agent.TOOL_NAMES
    for name in ("git_status", "git_diff"):
        assert name in agent.PLAN_TOOL_NAMES
    assert "git_commit" not in agent.PLAN_TOOL_NAMES
    assert "git_status" in agent.PARALLEL_SAFE and "git_diff" in agent.PARALLEL_SAFE
    assert agent._normalize_tool_name("status") == "git_status"
    assert agent._normalize_tool_name("diff") == "git_diff"
    assert agent._normalize_tool_name("commit") == "git_commit"
    schema = next(t for t in agent.TOOLS if t["function"]["name"] == "git_commit")
    assert "git commit" in schema["function"]["description"]


def test_plan_guards(repo, monkeypatch):
    monkeypatch.setattr(config, "is_plan_enabled", lambda: True)
    try:
        assert agent.run_tool("git_commit", {"message": "x"}).startswith("Blocked: plan mode")
        assert "Blocked" not in agent.run_tool("git_status", {})
        assert "Blocked" not in agent.run_tool("git_diff", {})
        assert any(t["function"]["name"] == "git_diff" for t in agent._active_tools())
    finally:
        monkeypatch.setattr(config, "is_plan_enabled", lambda: False)


def test_print_guards(repo):
    agent.set_print_approvals(False)
    try:
        assert "read-only" in agent.run_tool("git_commit", {"message": "x"})
        assert "Blocked" not in agent.run_tool("git_status", {})
    finally:
        agent.set_print_approvals(None)


def test_raw_git_writes_blocked():
    assert agent.run_tool("run_command", {"command": "git commit -m x"}).startswith("Blocked: use git_commit")
    assert agent.run_tool("run_command", {"command": "git reset --hard"}).startswith("Blocked: use git_commit")
    assert agent.run_tool("run_command", {"command": "git clean -fd"}).startswith("Blocked: use git_commit")


def test_safe_git_reads_skip_approval():
    assert rc.is_safe_command("git status") is True
    assert rc.is_safe_command("git diff --staged") is True
    assert rc.is_safe_command("git log --oneline") is True
    assert rc.is_safe_command("git push") is False
    assert rc.is_safe_command("git commit -m x") is False


def test_fastpath_git(repo):
    msgs = [{"role": "system", "content": "x"}]
    reply, trace, _ = agent.try_fast_path(msgs, "status")
    assert trace and trace[0]["tool"] == "git_status"
    assert "a.txt" not in reply
    (repo / "a.txt").write_text("one\ntwo\n")
    reply, trace, _ = agent.try_fast_path([{"role": "system", "content": "x"}], "git diff")
    assert trace[0]["tool"] == "git_diff" and "+two" in reply
    reply, trace, _ = agent.try_fast_path([{"role": "system", "content": "x"}], "log")
    assert trace[0]["tool"] == "git_log" and "init" in reply


def test_git_ui_renders(capsys):
    ui_mod.show_git_status("main", "## main\n M a.txt\n?? new.txt")
    out = capsys.readouterr().out
    assert "Git status" in out and "a.txt" in out
    ui_mod.show_git_status("main", "(clean)")
    assert "Clean" in capsys.readouterr().out
    ui_mod.show_git_log("abc1234 init\ndef5678 second")
    out = capsys.readouterr().out
    assert "Recent commits" in out and "abc1234" in out
    ui_mod.show_git_log("59bfbc0 (HEAD -> main, origin/main, tag: v1.4.7) feat(mcp): minimal stdio", "main")
    out = capsys.readouterr().out
    assert "→" in out and "main" in out and "v1.4.7" in out
    ui_mod.show_git_log("")
    assert "No commits yet" in capsys.readouterr().out
    ui_mod.show_git_commit("Nothing to commit — working tree clean.")
    assert "Nothing to commit" in capsys.readouterr().out


def test_git_diff_ui_renders(capsys):
    files = [
        {"path": "src/hazzel/ui.py", "key": "src/hazzel/ui.py", "status": "M", "added": 118, "deleted": 27},
        {"path": "new.txt", "key": "new.txt", "status": "?", "added": 2, "deleted": 0},
    ]
    ui_mod.show_git_file_list(files, False, "main")
    out = capsys.readouterr().out
    assert "Changed files" in out and "main" in out
    assert "src/hazzel/ui.py" in out and "+118" in out
    ui_mod.show_git_file_list([], False, "main")
    assert "No changes." in capsys.readouterr().out
    body = "diff --git a/x.py b/x.py\n@@ -1 +1 @@\n-old\n+new\n"
    ui_mod.show_git_file_diff("x.py", body, False, "1/2 ")
    out = capsys.readouterr().out
    assert "1/2 x.py" in out and "+1" in out and "−1" in out
    assert "@@" in out and "+new" in out
    ui_mod.show_diff("a\n" * 600)
    out = capsys.readouterr().out
    assert "capped for display" in out


def test_prompt_diff_selection(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *a: "2")
    assert ui_mod.prompt_diff_selection(3) == 1
    monkeypatch.setattr("builtins.input", lambda *a: "q")
    assert ui_mod.prompt_diff_selection(3) is None
    monkeypatch.setattr("builtins.input", lambda *a: "99")
    assert ui_mod.prompt_diff_selection(3) == "invalid"


def test_slash_palette_finds_git():
    names = [c["name"] for c in ui_mod._filter_slash_commands("/sta")]
    assert "/status" in names
    names = [c["name"] for c in ui_mod._filter_slash_commands("/omm")]
    assert "/commit" in names
