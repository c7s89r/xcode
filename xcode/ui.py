"""Look & feel: themes, the ghost+trees logo, the welcome box, and the
input header. Kept separate from cli.py so the chrome is easy to tweak.
"""

from __future__ import annotations

import json
import random
import time
from pathlib import Path
from typing import Callable

from rich.box import ROUNDED
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

PREFS = Path(".xcode") / "ui.json"
LOGO = Path(__file__).resolve().parent.parent / "logo.png"

SPIN_GLYPHS = "✻✷✶✳✺✸"
THINKING_WORDS = [
    "Envisioning", "Thinking", "Pondering", "Cooking", "Conjuring",
    "Crunching", "Noodling", "Percolating", "Scheming", "Manifesting",
    "Summoning", "Brewing",
]
TIPS = [
    "Use /btw to ask a quick side question without interrupting",
    "Press shift+tab to cycle normal → auto → plan mode",
    "Run /theme matrix to go full hacker mode",
    "Type /clear to wipe the conversation and start fresh",
    "Hit ↑/↓ or w/s to move through any menu, enter to pick",
    "Try 'fix typecheck errors'",
    "Ask me to 'make it more compact'",
    "Use @file to attach files to your message",
    "Press ctrl+z to undo your last edit in the input",
    "Type / to see every slash command with descriptions",
    "Use /model to switch the active model on the fly",
    "Run /init to explore the project and write an XCODE.md",
    "Use /compact to summarize and free up context",
    "Try 'explain this stack trace'",
    "Try 'write a commit message for my changes'",
    "Try 'find where we handle login'",
    "Ask 'how does <filepath> work?'",
    "Use /resume to pick up a previous session",
    "Use /memory to see what the project memory holds",
    "Use /perms reset to clear saved permissions",
    "Try 'add tests for the auth module'",
    "Press ctrl+c to cancel the current input",
]

THEMES: dict[str, dict] = {
    "ghost": {
        "border": "grey93", "ghost": "grey93", "eyes": "grey42",
        "tree": "grey58", "accent": "white", "title": "bold white",
        "user": "bold white", "tool": "grey50", "mode": "white",
    },
    "matrix": {
        "border": "green", "ghost": "green1", "eyes": "bright_green",
        "tree": "green3", "accent": "green1", "title": "bold green",
        "user": "bold green", "tool": "green4", "mode": "green",
    },
    "dracula": {
        "border": "purple", "ghost": "grey93", "eyes": "bright_magenta",
        "tree": "spring_green3", "accent": "orchid", "title": "bold purple",
        "user": "bold orchid", "tool": "grey50", "mode": "orchid",
    },
    "ember": {
        "border": "dark_orange3", "ghost": "wheat1", "eyes": "orange1",
        "tree": "dark_olive_green3", "accent": "orange1", "title": "bold orange1",
        "user": "bold orange1", "tool": "grey50", "mode": "dark_orange",
    },
    "mono": {
        "border": "grey50", "ghost": "grey93", "eyes": "grey70",
        "tree": "grey58", "accent": "grey85", "title": "bold white",
        "user": "bold white", "tool": "grey42", "mode": "grey70",
    },
}

DEFAULT_THEME = "ghost"

def _ghost_text(theme: dict) -> Text:
    """Tiny compact ghost facing right."""
    g = theme["ghost"]
    e = theme["eyes"]

    logo_lines = [
        " ▓▓▓▓▓",
        "▓▓▓▓▓▓▓",
        " ▓▒▓▓▒▓",
        "▓▓▓▓▓▓▓",
        " ▓  ▓",
    ]

    t = Text()
    for line in logo_lines:
        if "▒" in line:
            parts = line.split("▒")
            for i, part in enumerate(parts):
                if i > 0:
                    t.append("▒", style=e)
                t.append(part, style=g)
        else:
            t.append(line, style=g)
        t.append("\n")
    t.rstrip()
    return t


def _neighbors(x, y, w, h):
    if x > 0: yield x - 1, y
    if x < w - 1: yield x + 1, y
    if y > 0: yield x, y - 1
    if y < h - 1: yield x, y + 1


