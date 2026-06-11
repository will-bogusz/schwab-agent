# Schwab API — Reference

See `../CLAUDE.md` for all command syntax, order templates, and field reference.

## OAuth Flow

Two apps with independent tokens:

| App | Token File |
|-----|------------|
| `market` | `tokens_market.json` |
| `trading` | `tokens_trading.json` |

- Access tokens: 30 minutes (auto-refresh by schwab-py)
- Refresh tokens: 7 days (re-authenticate after expiry)
- Goliath is the default token authority when `config.json` uses
  `https://goliath.tailffd98c.ts.net/callback`.
- Local commands auto-refresh on goliath and sync rotated token files down.
- Manual local sync: `uv run schwab token-sync --app all --refresh`
- Manual/cron refresh on goliath: `uv run schwab-refresh --app all`
- Refresh plus browser fallback on goliath:
  `uv run schwab-auth-keepalive --app all --browser-fallback --headless`

### Re-authentication Steps

1. Visit `https://goliath.tailffd98c.ts.net/login/market`
2. Complete Schwab login/consent for the market app
3. Visit `https://goliath.tailffd98c.ts.net/login/trading`
4. Complete Schwab login/consent for the trading app
5. Verify locally with `uv run schwab token-sync --app all --refresh`

### Always-On Refresh

Use `uv run schwab-refresh --app all` from the Schwab package directory on
goliath to refresh both token files without running a new OAuth login. This is
the right command for launchd, cron, or a systemd timer. On each successful
refresh, the token timestamp is reset so the 7-day refresh window tracks the
newly issued Schwab refresh token.

On local machines, use `uv run schwab token-sync --app all --refresh` or
`uv run schwab-token-sync --app all --refresh`. This calls goliath's refresh
endpoint, then copies the rotated token files down. Do not run a separate local
refresh loop against copied tokens; that reintroduces token drift.

Use `uv run schwab-auth-keepalive --app all --browser-fallback --headless` for
the goliath timer. It refreshes first and only runs the Playwright login flow
when refresh fails.

### Browser Login Fallback

Credential handoff is via a local chmod-600 env file. Create it with:

```bash
uv run schwab-secrets write
```

The command prompts for username and a hidden password, then writes
`secrets/schwab-login.env` by default. Do not print, cat, or commit that file.

Manual fallback test:

```bash
uv run schwab-browser-auth --app all --headed
```

With goliath authority enabled, a successful local browser fallback redirects to
goliath and then syncs goliath's token file back down. If it cannot sync, the
fallback exits as failed.

For the goliath-hosted setup, see `deploy/goliath/`.

## App Selection

- **schwab CLI**: Smart defaults — `quote`/`options`/`history`/`movers`/`hours`/`search` use market app, others use trading app
- **schwab-api**: Defaults to trading, override with `--app market`
- **Python**: `from schwab_agent.client import get_client; get_client("market")`

## CLI Commands

| Command | Description | Default App |
|---------|-------------|-------------|
| `schwab quote <symbols>` | Session-aware Schwab quotes with regular/extended/reference/fundamental fields | market |
| `schwab technical <symbol>` | Intraday technical snapshot: VWAP, ranges, volume, SMA/EMA | market |
| `schwab options-eval <symbol>` | Outright call and call-spread scenarios with liquidity metrics | market |
| `schwab token-sync` | Show/sync/refresh token files from goliath authority | market |
| `schwab positions` | Account positions | trading |
| `schwab balances` | Account balances | trading |
| `schwab orders` | Show orders | trading |
| `schwab options <symbol>` | Raw/summary option chain | market |
| `schwab auth` | Check token status | trading |
| `schwab accounts` | List linked accounts | trading |
| `schwab order` | Place order via OrderBuilder | trading |
| `schwab preview` | Server-side order preview | trading |
| `schwab cancel` | Cancel an order | trading |
| `schwab replace` | Replace an order | trading |
| `schwab expirations <symbol>` | Option expiration chain | market |
| `schwab history <symbol>` | Price history | market |
| `schwab transactions` | Account transactions | trading |
| `schwab movers` | Market movers | market |
| `schwab hours` | Market hours | market |
| `schwab search <query>` | Search instruments | market |
| `schwab instrument <cusip>` | Instrument by CUSIP | market |

Schwab is the primary source for US live quotes, US options, intraday
technicals, extended-session marks, and Schwab account state. Polygon is only a
historical/bulk fallback for US data. yfinance is only a labeled fallback for
foreign, TSXV, KRX, FX, macro, or other assets Schwab does not cover well.

## Files

```
schwab/
├── config.json              # Multi-app credentials and callback URL (gitignored)
├── secrets/                 # Browser-login env file (gitignored, chmod 600)
├── .auth/                   # Playwright persistent profile (gitignored)
├── tokens_market.json       # OAuth tokens for market data app
├── tokens_trading.json      # OAuth tokens for trading app
├── pyproject.toml           # Dependencies + entry points (schwab, schwab-api, schwab-server)
├── deploy/goliath/          # Optional always-on OAuth host units
└── src/schwab_agent/
    ├── __init__.py           # Version (0.2.0)
    ├── config.py             # Config/path resolution
    ├── client.py             # Resilient multi-app client factory + 401 refresh retry
    ├── market.py             # Normalized quote/session model
    ├── technical.py          # Schwab history technical snapshots
    ├── options_eval.py       # Options/scenario evaluation helpers
    ├── stream_cache.py       # Read-only streaming cache daemon
    ├── output.py             # Formatting helpers (fmt_table, fmt_currency, emit)
    ├── orders.py             # OrderBuilder wrapper + safety checks
    ├── cli.py                # 18-command CLI (entry point: schwab)
    ├── remote_authority.py   # Goliath token authority sync/refresh
    ├── api.py                # Raw JSON order API (entry point: schwab-api)
    ├── browser_auth.py       # Browser fallback + secret writer
    └── server.py             # OAuth server (entry point: schwab-server)
```
