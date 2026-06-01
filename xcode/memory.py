"""Project memory: an XCODE.md file at the repo root that's auto-loaded into the
system prompt, so the agent remembers project conventions across sessions.

Mirrors how Claude Code uses CLAUDE.md.
"""

from __future__ import annotations

from pathlib import Path

CANDIDATES = ["XCODE.md", "CLAUDE.md", ".xcode/XCODE.md"]

INIT_INSTRUCTION = (
    "Explore this project and write an XCODE.md file at the repo root. "
    "Use list_dir, glob_files, grep and read_file to understand it. The file "
    "should be concise and cover: what the project is, how to build/run/test it, "
    "the main directories and entry points, and any conventions a new contributor "
    "should follow. Keep it under ~60 lines. When done, write the file with "
    "write_file and give a one-line confirmation."
)


def load() -> str:
    """Return the contents of the first project-memory file found, or ''."""
    for name in CANDIDATES:
        p = Path(name)
        if p.is_file():
            try:
                text = p.read_text(encoding="utf-8", errors="replace").strip()
                if text:
                    return f"# Project memory ({name})\n{text}"
            except Exception:
                pass
    return ""
