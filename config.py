"""
Configuration loader.
Reads config.yaml, then overrides with environment variables.

Env var mapping:
  LLM_BACKEND       → llm.backend
  OLLAMA_HOST       → llm.ollama.host
  OLLAMA_MODEL      → llm.ollama.model
  API_PROVIDER      → llm.api.provider
  GEMINI_API_KEY    → llm.api.api_key  (when provider=gemini)
  GROQ_API_KEY      → llm.api.api_key  (when provider=groq)
  MAX_FILE_SIZE_MB  → files.max_size_mb
  APP_PORT          → app.port
  APP_DEBUG         → app.debug
"""

import os
import re
import yaml
import logging

logger = logging.getLogger(__name__)

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.yaml")


def _resolve_env_refs(value: str) -> str:
    """Replace ${ENV_VAR} placeholders with actual environment variable values."""
    def replacer(match):
        var_name = match.group(1)
        return os.environ.get(var_name, "")
    return re.sub(r'\$\{([^}]+)\}', replacer, str(value))


def _deep_resolve(obj):
    """Recursively resolve env var placeholders in all string values."""
    if isinstance(obj, dict):
        return {k: _deep_resolve(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_deep_resolve(item) for item in obj]
    if isinstance(obj, str):
        return _resolve_env_refs(obj)
    return obj


def load_config(config_path: str = None) -> dict:
    """
    Load configuration from YAML file, resolve env var placeholders,
    then apply direct environment variable overrides.

    Returns a fully resolved config dict.
    """
    path = config_path or _CONFIG_PATH

    if not os.path.exists(path):
        raise FileNotFoundError(f"config.yaml not found at: {path}")

    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    # Resolve ${VAR} references throughout the config
    cfg = _deep_resolve(cfg)

    # Direct env var overrides (take precedence over yaml + placeholder resolution)
    overrides = {
        "LLM_BACKEND":      ("llm", "backend"),
        "OLLAMA_HOST":      ("llm", "ollama", "host"),
        "OLLAMA_MODEL":     ("llm", "ollama", "model"),
        "API_PROVIDER":     ("llm", "api", "provider"),
        "APP_HOST":         ("app", "host"),
        "APP_PORT":         ("app", "port"),
        "PORT":             ("app", "port"),   # Railway sets $PORT automatically
        "APP_DEBUG":        ("app", "debug"),
        "MAX_FILE_SIZE_MB": ("files", "max_size_mb"),
        "SESSION_TIMEOUT":  ("session", "timeout_minutes"),
    }
    for env_key, path_keys in overrides.items():
        val = os.environ.get(env_key)
        if val is not None:
            _set_nested(cfg, path_keys, _coerce(val))

    # Handle API key based on provider
    provider = cfg.get("llm", {}).get("api", {}).get("provider", "gemini")
    if provider == "groq":
        groq_key = os.environ.get("GROQ_API_KEY", "")
        if groq_key:
            cfg["llm"]["api"]["api_key"] = groq_key
    else:
        gemini_key = os.environ.get("GEMINI_API_KEY", "")
        if gemini_key:
            cfg["llm"]["api"]["api_key"] = gemini_key

    return cfg


def _set_nested(d: dict, keys: tuple, value):
    """Set a nested dict value by key path."""
    for key in keys[:-1]:
        d = d.setdefault(key, {})
    d[keys[-1]] = value


def _coerce(val: str):
    """Coerce string env var to appropriate Python type."""
    if val.lower() in ("true", "1", "yes"):
        return True
    if val.lower() in ("false", "0", "no"):
        return False
    try:
        return int(val)
    except ValueError:
        pass
    try:
        return float(val)
    except ValueError:
        pass
    return val


if __name__ == "__main__":
    import json
    cfg = load_config()
    # Mask API key for printing
    if cfg.get("llm", {}).get("api", {}).get("api_key"):
        cfg["llm"]["api"]["api_key"] = "***"
    print(json.dumps(cfg, indent=2))
    print("\n✓ Config loaded successfully.")
