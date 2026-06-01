"""Save / load / list conversation sessions under .xcode/sessions/.

A session is just the message list plus a little metadata, so you can quit and
pick up where you left off with `xcode --resume`.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

DIR = Path(".xcode") / "sessions"


def _slug() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def save(messages: list[dict], model: str, session_id: str | None) -> str:
    DIR.mkdir(parents=True, exist_ok=True)
    sid = session_id or _slug()
    path = DIR / f"{sid}.json"
    payload = {
        "id": sid,
        "model": model,
        "updated": time.time(),
        "messages": messages,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return sid


def latest() -> dict | None:
    sessions = _all_paths()
    return _read(sessions[0]) if sessions else None


def load(session_id: str) -> dict | None:
    path = DIR / f"{session_id}.json"
    return _read(path) if path.exists() else None


def listing() -> list[dict]:
    out = []
    for p in _all_paths():
        d = _read(p)
        if not d:
            continue
        msgs = [m for m in d.get("messages", []) if m.get("role") == "user"]
        first = msgs[0]["content"][:60] if msgs else "(empty)"
        out.append({"id": d.get("id", p.stem), "model": d.get("model", "?"),
                    "turns": len(msgs), "first": first})
    return out


def _all_paths() -> list[Path]:
    if not DIR.exists():
        return []
    return sorted(DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)


def _read(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
