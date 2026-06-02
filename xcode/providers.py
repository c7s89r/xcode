from __future__ import annotations

import json
import os
from pathlib import Path

CONFIG_DIR = Path.home() / ".xcode"
CONFIG_FILE = CONFIG_DIR / "config.json"

PROVIDERS: dict[str, dict] = {
    "ollama": {
        "label": "Ollama (local)",
        "base_url": "http://localhost:11434/v1",
        "key_env": None, "default": None, "local": True,
    },
    "llamacpp": {
        "label": "llama.cpp (local)",
        "base_url": "http://localhost:8080/v1",
        "key_env": None, "default": None, "local": True,
    },
    "anthropic": {
        "label": "Anthropic — Claude",
        "base_url": "https://api.anthropic.com/v1",
        "key_env": "ANTHROPIC_API_KEY", "default": "claude-sonnet-4-5",
        "console": "https://console.anthropic.com/settings/keys",
    },
    "openai": {
        "label": "OpenAI — GPT",
        "base_url": "https://api.openai.com/v1",
        "key_env": "OPENAI_API_KEY", "default": "gpt-4o",
        "console": "https://platform.openai.com/api-keys",
    },
    "openrouter": {
        "label": "OpenRouter — many models",
        "base_url": "https://openrouter.ai/api/v1",
        "key_env": "OPENROUTER_API_KEY", "default": "anthropic/claude-3.5-sonnet",
        "console": "https://openrouter.ai/keys",
    },
    "groq": {
        "label": "Groq — fast Llama/Qwen",
        "base_url": "https://api.groq.com/openai/v1",
        "key_env": "GROQ_API_KEY", "default": "llama-3.3-70b-versatile",
        "console": "https://console.groq.com/keys",
    },
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "key_env": "DEEPSEEK_API_KEY", "default": "deepseek-chat",
        "console": "https://platform.deepseek.com/api_keys",
    },
    "mistral": {
        "label": "Mistral",
        "base_url": "https://api.mistral.ai/v1",
        "key_env": "MISTRAL_API_KEY", "default": "mistral-large-latest",
        "console": "https://console.mistral.ai/api-keys",
    },
    "together": {
        "label": "Together AI",
        "base_url": "https://api.together.xyz/v1",
        "key_env": "TOGETHER_API_KEY",
        "default": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "console": "https://api.together.ai/settings/api-keys",
    },
    "xai": {
        "label": "xAI — Grok",
        "base_url": "https://api.x.ai/v1",
        "key_env": "XAI_API_KEY", "default": "grok-2-latest",
        "console": "https://console.x.ai",
    },
    "gemini": {
        "label": "Google — Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "key_env": "GEMINI_API_KEY", "default": "gemini-2.0-flash",
        "console": "https://aistudio.google.com/apikey",
    },
}


def load_config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(cfg: dict) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        try:
            os.chmod(CONFIG_FILE, 0o600)
        except Exception:
            pass
    except Exception:
        pass


def get_key(name: str, cfg: dict | None = None) -> str | None:
    p = PROVIDERS.get(name, {})
    env = p.get("key_env")
    if env and os.getenv(env):
        return os.getenv(env)
    cfg = cfg if cfg is not None else load_config()
    return (cfg.get("keys") or {}).get(name)


def set_key(name: str, key: str) -> None:
    cfg = load_config()
    cfg.setdefault("keys", {})[name] = key
    save_config(cfg)


def set_active(name: str, model: str | None = None) -> None:
    cfg = load_config()
    cfg["provider"] = name
    cfg.pop("embedded", None)
    if model:
        cfg["model"] = model
    elif PROVIDERS.get(name, {}).get("default"):
        cfg["model"] = PROVIDERS[name]["default"]
    save_config(cfg)


def clear_active() -> None:
    cfg = load_config()
    cfg.pop("provider", None)
    cfg.pop("model", None)
    cfg.pop("embedded", None)
    save_config(cfg)


def remember_local(model: str | None) -> None:
    cfg = load_config()
    cfg.pop("provider", None)
    cfg.pop("embedded", None)
    if model:
        cfg["local_model"] = model
    save_config(cfg)


def remember_embedded() -> None:
    cfg = load_config()
    cfg.pop("provider", None)
    cfg["embedded"] = True
    save_config(cfg)


def saved_local_model() -> str | None:
    return load_config().get("local_model")


def use_embedded() -> bool:
    return bool(load_config().get("embedded"))
