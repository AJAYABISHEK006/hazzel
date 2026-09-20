"""Read-only review of uncommitted changes.

``/review`` gathers the working-tree diff, asks the current model for a short
markdown review, and prints it. Read-only by construction: no file writes, no
shell commands, no undo checkpoints — the only effect is one model call.
"""

from __future__ import annotations

import re

REVIEW_SYSTEM = (
    "You review uncommitted changes in a git working tree. Answer in markdown with "
    "no preamble — nothing before the first heading. Use exactly these sections:\n"
    "**Summary** — one or two lines on what the diff does.\n"
    "**Risks** — concrete bugs, edge cases, security or performance problems, each "
    "tied to a file and line visible in the diff. Write 'none found' if it looks clean.\n"
    "**Missing** — tests, error handling, docs or changelog entries the change implies.\n"
    "**Before commit** — at most three imperative next steps.\n"
    "Judge only what the diff shows. Never invent files, line numbers, or behaviour. "
    "Be specific and terse: no praise, no restating the diff."
)

MAX_REVIEW_FILES = 20
MAX_REVIEW_FILE_CHARS = 4000
MAX_REVIEW_DIFF_CHARS = 12000
MAX_PROMPT_STATUS_CHARS = 1200
MAX_RISK_LINES = 6
LONG_LINE_CHARS = 200

_DEBUG_MARKERS = (
    "breakpoint()",
    "pdb.set_trace()",
    "import pdb",
    "console.log(",
    "debugger;",
)
_NOTE_MARKERS = ("TODO", "FIXME", "XXX", "HACK")
_STRING_LITERAL_RE = re.compile(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'')
_SILENT_EXCEPT_RE = re.compile(r"except[^:]*:\s*(pass|\.\.\.)\s*$")
_CODE_SUFFIXES = (".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".rb")
_TEST_MARKERS = ("test_", "_test.", "tests/", "spec.")


def _added_lines(diff):
    """Yield added lines from a unified diff, without the leading '+'."""
    for line in (diff or "").splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            yield line[1:]


def _strip_strings(line):
    """Blank out string literals so marker words inside them don't look like code."""
    return _STRING_LITERAL_RE.sub("", line)


def changed_totals(files):
    added = sum(int(f.get("added") or 0) for f in files or [])
    deleted = sum(int(f.get("deleted") or 0) for f in files or [])
    return added, deleted


def collect_diff(staged=False):
    """Return ``(files, diff, error)`` for the working tree. Read-only.

    Untracked files come through ``git.diff_file``, which synthesizes a diff for
    them, so a brand-new file is reviewed too. Both the file count and the diff
    size are capped so one huge change can't blow the context window.
    """
    from . import git as _git

    ok, files, error = _git.changed_files(staged)
    if not ok:
        return [], "", error
    if not files:
        return [], "", ""

    chunks = []
    used = 0
    shown = 0
    for item in files:
        if shown >= MAX_REVIEW_FILES or used >= MAX_REVIEW_DIFF_CHARS:
            break
        ok_file, body = _git.diff_file(item.get("key", ""), staged)
        if not ok_file or not body or body.strip() in ("", "No changes."):
            continue
        if len(body) > MAX_REVIEW_FILE_CHARS:
            body = body[:MAX_REVIEW_FILE_CHARS].rstrip() + "\n[…file diff truncated…]"
        chunk = f"--- {item.get('path', '')}  [{item.get('status', 'M')}]\n{body}"
        chunks.append(chunk)
        used += len(chunk)
        shown += 1

    hidden = len(files) - shown
    if hidden > 0:
        chunks.append(f"[…{hidden} more changed file(s) not shown…]")
    return files, "\n\n".join(chunks), ""


def build_prompt(files, diff, staged=False):
    lines = [
        f" {item.get('status', 'M')} {item.get('path', '')} "
        f"(+{item.get('added', 0)} −{item.get('deleted', 0)})"
        for item in files or []
    ]
    status = "\n".join(lines)[:MAX_PROMPT_STATUS_CHARS]
    scope = "staged changes" if staged else "uncommitted working-tree changes"
    return f"Review these {scope}.\n\nFILES:\n{status}\n\nDIFF:\n{diff}"


def heuristic_review(files, diff):
    """Deterministic offline review used when no model is reachable."""
    names = [str(f.get("path", "")) for f in files or []]
    lowered = [n.lower() for n in names]
    added, deleted = changed_totals(files)
    code_files = [n for n in names if n.lower().endswith(_CODE_SUFFIXES)]
    has_tests = any(marker in n for n in lowered for marker in _TEST_MARKERS)
    touched_changelog = any(n.endswith("changelog.md") for n in lowered)

    out = [
        f"**Summary** — {len(names)} file(s), +{added} −{deleted} "
        "(offline heuristics; no model reachable)."
    ]

    risks = []
    note_hits = 0
    for line in _added_lines(diff):
        code = _strip_strings(line.strip())
        if code:
            for marker in _DEBUG_MARKERS:
                risk = f"added line contains `{marker}`"
                if marker in code and risk not in risks:
                    risks.append(risk)
            if _SILENT_EXCEPT_RE.search(code):
                risk = "`except …: pass` swallows errors silently"
                if risk not in risks:
                    risks.append(risk)
            if any(note in code for note in _NOTE_MARKERS):
                note_hits += 1
        if len(line) > LONG_LINE_CHARS:
            risk = f"added line over {LONG_LINE_CHARS} chars"
            if risk not in risks:
                risks.append(risk)
    if risks:
        out.append("**Risks** — " + "; ".join(risks[:MAX_RISK_LINES]) + ".")
    else:
        out.append("**Risks** — nothing flagged by the heuristic scan; read the diff above yourself.")
    if note_hits:
        out.append(f"**Notes** — {note_hits} added TODO/FIXME-style comment(s).")

    missing = []
    if code_files and not has_tests:
        missing.append("no test file changed")
    if code_files and not touched_changelog:
        missing.append("`CHANGELOG.md` not updated")
    out.append("**Missing** — " + ("; ".join(missing) + "." if missing else "nothing obvious."))

    out.append("**Before commit** — run the test suite; skim the diff above; then `/commit`.")
    return "\n\n".join(out)


def review_working_tree(staged=False):
    """Return ``(files, markdown, fallback, error)``.

    ``fallback`` is True when the model was unreachable and the offline
    heuristics were used instead. ``error`` is a message when the diff itself
    could not be read (not a git repo, git failed); a clean tree returns
    ``([], "", False, "")``. This never raises and never mutates anything.
    """
    files, diff, error = collect_diff(staged)
    if error:
        return [], "", False, error
    if not files:
        return [], "", False, ""

    prompt = build_prompt(files, diff, staged)
    text = ""
    try:
        from .providers import get_provider

        response = get_provider().chat(
            [
                {"role": "system", "content": REVIEW_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            [],
        )
        text = (getattr(response, "content", None) or "").strip()
    except Exception:
        text = ""
    if not text:
        return files, heuristic_review(files, diff), True, ""
    return files, text, False, ""
