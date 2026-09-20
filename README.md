<p align="center">
  <img src="assets/logo.png" alt="Hazzel" width="140" />
</p>

<h1 align="center">Hazzel</h1>

<p align="center">
  <b>A terminal coding agent you can actually read.</b><br/>
  Bring your own key. No subscription. Every change shown as a diff before it touches disk.
</p>

<p align="center">
  <a href="https://github.com/mukundzha/hazzel/actions/workflows/ci.yml">
    <img src="https://github.com/mukundzha/hazzel/actions/workflows/ci.yml/badge.svg" alt="CI">
  </a>
  <a href="https://pypi.org/project/hazzel/">
    <img src="https://img.shields.io/pypi/v/hazzel" alt="PyPI">
  </a>
  <a href="https://pypistats.org/packages/hazzel">
    <img src="https://img.shields.io/badge/downloads-3.5k%2Fmonth-blue" alt="Downloads">
  </a>
  <a href="LICENSE">
    <img src="https://img.shields.io/badge/license-AGPL--3.0--or--later-green" alt="License">
  </a>
  <a href="https://github.com/mukundzha/hazzel/stargazers">
    <img src="https://img.shields.io/github/stars/mukundzha/hazzel?style=social" alt="Stars">
  </a>
</p>

<p align="center">
  <i>If this saves you a hunt through someone's agent framework later, the ⭐ at the top of the page takes one click.</i>
</p>

![Hazzel demo](assets/demo.gif)

**Recently shipped:** `/review` (1.5.0) · git `/commit` with auto-drafted messages (1.4.8) · background `!cmd &` jobs (1.4.9) · stdlib-only MCP client (1.4.7) · usage in real dollars (1.4.5) — [full changelog](CHANGELOG.md)

## The 30-second pitch

Every coding agent claims to be transparent. Most of them are 50k-line frameworks with a plugin system, a cloud dashboard, and a subscription.

Hazzel is ~10k lines of Python in a flat `src/hazzel/` layout you can trace end to end — `agent/core.py` is the whole loop, `tools/` is every action it can take, and `safety.py` is the entire undo system.

It does the things a coding agent is supposed to do — read your repo, edit files, run commands, work with git — and stops before every one of them to show you exactly what's about to happen.

```bash
pip install hazzel
export GROQ_API_KEY="..."   # or skip this and pick a provider inside with /model
cd your-project
hazzel
```

```text
❯ Fix the failing test in tests/test_agent.py

  ● read_file   tests/test_agent.py
  ● edit_file   src/hazzel/agent/core.py
  ● run_command pytest -q — passed
```

**Things you can say on day one**

```text
❯ /review --staged
❯ /commit
❯ what does agent/fastpath.py do — is it just caching?
❯ @screenshot.png make the nav match this
```

No project quiz, no config ceremony — the read-only commands answer instantly, and anything that touches disk stops at a diff first.

`/model`, pick a provider, paste a key — that's the whole setup.

Or export:

```text
OPENAI_API_KEY
ANTHROPIC_API_KEY
GROQ_API_KEY
MISTRAL_API_KEY
GEMINI_API_KEY
DEEPSEEK_API_KEY
OPENROUTER_API_KEY
```

and skip the prompt entirely.

Running local models through Ollama needs no key at all.

## Why it's built this way

Most agents ask you to trust a black box. Hazzel asks you to trust three specific, inspectable mechanisms instead:

* **Every write is a diff you approve, first.** File edits render as a unified diff before anything lands. Shell commands ask before they run — except a small allowlisted set of true read-onlys (`ls`, `cat`, `git status`), which skip the queue so exploration doesn't feel like a permission dialog.

* **Every write is checkpointed, automatically.** Before Hazzel touches a file, it snapshots the prior bytes to `~/.config/hazzel/undo/` — up to 200 events, 20 per file. `/undo` restores bytes that were saved before the edit happened.

* **Commands are sandboxed to your project root.** Destructive git commands such as `reset --hard` and `clean` are blocked outright. Raw `git commit` is steered into the `/commit` tool with its own diff preview and approval step. Push and pull run through the normal command-approval flow.

You can verify all three claims yourself in about 200 lines:

```text
src/hazzel/safety.py
src/hazzel/tools/run_command.py
```

## What it actually does

**Understands your repo**

Reads, searches, and lists your codebase. `@path` tags a file into context; `/init` walks the tree and drafts an `AGENTS.md` map so every future session starts oriented.

**Ships real changes**

Diff-preview-and-approve editing, `/undo` backed by real checkpoints, shell commands with timeouts, `!command` for a direct shell escape (`!cmd &` runs it in the background — `/jobs` polls and kills), `fetch <url>` to pull docs into context, and image attachment (`@screenshot.png`) for vision-capable models.

**Speaks fluent git**

