"""Claude-Code-style input bar: rules above and below the ❯ prompt, with a
status line below (mode, then the current file + token count).

The rules are sized to FIT THE TEXT on their line — not the full terminal
width. The top rule matches the `❯ ` prompt + its ghost placeholder; the
bottom rule matches the status line. The status line packs its segments
together with small separators rather than pushing the token count to the
far edge.

There are NO blank lines between the prompt and the status line — the bar is
exactly: rule / `❯` line / rule / status. On Win32 prompt_toolkit otherwise
stuffs a column of blanks in there; `_compact_layout()` pins the input window
to its content height so that slack falls below the bar instead.

⚠️ DO NOT revert these rules back to full terminal width (`"─" * w`),
re-introduce a large `pad` gap in the status line, or remove
`_compact_layout()`. "Fit the words, no blank lines" is the intended look and
must stay this way. See `_rule()`, `_compact_layout()`, `_message()`,
`_toolbar()`.

Live mode cycling via shift+tab. Falls back to a plain prompt if
prompt_toolkit isn't available (or isn't on a real console).
"""

from __future__ import annotations

import random
import shutil

MODES = ["normal", "auto", "plan"]
_LABEL = {
    "normal": ("·· normal", "ask before changes"),
    "auto":   ("⏵⏵ auto", "run & write without asking"),
    "plan":   ("◷ plan", "read-only, no changes"),
}

PLACEHOLDERS = [
    'Try "fix typecheck errors"',
    'Try "how does <filepath> work?"',
    'Try "add tests for the auth module"',
    'Try "explain this stack trace"',
    'Try "refactor this function to be smaller"',
    'Try "what does this regex do?"',
    'Try "write a commit message for my changes"',
    'Try "find where we handle login"',
    'Try "why is this test flaky?"',
    'Try "add a --verbose flag to the CLI"',
    'Ask me to "make it more compact"',
    'Use @file to attach a file to your message',
    'Press shift+tab to cycle normal → auto → plan',
    'Type / to see every slash command',
    'Hit ctrl+z to undo your last edit',
    'Run /theme matrix to go full hacker mode',
    'Press esc while I reply to interrupt me',
    'Run /theme to browse 16 color themes',
]

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.application import Application
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.formatted_text import FormattedText
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import HSplit, Layout, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.styles import Style
    AVAILABLE = True
except Exception:
    AVAILABLE = False


def _enable_shift_enter() -> None:
    """Make Shift+Enter distinguishable from Enter on the Windows console.

    prompt_toolkit's Win32 input reader collapses Shift+Enter into a plain
    Enter (there is no ShiftEnter key). We wrap it so that, when Shift is held
    on Return, the key is re-tagged as Ctrl+J — which we then bind to insert a
    newline. Enter (Ctrl+M) is left alone and still submits.
    """
    try:
        from prompt_toolkit.input.win32 import ConsoleInputReader
        from prompt_toolkit.keys import Keys
    except Exception:
        return
    orig = ConsoleInputReader._event_to_key_presses
    if getattr(orig, "_xcode_patched", False):
        return
    SHIFT_PRESSED = 0x0010

    def patched(self, ev):
        presses = orig(self, ev)
        if ev.ControlKeyState & SHIFT_PRESSED:
            for kp in presses:
                if kp.key in (Keys.ControlM, getattr(Keys, "Enter", Keys.ControlM)):
                    kp.key = Keys.ControlJ
        return presses

    patched._xcode_patched = True
    ConsoleInputReader._event_to_key_presses = patched


if AVAILABLE:
    _enable_shift_enter()


def cycle(mode: str) -> str:
    return MODES[(MODES.index(mode) + 1) % len(MODES)] if mode in MODES else "normal"


if AVAILABLE:
    class SlashCompleter(Completer):
        """Claude-Code-style dropdown: type `/` to see commands + descriptions."""

        def __init__(self, commands):
            self.commands = commands

        def get_completions(self, document, complete_event):
            text = document.text_before_cursor
            if not text.startswith("/") or " " in text:
                return
            for name, desc in self.commands:
                if name.startswith(text):
                    yield Completion(name, start_position=-len(text),
                                     display=name, display_meta=desc)
else:
    SlashCompleter = None


def select_menu(question: str, options: list) -> str:
    """Show an inline single-choice menu, Claude-Code style. Navigate with
    ↑/↓ or w/s (or j/k), Enter to pick, Esc to cancel (returns the first
    option). Returns the chosen *label*.

    `options` may be plain strings, or (label, description) pairs — the
    description is shown dimmed under each choice.
    """
    norm: list[tuple[str, str]] = []
    for o in options:
        if isinstance(o, (tuple, list)):
            label = str(o[0]).strip()
            desc = str(o[1]).strip() if len(o) > 1 else ""
        else:
            label, desc = str(o).strip(), ""
        if label:
            norm.append((label, desc))
    if not norm:
        return ""
    labels = [lbl for lbl, _ in norm]

    if not AVAILABLE:
        print(question)
        for i, (lbl, desc) in enumerate(norm, 1):
            print(f"  {i}. {lbl}" + (f"  — {desc}" if desc else ""))
        try:
            s = input("pick a number › ").strip()
            return labels[int(s) - 1] if s.isdigit() and 1 <= int(s) <= len(labels) else labels[0]
        except Exception:
            return labels[0]

    idx = [0]

    def render():
        frags = [("bold", f"  {question}\n")]
        for i, (lbl, desc) in enumerate(norm):
            if i == idx[0]:
                frags.append(("bold fg:ansiwhite", f"  ❯ {lbl}\n"))
            else:
                frags.append(("", f"    {lbl}\n"))
            if desc:
                frags.append(("fg:ansibrightblack", f"      {desc}\n"))
        frags.append(("fg:ansibrightblack",
                      "  ↑/↓ or w/s · enter to select · esc to cancel"))
        return FormattedText(frags)

    kb = KeyBindings()

    @kb.add("up")
    @kb.add("k")
    @kb.add("w")
    def _(e):
        idx[0] = (idx[0] - 1) % len(labels)

    @kb.add("down")
    @kb.add("j")
    @kb.add("s")
    def _(e):
        idx[0] = (idx[0] + 1) % len(labels)

    @kb.add("enter")
    def _(e):
        e.app.exit(result=idx[0])

    @kb.add("escape")
    @kb.add("c-c")
    def _(e):
        e.app.exit(result=None)

    app = Application(
        layout=Layout(HSplit([
            Window(FormattedTextControl(render), always_hide_cursor=True)])),
        key_bindings=kb, full_screen=False)
    try:
        res = app.run()
    except Exception:
        return labels[0]
    return labels[res] if res is not None else labels[0]


