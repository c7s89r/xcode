from __future__ import annotations

import atexit
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

import httpx

MODEL_DIR = Path.home() / ".xcode" / "models"
MODEL_REPO = "Qwen/Qwen2.5-3B-Instruct-GGUF"
MODEL_FILE = "qwen2.5-3b-instruct-q4_k_m.gguf"
MODEL_ALIAS = "qwen2.5-3b (built-in)"
MODEL_URL = f"https://huggingface.co/{MODEL_REPO}/resolve/main/{MODEL_FILE}"

PORT = int(os.getenv("XCODE_LOCAL_PORT", "8011"))
BASE_URL = f"http://localhost:{PORT}/v1"

_proc: subprocess.Popen | None = None


def model_path() -> Path:
    return MODEL_DIR / MODEL_FILE


_SERVER_DEPS = ("fastapi", "uvicorn", "starlette_context", "sse_starlette",
                "pydantic_settings")


def have_engine() -> bool:
    import importlib.util as u
    if u.find_spec("llama_cpp") is None:
        return False
    return all(u.find_spec(m) is not None for m in _SERVER_DEPS)


def ensure_engine(log: Callable[[str], None] = print) -> bool:
    if have_engine():
        return True
    log("installing the local engine (llama-cpp-python) — one-time, may take a minute…")
    subprocess.call([sys.executable, "-m", "pip", "install", "--upgrade",
                     "llama-cpp-python[server]"])
    if have_engine():
        return True
    subprocess.call([sys.executable, "-m", "pip", "install", "--upgrade",
                     *[d.replace("_", "-") for d in _SERVER_DEPS]])
    if have_engine():
        return True
    log("could not install the local engine automatically. "
        "Try: pip install 'llama-cpp-python[server]'")
    return False


def model_ready() -> bool:
    p = model_path()
    return p.exists() and p.stat().st_size > 100_000_000


def ensure_model(progress: Callable[[int, int], None] | None = None,
                 log: Callable[[str], None] = print) -> Path | None:
    p = model_path()
    if model_ready():
        return p
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".part")
    try:
        with httpx.stream("GET", MODEL_URL, follow_redirects=True,
                          timeout=httpx.Timeout(60.0, read=None)) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            done = 0
            with open(tmp, "wb") as f:
                for chunk in r.iter_bytes(chunk_size=1 << 20):
                    f.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
        tmp.replace(p)
        return p
    except Exception as e:
        log(f"download failed: {e}")
        try:
            tmp.unlink()
        except Exception:
            pass
        return None


def is_up() -> bool:
    try:
        httpx.get(f"http://localhost:{PORT}/v1/models", timeout=1.0)
        return True
    except Exception:
        return False


def start_server(log: Callable[[str], None] = print) -> bool:
    global _proc
    if is_up():
        return True
    if not model_ready():
        return False
    ctx = os.getenv("XCODE_LOCAL_CTX", "8192")
    _proc = subprocess.Popen(
        [sys.executable, "-m", "llama_cpp.server",
         "--model", str(model_path()),
         "--model_alias", MODEL_ALIAS,
         "--n_ctx", ctx,
         "--chat_format", "chatml-function-calling",
         "--port", str(PORT)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    atexit.register(stop_server)
    for _ in range(240):
        if _proc.poll() is not None:
            log("the local server exited while starting up.")
            return False
        if is_up():
            return True
        time.sleep(0.5)
    log("the local server did not come up in time.")
    return False


def stop_server() -> None:
    global _proc
    if _proc is not None and _proc.poll() is None:
        try:
            _proc.terminate()
        except Exception:
            pass
    _proc = None
