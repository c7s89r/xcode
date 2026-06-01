from __future__ import annotations

import os
import subprocess
import sys

import httpx

try:
    import importlib.metadata as _md
except Exception:
    _md = None

PKG = "xcoding"


def current_version() -> str | None:
    if _md is None:
        return None
    try:
        return _md.version(PKG)
    except Exception:
        return None


def latest_version(timeout: float = 1.5) -> str | None:
    try:
        r = httpx.get(f"https://pypi.org/pypi/{PKG}/json", timeout=timeout)
        r.raise_for_status()
        return r.json()["info"]["version"]
    except Exception:
        return None


def _parse(v: str) -> tuple:
    out = []
    for chunk in v.split("."):
        digits = ""
        for ch in chunk:
            if ch.isdigit():
                digits += ch
            else:
                break
        out.append(int(digits) if digits else 0)
    return tuple(out)


def check() -> tuple[str | None, str | None, bool]:
    cur = current_version()
    latest = latest_version()
    if not cur or not latest:
        return cur, latest, False
    return cur, latest, _parse(latest) > _parse(cur)


def upgrade() -> int:
    return subprocess.call(
        [sys.executable, "-m", "pip", "install", "--upgrade", "--no-cache-dir", PKG]
    )


def relaunch() -> None:
    os.execv(sys.executable, [sys.executable, "-m", "xcode"] + sys.argv[1:])
