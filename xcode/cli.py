"""The xcode REPL + headless runner.

Themed UI: ghost+trees welcome box, streaming output, persistent permissions,
diff-colored confirmations, auto mode, model picker, todos, @file mentions,
session save/resume, and a context meter.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from rich.console import Console, Group
from rich.live import Live
from rich.markup import escape
from rich.panel import Panel
from rich.text import Text

from .agent import Agent
from .backends import detect_backend, list_models
from .config import CONTEXT_TOKENS
from . import (memory, session, ui, hooks as hooks_mod, mcp as mcp_mod,
               input_bar, tools as tools_mod)
from .permissions import Permissions

console = Console()

# (command, description) — drives both /help and the slash-completion dropdown.
COMMANDS = [
    ("/help", "Show available commands"),
    ("/model", "Switch the active model"),
    ("/models", "List models on reachable backends"),
    ("/auto", "Toggle auto mode (run & write without asking)"),
    ("/theme", "Switch theme: ghost, matrix, dracula, ember, mono"),
    ("/mcp", "List connected MCP servers and their tools"),
    ("/init", "Explore the project and write an XCODE.md"),
    ("/memory", "Show the loaded project memory (XCODE.md)"),
    ("/todos", "Show the current task list"),
    ("/perms", "Show or clear saved permissions (/perms reset)"),
    ("/compact", "Summarize the conversation to free up context"),
    ("/sessions", "List saved sessions"),
    ("/resume", "Resume the latest (or a given) session"),
    ("/reset", "Clear the conversation"),
    ("/exit", "Quit xcode"),
]

HELP = "Commands:\n" + "\n".join(
    f"  {name:<10} {desc}" for name, desc in COMMANDS
) + "\n\nType a request to work. Use @path to attach files."


# ----------------------------------------------------------------- UI glue

class UI:
    def __init__(self, backend, perms: Permissions, theme: dict,
                 mode: str = "normal", quiet: bool = False,
                 auto_allow: bool = False):
        self.backend = backend
        self.perms = perms
        self.theme = theme
        self.mode = mode              # "normal" | "auto"
        self.quiet = quiet            # headless: suppress chatter
        self.auto_allow = auto_allow  # headless --yes
        self.last_file = None         # shown on the right of the input bar
        self._streaming = False
        # live "✻ Envisioning…" spinner state
        self._think = None            # ui.ThinkingStatus
        self._live = None             # rich.live.Live
        self._partial = ""            # current unfinished line of the reply

    # ---- the Claude-Code-style thinking spinner ---------------------------
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
            if self._partial:           # flush the last, unfinished line
                self._live.console.print(self._partial, style="white",
                                         highlight=False)
                self._partial = ""
            self._live.stop()
            self._live = None
            self._think = None
        self._streaming = False

    def on_token(self, text: str) -> None:
        # Live mode: stream finished lines above the pinned spinner.
        if self._live is not None:
            if self._think is not None:
                self._think.tokens += max(1, len(text) // 4)
            data = self._partial + text
            *done, self._partial = data.split("\n")
            for line in done:
                self._live.console.print(line, style="white", highlight=False)
            self._live.update(self._live_render())
            return
        # Fallback (headless / no TTY): plain inline streaming.
        # Also used for command output streaming
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
        # For run_command, add a visual separator before streaming output
        if name == "run_command":
            console.print(f"  [{self.theme['tool']}]┌─ output ─[/]")

    def on_tool_result(self, name: str, args: dict, result: str) -> None:
        if self.quiet or name == "update_todos":
            return
        if name == "ask_user":            # the menu already showed the Q&A
            return
        # For run_command, output was already streamed, just show summary
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
        if self.quiet or not options:        # headless: take the first option
            return options[0] if options else ""
        choice = input_bar.select_menu(question, options)
        # Record the Q&A in scrollback (the menu itself erases on exit).
        console.print(f"[{self.theme['accent']}]●[/] {escape(question)}")
        console.print(f"  [{self.theme['user']}]❯ {escape(choice)}[/]")
        return choice

    def confirm(self, kind: str, target: str, detail: str) -> bool:
        if self.auto_allow or self.mode == "auto" or self.perms.is_allowed(kind, target):
            return True  # silent — the ● header + mode bar already show intent

        # Plan mode: explore but make no changes.
        if self.mode == "plan":
            console.print(f"[dim yellow]· plan mode — skipping {kind}[/]")
            return False

        # Headless/non-interactive: never block on a prompt — deny mutations.
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


# ---- Claude-Code-style tool rendering ----------------------------------

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


# ------------------------------------------------------------ @file mentions

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


# ----------------------------------------------------------------- builders

def _make_agent(uic: UI, settings=None, mcp=None) -> Agent:
    return Agent(uic.backend, confirm=uic.confirm, on_token=uic.on_token,
                 on_turn_end=uic.on_turn_end, on_tool=uic.on_tool,
                 on_tool_result=uic.on_tool_result, on_ask=uic.on_ask,
                 on_todos=uic.on_todos, on_notice=uic.on_notice,
                 on_wait_start=uic.on_wait_start, on_wait_end=uic.on_wait_end,
                 project_memory=memory.load(), settings=settings, mcp=mcp)


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
    # Strip the current-model checkmark we may have appended to the label.
    picked = choice[:-2] if choice.endswith(" ✓") else choice
    if picked == uic.backend.model:
        return
    uic.backend.model = picked
    console.print(f"[green]switched to[/] {uic.backend.model}")


# ----------------------------------------------------------------- headless

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


# ----------------------------------------------------------------- REPL

def _run_repl(args) -> int:
    try:
        backend = detect_backend()
    except RuntimeError as e:
        console.print(f"[red]{e}[/]")
        return 1
    if args.model:
        backend.model = args.model

    prefs = ui.load_prefs()
    theme = ui.get_theme(prefs.get("theme", "ghost"))
    perms = Permissions()
    settings = hooks_mod.Settings()
    settings.seed_permissions(perms)
    uic = UI(backend, perms, theme, mode=prefs.get("mode", "normal"))

    mcp = mcp_mod.McpManager()
    # Don't connect MCP on startup - lazy load when needed
    # mcp.connect_all(settings.data.get("mcpServers", {}),
    #                 on_status=lambda s: console.print(f"[dim]· {s}[/]"))

    agent = _make_agent(uic, settings=settings, mcp=mcp)
    session_id = None

    notes = []
    if memory.load():
        notes.append("XCODE.md")
    if settings.loaded:
        notes.append("settings.json")
    mem_note = (" " + " · ".join(notes)) if notes else ""
    console.print(ui.welcome(theme, backend.model, str(Path.cwd()), mem_note))
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
        if not input_bar.AVAILABLE:  # plain fallback shows a status line
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

        # ---- slash commands ----
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
            else:
                console.print(f"themes: {', '.join(ui.THEMES)}  "
                              f"(usage: /theme matrix)")
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
        if raw == "/model":
            _pick_model(uic); continue
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
        if raw == "/init":
            raw = memory.INIT_INSTRUCTION

        # ---- a real request ----
        try:
            agent.send(_expand_mentions(raw))
            session_id = session.save(agent.messages, backend.model, session_id)
        except KeyboardInterrupt:
            uic.on_turn_end(); console.print("\n[yellow]interrupted[/]")
        except Exception as e:
            uic.on_turn_end(); console.print(f"[red]error: {e}[/]")
        console.print()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="xcode",
                                     description="Local-model coding agent.")
    parser.add_argument("-p", "--print", metavar="PROMPT",
                        help="headless: run one prompt, print result, exit")
    parser.add_argument("-m", "--model", help="force a model name")
    parser.add_argument("--resume", action="store_true",
                        help="resume the most recent session")
    parser.add_argument("--yes", action="store_true",
                        help="headless: auto-approve writes/commands")
    args = parser.parse_args()

    rc = _run_headless(args) if args.print else _run_repl(args)
    sys.exit(rc)


if __name__ == "__main__":
    main()
