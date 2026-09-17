# Roadmap

Must-have features tracked against competitors.

| Feature | Why | Status |
|---|---|---|
| Session persistence | Save/restore conversation state across restarts. Every competitor has this; it's the #1 complaint for terminal agents that don't. | Shipped (single last-session slot per project in `~/.config/hazzel/sessions/` — save on exit, restore on launch, `/session restore` resumes, `/clear` archives for one restore) |
| AGENTS.md support | The de-facto standard for per-repo instructions (used by Codex, Copilot, OpenCode, Omp). Read it at startup, merge it into the system prompt, and keep repo guidance in context automatically. | Shipped (`/init` generates it; startup loads it automatically) |
| Local model support (Ollama) | One of Hazzel's stated values is BYOK — Ollama is the natural extension for offline/private use. | Shipped (keyless, `OLLAMA_HOST` override) |
| MCP (Model Context Protocol) | Now the standard extension mechanism. Even a minimal stdio transport gets you access to the entire MCP server ecosystem. | Shipped (minimal stdio transport in `mcp.py`: `.hazzel/mcp.json` + global config, lazy `initialize`/`tools/list`/`tools/call`, single skill-like `mcp` tool with read-only discovery, `/mcp` REPL command) |
| Parallel tool execution | Biggest speed win — run independent tool calls concurrently instead of sequentially. | Shipped (read-only batches run in ThreadPoolExecutor, writes stay sequential) |
| Reasoning model pass-through (`/think` mode) | Surface model reasoning levels directly; let power models think harder on demand. | Shipped (`/think on` toggles extended thinking: Anthropic `thinking`, OpenAI + GPT-OSS `reasoning_effort`, with graceful fallback when unsupported) |

Priority order: polish shipped features (named sessions, richer MCP coverage) → new transports.
