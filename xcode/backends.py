"""Backend auto-detection and client construction.

Both Ollama and llama.cpp's ``llama-server`` expose an OpenAI-compatible
``/v1`` endpoint, so we can drive either of them through the ``openai`` SDK.
This module figures out which one is actually running and what model to use.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx
from openai import OpenAI

# (label, base_url-without-/v1, how-to-list-models)
_CANDIDATES = [
    ("ollama", "http://localhost:11434", "/api/tags"),
    ("llama.cpp", "http://localhost:8080", "/v1/models"),
]

# Substrings (in priority order) of models that tend to be good at tool-calling.
# Used to pick a sensible default instead of just grabbing the first model.
_PREFERRED = [
    "qwen2.5-coder", "qwen3-coder", "qwen2.5", "qwen3",
    "llama3.1", "llama3.3", "mistral-nemo", "mistral", "deepseek-coder",
    "command-r", "firefunction", "gpt-oss",
]


def _pick_default(models: list[str]) -> str:
    for needle in _PREFERRED:
        for m in models:
            if needle in m.lower():
                return m
    return models[0]


@dataclass
class Backend:
    name: str          # "ollama" | "llama.cpp"
    base_url: str      # e.g. http://localhost:11434/v1
    model: str
    client: OpenAI

    def describe(self) -> str:
        return f"{self.name} · {self.model} · {self.base_url}"


def _list_ollama_models(root: str) -> list[str]:
    r = httpx.get(f"{root}/api/tags", timeout=1.0)  # Reduced from 2.0s
    r.raise_for_status()
    return [m["name"] for m in r.json().get("models", [])]


def _list_openai_models(root: str) -> list[str]:
    r = httpx.get(f"{root}/v1/models", timeout=1.0)  # Reduced from 2.0s
    r.raise_for_status()
    return [m["id"] for m in r.json().get("data", [])]


def _probe(root: str) -> bool:
    try:
        httpx.get(root, timeout=0.5)  # Reduced from 1.5s to 0.5s
        return True
    except Exception:
        return False


def detect_backend() -> Backend:
    """Find a running local backend, or raise RuntimeError with guidance.

    Honors overrides:
      XCODE_BASE_URL  — point straight at an OpenAI-compatible /v1 endpoint
      XCODE_MODEL     — force a specific model name
      XCODE_API_KEY   — token, if your endpoint needs one (defaults to "local")
    """
    forced_model = os.getenv("XCODE_MODEL")
    api_key = os.getenv("XCODE_API_KEY", "local")

    base_override = os.getenv("XCODE_BASE_URL")
    if base_override:
        base_url = base_override.rstrip("/")
        model = forced_model or _first_model_at(base_url) or "local-model"
        return Backend("custom", base_url, model,
                       OpenAI(base_url=base_url, api_key=api_key))

    errors = []
    # Try candidates in parallel for speed
    for name, root, _ in _CANDIDATES:
        if not _probe(root):
            errors.append(f"  - {name}: nothing listening at {root}")
            continue
        try:
            if name == "ollama":
                models = _list_ollama_models(root)
            else:
                models = _list_openai_models(root)
        except Exception as e:  # responded but couldn't list models
            errors.append(f"  - {name}: reachable but model list failed ({e})")
            continue

        if not models and not forced_model:
            errors.append(f"  - {name}: running but no models pulled")
            continue

        model = forced_model or _pick_default(models)
        base_url = f"{root}/v1"
        return Backend(name, base_url, model,
                       OpenAI(base_url=base_url, api_key=api_key))

    raise RuntimeError(
        "No local model backend found.\n"
        + "\n".join(errors)
        + "\n\nStart one of:\n"
        "  Ollama   : `ollama serve` then `ollama pull qwen2.5-coder`\n"
        "  llama.cpp: `llama-server -m model.gguf` (listens on :8080)\n"
        "Or set XCODE_BASE_URL to any OpenAI-compatible endpoint."
    )


def _first_model_at(base_url: str) -> str | None:
    root = base_url[:-3] if base_url.endswith("/v1") else base_url
    try:
        return (_list_openai_models(root) or [None])[0]
    except Exception:
        return None


def list_models() -> dict[str, list[str]]:
    """For diagnostics: every model visible on every reachable backend."""
    out: dict[str, list[str]] = {}
    for name, root, _ in _CANDIDATES:
        if not _probe(root):
            continue
        try:
            out[name] = (_list_ollama_models(root) if name == "ollama"
                         else _list_openai_models(root))
        except Exception:
            out[name] = []
    return out
