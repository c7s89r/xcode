# xcoding · by [@c7s89r](https://github.com/c7s89r)
<img width="421" height="269" alt="image" src="https://github.com/user-attachments/assets/ab92aad1-0d05-4f66-8315-cbab80d6473e" />

A local-model coding agent — like Claude Code, but it talks to a
model running on your own machine instead of a cloud API.

> **✅ Works with [Ollama](https://ollama.com) for now.** Just install Ollama,
> pull a tool-capable model, then `pip install xcoding` and run `xcoding`.
> (llama.cpp support is in too, but Ollama is the tested path.)

It auto-detects whichever backend is running, gives the model tools to read/write
files and run shell commands, and loops until your task is done. Every file write
and every shell command asks for your approval first.
[![Watch the video](https://cdn-cf-east.streamable.com/image/rpw3lf.jpg)](https://streamable.com/rpw3lf)
### Zero-setup (no Ollama, no API key)

```bash
pip install xcoding
xcode --local
```

`--local` grabs a capable model and runs it **in-process** — no Ollama, no
llama.cpp, no API key, nothing to configure. **Runs CPU-only** (no GPU needed).
You can also type `/local` inside xcode.

Pick a size for your machine (default is **base**):

| size | model | download | notes |
|------|-------|----------|-------|
| `tiny`  | Qwen2.5-0.5B | ~0.4 GB | fastest; **chat only** — too small to use tools reliably |
| `small` | Qwen2.5-1.5B | ~1 GB   | light; tool use is hit-or-miss |
| `base`  | Qwen2.5-3B   | ~2 GB   | **default** — the smallest that reliably drives the agent (reads/edits files, runs commands) |

```bash
xcode --local                    # base (3B) by default — runs on CPU
XCODE_LOCAL_MODEL=tiny xcode --local
# or inside xcode:  /local tiny   ·   /local base
```

> The 3B is the floor for an agent that actually *uses tools*; smaller models
> mostly just chat. The 3B still runs fine on a plain CPU (~2 GB RAM for the
> weights) — just slower than on a GPU.

It installs the right **prebuilt** engine for your machine automatically — no
compiler needed:

- **NVIDIA GPU** → CUDA build, offloads the model to your GPU
- **Apple Silicon** → Metal build, runs on the GPU
- **AMD / no GPU / anything else** → optimized CPU build (always works)

(Detection is automatic; force it with `XCODE_LOCAL_ACCEL=cuda|metal|cpu`.)

### Quick start (Ollama)

```bash
ollama serve
ollama pull qwen2.5-coder     # a model that's good at tool use
pip install xcoding
xcoding
```

## Install

### One-liner (recommended — also fixes PATH for you)

**Windows** (PowerShell):

```powershell
iex (irm https://raw.githubusercontent.com/c7s89r/xcode/main/install.ps1)
```

**Linux / macOS**:

```bash
curl -fsSL https://raw.githubusercontent.com/c7s89r/xcode/main/install.sh | bash
```

These detect your Python, install `xcoding`, and add pip's scripts folder to
your `PATH` so `xcode` works in a new terminal — no "command not found".

### With pip

```bash
pip install xcoding
```

Then run `xcode` (or `xcoding`) from any project folder.

Or from source:

```bash
pip install -e .
```

(Python 3.9+. Pulls in `openai`, `httpx`, `rich`.)

### `xcoding: command not found` after installing?

Install worked, but your shell can't find the command? This almost always
means pip put the `xcoding` launcher in its **Scripts** folder, which isn't on
your `PATH`. (Having `python` on PATH is **not** the same thing — the launcher
lives in a separate directory.) pip usually prints a warning about this during
install, e.g. *"The script xcoding.exe is installed in '...\Scripts' which is
not on PATH."*

Two ways to fix it:

1. **Just run it as a module** (works whenever `python` is on PATH):

   ```bash
   python -m xcode
   ```

2. **Put pip's scripts folder on PATH.** Find where it is:

   ```bash
   pip show -f xcoding                                          # lists installed files
   python -c "import sysconfig; print(sysconfig.get_path('scripts'))"
   ```

   Add that printed folder to your `PATH`, then open a new terminal. Typical
   locations:

   - **Windows:** `%APPDATA%\Python\Python3X\Scripts` (user install) or
     `...\PythonXX\Scripts` next to `python.exe`
   - **macOS/Linux:** `~/.local/bin`

   On Windows you can also reinstall without `--user` so the launcher lands
   next to `python.exe`, or use `py -m pip install xcoding`.

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

## Cloud APIs (Claude, OpenAI, and more)

Prefer a hosted model? xcode talks to any OpenAI-compatible API, with presets
for the big providers. Inside xcode, just run **`/provider`** and pick one — it
asks for your API key once, saves it to `~/.xcode/config.json`, and switches
over. Switch back to local anytime with `/provider ollama`.

Built-in providers: **anthropic** (Claude), **openai** (GPT), **openrouter**,
**groq**, **deepseek**, **mistral**, **together**, **xai** (Grok),
**gemini**, plus local **ollama** / **llamacpp**.

```
/provider                 browse and pick a provider
/provider openai          switch to a provider (prompts for a key if needed)
/key openai sk-…          save an API key without the prompt
/model gpt-4o-mini        set the exact model name for the active provider
```

Or configure it with env vars (no in-app step):

```bash
export XCODE_PROVIDER=anthropic
export ANTHROPIC_API_KEY=sk-ant-…
# optional: export XCODE_MODEL=claude-sonnet-4-5
```

> **Heads-up on billing:** an API key is **not** the same as a Claude Pro or
> ChatGPT Plus subscription. The API is billed separately, pay-as-you-go —
> get a key at [console.anthropic.com](https://console.anthropic.com/settings/keys)
> or [platform.openai.com](https://platform.openai.com/api-keys). A Pro/Plus
> plan alone won't authenticate the API.

## Use it

```bash
xcoding
# same thing:  xcode
# or:          python -m xcode
```

`xcoding` and `xcode` are interchangeable — type whichever you like.

Then just talk to it:

```
› add a /health endpoint to app.py that returns {"ok": true}
```

Type `/` to see every command. There's a full Claude-Code-style set:
`/help`, `/model`, `/models`, `/auto`, `/theme`, `/vim`, `/status`, `/cost`,
`/doctor`, `/config`, `/mcp`, `/agents`, `/init`, `/memory`, `/todos`, `/perms`,
`/export`, `/compact`, `/clear`, `/sessions`, `/resume`, `/reset`, `/upgrade`,
`/release-notes`, `/bug`, `/login`, `/logout`, `/privacy`, `/terminal-setup`,
`/exit`.

- **Press `esc` while it's replying to interrupt** — it stops mid-thought and
  hands the prompt back, just like Claude Code.
- **16 color themes** — run `/theme` to browse the gallery, `/theme nord` to
  switch (ghost, matrix, dracula, ember, mono, nord, gruvbox, solarized, neon,
  ocean, rose, sunset, ice, forest, vapor, coffee).
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
