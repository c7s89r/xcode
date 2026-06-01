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
    "Press esc while I'm replying to stop me mid-thought",
    "Run /theme to browse every color theme",
    "Use /export to save this conversation as Markdown",
    "Run /doctor if something looks off",
]

def _theme(border, ghost, eyes, tree, accent, tool, mode):
    return {
        "border": border, "ghost": ghost, "eyes": eyes, "tree": tree,
        "accent": accent, "title": f"bold {accent}", "user": f"bold {accent}",
        "tool": tool, "mode": mode,
    }


THEMES: dict[str, dict] = {
    "ghost":     _theme("grey93", "grey93", "grey42", "grey58", "white", "grey50", "white"),
    "matrix":    _theme("green", "green1", "bright_green", "green3", "green1", "green4", "green"),
    "dracula":   _theme("#bd93f9", "#f8f8f2", "#ff79c6", "#50fa7b", "#bd93f9", "#6272a4", "#ff79c6"),
    "ember":     _theme("dark_orange3", "wheat1", "orange1", "dark_olive_green3", "orange1", "grey50", "dark_orange"),
    "mono":      _theme("grey50", "grey93", "grey70", "grey58", "grey85", "grey42", "grey70"),
    "nord":      _theme("#88c0d0", "#eceff4", "#5e81ac", "#a3be8c", "#88c0d0", "#4c566a", "#81a1c1"),
    "gruvbox":   _theme("#d79921", "#fbf1c7", "#cc241d", "#98971a", "#fabd2f", "#7c6f64", "#d65d0e"),
    "solarized": _theme("#268bd2", "#fdf6e3", "#b58900", "#859900", "#2aa198", "#586e75", "#6c71c4"),
    "neon":      _theme("#ff007c", "#f6f6ff", "#00e5ff", "#7c4dff", "#00e5ff", "#6a3d9a", "#ff2bd6"),
    "ocean":     _theme("#2389da", "#e0fbfc", "#05668d", "#028090", "#00a5cf", "#386170", "#2389da"),
    "rose":      _theme("#ff8fab", "#fff0f3", "#c9184a", "#ffb3c1", "#ff758f", "#a4677b", "#ff758f"),
    "sunset":    _theme("#ff7b00", "#ffedd8", "#ff006e", "#ffaa00", "#ff5400", "#9d4e15", "#ff006e"),
    "ice":       _theme("#90e0ef", "#caf0f8", "#0077b6", "#48cae4", "#00b4d8", "#5c7c8a", "#48cae4"),
    "forest":    _theme("#2d6a4f", "#d8f3dc", "#1b4332", "#40916c", "#52b788", "#4a5e54", "#2d6a4f"),
    "vapor":     _theme("#b14aed", "#f7f0ff", "#05ffa1", "#ff71ce", "#01cdfe", "#6d5b97", "#b14aed"),
    "coffee":    _theme("#a47148", "#f3e5d8", "#6f4e37", "#a47148", "#c8a27c", "#7f5539", "#a47148"),
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
        meta += " · esc to interrupt)"
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


def theme_gallery(current: str = "") -> Group:
    """A swatch list of every theme, each rendered in its own colors."""
    from rich.style import Style
    rows = [Text("Themes  ", style="bold").append("(usage: /theme nord)",
                                                   style="dim")]
    for name, th in THEMES.items():
        line = Text("  ")
        mark = "●" if name == current else "○"
        line.append(f"{mark} ", style=th["accent"])
        line.append(f"{name:<11}", style=th["title"])
        for key in ("border", "ghost", "eyes", "tree", "accent"):
            line.append("██", style=Style(color=th[key]))
        rows.append(line)
    return Group(*rows)