def _largest_blob(mask, w, h):
    """(bounding box, mask) of the biggest connected True region — used to crop
    to the ghost and to drop the little floating sparkles around it."""
    from collections import deque
    seen = [[False] * w for _ in range(h)]
    best, best_box, best_cells = 0, (0, 0, w - 1, h - 1), None
    for sy in range(h):
        for sx in range(w):
            if not mask[sy][sx] or seen[sy][sx]:
                continue
            dq = deque([(sx, sy)]); seen[sy][sx] = True
            cells, l, t, r, b = [], sx, sy, sx, sy
            while dq:
                x, y = dq.popleft(); cells.append((x, y))
                l, t, r, b = min(l, x), min(t, y), max(r, x), max(b, y)
                for nx, ny in _neighbors(x, y, w, h):
                    if mask[ny][nx] and not seen[ny][nx]:
                        seen[ny][nx] = True; dq.append((nx, ny))
            if len(cells) > best:
                best, best_box, best_cells = len(cells), (l, t, r, b), cells
    keep = [[False] * w for _ in range(h)]
    for x, y in (best_cells or []):
        keep[y][x] = True
    return best_box, keep


def _logo_segments(width: int, rows: int):
    """Read logo.png and label every pixel as background / body / feature.

    The logo is RGBA with a *transparent* field, so the alpha channel tells us
    the ghost from the background directly. We: (1) sample at high res, (2) take
    the largest opaque blob as the ghost (dropping the floating sparkles),
    (3) crop + transparent-pad to it, (4) at display size, split the ghost into
    its white *body* and its enclosed black *features* (the eyes + </> mouth).
    The black outline rim is folded into the body so the silhouette stays solid.
    Result codes: 0=bg, 1=body, 2=feature.
    """
    from collections import deque

    from PIL import Image, ImageOps

    base = 220
    im = Image.open(LOGO).convert("RGBA").resize((base, base))
    apx = im.load()
    opaque = [[apx[x, y][3] >= 128 for x in range(base)] for y in range(base)]
    (l, t, r, b), _ = _largest_blob(opaque, base, base)
    im = im.crop((l, t, r + 1, b + 1))
    im = ImageOps.expand(im, border=max(2, (r - l) // 20), fill=(0, 0, 0, 0))
    im = im.resize((width, rows))

    px = im.load()
    opq = [[px[x, y][3] >= 128 for x in range(width)] for y in range(rows)]
    _, ghost = _largest_blob(opq, width, rows)

    def lum(x, y):
        p = px[x, y]
        return (p[0] * 299 + p[1] * 587 + p[2] * 114) // 1000

    dark = [[ghost[y][x] and lum(x, y) < 128 for x in range(width)] for y in range(rows)]

    outline = [[False] * width for _ in range(rows)]
    dq = deque()
    for y in range(rows):
        for x in range(width):
            if dark[y][x] and any(not ghost[ny][nx]
                                  for nx, ny in _neighbors(x, y, width, rows)):
                outline[y][x] = True; dq.append((x, y))
    while dq:
        x, y = dq.popleft()
        for nx, ny in _neighbors(x, y, width, rows):
            if dark[ny][nx] and not outline[ny][nx]:
                outline[ny][nx] = True; dq.append((nx, ny))

    out = [[0] * width for _ in range(rows)]
    for y in range(rows):
        for x in range(width):
            if not ghost[y][x]:
                out[y][x] = 0
            elif dark[y][x] and not outline[y][x]:
                out[y][x] = 2
            else:
                out[y][x] = 1
    return out


def logo(theme: dict, width: int = 26) -> Text:
    """Render logo.png into the terminal with truecolor half-blocks.

    Each character is the 'upper half block' ▀ whose *foreground* paints the
    top pixel and *background* paints the bottom pixel — so one cell carries
    two stacked pixels. The body fills with the theme's ghost colour; the eyes
    and </> mouth fill black; the field stays transparent.
    """
    from rich.style import Style

    rows = width + (width & 1)
    try:
        seg = _logo_segments(width, rows)
    except Exception:
        return _ghost_text(theme)

    fill = {0: None, 1: theme["ghost"], 2: "grey3"}
    t = Text()
    for cr in range(rows // 2):
        for c in range(width):
            top = fill[seg[2 * cr][c]]
            bot = fill[seg[2 * cr + 1][c]]
            if top and bot:
                t.append("▀", style=Style(color=top, bgcolor=bot))
            elif top:
                t.append("▀", style=Style(color=top))
            elif bot:
                t.append("▄", style=Style(color=bot))
            else:
                t.append(" ")
        t.append("\n")
    t.rstrip()
    return t


def welcome(theme: dict, model: str, cwd: str, notes: str = "") -> Panel:
    """Landscape welcome card: ghost on the left, info on the right."""
    info = Group(
        Text("xcode", style=theme["title"]),
        Text("local-model coding agent", style=theme["tool"]),
        Text(""),
        Text(model, style=theme["accent"]),
        Text(cwd + (f"  ·{notes}" if notes else ""), style=theme["tool"]),
    )
    grid = Table.grid(padding=(0, 2))
    grid.add_column(justify="left")
    grid.add_column(justify="left")
    grid.add_row(_ghost_text(theme), info)

    return Panel(grid, box=ROUNDED, border_style=theme["border"],
                 padding=(0, 2), expand=False)


def status_line(theme: dict, mode: str, tokens: int, budget: int,
                model: str) -> Text:
    t = Text("  ")
    if mode == "auto":
        t.append("⏵⏵ auto mode on ", style=f"bold {theme['mode']}")
        t.append("(shift+tab to cycle)", style="dim")
    elif mode == "plan":
        t.append("◷ plan mode ", style=f"bold {theme['mode']}")
        t.append("(read-only · shift+tab to cycle)", style="dim")
    else:
        t.append("·· normal mode ", style=theme["mode"])
        t.append("(shift+tab to cycle)", style="dim")
    pct = min(100, int(100 * tokens / budget)) if budget else 0
    tok_color = "green" if pct < 60 else "yellow" if pct < 85 else "red"
    t.append("  ·  ")
    t.append(f"~{tokens/1000:.1f}k/{budget//1000}k", style=tok_color)
    t.append("  ·  ")
    t.append(f"● {model}", style=theme["accent"])
    return t


class ThinkingStatus:
    """A live, self-animating status line shown while the model works.

    Renders like Claude Code's:

        ✻ Envisioning… (48s · ↓ 1.7k tokens · 2 shells running)  ⎿ Tip: Use /btw to ask a quick side question

    Drive it with a rich.live.Live; the glyph spins, the timer ticks and the
    token counter climbs on every refresh — no extra work needed from caller.
    Mutate `.tokens` and `.preview` from the stream loop to update them.
    """

    def __init__(self, theme: dict, get_shells: Callable[[], int] | None = None):
        self.theme = theme
        self.get_shells = get_shells or (lambda: 0)
        self.start = time.monotonic()
        self.word = random.choice(THINKING_WORDS)
        self.tip = random.choice(TIPS)
        self.tokens = 0
        self.preview = ""

    def __rich__(self) -> Group:
        elapsed = time.monotonic() - self.start
        glyph = SPIN_GLYPHS[int(elapsed * 6) % len(SPIN_GLYPHS)]
        shells = self.get_shells()

        head = Text()
        head.append(f"{glyph} ", style=self.theme["accent"])
        head.append(f"{self.word}… ", style=self.theme["title"])
        meta = f"({int(elapsed)}s · ↓ {self.tokens / 1000:.1f}k tokens"
        if shells:
            meta += f" · {shells} shell{'s' if shells != 1 else ''} running"
        meta += ")"
        head.append(meta, style="dim")
        
        lines = [head]
        if self.preview:
            snippet = self.preview.replace("\n", " ").strip()[-80:]
            lines.append(Text(f"  {snippet}", style="dim"))
        lines.append(Text(f"  ⎿ Tip: {self.tip}", style="dim"))
        return Group(*lines)


def load_prefs() -> dict:
    if PREFS.exists():
        try:
            return json.loads(PREFS.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"theme": DEFAULT_THEME, "mode": "normal"}


def save_prefs(prefs: dict) -> None:
    try:
        PREFS.parent.mkdir(parents=True, exist_ok=True)
        PREFS.write_text(json.dumps(prefs, indent=2), encoding="utf-8")
    except Exception:
        pass


def get_theme(name: str) -> dict:
    return THEMES.get(name, THEMES[DEFAULT_THEME])
