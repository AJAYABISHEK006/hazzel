import shutil
import subprocess
from types import SimpleNamespace

import pytest

from hazzel import config, review, safety
from hazzel import git as git_mod
from hazzel import providers as providers_mod

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


class FakeProvider:
    """Stands in for a provider adapter; records the request it received."""

    def __init__(self, content="", error=None):
        self.content = content
        self.error = error
        self.calls = []

    def chat(self, messages, tools=None, **kwargs):
        self.calls.append({"messages": messages, "tools": tools})
        if self.error:
            raise self.error
        return SimpleNamespace(content=self.content)


def _use_provider(monkeypatch, provider):
    monkeypatch.setattr(providers_mod, "get_provider", lambda: provider)
    return provider


def _fake_files(count, prefix="f"):
    return [
        {"path": f"{prefix}{i}.py", "key": f"{prefix}{i}.py", "status": "M", "added": 1, "deleted": 0}
        for i in range(count)
    ]


def test_collect_diff_reads_working_tree(repo):
    (repo / "a.txt").write_text("one\ntwo\n")
    files, diff, error = review.collect_diff()
    assert error == ""
    assert [f["path"] for f in files] == ["a.txt"]
    assert "+two" in diff


def test_collect_diff_clean_tree(repo):
    files, diff, error = review.collect_diff()
    assert (files, diff, error) == ([], "", "")


def test_collect_diff_outside_repo(tmp_path, monkeypatch):
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.setattr(git_mod, "PROJECT_ROOT", plain)
    _files, diff, error = review.collect_diff()
    assert diff == ""
    assert "Not a git repo" in error


def test_collect_diff_caps_file_count(monkeypatch):
    monkeypatch.setattr(git_mod, "changed_files", lambda staged=False: (True, _fake_files(30), ""))
    monkeypatch.setattr(git_mod, "diff_file", lambda key, staged=False: (True, f"+{key}"))
    files, diff, error = review.collect_diff()
    assert error == ""
    assert len(files) == 30
    assert diff.count("--- f") == review.MAX_REVIEW_FILES
    assert "10 more changed file(s) not shown" in diff


def test_collect_diff_caps_total_chars(monkeypatch):
    monkeypatch.setattr(git_mod, "changed_files", lambda staged=False: (True, _fake_files(30), ""))
    monkeypatch.setattr(git_mod, "diff_file", lambda key, staged=False: (True, "x" * 3000))
    _files, diff, _error = review.collect_diff()
    assert diff.count("--- f") < review.MAX_REVIEW_FILES
    assert "more changed file(s) not shown" in diff


def test_collect_diff_truncates_one_huge_file(monkeypatch):
    monkeypatch.setattr(git_mod, "changed_files", lambda staged=False: (True, _fake_files(1), ""))
    monkeypatch.setattr(git_mod, "diff_file", lambda key, staged=False: (True, "x" * 5000))
    _files, diff, _error = review.collect_diff()
    assert "[…file diff truncated…]" in diff
    assert len(diff) < 5000


def test_collect_diff_passes_staged_flag(monkeypatch):
    seen = {}

    def fake_changed(staged=False):
        seen["staged"] = staged
        return True, _fake_files(1), ""

    monkeypatch.setattr(git_mod, "changed_files", fake_changed)
    monkeypatch.setattr(git_mod, "diff_file", lambda key, staged=False: (True, "+x"))
    review.collect_diff(staged=True)
    assert seen["staged"] is True


def test_collect_diff_ignores_unreadable_file(monkeypatch):
    monkeypatch.setattr(git_mod, "changed_files", lambda staged=False: (True, _fake_files(2), ""))
    monkeypatch.setattr(
        git_mod,
        "diff_file",
        lambda key, staged=False: (False, "boom") if key == "f0.py" else (True, "+ok"),
    )
    _files, diff, error = review.collect_diff()
    assert error == ""
    assert "f0.py" not in diff and "f1.py" in diff


