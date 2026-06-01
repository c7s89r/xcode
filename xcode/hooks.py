"""Hooks + settings: .xcode/settings.json lets you run shell commands after the
agent does things (e.g. auto-format after every edit), set env vars, and seed
permission rules. Mirrors the spirit of Claude Code's settings.json hooks.

Example .xcode/settings.json:
{
  "env": {"PYTHONWARNINGS": "ignore"},
  "hooks": {
    "after_write": ["ruff format {path}"],
    "after_edit":  ["ruff format {path}"],
    "after_command": []
  },
  "permissions": {"tools": ["read_file"], "commands": ["git", "ls"]}
}
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

SETTINGS = Path(".xcode") / "settings.json"


class Settings:
    def __init__(self, path: Path = SETTINGS):
        self.data: dict = {}
        if path.exists():
            try:
                self.data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                self.data = {}
        for k, v in (self.data.get("env") or {}).items():
            os.environ.setdefault(k, str(v))

    @property
    def loaded(self) -> bool:
        return bool(self.data)

    def hooks_for(self, event: str) -> list[str]:
        return (self.data.get("hooks") or {}).get(event, []) or []

    def seed_permissions(self, perms) -> None:
        block = self.data.get("permissions") or {}
        for t in block.get("tools", []):
            perms.tools.add(t)
        for c in block.get("commands", []):
            perms.cmd_prefixes.add(c)


def run_hooks(settings: Settings, event: str, **vars) -> str:
    """Run every command registered for an event. Returns a note for the model
    if anything ran (so it sees formatter output / failures)."""
    cmds = settings.hooks_for(event)
    if not cmds:
        return ""
    notes = []
    for tmpl in cmds:
        try:
            cmd = tmpl.format(**vars)
        except (KeyError, IndexError):
            cmd = tmpl
        try:
            p = subprocess.run(cmd, shell=True, capture_output=True,
                               text=True, timeout=60)
            tag = "ok" if p.returncode == 0 else f"exit {p.returncode}"
            out = (p.stdout + p.stderr).strip()
            notes.append(f"[hook {event}: {cmd}] {tag}"
                         + (f"\n{out[:500]}" if out else ""))
        except Exception as e:
            notes.append(f"[hook {event}: {cmd}] failed: {e}")
    return "\n".join(notes)
