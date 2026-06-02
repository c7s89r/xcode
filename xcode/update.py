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


def upgrade_detached() -> bool:
    py = sys.executable
    pip_cmd = f'"{py}" -m pip install --upgrade --no-cache-dir {PKG}'
    try:
        if os.name == "nt":
            line = f'ping -n 3 127.0.0.1 >nul & {pip_cmd}'
            detached = 0x00000008
            new_group = 0x00000200
            no_window = 0x08000000
            subprocess.Popen(["cmd", "/c", line],
                             creationflags=detached | new_group | no_window,
                             close_fds=True)
        else:
            subprocess.Popen(["sh", "-c", f'sleep 1; {pip_cmd}'],
                             start_new_session=True)
        return True
    except Exception:
        return False


def relaunch() -> None:
    os.execv(sys.executable, [sys.executable, "-m", "xcode"] + sys.argv[1:])
