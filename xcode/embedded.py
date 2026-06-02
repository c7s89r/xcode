from __future__ import annotations

import atexit
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

import httpx

MODEL_DIR = Path.home() / ".xcode" / "models"

PRESETS = {
    "tiny":  ("Qwen/Qwen2.5-0.5B-Instruct-GGUF", "qwen2.5-0.5b-instruct-q4_k_m.gguf", "xcode-0.5b", "~0.4 GB"),
    "small": ("Qwen/Qwen2.5-1.5B-Instruct-GGUF", "qwen2.5-1.5b-instruct-q4_k_m.gguf", "xcode-1.5b", "~1 GB"),
    "base":  ("Qwen/Qwen2.5-3B-Instruct-GGUF",   "qwen2.5-3b-instruct-q4_k_m.gguf",   "xcode-3b",   "~2 GB"),
}
DEFAULT_PRESET = "base"

PORT = int(os.getenv("XCODE_LOCAL_PORT", "8011"))
BASE_URL = f"http://localhost:{PORT}/v1"

_proc: subprocess.Popen | None = None


def _selected() -> tuple[str, str, str, str]:
    sel = os.getenv("XCODE_LOCAL_MODEL", DEFAULT_PRESET).strip()
    if sel in PRESETS:
        return PRESETS[sel]
    if "/" in sel and sel.endswith(".gguf"):
        repo, file = sel.rsplit("/", 1)
        return (repo, file, file[:-5], "")
    return PRESETS[DEFAULT_PRESET]


def model_repo() -> str:
    return _selected()[0]


def model_file() -> str:
    return _selected()[1]


def model_alias() -> str:
    return _selected()[2]


def model_size() -> str:
    return _selected()[3]


def model_url() -> str:
    return f"https://huggingface.co/{model_repo()}/resolve/main/{model_file()}"


def model_path() -> Path:
    return MODEL_DIR / model_file()


_SERVER_DEPS = ("fastapi", "uvicorn", "starlette_context", "sse_starlette",
                "pydantic_settings")


_ACCEL_LABEL = {
    "cuda": "NVIDIA GPU (CUDA)",
    "metal": "Apple GPU (Metal)",
    "rocm": "AMD GPU",
    "cpu": "CPU",
}


def detect_accel() -> str:
    forced = os.getenv("XCODE_LOCAL_ACCEL")
    if forced:
        return forced.strip().lower()
    if sys.platform == "darwin":
        return "metal"
    if shutil.which("nvidia-smi"):
        return "cuda"
    if shutil.which("rocminfo") or shutil.which("rocm-smi"):
        return "rocm"
    return "cpu"


def _cuda_tag() -> str:
    try:
        out = subprocess.run(["nvidia-smi"], capture_output=True, text=True,
                             timeout=5).stdout
        m = re.search(r"CUDA Version:\s*(\d+)\.(\d+)", out)
        if m:
            major, minor = int(m.group(1)), int(m.group(2))
            if major >= 12:
                if minor >= 4:
                    return "cu124"
                if minor >= 3:
                    return "cu123"
                if minor >= 2:
                    return "cu122"
                return "cu121"
    except Exception:
        pass
    return "cu121"


def _accel_index(accel: str) -> str | None:
    base = "https://abetlen.github.io/llama-cpp-python/whl"
    if accel == "cuda":
        return f"{base}/{_cuda_tag()}"
    if accel == "metal":
        return f"{base}/metal"
    if accel == "cpu":
        return f"{base}/cpu"
    return None


def _gpu_offload(accel: str | None = None) -> bool:
    return (accel or detect_accel()) in ("cuda", "metal")


def have_engine() -> bool:
    import importlib.util as u
    if u.find_spec("llama_cpp") is None:
        return False
    return all(u.find_spec(m) is not None for m in _SERVER_DEPS)


def _pip_install_from(index: str, log: Callable[[str], None]) -> bool:
    rc = subprocess.call(
        [sys.executable, "-m", "pip", "install", "--upgrade", "--prefer-binary",
         "llama-cpp-python[server]", "--extra-index-url", index])
    return rc == 0 and have_engine()


def ensure_engine(log: Callable[[str], None] = print) -> bool:
    if have_engine():
        return True
    accel = detect_accel()
    chosen = accel if accel in ("cuda", "metal", "cpu") else "cpu"
    log(f"detected {_ACCEL_LABEL.get(accel, accel)} — installing the matching "
        "local engine (prebuilt, one-time, may take a minute)…")
    if accel == "rocm":
        log("no prebuilt AMD-GPU wheel — running on CPU (still works; build "
            "llama-cpp-python with ROCm/Vulkan yourself for GPU offload).")

    if _pip_install_from(_accel_index(chosen), log):
        return True
    if chosen != "cpu" and _pip_install_from(_accel_index("cpu"), log):
        log("GPU engine unavailable for this setup — using the CPU build.")
        return True

    log("could not install the local engine automatically. Try:\n"
        "  pip install 'llama-cpp-python[server]' --prefer-binary \\\n"
        "    --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu")
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
        with httpx.stream("GET", model_url(), follow_redirects=True,
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
    n_gpu_layers = "-1" if _gpu_offload() else "0"
    _proc = subprocess.Popen(
        [sys.executable, "-m", "llama_cpp.server",
         "--model", str(model_path()),
         "--model_alias", model_alias(),
         "--n_ctx", ctx,
         "--n_gpu_layers", n_gpu_layers,
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
