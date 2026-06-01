"""Persistent permission rules, stored per-project in .xcode/permissions.json.

The model proposes an action (write a file, run a command); the CLI asks the
user. If the user picks "always", we remember it here so we stop asking.
"""

from __future__ import annotations

import json
from pathlib import Path

STORE = Path(".xcode") / "permissions.json"


class Permissions:
    def __init__(self, store: Path = STORE):
        self.store = store
        self.tools: set[str] = set()
        self.cmd_prefixes: set[str] = set()
        self._load()

    def is_allowed(self, kind: str, target: str) -> bool:
        if kind in self.tools:
            return True
        if kind == "run_command":
            head = _first_word(target)
            return head in self.cmd_prefixes
        return False

    def allow_kind(self, kind: str) -> None:
        self.tools.add(kind)
        self._save()

    def allow_command(self, target: str) -> str:
        head = _first_word(target)
        self.cmd_prefixes.add(head)
        self._save()
        return head

    def reset(self) -> None:
        self.tools.clear()
        self.cmd_prefixes.clear()
        if self.store.exists():
            self.store.unlink()

    def summary(self) -> str:
        parts = []
        if self.tools:
            parts.append("tools: " + ", ".join(sorted(self.tools)))
        if self.cmd_prefixes:
            parts.append("commands: " + ", ".join(sorted(self.cmd_prefixes)))
        return " · ".join(parts) or "(none yet)"

    def _load(self) -> None:
        if not self.store.exists():
            return
        try:
            data = json.loads(self.store.read_text(encoding="utf-8"))
            self.tools = set(data.get("tools", []))
            self.cmd_prefixes = set(data.get("cmd_prefixes", []))
        except Exception:
            pass

    def _save(self) -> None:
        try:
            self.store.parent.mkdir(parents=True, exist_ok=True)
            self.store.write_text(json.dumps({
                "tools": sorted(self.tools),
                "cmd_prefixes": sorted(self.cmd_prefixes),
            }, indent=2), encoding="utf-8")
        except Exception:
            pass


def _first_word(command: str) -> str:
    toks = command.strip().split()
    return toks[0] if toks else ""
