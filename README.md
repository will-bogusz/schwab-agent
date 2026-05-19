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
  ├── schwab-secrets write
  │     hidden credential prompt for fallback login
  ├── tokens_market.json
  └── tokens_trading.json
```

Common commands:

```bash
uv run schwab auth
uv run schwab quote AAPL
uv run schwab technical AAPL
uv run schwab options-eval AAPL --target-pct 30,50,70
uv run schwab positions
uv run schwab-refresh --app all
uv run schwab-auth-keepalive --app all --browser-fallback --headless
uv run schwab-stream-cache --symbols LITE,SMTC,TSEM --account-activity
uv run schwab-secrets write
uv run schwab-server
```

For an always-on goliath deployment, see `deploy/goliath/`.
