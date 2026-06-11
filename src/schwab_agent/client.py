"""
Schwab Client Factory
---------------------
Multi-app client factory with multi-account support.
Uses config module for all paths — no duplicated logic.
"""

import functools
import json
import time
from pathlib import Path

from schwab.auth import client_from_token_file

from . import config
from . import remote_authority


def _normalize_token_file(token_path: Path):
    """Migrate older top-level OAuth token files to schwab-py's wrapped shape."""
    with open(token_path) as f:
        data = json.load(f)

    if "token" in data:
        return

    if "access_token" not in data:
        return

    creation_timestamp = data.get("creation_timestamp", int(token_path.stat().st_mtime))
    token = {k: v for k, v in data.items() if k != "creation_timestamp"}
    wrapped = {
        "creation_timestamp": creation_timestamp,
        "token": token,
    }

    tmp_path = token_path.with_suffix(token_path.suffix + ".tmp")
    with open(tmp_path, "w") as f:
        json.dump(wrapped, f, indent=2)
    tmp_path.replace(token_path)


RECOVERY_COMMAND = "uv run schwab-auth-keepalive --app {app} --browser-fallback --headed"


def _refresh_ok(result: dict | bool | None) -> bool:
    """Return True only when refresh_tokens actually reports success."""
    if isinstance(result, dict):
        return result.get("status") == "success"
    return bool(result)


def _refresh_error(app: str, result: dict | bool | None) -> RuntimeError:
    detail = ""
    if isinstance(result, dict):
        error = result.get("error")
        details = result.get("details")
        parts = [str(value) for value in (error, details) if value]
        if parts:
            detail = "\n" + "\n".join(parts)
    return RuntimeError(_recovery_message(app) + detail)


def _recovery_message(app: str) -> str:
    if remote_authority.remote_enabled():
        return (
            f"Schwab token refresh failed for '{app}' via goliath authority. Recover with:\n"
            f"  open {remote_authority.base_url()}/login/{app}\n"
            f"Then verify:\n"
            f"  uv run schwab-token-sync --app {app} --refresh"
        )
    return (
        f"Schwab token refresh failed for '{app}'. Recover with:\n"
        f"  {RECOVERY_COMMAND.format(app=app)}"
    )


# Per-process memo: once a token is known fresh, skip all checks until just
# before its access expiry. Cuts the previous scp-per-client-call pattern to
# at most one authority round-trip per process per token lifetime.
_FRESH_UNTIL: dict[str, float] = {}


def _access_valid_for(status: dict) -> float:
    """Seconds until access-token expiry per local token state (or 0)."""
    access_expires = status.get("access_expires")
    if not access_expires:
        return 0.0
    try:
        # Stored without timezone; compare in local time like server.py.
        import datetime as _dt

        return _dt.datetime.fromisoformat(access_expires).timestamp() - time.time()
    except Exception:
        return 0.0


def ensure_fresh_token(app: str, min_valid_seconds: int = 180) -> None:
    """Make sure the local token file is usable, with minimal authority traffic.

    Order matters for latency: check the local file first and return without
    any network I/O when it is still valid. Only sync/refresh via goliath when
    the local token is missing, stale, or near expiry.
    """
    from .server import get_token_status, refresh_tokens

    now = time.time()
    if _FRESH_UNTIL.get(app, 0.0) > now:
        return

    def _fresh(status: dict) -> bool:
        return (
            status.get("exists")
            and status.get("status") in {"valid", "unknown_expiry"}
            and _access_valid_for(status) > min_valid_seconds
        )

    status = get_token_status(app)
    if _fresh(status):
        _FRESH_UNTIL[app] = now + min(_access_valid_for(status) - min_valid_seconds, 300.0)
        return

    # Local token stale or missing. The authority may already hold a fresher
    # copy (goliath refreshes on its own schedule) — pull it before asking for
    # a new refresh.
    if remote_authority.remote_enabled():
        synced = remote_authority.sync_from_authority(app)
        if synced.get("status") not in {"success", "skipped"}:
            raise _refresh_error(app, synced)
        status = get_token_status(app)
        if _fresh(status):
            _FRESH_UNTIL[app] = now + min(_access_valid_for(status) - min_valid_seconds, 300.0)
            return

    if not status.get("exists"):
        raise RuntimeError(_recovery_message(app))

    result = remote_authority.refresh_on_authority(app) if remote_authority.remote_enabled() else refresh_tokens(app)
    if not _refresh_ok(result):
        raise _refresh_error(app, result)
    status = get_token_status(app)
    if _fresh(status):
        _FRESH_UNTIL[app] = now + min(_access_valid_for(status) - min_valid_seconds, 300.0)


