<p align="center">
  <img src="assets/logo.png" alt="Hazzel" width="160" />
</p>

<h1 align="center">Hazzel</h1>

<p align="center">A small terminal coding agent. Bring your own key.</p>

<p align="center">
  <a href="https://pypi.org/project/hazzel/"><img src="https://img.shields.io/pypi/v/hazzel" alt="PyPI"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-%3E%3D3.10-blue" alt="Python"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-AGPL--3.0--or--later-green" alt="License"></a>
</p>

Hazzel lives in your terminal. It reads code, edits files, runs commands, and reads the web — **always with your approval first**. No subscription, no background agents, no hidden behavior: a terminal agent you can see through.

![Hazzel demo](assets/demo.gif)

## Quickstart

```bash
pip install hazzel
cd your-project
hazzel
```

Run `/model`, pick a provider, paste your key — Hazzel remembers it. Keys live at `~/.config/hazzel/config.json` with `0600` permissions. Env vars (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `MISTRAL_API_KEY`, `GROQ_API_KEY`, `GEMINI_API_KEY`, `DEEPSEEK_API_KEY`, `OPENROUTER_API_KEY`) work too. Ollama runs local models with no key (`OLLAMA_HOST` overrides the default `http://localhost:11434/v1`).

Windows works too (PowerShell or cmd) — the full-screen menus gracefully fall back to plain prompts, no new dependencies.

## Watch it work

```
❯ Fix the failing test in tests/test_agent.py

  ● read_file   tests/test_agent.py
  ● edit_file   src/hazzel/agent/core.py
  ● run_command pytest -q — passed
```

One shot, no REPL:

```bash
git diff | hazzel -p "summarize this change"
hazzel -p "where is auth handled?" --output-format json
```

## Features

**Build with approval**

- Read, search, and list your codebase. Tag files with `@path` to put them in context.
- Create and edit files with diff preview and approval. Undo anytime with `/undo`.
- Run shell commands with approval and timeout, sandboxed to your project root. Read-only commands (`ls`, `cat`…) skip the queue.
- `!command` runs shell directly; `@path` attaches files; `fetch <url>` pulls public docs into context.
- Multiline input with Ctrl+J and full paste support.

**Know your spend**

- Real cost visibility: provider-reported tokens priced into dollars and logged locally (`~/.config/hazzel/usage.jsonl`).
- `/usage today|week|month`, `/usage --by-model`, `/usage export` — plus `/budget` limits that warn but never block.

**Stay in flow**

- Plan mode (`/plan on`): read-only exploration ending in a numbered plan. Nothing changes until `/plan off`.
- Think mode (`/think on`): supported models reason step-by-step — costs more tokens, wins on hard edits. Reasoning stays collapsed unless you peek.
- Goal (`/goal`): pin an objective, run it with `/goal run`; every turn steers toward it.
- Sessions survive restarts: per-project history saves automatically, `/session restore` picks up where you left off.
- Skills (`SKILL.md`) and `AGENTS.md` project maps load into every turn — `/skills` to browse, `/init` to draft one.

**Script it**

- `hazzel -p "prompt"` answers once and exits — pipe stdin in, `-y` allows writes/runs, `--output-format json` for pipelines.
- `/export` saves the transcript, `/copy` grabs the last reply, `/retry` re-runs your last message, `/docs` prints the full guide in-terminal.

## Providers

Bring your own key. No subscription. Switch anytime with `/model`.

| Provider | Notes |
|---|---|
| Groq | Default: `openai/gpt-oss-120b` |
| OpenAI | |
| Anthropic | |
| Mistral | |
| Gemini | |
| DeepSeek | |
| OpenRouter | 100+ models through one key |
| Ollama | Local, no key |

## Commands

| Group | Commands |
|---|---|
| Modes | `/model` · `/plan on\|off` · `/think on\|off` · `/goal [@objective]` + `/goal run` |
| Cost | `/usage [today\|week\|month\|--by-model]` · `/budget` |
| Transcript | `/summary` · `/export [file]` · `/copy [code]` · `/retry` · `/undo [n]` · `/session restore` · `/clear` |
| Project | `/init [file]` · `/skills [name]` · `/help` · `/docs` · `/logout` · `/exit` |

Type `/` to filter commands live, `@` to attach files. The full guide lives in your terminal: `/docs`.

## Why Hazzel?

Most coding agents keep getting bigger. Hazzel stays small on purpose.

The model suggests what to do. Hazzel decides whether and how to do it. Every mutation goes through you: file changes show a diff before they apply, shell commands ask first, and destructive file ops are checkpointed so `/undo` always works.

If you want the most feature-heavy agent, there are better options. If you want a terminal agent you can see through, that's Hazzel.

## Status

Early-stage (v1.4.7). Expect rough edges.

No deploys, no background agents. It doesn't replace your editor — it stays in the terminal next to it.

## Contributing

Issues and pull requests welcome.

## License

AGPL-3.0-or-later. See [LICENSE](LICENSE).

---

If it fits your workflow, star the repo. It helps other terminal-first developers find it.
