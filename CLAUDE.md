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

### Re-authentication Steps

1. Start SSH tunnel: `ssh -R 9000:localhost:8000 -N goliath`
2. Start auth server: `cd schwab && uv run schwab-server`
3. Visit `http://localhost:8000` and authenticate each app
4. Callback URL: `https://goliath.tailffd98c.ts.net/callback`

## App Selection

- **schwab CLI**: Smart defaults — `quote`/`options`/`history`/`movers`/`hours`/`search` use market app, others use trading app
- **schwab-api**: Defaults to trading, override with `--app market`
- **Python**: `from schwab_agent.client import get_client; get_client("market")`

## CLI Commands (18)

| Command | Description | Default App |
|---------|-------------|-------------|
| `schwab quote <symbols>` | Get quotes | market |
| `schwab positions` | Account positions | trading |
| `schwab balances` | Account balances | trading |
| `schwab orders` | Show orders | trading |
| `schwab options <symbol>` | Option chain | market |
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

## Files

```
schwab/
├── config.json              # Multi-app credentials and callback URL (gitignored)
├── tokens_market.json       # OAuth tokens for market data app
├── tokens_trading.json      # OAuth tokens for trading app
├── pyproject.toml           # Dependencies + entry points (schwab, schwab-api, schwab-server)
└── src/schwab_agent/
    ├── __init__.py           # Version (0.2.0)
    ├── config.py             # Config/path resolution
    ├── client.py             # Multi-app client factory + multi-account support
    ├── output.py             # Formatting helpers (fmt_table, fmt_currency, emit)
    ├── orders.py             # OrderBuilder wrapper + safety checks
    ├── cli.py                # 18-command CLI (entry point: schwab)
    ├── api.py                # Raw JSON order API (entry point: schwab-api)
    └── server.py             # OAuth server (entry point: schwab-server)
```