def _width(default: int = 100) -> int:
    try:
        from prompt_toolkit.application.current import get_app
        return get_app().output.get_size().columns
    except Exception:
        try:
            return shutil.get_terminal_size((default, 24)).columns
        except Exception:
            return default


def _rule(text: str) -> str:
    """A horizontal rule sized to FIT `text` — never the full terminal width.

    Length = the display width of the line it accompanies, capped to the
    terminal so a very long line can't overflow and wrap into a blank pad row.
    """
    n = max(1, min(len(text), _width() - 1))
    return "─" * n


class InputBar:
    def __init__(self, uic, on_mode_change=lambda m: None, commands=None):
        self.uic = uic
        self.on_mode_change = on_mode_change
        self.commands = commands or []
        self.budget = 8000
        self.model = ""
        self.tokens = lambda: 0
        self._ph_text = ""
        self._session = None
        if AVAILABLE:
            try:
                self._build()
            except Exception:
                self._session = None

    def _build(self) -> None:
        kb = KeyBindings()

        @kb.add("s-tab")
        def _(event):
            self.uic.mode = cycle(self.uic.mode)
            self.on_mode_change(self.uic.mode)
            event.app.invalidate()

        @kb.add("c-c")
        def _(event):
            event.app.exit(exception=KeyboardInterrupt)

        @kb.add("c-z")
        def _(event):
            event.current_buffer.undo()

        @kb.add("c-j")
        def _(event):
            event.current_buffer.insert_text("\n")

        style = Style.from_dict({
            "bottom-toolbar": "bg:default noreverse",
            "completion-menu.completion": "bg:default",
            "completion-menu.completion.current": "bg:ansiwhite fg:ansiblack",
            "completion-menu.meta.completion": "bg:default fg:ansibrightblack",
            "completion-menu.meta.completion.current": "bg:ansibrightblack fg:ansiwhite",
        })
        self._session = PromptSession(
            key_bindings=kb, style=style, message=self._message,
            bottom_toolbar=self._toolbar,
            completer=SlashCompleter(self.commands) if SlashCompleter else None,
            complete_while_typing=True,
            reserve_space_for_menu=0)
        self._compact_layout()

    def _compact_layout(self) -> None:
        """Kill the blank lines between the ❯ line and the status toolbar.

        On Win32, prompt_toolkit reserves every row below the cursor
        (renderer: `_min_available_height = get_rows_below_cursor_position()`)
        and lets the input window stretch to fill it — which stacks a column
        of blank lines between the prompt and the bottom toolbar. Pinning the
        input window to its content height makes that slack fall BELOW the bar
        instead, so the bar stays tight: rule, ❯ line, rule, status — and only
        ONE line per row of words. ⚠️ Don't remove this; the gap comes back.
        """
        try:
            from prompt_toolkit.filters import to_filter
            from prompt_toolkit.layout import walk
            from prompt_toolkit.layout.controls import BufferControl
            buf = self._session.default_buffer
            for cont in walk(self._session.layout.container):
                ctrl = getattr(cont, "content", None)
                if isinstance(ctrl, BufferControl) and ctrl.buffer is buf:
                    cont.dont_extend_height = to_filter(True)
                    break
        except Exception:
            pass

    def _message(self):
        prompt_line = "❯ " + (self._ph_text or "")
        return FormattedText([
            ("fg:ansibrightblack", _rule(prompt_line) + "\n"),
            ("bold fg:ansiwhite", "❯ "),
        ])

    def _toolbar(self):
        label, _hint = _LABEL.get(self.uic.mode, _LABEL["normal"])
        seg_mode = f"  {label} mode on (shift+tab to cycle)"
        seg_agents = " · ← for agents"

        n = self.tokens()
        tok = f"{n:,} tokens"
        fname = getattr(self.uic, "last_file", None)
        hint = "  ·  ⇧⏎ newline"
        right = "  ·  " + (f"⧉ {fname}  ·  " if fname else "") + tok + hint
        status_line = seg_mode + seg_agents + right

        return FormattedText([
            ("fg:ansibrightblack", _rule(status_line) + "\n"),
            ("bold fg:ansiwhite", seg_mode),
            ("fg:ansibrightblack", seg_agents),
            ("fg:ansibrightblack", right),
        ])

    def ask(self, model: str, tokens_fn, budget: int) -> str:
        self.model = model
        self.tokens = tokens_fn
        self.budget = budget
        if self._session is not None:
            self._ph_text = random.choice(PLACEHOLDERS)
            ph = FormattedText([("fg:ansibrightblack", self._ph_text)])
            return self._session.prompt(placeholder=ph).strip()
        self._ph_text = random.choice(PLACEHOLDERS)
        rule = _rule("❯ " + self._ph_text)
        print(rule)
        try:
            line = input("❯ ").strip()
        finally:
            print(rule)
        return line
