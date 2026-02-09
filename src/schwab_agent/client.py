"""
Schwab Client Factory
---------------------
Multi-app client factory with multi-account support.
Uses config module for all paths — no duplicated logic.
"""

from schwab.auth import client_from_token_file

from . import config


def get_client(app: str = config.DEFAULT_APP, asyncio: bool = False):
    """
    Get an authenticated Schwab client for the specified app.

    Args:
        app: Which app to use ("market" or "trading").
        asyncio: If True, returns an async client.

    Returns:
        schwab.client.Client or schwab.client.AsyncClient.
    """
    app_config = config.get_app_config(app)
    token_path = config.get_token_path(app)

    if not token_path.exists():
        raise RuntimeError(
            f"No tokens for '{app}' app. Authenticate first:\n"
            f"  1. uv run schwab-server\n"
            f"  2. Visit http://localhost:8000/login/{app}"
        )

    return client_from_token_file(
        token_path=str(token_path),
        api_key=app_config["client_id"],
        app_secret=app_config["client_secret"],
        asyncio=asyncio,
    )


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