def test_build_prompt_includes_scope_and_files():
    files = [{"path": "a.py", "status": "M", "added": 2, "deleted": 1}]
    staged = review.build_prompt(files, "DIFFBODY", staged=True)
    assert "staged changes" in staged
    assert "a.py" in staged and "+2 −1" in staged and "DIFFBODY" in staged
    assert "uncommitted working-tree changes" in review.build_prompt(files, "DIFFBODY")


def test_heuristic_flags_risks_and_gaps():
    files = [{"path": "src/app.py", "status": "M", "added": 3, "deleted": 1}]
    diff = "+++ b/src/app.py\n+def f():\n+    breakpoint()\n+except Exception: pass\n"
    out = review.heuristic_review(files, diff)
    assert "breakpoint()" in out
    assert "swallows errors silently" in out
    assert "no test file changed" in out
    assert "`CHANGELOG.md` not updated" in out


def test_heuristic_clean_when_tests_and_changelog_touched():
    files = [
        {"path": "tests/test_app.py", "status": "M", "added": 5, "deleted": 0},
        {"path": "CHANGELOG.md", "status": "M", "added": 1, "deleted": 0},
    ]
    out = review.heuristic_review(files, "+++ b/CHANGELOG.md\n+- fix a thing\n")
    assert "nothing flagged" in out
    assert "nothing obvious" in out


def test_heuristic_reports_totals_and_long_lines():
    files = [{"path": "src/a.py", "status": "M", "added": 2, "deleted": 3}]
    out = review.heuristic_review(files, "+" + "y" * 300 + "\n")
    assert "+2 −3" in out
    assert "added line over 200 chars" in out


def test_heuristic_ignores_markers_inside_string_literals():
    files = [{"path": "src/markers.py", "status": "M", "added": 2, "deleted": 0}]
    diff = '+MARKERS = ("breakpoint()", "console.log(")\n+doc = "call breakpoint() to stop"\n'
    out = review.heuristic_review(files, diff)
    assert "nothing flagged" in out
    assert "**Notes**" not in out


def test_heuristic_ignores_markers_in_escaped_strings():
    files = [{"path": "tests/test_x.py", "status": "M", "added": 1, "deleted": 0}]
    diff = '+    diff = "+++ b/a.py\\n+    breakpoint()\\n"\n'
    out = review.heuristic_review(files, diff)
    assert "nothing flagged" in out


def test_heuristic_reports_todo_notes_separately():
    files = [{"path": "src/a.py", "status": "M", "added": 1, "deleted": 0}]
    out = review.heuristic_review(files, "+# TODO: wire this up\n")
    assert "nothing flagged" in out
    assert "**Notes** — 1 added TODO/FIXME-style comment(s)." in out


def test_heuristic_omits_notes_when_no_todos():
    files = [{"path": "src/a.py", "status": "M", "added": 1, "deleted": 0}]
    assert "**Notes**" not in review.heuristic_review(files, "+value = 1\n")


def test_review_uses_model_output(monkeypatch, repo):
    (repo / "a.txt").write_text("one\ntwo\n")
    provider = _use_provider(monkeypatch, FakeProvider("**Summary** — mocked review"))
    files, markdown, fallback, error = review.review_working_tree()
    assert error == ""
    assert fallback is False
    assert markdown == "**Summary** — mocked review"
    assert files
    assert provider.calls[0]["tools"] == []
    assert "a.txt" in provider.calls[0]["messages"][1]["content"]


