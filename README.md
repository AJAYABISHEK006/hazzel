<p align="center">
  <img src="assets/logo.png" alt="Hazzel" width="140" />
</p>

<h1 align="center">Hazzel</h1>

<p align="center"><b>A terminal coding agent you can actually read.</b><br/>Bring your own key. No subscription. Every change shown as a diff before it touches disk.</p>

<p align="center">
  <a href="https://pypi.org/project/hazzel/"><img src="https://img.shields.io/pypi/v/hazzel" alt="PyPI"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-%3E%3D3.10-blue" alt="Python"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-AGPL--3.0--or--later-green" alt="License"></a>
  <a href="https://github.com/mukundzha/hazzel/stargazers"><img src="https://img.shields.io/github/stars/mukundzha/hazzel?style=social" alt="Stars"></a>
</p>

<!-- <p align="center">
  <a href="https://paypal.me/mukundji">
    <img src="https://img.shields.io/badge/Sponsor-PayPal-0070BA?style=for-the-badge&logo=paypal&logoColor=white" alt="Sponsor Hazzel on PayPal">
  </a>
</p> -->

<p align="center"><i>If this saves you a hunt through someone's agent framework later, the ⭐ at the top of the page takes one click.</i></p>

![Hazzel demo](assets/demo.gif)

## The 30-second pitch

Every coding agent claims to be transparent. Most of them are 50k-line frameworks with a plugin system, a cloud dashboard, and a subscription. Hazzel is ~10k lines of Python in a flat `src/hazzel/` layout you can trace end to end — `agent/core.py` is the whole loop, `tools/` is every action it can take, `safety.py` is the entire undo system.

It does the things a coding agent is supposed to do — read your repo, edit files, run commands, work with git — and stops before every one of them to show you exactly what's about to happen.

```bash
pip install hazzel
cd your-project
hazzel
```

```
❯ Fix the failing test in tests/test_agent.py

  ● read_file   tests/test_agent.py
  ● edit_file   src/hazzel/agent/core.py
  ● run_command pytest -q — passed
```

`/model`, pick a provider, paste a key — that's the whole setup. Or export `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GROQ_API_KEY` / `MISTRAL_API_KEY` / `GEMINI_API_KEY` / `DEEPSEEK_API_KEY` / `OPENROUTER_API_KEY` and skip the prompt entirely. Running local models through Ollama needs no key at all.

## Why it's built this way

Most agents ask you to trust a black box. Hazzel asks you to trust three specific, inspectable mechanisms instead:

* **Every write is a diff you approve, first.** File edits render as a unified diff before anything lands. Shell commands ask before they run — except a small allowlisted set of true read-onlys (`ls`, `cat`, `git status`), which skip the queue so exploration doesn't feel like a permission dialog.
* **Every write is checkpointed, automatically.** Before Hazzel touches a file, it snapshots the prior bytes to `~/.config/hazzel/undo/` (up to 200 events, 20 per file). `/undo` is not "hope the model didn't break anything" — it's restoring bytes that were saved before the edit happened.
* **Commands are sandboxed to your project root.** Destructive git — `reset --hard`, `clean` — is blocked outright; raw `git commit` is steered into the `/commit` tool with its own diff preview and approval step. Push/pull run through the normal command-approval flow.

You can verify all three claims yourself in about 200 lines: `src/hazzel/safety.py` and `src/hazzel/tools/run_command.py`.

## What it actually does

**Understands your repo**
Reads, searches, and lists your codebase. `@path` tags a file into context; `/init` walks the tree and drafts an `AGENTS.md` map so every future session starts oriented.

**Ships real changes**
Diff-preview-and-approve editing, `/undo` backed by real checkpoints, shell commands with timeouts, `!command` for a direct shell escape (`!cmd &` runs it in the background — `/jobs` polls, kills), `fetch <url>` to pull docs into context, image attach (`@screenshot.png`) for vision-capable models.

**Speaks fluent git**
`/status`, `/diff --staged`, `/commit` (auto-drafted Conventional Commit message, diff preview, y/e/n), `/log` — reads run instantly with zero LLM round-trip, and push/pull go through the standard approval flow.

**Extends through open standards, not lock-in**
A minimal MCP stdio client (stdlib only, no new dependencies) talks to any MCP server via `.hazzel/mcp.json`. `SKILL.md` files load project- or user-level skills on demand. Neither requires Hazzel-specific tooling to author.

**Shows you the bill**
Provider-reported tokens are parsed into real dollar figures and logged locally — not estimated. `/usage today|week|month|--by-model`, `/budget` for warn-only limits, a live `tokens · $` line every turn.

**Stays out of your way between sessions**
Per-project sessions persist across restarts (`/session restore`). Plan mode (`/plan on`) explores read-only and proposes a numbered plan before touching anything. Think mode (`/think on`) turns on extended reasoning for hard edits when you're willing to pay the token cost.

**Works in a pipeline, not just a REPL**
`hazzel -p "prompt"` runs one turn and exits — pipe a diff in, get a summary out, `--output-format json` for scripts, real exit codes (0/1/2/130) for CI.

## Providers — bring your own key, no subscription

| Provider   | Notes                           |
| ---------- | ------------------------------- |
| Groq       | Default (`openai/gpt-oss-120b`) |
| OpenAI     |                                 |
| Anthropic  |                                 |
| Mistral    |                                 |
| Gemini     |                                 |
| DeepSeek   |                                 |
| OpenRouter | 100+ models through one key     |
| Ollama     | Fully local, no key needed      |

Switch anytime with `/model`. Nothing is metered by Hazzel — you pay your provider directly, or nothing at all if you're running local.

## Commands at a glance

| Group      | Commands                                                                               |
| ---------- | -------------------------------------------------------------------------------------- |
| Modes      | `/model` · `/plan on\|off` · `/think on\|off` · `/goal [@objective]`                   |
| Git        | `/status` · `/diff [--staged]` · `/commit` · `/log`                                    |
| Cost       | `/usage [today\|week\|month\|--by-model]` · `/budget`                                  |
| Extend     | `/mcp [server [tool]]` · `/skills [name]` · `/init`                                    |
| Transcript | `/export` · `/copy` · `/retry` · `/jobs` · `/undo [n]` · `/session restore` · `/clear` |

Type `/` to filter live, `@` to attach a file. `/docs` prints the full guide without leaving the terminal.

## What it's honest about not being

v1.4.9, early-stage. No autonomous PRs, no cloud dashboard, no session across machines. It doesn't replace your editor — it sits in the terminal next to it, and it stays small on purpose. If you need a heavier, more automated agent, better options exist. If you want to see exactly what's about to happen to your files before it happens, this is built for that.

## Contributing

Issues and pull requests are genuinely welcome — the ROADMAP.md tracks feature gaps against other terminal agents, and `AGENTS.md` (regenerate with `/init`) has the house rules: no new dependencies without asking, no public API changes without a CHANGELOG entry.

## License

AGPL-3.0-or-later. See [LICENSE](LICENSE).

---

<p align="center">
Small tools stay small because people who find them useful say so.<br/>
If Hazzel is now sitting in your terminal next to your editor, <a href="https://github.com/mukundzha/hazzel">a star</a> is how the next person finds it too.
</p>