`/status`, `/diff --staged`, `/review [--staged]` (read-only review of what you're about to commit), `/commit` with an auto-drafted Conventional Commit message and diff preview, `/log` — reads run instantly with zero LLM round-trip.

Push and pull go through the standard approval flow.

**Extends through open standards, not lock-in**

A minimal MCP stdio client using only the standard library talks to any MCP server through `.hazzel/mcp.json`.

`SKILL.md` files load project- or user-level skills on demand.

Neither requires Hazzel-specific tooling to author.

**Shows you the bill**

Provider-reported tokens are parsed into real dollar figures and logged locally — not estimated.

```text
/usage today
/usage week
/usage month
/usage --by-model
/budget
```

A live `tokens · $` line is shown every turn.

**Stays out of your way between sessions**

Per-project sessions persist across restarts with `/session restore`.

Plan mode (`/plan on`) explores read-only and proposes a numbered plan before touching anything.

Think mode (`/think on`) turns on extended reasoning for hard edits when you're willing to pay the token cost.

**Works in a pipeline, not just a REPL**

```bash
hazzel -p "prompt"
```

Runs one turn and exits.

Pipe a diff in, get a summary out. Use `--output-format json` for scripts and real exit codes (`0`, `1`, `2`, `130`) for CI.

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

Switch anytime with `/model`.

Nothing is metered by Hazzel — you pay your provider directly, or nothing at all if you're running local.

## Commands at a glance

| Group      | Commands                                                                               |
| ---------- | -------------------------------------------------------------------------------------- |
| Modes      | `/model` · `/plan on\|off` · `/think on\|off` · `/goal [@objective]`                   |
| Git        | `/status` · `/diff [--staged]` · `/review [--staged]` · `/commit` · `/log`            |
| Cost       | `/usage [today\|week\|month\|--by-model]` · `/budget`                                  |
| Extend     | `/mcp [server [tool]]` · `/skills [name]` · `/init`                                    |
| Transcript | `/export` · `/copy` · `/retry` · `/jobs` · `/undo [n]` · `/session restore` · `/clear` |

Type `/` to filter live.

Use `@` to attach a file.

```text
/docs
```

prints the full guide without leaving the terminal.

## What it's honest about not being

v1.5.0, early-stage.

No autonomous PRs, no cloud dashboard, and no session synchronization across machines.

It doesn't replace your editor — it sits in the terminal next to it, and it stays small on purpose.

If you need a heavier, more automated agent, better options exist.

If you want to see exactly what's about to happen to your files before it happens, this is built for that.

## Support Hazzel

Hazzel is free and open-source.

If you find it useful, you can support its development and help keep it maintained, improved, and dependency-light.

<p align="center">
  <a href="https://paypal.me/mukundzi">
    <img src="https://img.shields.io/badge/Sponsor%20Hazzel-PayPal-0070BA?style=for-the-badge&logo=paypal&logoColor=white" alt="Sponsor Hazzel on PayPal">
  </a>
</p>

<p align="center">
  <i>Every contribution helps fund continued development and maintenance.</i>
</p>

## Who's behind this

<table>
  <tr>
    <td align="center">
      <a href="https://github.com/mukundzha">
        <img src="https://avatars.githubusercontent.com/mukundzha?v=4&s=80" width="80" alt="mukundzha"/><br/>
        <sub><b>Mukund Jha</b><br/>creator</sub>
      </a>
    </td>
    <td align="center">
      <a href="https://github.com/ronaldsterners">
        <img src="https://avatars.githubusercontent.com/ronaldsterners?v=4&s=80" width="80" alt="ronaldsterners"/><br/>
        <sub><b>ronaldsterners</b></sub>
      </a>
    </td>
    <td align="center">
      <a href="https://github.com/Gambit-Checkmate">
        <img src="https://avatars.githubusercontent.com/Gambit-Checkmate?v=4&s=80" width="80" alt="Gambit-Checkmate"/><br/>
        <sub><b>Gambit-Checkmate</b></sub>
      </a>
    </td>
  </tr>
</table>

Contributions land reviewed and CI-verified, and every external contributor is credited in the release notes.

## Contributing

Issues and pull requests are genuinely welcome.

`ROADMAP.md` tracks feature gaps against other terminal agents, and `AGENTS.md` — regenerate it with `/init` — contains the project rules:

* No new dependencies without asking.
* No public API changes without a CHANGELOG entry.
* Keep the implementation small and inspectable.

## License

AGPL-3.0-or-later.

See [LICENSE](LICENSE).

---

<p align="center">
  Small tools stay small because people who find them useful say so.<br/>
  If Hazzel is now sitting in your terminal next to your editor,
  <a href="https://github.com/mukundzha/hazzel">a star</a>
  is how the next person finds it too.
</p>
