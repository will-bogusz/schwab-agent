# Schwab API Capability Audit And Tooling Proposal

Date: 2026-05-19

## Current Auth Shape

```text
normal path
  └── schwab-auth-keepalive
        ├── refresh market token
        └── refresh trading token

fallback path
  └── refresh failure
        └── Playwright browser login
              ├── reads secrets/schwab-login.env
              ├── completes Schwab login/consent
              └── writes fresh tokens_market.json / tokens_trading.json

goliath
  ├── schwab-oauth.service on 127.0.0.1:9000
  ├── Tailscale Serve -> https://goliath.tailffd98c.ts.net
  └── schwab-refresh.timer at 00:15 and 12:15 ET
```

Verified:

- Local headless browser auth succeeded for `market` and `trading`.
- Goliath headless browser auth succeeded for `market` and `trading`.
- Goliath `schwab-auth-keepalive --app all --browser-fallback --headless` refreshed both apps.
- Goliath callback status is reachable at `https://goliath.tailffd98c.ts.net/status`.
- Secret/token/browser-profile files are chmod private.

## Schwab Data We Can Use

```text
Schwab Trader API
  ├── Accounts and Trading
  │     ├── linked account hashes
  │     ├── balances
  │     ├── positions
  │     ├── current day P/L fields
  │     ├── orders
  │     ├── transactions
  │     ├── order preview / place / cancel / replace
  │     └── user preferences + streamer credentials
  │
  ├── Market Data REST
  │     ├── quotes
  │     │     ├── quote
  │     │     ├── regular
  │     │     ├── extended
  │     │     ├── reference
  │     │     └── fundamental
  │     ├── multi-symbol quotes
  │     ├── option chains
  │     ├── option expiration chains
  │     ├── equity/ETF price history
  │     ├── market hours
  │     ├── movers
  │     └── instruments / fundamentals search
  │
  └── Streaming
        ├── level one equities/options/futures/forex
        ├── equity/futures chart candles
        ├── NYSE / NASDAQ / options order book
        ├── screeners
        └── account activity
```

Live samples confirmed useful fields for `LITE`, `SMTC`, and `TSEM`:

- `quote`: `lastPrice`, `mark`, `bidPrice`, `askPrice`, `bidSize`, `askSize`, `totalVolume`, `quoteTime`, `tradeTime`, `postMarketChange`, `postMarketPercentChange`.
- `regular`: `regularMarketLastPrice`, `regularMarketNetChange`, `regularMarketPercentChange`, `regularMarketTradeTime`.
- `extended`: `lastPrice`, `mark`, `bidPrice`, `askPrice`, `bidSize`, `askSize`, `quoteTime`, `tradeTime`.
- `reference`: description, exchange, shortability, optionability.
- `fundamental`: EPS, P/E, dividend fields, shares outstanding, average volume.
- options: bid/ask/last/mark, Greeks, IV, OI, volume, theoretical value, intrinsic/extrinsic value, underlying quote, delayed flag.
- history: minute candles can include extended-hours data when requested.
- user preferences: trading app returns streamer URL/IDs and `level2Permissions=true`; market app returns unauthorized for this endpoint.

## Important Boundaries

- Schwab is excellent for US-listed holdings, US options, Schwab account state, and live/extended-session quote state.
- Schwab should not be treated as a replacement for IBKR/yfinance for TSXV, Frankfurt, KRX, or other foreign holdings unless we directly verify symbol support.
- Schwab price history is useful for equities/ETFs. The installed client documentation says it does not provide price history for options, futures, or other instruments.
- Schwab order write endpoints are throttled and should stay behind existing preview/confirm safeguards.
- Streaming is available, but the first implementation should be read-only and write cached snapshots for portfolio tools rather than place orders.

## Proposed Tooling Improvements

### 1. Schwab Quote Engine

Add a reusable quote module around Schwab market data:

```text
schwab_quote(symbols)
  ├── regular session price/change
  ├── extended session price/change
  ├── bid/ask + size
  ├── quote/trade timestamps
  ├── stale/delayed flags
  ├── reference/fundamental fields
  └── normalized best_display_price
```