def _raw_client(app: str = config.DEFAULT_APP, asyncio: bool = False):
    """Build a plain schwab-py client without retry wrapping."""
    app_config = config.get_app_config(app)
    token_path = config.get_token_path(app)

    if not token_path.exists():
        raise RuntimeError(_recovery_message(app))

    _normalize_token_file(token_path)

    return client_from_token_file(
        token_path=str(token_path),
        api_key=app_config["client_id"],
        app_secret=app_config["client_secret"],
        asyncio=asyncio,
    )


class ResilientClient:
    """Thin proxy that refreshes tokens and retries one 401 per API call."""

    def __init__(self, app: str, asyncio: bool = False):
        self._app = app
        self._asyncio = asyncio
        ensure_fresh_token(app)
        self._client = _raw_client(app, asyncio=asyncio)

    def _rebuild(self):
        self._client = _raw_client(self._app, asyncio=self._asyncio)

    def __getattr__(self, name):
        attr = getattr(self._client, name)
        if not callable(attr):
            return attr

        @functools.wraps(attr)
        def wrapped(*args, **kwargs):
            ensure_fresh_token(self._app)
            resp = attr(*args, **kwargs)
            if getattr(resp, "status_code", None) == 401:
                from .server import refresh_tokens

                _FRESH_UNTIL.pop(self._app, None)
                result = (
                    remote_authority.refresh_on_authority(self._app)
                    if remote_authority.remote_enabled()
                    else refresh_tokens(self._app)
                )
                if not _refresh_ok(result):
                    raise _refresh_error(self._app, result)
                self._rebuild()
                retry_attr = getattr(self._client, name)
                resp = retry_attr(*args, **kwargs)
            return resp

        return wrapped


# One client per (app, flavor) per process — callers in per-symbol loops get
# the same underlying httpx session instead of re-running auth checks and
# connection setup for every symbol.
_CLIENT_CACHE: dict[tuple, object] = {}


def get_client(app: str = config.DEFAULT_APP, asyncio: bool = False, resilient: bool = True):
    """
    Get an authenticated Schwab client for the specified app.

    Args:
        app: Which app to use ("market" or "trading").
        asyncio: If True, returns an async client.

    Returns:
        schwab.client.Client or schwab.client.AsyncClient (cached per process).
    """
    key = (app, asyncio, resilient)
    client = _CLIENT_CACHE.get(key)
    if client is None:
        client = ResilientClient(app, asyncio=asyncio) if resilient else _raw_client(app, asyncio=asyncio)
        _CLIENT_CACHE[key] = client
    return client


def get_account_hashes(client) -> list[dict]:
    """
    Get all linked account numbers and hashes.

    Returns:
        List of {"accountNumber": str, "hashValue": str} dicts.
    """
    resp = client.get_account_numbers()
    resp.raise_for_status()
    accounts = resp.json()
    if not accounts:
        raise RuntimeError("No accounts found")
    return accounts


def resolve_account(client, identifier: str | None = None) -> str:
    """
    Resolve an account identifier to an account hash.

    Args:
        identifier: One of:
            - None → first account (backward compat)
            - "1", "2" → 1-based index
            - "12345678" → account number match
            - "ABC..." → partial hash match

    Returns:
        Account hash string.

    Raises:
        ValueError: If identifier doesn't match any account.
    """
    accounts = get_account_hashes(client)

    if identifier is None:
        return accounts[0]["hashValue"]

    # 1-based index
    if identifier.isdigit() and 1 <= int(identifier) <= len(accounts):
        return accounts[int(identifier) - 1]["hashValue"]

    # Account number match
    for acct in accounts:
        if acct["accountNumber"] == identifier:
            return acct["hashValue"]

    # Partial hash match
    for acct in accounts:
        if acct["hashValue"].startswith(identifier):
            return acct["hashValue"]

    # No match — show available accounts
    available = "\n".join(
        f"  [{i + 1}] {a['accountNumber']} ({a['hashValue'][:12]}...)"
        for i, a in enumerate(accounts)
    )
    raise ValueError(f"No account matching '{identifier}'. Available:\n{available}")
