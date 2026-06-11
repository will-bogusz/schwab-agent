"""
Configuration Management
------------------------
Single source for config paths and loading. Replaces duplicated load_config()
across client.py and server.py.

Search order for config directory:
  1. SCHWAB_AGENT_DIR environment variable
  2. Walk up from CWD looking for config.json
  3. ~/.config/schwab-agent/
"""

import json
import os
from pathlib import Path

VALID_APPS = ("market", "trading")
DEFAULT_APP = "market"

_REQUIRED_CONFIG_KEYS = {"callback_url", "apps"}


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
            # Verify it looks like a schwab config (has "apps" key or "callback_url")
            try:
                with open(parent / "config.json") as f:
                    data = json.load(f)
                if "apps" in data or "callback_url" in data:
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


def get_token_path(app: str = DEFAULT_APP) -> Path:
    """Get the token file path for a specific app."""
    if app not in VALID_APPS:
        raise ValueError(f"Invalid app '{app}'. Must be one of: {VALID_APPS}")
    return find_config_dir() / f"tokens_{app}.json"


def get_auth_meta_path() -> Path:
    """Sidecar recording the last full-OAuth login time per app.

    Lives outside the token files because schwab-py rewrites those on its own
    refreshes and would drop unknown fields. Only the OAuth callback (a real
    browser login) writes this; refreshes never touch it, so the 7-day
    refresh-token window can be computed honestly.
    """
    return find_config_dir() / "auth_meta.json"


def get_auth_health_path() -> Path:
    """Keepalive health report consumed by status tooling and local CLIs."""
    return find_config_dir() / "auth_health.json"


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


def get_app_config(app: str = DEFAULT_APP) -> dict:
    """Get configuration for a specific app."""
    if app not in VALID_APPS:
        raise ValueError(f"Invalid app '{app}'. Must be one of: {VALID_APPS}")

    config = load_config()
    app_config = config.get("apps", {}).get(app)

    if not app_config:
        raise ValueError(f"App '{app}' not found in config")

    return {
        "client_id": app_config["client_id"],
        "client_secret": app_config["client_secret"],
        "callback_url": config["callback_url"],
    }
