# Schwab Agent

CLI and OAuth helpers for the Schwab Trader API.

```text
OAuth/token flow
  ├── schwab-server
  │     interactive OAuth callback server
  ├── schwab-refresh
  │     non-interactive refresh-token keepalive
  ├── schwab-auth-keepalive
  │     refresh first; browser login fallback only if refresh fails
  ├── goliath token authority
  │     local commands refresh on goliath and sync rotated token files down
  ├── schwab-token-sync
  │     manual token sync / refresh from goliath
  ├── schwab-secrets write
  │     hidden credential prompt for fallback login
  ├── tokens_market.json
  └── tokens_trading.json
```

Common commands:

```bash
uv run schwab auth
uv run schwab token-sync --status
uv run schwab token-sync --refresh
uv run schwab quote AAPL
uv run schwab technical AAPL
uv run schwab options-eval AAPL --target-pct 30,50,70
uv run schwab positions
uv run schwab-refresh --app all
uv run schwab-auth-keepalive --app all --browser-fallback --headless
uv run schwab-token-sync --app all --refresh
uv run schwab-stream-cache --symbols LITE,SMTC,TSEM --account-activity
uv run schwab-secrets write
uv run schwab-server
```

When `config.json` uses the goliath callback URL, non-goliath hosts
automatically treat goliath as the only Schwab token writer. Local clients first
sync `tokens_market.json` / `tokens_trading.json` from goliath, refresh on
goliath when needed, and then use the synced files to build schwab-py clients.
Set `SCHWAB_TOKEN_AUTHORITY=local` only for deliberate local OAuth testing.

For the always-on goliath deployment, see `deploy/goliath/`.