CLI shape:

```bash
uv run schwab quote-rich LITE SMTC TSEM
uv run schwab quote-rich LITE --json
uv run schwab quote-rich LITE --session-aware
```

Use this for:

- premarket / after-hours marks;
- bid/ask sanity before orders;
- detecting whether a print is regular-session or extended-session;
- showing quote age in portfolio output.

### 2. Schwab-Backed HSA Portfolio

Remove the hardcoded HSA position block in `portfolio.py` and pull the Schwab HSA directly:

```text
portfolio.py
  ├── IBKR accounts
  ├── Schwab HSA account
  │     ├── positions
  │     ├── balances
  │     └── current day P/L
  └── pricing layer
        ├── Schwab for US-listed symbols
        └── existing non-Schwab sources only where Schwab cannot cover the asset
```

This should improve SMTC/HSA freshness without weakening the foreign-stock coverage already handled elsewhere.

### 3. Session-Aware Portfolio Marks

Current `portfolio.py` mostly treats the latest screen price as one price. Schwab lets us show the shape:

```text
US holding row
  ├── regular close / regular last
  ├── after-hours or premarket mark
  ├── extended-session change
  ├── bid/ask spread
  ├── quote age
  └── regular vs extended source label
```

Suggested display columns:

- `Reg Price`
- `Ext Price`
- `Ext %`
- `Bid/Ask`
- `Quote Age`
- `Source`

For compact mode, replace `Price` with session-aware best mark and append a source suffix like `AH`, `PM`, `REG`, or `STALE`.

### 4. Schwab Options Analyzer

Build options evaluation directly on Schwab chains:

```text
schwab options-eval SYMBOL
  ├── target move scenarios
  ├── expiry windows
  ├── outright calls/puts
  ├── vertical spreads
  ├── debit paid / max value / breakeven
  ├── IV / delta / theta / volume / OI
  └── liquidity filter using bid/ask width
```

This is directly useful for the structural-long convexity work because Schwab gives chain marks, Greeks, OI, volume, IV, theoretical values, and underlying quote in one response.

### 5. Intraday Technical Snapshot From Schwab Only

For US-listed symbols, use Schwab minute history with extended hours:

```text
schwab technical SYMBOL
  ├── 1m/5m candles
  ├── regular-session VWAP
  ├── extended-session VWAP
  ├── day high/low
  ├── premarket high/low
  ├── after-hours high/low
  ├── relative volume vs recent Schwab daily bars
  └── SMA/EMA from Schwab history
```

This gives us the price-action context we wanted for LITE-style trims without leaning on Polygon for real-time data.

### 6. Streaming Watchlist Daemon

After the REST quote path is clean, add an optional read-only streamer:

```text
schwab-stream-watch
  ├── reads watchlist from current portfolio + configured tickers
  ├── subscribes to level one equities/options
  ├── subscribes to chart equity candles
  ├── optionally subscribes to account activity
  └── writes latest state to artifacts/schwab/live/*.json
```

Portfolio and monitor scripts can read the cache instead of making repeated REST calls during active sessions.

## Implementation Order

1. Add a `src/schwab_agent/quotes.py` normalizer and `schwab quote-rich`.
2. Add Schwab HSA account ingestion to `portfolio.py`, keeping IBKR untouched.
3. Add session-aware US quote display in `portfolio.py` behind `--schwab-us-quotes` or make it default for US tickers after comparison.
4. Add `schwab options-eval` for target-return option/spread comparisons.
5. Add `schwab technical` for intraday/extended-hours technical context.
6. Add read-only streaming cache only after REST tools are stable.

## Non-Goals

- Do not replace foreign-stock/TSXV/KRX pricing with Schwab unless verified.
- Do not place orders from any new monitor/streaming tool.
- Do not implement any data field that cannot be sourced directly from Schwab in this Schwab tooling pass.
- Do not mix Schwab-derived fields with yfinance/Polygon fields without labeling the source.
