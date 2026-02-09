"""
Configuration Management
------------------------
Single source for config paths and loading. Replaces paths.py.

Search order for config directory:
  1. SCHWAB_AGENT_DIR environment variable
  2. Walk up from CWD looking for config.json
  3. ~/.config/schwab-agent/
"""

import json
import os
from pathlib import Path

_REQUIRED_CONFIG_KEYS = {"client_id", "client_secret", "callback_url"}


def find_config_dir() -> Path:
    """Find the config directory using search order."""
    # 1. Environment variable
    env_dir = os.environ.get("SCHWAB_AGENT_DIR")
    if env_dir:
        p = Path(env_dir)
        if p.is_dir():
            return p
        raise FileNotFoundError(f"SCHWAB_AGENT_DIR={env_dir} is not a directory")

    # 2. Walk up from CWD looking for config.json
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / "config.json").exists():
            try:
                with open(parent / "config.json") as f:
                    data = json.load(f)
                if "client_id" in data or "callback_url" in data:
                    return parent
            except (json.JSONDecodeError, OSError):
                continue

    # 3. Fallback to ~/.config/schwab-agent/
    fallback = Path.home() / ".config" / "schwab-agent"
    if fallback.is_dir():
        return fallback

    raise FileNotFoundError(
        "Cannot find schwab-agent config. Set SCHWAB_AGENT_DIR or run from project directory."
    )


def get_config_path() -> Path:
    """Get the path to config.json."""
    return find_config_dir() / "config.json"


def get_token_path() -> Path:
    """Get the token file path."""
    return find_config_dir() / "tokens.json"


def load_config() -> dict:
    """Load and validate the configuration file."""
    config_path = get_config_path()
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path) as f:
        config = json.load(f)

    missing = _REQUIRED_CONFIG_KEYS - set(config.keys())
    if missing:
        raise ValueError(f"Config missing required keys: {missing}")

    return config