def test_review_prompt_shape(monkeypatch, repo):
    (repo / "a.txt").write_text("one\ntwo\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    provider = _use_provider(monkeypatch, FakeProvider("ok"))
    review.review_working_tree(staged=True)
    messages = provider.calls[0]["messages"]
    assert [m["role"] for m in messages] == ["system", "user"]
    assert messages[0]["content"] == review.REVIEW_SYSTEM
    assert "staged changes" in messages[1]["content"]
    assert "+two" in messages[1]["content"]


def test_review_falls_back_when_provider_raises(monkeypatch, repo):
    (repo / "a.txt").write_text("one\ntwo\n")
    _use_provider(monkeypatch, FakeProvider(error=RuntimeError("no key")))
    files, markdown, fallback, error = review.review_working_tree()
    assert error == ""
    assert fallback is True
    assert "**Summary**" in markdown and "heuristics" in markdown
    assert files


def test_review_falls_back_on_empty_reply(monkeypatch, repo):
    (repo / "a.txt").write_text("x\n")
    _use_provider(monkeypatch, FakeProvider("   "))
    _files, _markdown, fallback, _error = review.review_working_tree()
    assert fallback is True


def test_review_clean_tree_skips_model(monkeypatch, repo):
    provider = _use_provider(monkeypatch, FakeProvider("should not be used"))
    files, markdown, fallback, error = review.review_working_tree()
    assert (files, markdown, fallback, error) == ([], "", False, "")
    assert provider.calls == []


def test_review_outside_repo_reports_error(tmp_path, monkeypatch):
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.setattr(git_mod, "PROJECT_ROOT", plain)
    provider = _use_provider(monkeypatch, FakeProvider("nope"))
    files, markdown, fallback, error = review.review_working_tree()
    assert (files, markdown, fallback) == ([], "", False)
    assert "Not a git repo" in error
    assert provider.calls == []


def test_review_is_read_only(monkeypatch, repo):
    (repo / "a.txt").write_text("one\ntwo\n")

    def _boom(*args, **kwargs):
        raise AssertionError("review must not touch disk or git history")

    monkeypatch.setattr(safety, "checkpoint", _boom)
    monkeypatch.setattr(git_mod, "commit", _boom)
    _use_provider(monkeypatch, FakeProvider("**Summary** — fine"))
    files, markdown, fallback, error = review.review_working_tree()
    assert error == "" and fallback is False and files
    assert markdown.startswith("**Summary**")


def test_review_slash_command_is_wired(monkeypatch, repo):
    from hazzel import __main__ as main_mod

    (repo / "a.txt").write_text("one\ntwo\n")
    _use_provider(monkeypatch, FakeProvider("**Summary** — from the slash command"))
    monkeypatch.setattr(config, "should_show_star_nudge", lambda: False)
    monkeypatch.setattr(main_mod.session, "save", lambda *a, **k: None)
    monkeypatch.setattr(main_mod.ui, "show_loader", lambda *a, **k: None)
    monkeypatch.setattr(main_mod.ui, "hide_loader", lambda *a, **k: None)
    seen = {}
    monkeypatch.setattr(
        main_mod.ui,
        "show_review",
        lambda md, files, **kw: seen.update(markdown=md, files=files, **kw),
    )
    answers = ["/review", "/exit"]
    monkeypatch.setattr(main_mod.ui, "get_input", lambda messages=None, prefill="": answers.pop(0))

    main_mod.main([])

    assert seen["markdown"] == "**Summary** — from the slash command"
    assert seen["fallback"] is False
    assert [f["path"] for f in seen["files"]] == ["a.txt"]
    assert main_mod._last_response == "**Summary** — from the slash command"


def test_review_staged_with_nothing_staged_skips_model(monkeypatch, repo):
    from hazzel import __main__ as main_mod

    (repo / "a.txt").write_text("one\ntwo\n")  # unstaged only, nothing added
    provider = _use_provider(monkeypatch, FakeProvider("should not run"))
    monkeypatch.setattr(config, "should_show_star_nudge", lambda: False)
    monkeypatch.setattr(main_mod.session, "save", lambda *a, **k: None)
    rendered = []
    monkeypatch.setattr(main_mod.ui, "show_review", lambda *a, **k: rendered.append(a))
    answers = ["/review --staged", "/exit"]
    monkeypatch.setattr(main_mod.ui, "get_input", lambda messages=None, prefill="": answers.pop(0))

    main_mod.main([])

    assert provider.calls == []
    assert rendered == []
