# xcoding · by [@c7s89r](https://github.com/c7s89r)
<img width="421" height="269" alt="image" src="https://github.com/user-attachments/assets/ab92aad1-0d05-4f66-8315-cbab80d6473e" />

A local-model coding agent by **@c7s89r** — like Claude Code, but it talks to a
model running on your own machine instead of a cloud API.

> **✅ Works with [Ollama](https://ollama.com) for now.** Just install Ollama,
> pull a tool-capable model, then `pip install xcoding` and run `xcoding`.
> (llama.cpp support is in too, but Ollama is the tested path.)

It auto-detects whichever backend is running, gives the model tools to read/write
files and run shell commands, and loops until your task is done. Every file write
and every shell command asks for your approval first.

### Quick start (Ollama)

```bash
ollama serve
ollama pull qwen2.5-coder     # a model that's good at tool use
pip install xcoding
xcoding
```

## Install

```bash
pip install xcoding
```

Then just run `xcoding` from any project folder.

Or from source:

```bash
pip install -e .
```

(Python 3.9+. Pulls in `openai`, `httpx`, `rich`.)

## Run a backend

**Ollama** (easiest — supports tool-calling natively):

```bash
ollama serve
ollama pull qwen2.5-coder        # a model that's good at tool use
```

**llama.cpp** (raw GGUF files):

```bash
llama-server -m your-model.gguf   # listens on :8080, OpenAI-compatible
```

> Tool-calling quality depends heavily on the model. Use a model trained for it
> (e.g. `qwen2.5-coder`, `llama3.1`, `mistral-nemo`). Tiny models will struggle.

## Use it

```bash
xcoding
# or:  python -m xcode
```

Then just talk to it:

```
› add a /health endpoint to app.py that returns {"ok": true}
```

In-REPL commands: `/help`, `/models`, `/model`, `/init`, `/todos`, `/perms`,
`/compact`, `/sessions`, `/resume`, `/reset`, `/exit`.

- Replies **stream** live; the prompt shows a **context meter** (`~3.2k/8k`).
- Writes/commands ask `y / n / a`; **a** ("always") is saved to
  `.xcode/permissions.json`. Edits show a **colored diff** preview.
- Attach files inline with `@path` (e.g. `explain @xcode/agent.py`).
- The agent tracks a **todo list** for multi-step work (`/todos` to view).
- Old turns are **auto-compacted** when the context meter fills; `/compact`
  forces it. Conversations are **saved** per project — `xcoding --resume` or
  `/resume` to pick up where you left off.
- Drop an **XCODE.md** at the repo root (or run `/init`) and it's auto-loaded
  as project memory.

### Modes (shift+tab to cycle)

- **·· normal** — asks before writes/commands
- **⏵⏵ auto** — runs & writes without asking
- **◷ plan** — read-only; explores but makes no changes

### Sub-agents, web, MCP, hooks

- `spawn_agent` lets the model delegate an isolated subtask to a fresh context.
- `web_search` (DuckDuckGo) and `web_fetch` give it internet access.
- Drop a `.xcode/settings.json` to add **hooks** (run a formatter after every
  edit), **env** vars, seed **permissions**, and declare **MCP servers**:

```json
{
  "hooks": { "after_edit": ["ruff format {path}"] },
  "permissions": { "commands": ["git", "ls", "python"] },
  "mcpServers": {
    "fs": { "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "."] }
  }
}
```

MCP tools show up to the model as `mcp__<server>__<tool>`.

### Headless / scripting

```bash
xcoding -p "summarize what this repo does"        # read-only, prints, exits
xcoding -p "bump the version to 0.2.0" --yes      # auto-approve writes
xcoding -p "what changed?" --resume               # continue last session
```

## Configuration (env vars)

| var              | meaning                                              |
|------------------|------------------------------------------------------|
| `XCODE_BASE_URL` | point straight at any OpenAI-compatible `/v1` URL    |
| `XCODE_MODEL`    | force a specific model name                          |
| `XCODE_API_KEY`  | token if your endpoint needs one (default `local`)   |
| `XCODE_MAX_STEPS`| max tool round-trips per turn (default 25)           |

## How it works

```
cli.py       REPL + permission prompts (the only UI code)
agent.py     the loop: model ⇄ tools until it stops calling tools
backends.py  auto-detect Ollama (:11434) / llama.cpp (:8080)
tools.py     read_file, write_file, list_dir, run_command + JSON schemas
config.py    system prompt + knobs
```

## Roadmap

- [x] Streaming token output
- [x] `edit_file` (targeted edits instead of full rewrites)
- [x] `grep` / `glob_files` search tools
- [x] Persistent permission rules ("always allow `git …`")
- [x] `/model` picker + smart default-model selection
- [x] Context compaction for long sessions + context meter
- [x] Diff-style preview when confirming edits
- [x] Project memory (XCODE.md) + `/init`
- [x] Todo/task tracking
- [x] Session save + `--resume`
- [x] Headless mode (`-p`) + `@file` mentions
- [x] Web fetch / web search tools
- [x] Sub-agents (delegate a subtask to a fresh context)
- [x] MCP server support
- [x] Hooks + settings.json
- [x] Themes + ghost logo, shift+tab mode cycling (normal/auto/plan)

## Made by

Built by **@c7s89r** (nzv).

- GitHub: [@c7s89r](https://github.com/c7s89r)
- Discord: `c7s89r`

MIT licensed — see [LICENSE](LICENSE).
