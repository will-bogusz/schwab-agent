"""
Remote token authority helpers.

Goliath is the preferred always-on Schwab OAuth host. Local clients should not
independently refresh copied token files because Schwab rotates refresh tokens;
two writers create stale-token drift. In auto mode, a config whose callback URL
points at goliath makes non-goliath hosts refresh on goliath and then copy the
fresh token file down before building a schwab-py client.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import httpx

from . import config


MODE_ENV = "SCHWAB_TOKEN_AUTHORITY"
HOST_ENV = "SCHWAB_GOLIATH_HOST"
DIR_ENV = "SCHWAB_GOLIATH_DIR"
BASE_URL_ENV = "SCHWAB_GOLIATH_BASE_URL"
DISABLE_ENV = "SCHWAB_DISABLE_REMOTE_TOKEN_SYNC"


def _hostname() -> str:
    return socket.gethostname().split(".")[0].lower()


def authority_host() -> str:
    return os.environ.get(HOST_ENV, "goliath")


def authority_dir() -> str:
    return os.environ.get(DIR_ENV, "/home/will/tmp/schwab")


def base_url() -> str | None:
    explicit = os.environ.get(BASE_URL_ENV)
    if explicit:
        return explicit.rstrip("/")

    try:
        callback_url = config.load_config().get("callback_url", "")
    except Exception:
        return None

    parsed = urlparse(callback_url)
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def is_authority_host() -> bool:
    return _hostname() == authority_host().split(".")[0].lower()


def remote_enabled() -> bool:
    """Return whether this process should treat goliath as token authority."""
    if os.environ.get(DISABLE_ENV) in {"1", "true", "TRUE", "yes"}:
        return False

    mode = os.environ.get(MODE_ENV, "auto").lower()
    if mode in {"local", "off", "false", "0"}:
        return False
    if mode in {"remote", "goliath", "on", "true", "1"}:
        return not is_authority_host()

    # Auto mode: if the registered Schwab callback URL points at goliath, local
    # machines should use that host as the single token writer.
    url = base_url() or ""
    host = urlparse(url).hostname or ""
    return "goliath" in host.lower() and not is_authority_host()


def _token_path(app_name: str) -> Path:
    return config.get_token_path(app_name)


def _remote_token_ref(app_name: str) -> str:
    return f"{authority_host()}:{authority_dir().rstrip('/')}/tokens_{app_name}.json"


def sync_from_authority(app_name: str) -> dict:
    """Copy one token file from goliath to the local config directory."""
    if app_name not in config.VALID_APPS:
        return {"status": "error", "app": app_name, "error": f"Invalid app: {app_name}"}
    if not remote_enabled():
        return {"status": "skipped", "app": app_name, "reason": "remote authority disabled"}

    dest = _token_path(app_name)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix=f"tokens_{app_name}.", suffix=".json", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        proc = subprocess.run(
            ["scp", "-p", "-q", _remote_token_ref(app_name), str(tmp_path)],
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
        if proc.returncode != 0:
            return {
                "status": "error",
                "app": app_name,
                "error": "Failed to copy token file from goliath",
                "details": (proc.stderr or proc.stdout).strip(),
            }

        # Validate JSON before replacing the local file.
        with open(tmp_path) as f:
            json.load(f)
        tmp_path.replace(dest)
        return {"status": "success", "app": app_name, "path": str(dest)}
    except Exception as exc:
        return {"status": "error", "app": app_name, "error": str(exc)}
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def refresh_on_authority(app_name: str) -> dict:
    """Refresh on goliath, then sync the rotated token file locally."""
    if not remote_enabled():
        return {"status": "skipped", "app": app_name, "reason": "remote authority disabled"}

    url = base_url()
    if not url:
        return {"status": "error", "app": app_name, "error": "No Schwab authority base URL configured"}

    try:
        resp = httpx.get(f"{url}/refresh/{app_name}", timeout=45)
        try:
            result = resp.json()
        except Exception:
            result = {"status": "error", "app": app_name, "error": resp.text}
    except Exception as exc:
        return {"status": "error", "app": app_name, "error": f"Remote refresh request failed: {exc}"}

    if result.get("status") != "success":
        return result

    synced = sync_from_authority(app_name)
    if synced.get("status") != "success":
        return synced
    result["synced"] = True
    return result


def status_summary() -> dict:
    return {
        "enabled": remote_enabled(),
        "authority_host": authority_host(),
        "authority_dir": authority_dir(),
        "base_url": base_url(),
        "is_authority_host": is_authority_host(),
        "mode": os.environ.get(MODE_ENV, "auto"),
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Sync Schwab token files from the configured authority host")
    parser.add_argument("--app", choices=[*config.VALID_APPS, "all"], default="all")
    parser.add_argument("--refresh", action="store_true", help="Refresh on the authority before syncing")
    parser.add_argument("--status", action="store_true", help="Print authority configuration")
    args = parser.parse_args()

    if args.status:
        print(json.dumps(status_summary(), indent=2))
        return

    apps = list(config.VALID_APPS) if args.app == "all" else [args.app]
    ok = True
    for app_name in apps:
        result = refresh_on_authority(app_name) if args.refresh else sync_from_authority(app_name)
        print(f"{app_name}: {result.get('status')}")
        if result.get("error"):
            print(result["error"])
        if result.get("details"):
            print(result["details"])
        ok = ok and result.get("status") == "success"
    raise SystemExit(0 if ok else 1)
