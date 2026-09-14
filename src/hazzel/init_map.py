from datetime import datetime

SKIP_DIRS = frozenset({
    ".git", ".venv", "venv", "__pycache__", "node_modules", "dist", "build",
    ".ruff_cache", ".pytest_cache", ".mypy_cache", ".tox", "target", ".idea",
    ".vscode", "eggs",
})

STACK_FILES = {
    "pyproject.toml": "Python (pyproject)",
    "requirements.txt": "Python (requirements)",
    "setup.py": "Python (setuptools)",
    "package.json": "Node (package.json)",
    "Cargo.toml": "Rust (cargo)",
    "go.mod": "Go (modules)",
    "Gemfile": "Ruby (bundler)",
    "composer.json": "PHP (composer)",
    "pom.xml": "Java (maven)",
    "build.gradle": "Java (gradle)",
    "Dockerfile": "Docker",
    "Makefile": "Make",
}

MAX_TOP_LEVEL = 30
TODO = "# TODO: fill in"


def _top_level(root):
    try:
        entries = sorted(root.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError:
        return []
    out = []
    for entry in entries:
        name = entry.name
        if name in SKIP_DIRS or name.endswith(".egg-info"):
            continue
        if name.startswith(".") and name != ".env.example":
            continue
        try:
            is_dir = entry.is_dir()
        except OSError:
            continue
        out.append(f"{name}/" if is_dir else name)
        if len(out) >= MAX_TOP_LEVEL:
            break
    return out


def _infer_commands(root, names):
    cmds = {
        "install": TODO,
        "build": TODO,
        "test": TODO,
        "lint": TODO,
        "typecheck": TODO,
    }
    if "package.json" in names:
        if (root / "pnpm-lock.yaml").exists():
            mgr = "pnpm"
        elif (root / "yarn.lock").exists():
            mgr = "yarn"
        elif (root / "bun.lockb").exists() or (root / "bun.lock").exists():
            mgr = "bun"
        else:
            mgr = "npm"
        scripts = set()
        try:
            import json

            pkg = json.loads((root / "package.json").read_text(encoding="utf-8", errors="replace"))
            raw = pkg.get("scripts") or {}
            if isinstance(raw, dict):
                scripts = set(raw)
        except (OSError, ValueError):
            pass
        cmds["install"] = f"{mgr} i" if mgr != "npm" else "npm install"
        cmds["build"] = f"{mgr} build" if "build" in scripts else TODO
        if "test" in scripts:
            cmds["test"] = f"{mgr} test"
        cmds["lint"] = f"{mgr} lint" if "lint" in scripts else TODO
        cmds["typecheck"] = f"{mgr} typecheck" if "typecheck" in scripts else TODO
    elif "pyproject.toml" in names or "requirements.txt" in names or "setup.py" in names:
        cmds["install"] = "pip install -e ." if "pyproject.toml" in names else "pip install -r requirements.txt"
        cmds["test"] = "pytest"
        cmds["lint"] = "ruff check ."
    elif "Cargo.toml" in names:
        cmds["install"] = "cargo build"
        cmds["build"] = "cargo build"
        cmds["test"] = "cargo test"
        cmds["lint"] = "cargo clippy"
        cmds["typecheck"] = TODO
    elif "go.mod" in names:
        cmds["install"] = "go mod download"
        cmds["build"] = "go build ./..."
        cmds["test"] = "go test ./..."
        cmds["lint"] = TODO
        cmds["typecheck"] = "go vet ./..."
    return cmds


def build_map(root):
    from pathlib import Path

    root = Path(root)
    try:
        title = root.resolve().name
    except OSError:
        title = root.name
    if not title:
        title = "project"
    stamp = datetime.now().strftime("%Y-%m-%d")
    try:
        names = {p.name for p in root.iterdir()}
    except OSError:
        names = set()
    stack = sorted({label for fname, label in STACK_FILES.items() if fname in names})
    top = _top_level(root)
    cmds = _infer_commands(root, names)
    lines = [
        f"# {title} (Hazzel context, {stamp})",
        "",
        "## Stack",
        ", ".join(stack) if stack else "unknown",
        "",
        "## Commands",
        f"install: {cmds['install']}",
        f"build: {cmds['build']}",
        f"test: {cmds['test']}",
        f"lint: {cmds['lint']}",
        f"typecheck: {cmds['typecheck']}",
        "",
        "## Conventions",
        TODO,
        "",
        "## Layout",
    ]
    lines.extend(top or [TODO])
    lines.extend([
        "",
        "## Gotchas",
        TODO,
        "",
        "## Don't",
        "no new deps without asking",
        "no public API changes without changelog",
        "no reformatting untouched files",
        "",
        "_Regenerate with `/init`. Edit freely — Hazzel reads this file for context._",
        "",
    ])
    return "\n".join(lines)
