"""The xcode REPL + headless runner.

Themed UI: ghost+trees welcome box, streaming output, persistent permissions,
diff-colored confirmations, auto mode, model picker, todos, @file mentions,
session save/resume, and a context meter.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

from rich.console import Console, Group
from rich.live import Live
from rich.markup import escape
from rich.panel import Panel
from rich.text import Text

from .agent import Agent
from .backends import (detect_backend, list_models, build_provider_backend,
                       Backend)
from . import providers
from .config import CONTEXT_TOKENS
from . import (memory, session, ui, hooks as hooks_mod, mcp as mcp_mod,
               input_bar, tools as tools_mod, update as update_mod,
               embedded as embedded_mod)
from .permissions import Permissions

console = Console()

COMMANDS = [
    ("/help", "Show available commands"),
    ("/local", "Run a built-in model — /local tiny|small|base"),
    ("/provider", "Switch backend: local, Claude, OpenAI, Groq, …"),
    ("/key", "Save an API key (/key openai sk-…)"),
    ("/model", "Switch the active model (or /model <name>)"),
    ("/models", "List models on reachable backends"),
    ("/auto", "Toggle auto mode (run & write without asking)"),
    ("/theme", "Switch color theme (/theme to list them)"),
    ("/vim", "Toggle vim editing mode in the input"),
    ("/status", "Show backend, model, mode, context, version"),
    ("/cost", "Show session cost (always $0 — runs locally)"),
    ("/doctor", "Check backend, version, and environment"),
    ("/config", "Show current settings"),
    ("/mcp", "List connected MCP servers and their tools"),
    ("/agents", "About sub-agents"),
    ("/init", "Explore the project and write an XCODE.md"),
    ("/memory", "Show the loaded project memory (XCODE.md)"),
    ("/todos", "Show the current task list"),
    ("/perms", "Show or clear saved permissions (/perms reset)"),
    ("/permissions", "Alias of /perms"),
    ("/export", "Export the conversation to a Markdown file"),
    ("/compact", "Summarize the conversation to free up context"),
    ("/clear", "Clear the conversation and the screen"),
    ("/sessions", "List saved sessions"),
    ("/resume", "Resume the latest (or a given) session"),
    ("/reset", "Clear the conversation"),
    ("/upgrade", "Check for and install a new version"),
    ("/release-notes", "Open the release notes"),
    ("/bug", "Report a bug on GitHub"),
    ("/login", "Not needed — xcode is local"),
    ("/logout", "Not needed — xcode is local"),
    ("/privacy", "How your data is handled"),
    ("/terminal-setup", "Terminal key setup info"),
    ("/exit", "Quit xcode"),
]

HELP = "Commands:\n" + "\n".join(
    f"  {name:<16} {desc}" for name, desc in COMMANDS
) + ("\n\nType a request to work. Use @path to attach files. "
     "Press esc to interrupt a reply, shift+tab to cycle modes.")


class UI:
    def __init__(self, backend, perms: Permissions, theme: dict,
                 mode: str = "normal", quiet: bool = False,
                 auto_allow: bool = False):
        self.backend = backend
        self.perms = perms
        self.theme = theme
        self.mode = mode
        self.quiet = quiet
        self.auto_allow = auto_allow
        self.last_file = None
        self._streaming = False
        self._think = None
        self._live = None
        self._partial = ""

    def _live_ok(self) -> bool:
        return not self.quiet and console.is_terminal

    def _live_render(self) -> Group:
        parts = []
        if self._partial:
            parts.append(Text(self._partial, style="white"))
        parts.append(self._think)
        return Group(*parts)

    def on_wait_start(self) -> None:
        self._partial = ""
        if not self._live_ok():
            return
        self._think = ui.ThinkingStatus(self.theme,
                                        get_shells=tools_mod.background_count)
        self._live = Live(self._live_render(), console=console,
                          refresh_per_second=12, transient=True)
        self._live.start()

    def on_wait_end(self) -> None:
        if self._live is not None:
            if self._partial:
                self._live.console.print(self._partial, style="white",
                                         highlight=False)
                self._partial = ""
            self._live.stop()
            self._live = None
            self._think = None
        self._streaming = False

    def on_token(self, text: str) -> None:
        if self._live is not None:
            if self._think is not None:
                self._think.tokens += max(1, len(text) // 4)
            data = self._partial + text
            *done, self._partial = data.split("\n")
            for line in done:
                self._live.console.print(line, style="white", highlight=False)
            self._live.update(self._live_render())
            return
        self._streaming = True
        console.print(text, end="", style="white", highlight=False)
        console.file.flush()

    def on_turn_end(self) -> None:
        if self._streaming:
            console.print()
            self._streaming = False

    def on_tool(self, name: str, args: dict) -> None:
        if args.get("path"):
            self.last_file = Path(args["path"]).name
        if self.quiet or name in ("update_todos", "ask_user"):
            return
        verb, target = _friendly(name, args)
        console.print(f"[{self.theme['accent']}]●[/] [bold]{escape(verb)}[/]"
                      f"([{self.theme['user']}]{escape(target)}[/])")
        if name == "run_command":
            console.print(f"  [{self.theme['tool']}]┌─ output ─[/]")

    def on_tool_result(self, name: str, args: dict, result: str) -> None:
        if self.quiet or name == "update_todos":
            return
        if name == "ask_user":
            return
        if name == "run_command":
            summary, ok = _summary(name, result)
            glyph = "[green]⎿[/]" if ok else "[red]⎿[/]"
            console.print(f"  [{self.theme['tool']}]└─[/]")
            console.print(f"  {glyph} [dim]{escape(summary)}[/]")
            return
        summary, ok = _summary(name, result)
        glyph = "[green]⎿[/]" if ok else "[red]⎿[/]"
        console.print(f"  {glyph} [dim]{escape(summary)}[/]")
        if name in ("edit_file", "write_file") and tools_mod.RENDER.get("diff"):
            _render_numbered_diff(tools_mod.RENDER["diff"])

    def on_todos(self, todos: list) -> None:
        if not self.quiet:
            _render_todos(todos, self.theme)

    def on_notice(self, msg: str) -> None:
        if not self.quiet:
            console.print(f"[dim italic]… {msg}[/]")

    def on_ask(self, question: str, options: list) -> str:
        options = [str(o) for o in options if str(o).strip()]
        if self.quiet or not options:
            return options[0] if options else ""
        choice = input_bar.select_menu(question, options)
        console.print(f"[{self.theme['accent']}]●[/] {escape(question)}")
        console.print(f"  [{self.theme['user']}]❯ {escape(choice)}[/]")
        return choice

    def confirm(self, kind: str, target: str, detail: str) -> bool:
        if self.auto_allow or self.mode == "auto" or self.perms.is_allowed(kind, target):
            return True

        if self.mode == "plan":
            console.print(f"[dim yellow]· plan mode — skipping {kind}[/]")
            return False

        if self.quiet:
            console.print(f"[dim yellow]· denied ({kind}); pass --yes to allow[/]")
            return False

        console.print(Panel(_colorize_diff(detail), title=f"[yellow]{kind}?[/]",
                            border_style="yellow", expand=False))

        ALWAYS = "Yes, and don't ask again"
        if kind == "run_command":
            always_desc = f"trust `{target.split()[0] if target.split() else target}` from now on"
        else:
            always_desc = f"trust all {kind} this session"
        try:
            choice = input_bar.select_menu(
                f"Allow this {kind}?",
                [("Yes", "run it once"),
                 (ALWAYS, always_desc),
                 ("No", "skip it and tell the model")],
            )
        except (EOFError, KeyboardInterrupt):
            return False

        if choice == "No":
            return False
        if choice == ALWAYS:
            if kind == "run_command":
                head = self.perms.allow_command(target)
                console.print(f"[dim green]· will always allow `{head} …`[/]")
            else:
                self.perms.allow_kind(kind)
                console.print(f"[dim green]· will always allow {kind}[/]")
        return True


def _short(v, n: int = 60) -> str:
    s = str(v).replace("\n", " ")
    return s if len(s) <= n else s[:n] + "…"


def _friendly(name: str, args: dict) -> tuple[str, str]:
    """Map a tool call to a (Verb, target) pair for the ● header line."""
    if name.startswith("mcp__"):
        try:
            _, server, tool = name.split("__", 2)
        except ValueError:
            server, tool = "mcp", name
        return f"{server}.{tool}", _short(next(iter(args.values()), ""), 50)
    table = {
        "read_file": ("Read", args.get("path", "")),
        "write_file": ("Write", args.get("path", "")),
        "edit_file": ("Update", args.get("path", "")),
        "list_dir": ("List", args.get("path", ".")),
        "glob_files": ("Search", args.get("pattern", "")),
        "grep": ("Search", args.get("pattern", "")),
        "run_command": ("Bash", _short(args.get("command", ""), 70)),
        "web_search": ("Web Search", args.get("query", "")),
        "web_fetch": ("Fetch", args.get("url", "")),
        "spawn_agent": ("Task", _short(args.get("task", ""), 50)),
    }
    return table.get(name, (name, _short(next(iter(args.values()), ""), 50)))


def _count_lines(text: str) -> int:
    return len(text.splitlines())


def _summary(name: str, result: str) -> tuple[str, bool]:
    """A one-line ⎿ summary plus whether it succeeded."""
    if result.startswith(("ERROR", "DENIED")):
        return (result.splitlines()[0][:80], False)
    if name in ("edit_file", "write_file"):
        diff = tools_mod.RENDER.get("diff", "")
        added = sum(1 for l in diff.splitlines()
                    if l.startswith("+") and not l.startswith("+++"))
        removed = sum(1 for l in diff.splitlines()
                      if l.startswith("-") and not l.startswith("---"))
        return (f"Added {added} line{'s'*(added!=1)}, "
                f"removed {removed} line{'s'*(removed!=1)}", True)
    if name == "read_file":
        return (f"Read {_count_lines(result)} lines", True)
    if name == "list_dir":
        return (f"{_count_lines(result)} items", True)
    if name == "glob_files":
        n = 0 if result.startswith("(no files") else _count_lines(result)
        return (f"Found {n} file{'s'*(n!=1)}", True)
    if name == "grep":
        n = 0 if result.startswith("(no matches") else _count_lines(result)
        return (f"{n} match{'es'*(n!=1)}", True)
    if name == "run_command":
        ok = "[exit 0]" in result or not result
        body = [l for l in result.splitlines()
                if l.strip() and not l.startswith("[exit")]
        first = body[0] if body else "(no output)"
        return (_short(first, 80), ok)
    if name == "web_search":
        n = sum(1 for l in result.splitlines() if l.startswith("- "))
        return (f"{n} result{'s'*(n!=1)}", True)
    if name == "web_fetch":
        return (f"Fetched {len(result)} chars", True)
    if name == "spawn_agent":
        return (f"Sub-agent finished ({len(result)} chars)", True)
    return (_short(result.splitlines()[0] if result else "ok", 80), True)


def _render_numbered_diff(diff: str, max_lines: int = 12) -> None:
    """Render a unified diff like Claude Code: line numbers + green/red."""
    new_no = 0
    shown = 0
    for line in diff.splitlines():
        if line.startswith(("---", "+++")):
            continue
        if line.startswith("@@"):
            m = re.search(r"\+(\d+)", line)
            new_no = int(m.group(1)) if m else new_no
            continue
        if shown >= max_lines:
            console.print("     [dim]…[/]")
            break
        content = escape(line[1:]) if line else ""
        if line.startswith("+"):
            console.print(f"  [dim]{new_no:>4}[/] [green]+ {content}[/]")
            new_no += 1; shown += 1
        elif line.startswith("-"):
            console.print(f"  [dim]     [/][red]- {content}[/]")
            shown += 1
        else:
            console.print(f"  [dim]{new_no:>4}   {content}[/]")
            new_no += 1; shown += 1


def _colorize_diff(text: str) -> Text:
    t = Text()
    for line in text.splitlines(keepends=True):
        s = line.rstrip("\n")
        if s.startswith(("+++", "---")):
            t.append(line, style="bold")
        elif s.startswith("+"):
            t.append(line, style="green")
        elif s.startswith("-"):
            t.append(line, style="red")
        elif s.startswith("@@"):
            t.append(line, style="cyan")
        else:
            t.append(line)
    return t


def _render_todos(todos: list, theme: dict) -> None:
    if not todos:
        console.print("[dim](no todos)[/]")
        return
    marks = {"completed": "[green]✓[/]", "in_progress": f"[{theme['mode']}]▶[/]",
             "pending": "[dim]○[/]"}
    lines = []
    for t in todos:
        mark = marks.get(t.get("status", "pending"), "○")
        text = t.get("content", "")
        if t.get("status") == "completed":
            lines.append(f" {mark} [dim strike]{text}[/]")
        else:
            lines.append(f" {mark} {text}")
    console.print(Panel("\n".join(lines), title="todos",
                        border_style=theme["border"], expand=False, padding=(0, 1)))


_MENTION = re.compile(r"@([^\s]+)")


def _expand_mentions(text: str) -> str:
    attached = []
    for m in _MENTION.finditer(text):
        p = Path(m.group(1))
        if p.is_file():
            try:
                body = p.read_text(encoding="utf-8", errors="replace")[:8000]
                attached.append(f"--- {p} ---\n{body}")
            except Exception:
                pass
    if not attached:
        return text
    return text + "\n\n[Attached files]\n" + "\n\n".join(attached)


def _print_status(backend, uic, agent) -> None:
    ver = update_mod.current_version() or "?"
    where = backend.describe() if backend.available else "none (no model running)"
    console.print(f"[bold]xcode[/] v{ver}")
    console.print(f"  backend   {where}")
    console.print(f"  mode      {uic.mode}")
    console.print(f"  context   ~{agent.context_tokens():,} tokens")
    console.print(f"  cwd       {Path.cwd()}")
    console.print(f"  models    {embedded_mod.MODEL_DIR}")
    console.print(f"  config    {providers.CONFIG_FILE}")


def _doctor(backend) -> None:
    console.print("[bold]xcode doctor[/]")
    console.print(f"  python    {sys.version.split()[0]}")
    console.print(f"  version   {update_mod.current_version() or '?'}")
    found = list_models()
    if found:
        for name, models in found.items():
            console.print(f"  [green]✓[/] {name}: {', '.join(models) or '(no models pulled)'}")
    else:
        console.print("  [yellow]✗[/] no local backend reachable "
                      "— start ollama or llama.cpp")
    cur, latest, avail = update_mod.check()
    if avail:
        console.print(f"  [yellow]update[/] {cur} → {latest}  (run /upgrade)")
    elif cur:
        console.print("  [green]✓[/] up to date")


def _export_conversation(agent, path: str | None = None) -> str | None:
    from datetime import datetime
    lines: list[str] = []
    for m in agent.messages:
        role = m.get("role")
        if role == "system":
            continue
        content = m.get("content") or ""
        if role == "user":
            lines.append(f"## You\n\n{content}\n")
        elif role == "assistant":
            if content:
                lines.append(f"## xcode\n\n{content}\n")
            for tc in m.get("tool_calls", []) or []:
                fn = tc.get("function", {})
                lines.append(f"> 🛠 `{fn.get('name')}` {fn.get('arguments', '')}\n")
        elif role == "tool":
            lines.append(f"> ⎿ {(content or '')[:500]}\n")
    if not lines:
        return None
    if not path:
        path = f"xcode-conversation-{datetime.now():%Y%m%d-%H%M%S}.md"
    try:
        Path(path).write_text("\n".join(lines), encoding="utf-8")
        return path
    except Exception:
        return None


def _toggle_vim(bar) -> bool:
    try:
        from prompt_toolkit.enums import EditingMode
        s = getattr(bar, "_session", None)
        if s is None:
            return False
        s.editing_mode = (EditingMode.EMACS if s.editing_mode == EditingMode.VI
                          else EditingMode.VI)
        return s.editing_mode == EditingMode.VI
    except Exception:
        return False


def _make_agent(uic: UI, settings=None, mcp=None) -> Agent:
    return Agent(uic.backend, confirm=uic.confirm, on_token=uic.on_token,
                 on_turn_end=uic.on_turn_end, on_tool=uic.on_tool,
                 on_tool_result=uic.on_tool_result, on_ask=uic.on_ask,
                 on_todos=uic.on_todos, on_notice=uic.on_notice,
                 on_wait_start=uic.on_wait_start, on_wait_end=uic.on_wait_end,
                 project_memory=memory.load(), settings=settings, mcp=mcp)


def _boot_local(existing=None):
    from openai import OpenAI
    from rich.progress import (Progress, BarColumn, DownloadColumn,
                               TransferSpeedColumn, TextColumn)

    if embedded_mod.is_up():
        return Backend("local", embedded_mod.BASE_URL, embedded_mod.model_alias(),
                       OpenAI(base_url=embedded_mod.BASE_URL, api_key="local"))

    if not embedded_mod.have_engine():
        console.print("[bold]Setting up a built-in model[/] — no Ollama needed.")
    if not embedded_mod.ensure_engine(log=lambda s: console.print(f"[dim]{s}[/]")):
        return None

    if not embedded_mod.model_ready():
        console.print(f"[dim]downloading {embedded_mod.model_file()} "
                      f"({embedded_mod.model_size()}, one time)…[/]")
        with Progress(TextColumn("  [cyan]model[/]"), BarColumn(),
                      DownloadColumn(), TransferSpeedColumn(),
                      console=console, transient=True) as prog:
            task = prog.add_task("download", total=None)

            def on_progress(done, total):
                prog.update(task, completed=done, total=total or None)

            path = embedded_mod.ensure_model(progress=on_progress,
                                             log=lambda s: console.print(f"[red]{s}[/]"))
        if not path:
            console.print("[yellow]model download failed.[/]")
            return None
        console.print("[green]model ready.[/]")

    console.print("[dim]starting the local server…[/]")
    if not embedded_mod.start_server(log=lambda s: console.print(f"[yellow]{s}[/]")):
        return None

    bk = Backend("local", embedded_mod.BASE_URL, embedded_mod.model_alias(),
                 OpenAI(base_url=embedded_mod.BASE_URL, api_key="local"))
    if existing is not None:
        existing.adopt(bk)
        console.print(f"[green]running[/] {existing.describe()}")
        return existing
    return bk


def _activate_provider(name: str, backend) -> None:
    p = providers.PROVIDERS.get(name)
    if not p:
        console.print(f"[yellow]unknown provider '{name}'[/] — "
                      f"try one of: {', '.join(providers.PROVIDERS)}")
        return
    if p.get("local"):
        providers.clear_active()
        try:
            backend.adopt(detect_backend())
            console.print(f"[green]switched to[/] {backend.describe()}")
        except RuntimeError as e:
            console.print(f"[yellow]{e}[/]")
        return
    key = providers.get_key(name)
    if not key:
        if p.get("console"):
            console.print(f"[dim]get a key: {p['console']}[/]")
        try:
            key = console.input(f"  paste your {p['label']} API key: ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("[yellow]cancelled[/]"); return
        if not key:
            console.print("[yellow]no key — cancelled[/]"); return
        providers.set_key(name, key)
    providers.set_active(name)
    bk = build_provider_backend(name)
    if bk is None:
        console.print("[yellow]could not configure that provider[/]"); return
    backend.adopt(bk)
    console.print(f"[green]connected[/] {backend.describe()}")
    console.print(f"[dim]model: {backend.model} — change it with /model <name>[/]")


def _provider_menu(backend) -> None:
    cur = providers.load_config().get("provider", "")
    options = []
    for name, p in providers.PROVIDERS.items():
        label = name + ("  ✓" if name == cur else "")
        options.append((label, p["label"]))
    choice = input_bar.select_menu("Choose a provider", options)
    if not choice:
        return
    _activate_provider(choice.split()[0], backend)


def _pick_model(uic: UI) -> None:
    options: list[tuple[str, str]] = []
    for name, models in list_models().items():
        for mdl in models:
            label = f"{mdl} ✓" if mdl == uic.backend.model else mdl
            options.append((label, f"on {name}"))
    if not options:
        console.print("[yellow]no models found[/]")
        return
    choice = input_bar.select_menu("Switch model", options)
    if not choice:
        return
    picked = choice[:-2] if choice.endswith(" ✓") else choice
    if picked == uic.backend.model:
        return
    uic.backend.model = picked
    _remember_choice(uic.backend)
    console.print(f"[green]switched to[/] {uic.backend.model}")


def _remember_choice(backend) -> None:
    if backend.name in ("ollama", "llamacpp"):
        providers.remember_local(backend.model)
    elif backend.name == "local":
        providers.remember_embedded()
    elif backend.name in providers.PROVIDERS:
        providers.set_active(backend.name, backend.model)


def _run_headless(args) -> int:
    try:
        backend = detect_backend()
    except RuntimeError as e:
        console.print(f"[red]{e}[/]")
        return 1
    if args.model:
        backend.model = args.model
    prefs = ui.load_prefs()
    perms = Permissions()
    settings = hooks_mod.Settings()
    settings.seed_permissions(perms)
    uic = UI(backend, perms, ui.get_theme(prefs.get("theme", "ghost")),
             quiet=True, auto_allow=args.yes)
    mcp = mcp_mod.McpManager()
    mcp.connect_all(settings.data.get("mcpServers", {}))
    agent = _make_agent(uic, settings=settings, mcp=mcp)
    if args.resume:
        data = session.latest()
        if data:
            agent.load_messages(data["messages"])
    try:
        agent.send(_expand_mentions(args.print))
    except Exception as e:
        console.print(f"[red]error: {e}[/]")
        return 1
    return 0


def _update_gate() -> None:
    cur, latest, avail = update_mod.check()
    if not avail:
        return
    console.clear()
    body = Text()
    body.append("A new version of xcode is available\n\n", style="bold")
    body.append(f"  installed   {cur}\n", style="dim")
    body.append(f"  latest      {latest}\n", style="green")
    body.append("\n[I] install        [C] cancel", style="bold")
    console.print(Panel(body, title="xcode update", border_style="cyan",
                        expand=False, padding=(1, 3)))
    try:
        choice = console.input("  > ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return
    if choice in ("i", "install", "y", "yes"):
        if update_mod.upgrade_detached():
            console.print(f"\n[green]updating to {latest} in the background…[/]")
            console.print("[dim]xcode will close — run [/][bold]xcode[/][dim] "
                          "again in a few seconds.[/]\n")
            sys.exit(0)
        console.print("[red]could not start the update.[/] "
                      "Close xcode and run: [bold]pip install -U xcoding[/]\n")
    else:
        console.clear()


def _startup_backend(args):
    if getattr(args, "local", False) or providers.use_embedded():
        booted = _boot_local()
        return booted if booted is not None else detect_backend(allow_missing=True)

    cfg = providers.load_config()
    if cfg.get("provider") or cfg.get("local_model"):
        return detect_backend(allow_missing=True)

    if embedded_mod.model_ready():
        booted = _boot_local()
        if booted is not None:
            providers.remember_embedded()
            return booted
    else:
        probe = detect_backend(allow_missing=True)
        if probe.available:
            return probe
        booted = _boot_local()
        if booted is not None:
            providers.remember_embedded()
            return booted
        return probe

    return detect_backend(allow_missing=True)


def _run_repl(args) -> int:
    _update_gate()
    backend = _startup_backend(args)
    if args.model:
        backend.model = args.model

    prefs = ui.load_prefs()
    theme = ui.get_theme(prefs.get("theme", "ghost"))
    perms = Permissions()
    settings = hooks_mod.Settings()
    settings.seed_permissions(perms)
    uic = UI(backend, perms, theme, mode=prefs.get("mode", "normal"))

    mcp = mcp_mod.McpManager()

    agent = _make_agent(uic, settings=settings, mcp=mcp)
    session_id = None

    notes = []
    if memory.load():
        notes.append("XCODE.md")
    if settings.loaded:
        notes.append("settings.json")
    mem_note = (" " + " · ".join(notes)) if notes else ""
    console.print(ui.welcome(theme, backend.model, str(Path.cwd()), mem_note))
    if not backend.available:
        console.print(f"[yellow]{backend.note}[/]")
        console.print("[dim]No setup? Type [/][bold]/local[/][dim] to download a small "
                      "built-in model and run it right here.[/]")
        console.print("[dim]Or start a model and just type — I'll connect when it's up.[/]")
    console.print()

    def _save_mode(m):
        prefs["mode"] = m
        ui.save_prefs(prefs)
    bar = input_bar.InputBar(uic, on_mode_change=_save_mode, commands=COMMANDS)

    if args.resume:
        data = session.latest()
        if data:
            agent.load_messages(data["messages"])
            session_id = data["id"]
            console.print(f"[green]resumed[/] session {session_id} "
                          f"({len(data['messages'])} msgs)\n")

    while True:
        if not input_bar.AVAILABLE:
            console.print(ui.status_line(theme, uic.mode, agent.context_tokens(),
                                         CONTEXT_TOKENS, backend.model))
            console.rule(style=theme["border"])
        try:
            raw = bar.ask(backend.model, agent.conversation_tokens, CONTEXT_TOKENS).strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]bye 👻[/]")
            break
        if not raw:
            continue

        if raw in ("/exit", "/quit"):
            console.print("[dim]bye 👻[/]"); break
        if raw == "/help":
            console.print(HELP); continue
        if raw == "/auto":
            uic.mode = "auto" if uic.mode == "normal" else "normal"
            prefs["mode"] = uic.mode; ui.save_prefs(prefs)
            if uic.mode == "auto":
                console.print(f"[{theme['mode']}]⏵⏵ auto mode ON[/] — "
                              "running & writing without asking")
            else:
                console.print("[dim]·· auto mode off — I'll ask before changes[/]")
            continue
        if raw.startswith("/theme"):
            parts = raw.split()
            if len(parts) > 1 and parts[1] in ui.THEMES:
                theme = ui.get_theme(parts[1]); uic.theme = theme
                prefs["theme"] = parts[1]; ui.save_prefs(prefs)
                console.print(ui.welcome(theme, backend.model, str(Path.cwd())))
            elif len(parts) > 1:
                console.print(f"[yellow]no theme '{parts[1]}'[/]")
                console.print(ui.theme_gallery(prefs.get("theme", "ghost")))
            else:
                console.print(ui.theme_gallery(prefs.get("theme", "ghost")))
            continue
        if raw == "/models":
            for name, models in list_models().items():
                console.print(f"[bold]{name}[/]: {', '.join(models) or '(none)'}")
            continue
        if raw == "/mcp":
            if not mcp.clients:
                console.print("[dim]no MCP servers connected "
                              "(add them in .xcode/settings.json)[/]")
            for sname, client in mcp.clients.items():
                tools = ", ".join(t["name"] for t in client.tools) or "(none)"
                console.print(f"[bold]{sname}[/]: {tools}")
            continue
        if raw == "/memory":
            mem = memory.load()
            console.print(mem if mem else "[dim]no XCODE.md found (run /init)[/]")
            continue
        if raw.startswith("/model "):
            name = raw.split(maxsplit=1)[1].strip()
            uic.backend.model = name
            _remember_choice(uic.backend)
            console.print(f"[green]model set to[/] {name}"); continue
        if raw == "/model":
            _pick_model(uic); continue
        if raw.split()[0] in ("/local", "/try"):
            parts = raw.split()
            if len(parts) > 1:
                if parts[1] in embedded_mod.PRESETS:
                    os.environ["XCODE_LOCAL_MODEL"] = parts[1]
                    embedded_mod.stop_server()
                else:
                    console.print(f"[dim]sizes: {', '.join(embedded_mod.PRESETS)} "
                                  "(tiny=fastest, base=smartest)[/]")
            if _boot_local(backend) is not None:
                providers.remember_embedded()
            continue
        if raw.startswith("/provider"):
            parts = raw.split(maxsplit=1)
            if len(parts) > 1:
                _activate_provider(parts[1].strip(), backend)
            else:
                _provider_menu(backend)
            continue
        if raw.startswith("/key"):
            parts = raw.split()
            if len(parts) >= 3:
                providers.set_key(parts[1], parts[2])
                console.print(f"[green]saved API key for {parts[1]}[/]")
            else:
                console.print("usage: /key <provider> <api-key>   "
                              f"(providers: {', '.join(providers.PROVIDERS)})")
            continue
        if raw == "/todos":
            _render_todos(agent.todos, theme); continue
        if raw == "/perms":
            console.print(f"[bold]saved permissions:[/] {uic.perms.summary()}")
            continue
        if raw == "/perms reset":
            uic.perms.reset(); console.print("[dim]permissions cleared[/]"); continue
        if raw == "/compact":
            did = agent.compact(force=True)
            console.print("[dim]compacted[/]" if did else "[dim]nothing to compact[/]")
            continue
        if raw == "/sessions":
            rows = session.listing()
            if not rows:
                console.print("[dim](no saved sessions)[/]")
            for r in rows:
                console.print(f"  [cyan]{r['id']}[/] · {r['turns']} turns · "
                              f"{r['model']} · [dim]{r['first']}[/]")
            continue
        if raw.startswith("/resume"):
            parts = raw.split()
            data = session.load(parts[1]) if len(parts) > 1 else session.latest()
            if not data:
                console.print("[yellow]no such session[/]")
            else:
                agent.load_messages(data["messages"]); session_id = data["id"]
                console.print(f"[green]resumed[/] {session_id}")
            continue
        if raw == "/reset":
            agent.reset(); session_id = None
            console.print("[dim]conversation cleared[/]"); continue
        if raw == "/clear":
            agent.reset(); session_id = None
            console.clear()
            console.print(ui.welcome(theme, backend.model, str(Path.cwd())))
            console.print(); continue
        if raw == "/permissions":
            console.print(f"[bold]saved permissions:[/] {uic.perms.summary()}")
            continue
        if raw in ("/status", "/about"):
            _print_status(backend, uic, agent); continue
        if raw == "/cost":
            console.print("[green]$0.00[/] — xcode runs a local model, "
                          "so there are no API costs."); continue
        if raw == "/doctor":
            _doctor(backend); continue
        if raw == "/config":
            console.print(f"  [bold]theme[/]  {prefs.get('theme', 'ghost')}")
            console.print(f"  [bold]mode[/]   {uic.mode}")
            console.print(f"  [dim]prefs: {ui.PREFS}[/]"); continue
        if raw == "/agents":
            console.print("[dim]Sub-agents are built in — ask me to delegate a "
                          "subtask and I'll spawn an isolated agent automatically.[/]")
            continue
        if raw.startswith("/export"):
            parts = raw.split(maxsplit=1)
            out = _export_conversation(agent, parts[1].strip() if len(parts) > 1 else None)
            console.print(f"[green]exported[/] → {out}" if out
                          else "[yellow]nothing to export yet[/]"); continue
        if raw == "/vim":
            on = _toggle_vim(bar)
            console.print(f"[dim]vim mode {'on' if on else 'off'}[/]"); continue
        if raw in ("/upgrade", "/update"):
            _update_gate(); continue
        if raw in ("/release-notes", "/changelog"):
            console.print("Release notes: "
                          "https://github.com/c7s89r/xcode/releases"); continue
        if raw == "/bug":
            console.print("Report a bug: "
                          "https://github.com/c7s89r/xcode/issues/new"); continue
        if raw in ("/login", "/logout"):
            console.print("[dim]xcode talks to a local model — "
                          "no account or login needed.[/]"); continue
        if raw in ("/privacy", "/privacy-settings"):
            console.print("[dim]Everything stays on your machine. No telemetry, "
                          "nothing leaves your computer.[/]"); continue
        if raw == "/terminal-setup":
            console.print("[dim]Enter sends · Shift+Enter inserts a newline "
                          "(auto-configured on Windows).[/]"); continue
        if raw.startswith("/add-dir"):
            console.print("[dim]xcode already reads your whole project tree "
                          "from the current directory.[/]"); continue
        if raw == "/init":
            raw = memory.INIT_INSTRUCTION

        if not backend.available:
            try:
                backend.adopt(detect_backend())
                console.print(f"[green]connected[/] {backend.describe()}\n")
            except RuntimeError as e:
                console.print(f"[yellow]{e}[/]\n")
                continue

        try:
            agent.send(_expand_mentions(raw))
            session_id = session.save(agent.messages, backend.model, session_id)
            if agent.interrupted:
                console.print("[yellow]⎿ interrupted[/] [dim]· press esc anytime to stop a reply[/]")
        except KeyboardInterrupt:
            uic.on_turn_end()
            console.print("[yellow]⎿ interrupted[/] [dim]· press esc anytime to stop a reply[/]")
        except Exception as e:
            uic.on_turn_end(); console.print(f"[red]error: {e}[/]")
        console.print()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="xcoding",
                                     description="Local-model coding agent.")
    parser.add_argument("-p", "--print", metavar="PROMPT",
                        help="headless: run one prompt, print result, exit")
    parser.add_argument("-m", "--model", help="force a model name")
    parser.add_argument("--resume", action="store_true",
                        help="resume the most recent session")
    parser.add_argument("--yes", action="store_true",
                        help="headless: auto-approve writes/commands")
    parser.add_argument("--local", action="store_true",
                        help="download & run a small built-in model (no Ollama needed)")
    args = parser.parse_args()

    rc = _run_headless(args) if args.print else _run_repl(args)
    sys.exit(rc)


if __name__ == "__main__":
    main()
