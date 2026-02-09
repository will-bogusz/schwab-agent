# schwab-agent

## On Session Start

1. Check if `config.json` exists. If not, start the Setup Wizard below.
2. If config exists, check auth: `uv run schwab auth`
3. If auth fails, guide re-authentication (see Re-Auth below).

The user is non-technical. Explain things simply, confirm each step before moving on.

Full setup instructions, platform-specific install commands, and troubleshooting are in `README.md` — read it when needed rather than guessing.

---

## Setup Wizard

When setup is needed, follow this flow. Detect the OS first (`uname` or platform check), then work through each phase.

### Phase 1: Prerequisites (agent can automate)

Check and install each tool. Run the check command — if it fails, install it. See README.md for platform-specific install commands (Mac/Windows/Linux sections).

| Tool | Check | Notes |
|------|-------|-------|
| Python 3.10+ | `python3 --version` | brew / apt / python.org installer |
| uv | `uv --version` | brew / curl / powershell |
| ngrok | `ngrok version` | brew / apt / choco |

After all tools pass, run `uv sync` to install project dependencies.

### Phase 2: Account setup (requires user in browser)

These steps require the user to interact with websites. Guide them through each one, then ask them to provide the resulting values.

1. **Schwab developer account + app** — This is a separate account from their brokerage login. User must:
   - Create a developer account at https://developer.schwab.com/ (if they don't have one)
   - Go to https://developer.schwab.com/dashboard/apps and click Create App
   - Select **both** API products: "Accounts and Trading Production" AND "Market Data Production"
   - Fill in App Name (anything), leave Callback URL blank for now (filled in after ngrok setup)
   - Ask them for the **App Key** and **Secret** when done
   - **App requires Schwab approval** — not instant. Could take minutes to days. Status shows "Ready" when approved. 403 errors before approval are expected.

2. **ngrok account** — User must visit https://dashboard.ngrok.com/signup, then:
   - Copy their auth token → agent runs `ngrok config add-authtoken TOKEN`
   - Claim a free static domain at https://dashboard.ngrok.com/domains → ask user for the domain name

3. **Set callback URL** — User must go back to the Schwab developer portal and set the app's callback URL to `https://THEIR-DOMAIN.ngrok-free.app/callback`

### Phase 3: Configuration (agent can automate)

Once the user provides their credentials, create `config.json`:

```bash
cp config.example.json config.json
```

Then write the values into it:
```json
{
  "client_id": "their App Key",
  "client_secret": "their Secret",
  "callback_url": "https://THEIR-DOMAIN.ngrok-free.app/callback"
}
```

### Phase 4: First authentication (mixed)

This requires two processes running simultaneously. The agent can start them, but the user must complete the browser auth.

1. Agent starts ngrok: `ngrok http 8000 --url=THEIR-DOMAIN.ngrok-free.app`
2. Agent starts auth server: `uv run schwab-auth`
3. Tell the user to open http://localhost:8000 and click **Authenticate**
4. User logs into Schwab and authorizes the app
5. After user confirms success, stop both processes
6. Verify: `uv run schwab auth`

---

## Re-Auth (Every 7 Days)

When commands fail with auth errors, the refresh token has expired.

1. Start ngrok: `ngrok http 8000 --url=THEIR-DOMAIN.ngrok-free.app`
2. Start server: `uv run schwab-auth`
3. Tell user to open http://localhost:8000 and click Authenticate
4. After success, stop both and verify with `uv run schwab auth`

The user's ngrok domain is in `config.json` under `callback_url`.

---

## Commands

### Market Data

| Task | Command |
|------|---------|
| Stock quote | `uv run schwab quote AAPL GOOGL` |
| Quote with fields | `uv run schwab quote AAPL --fields fundamental` |
| Option chain | `uv run schwab options AAPL` |
| Options (filtered) | `uv run schwab options AAPL --calls --expiry 20250321 --strikes 5` |
| Option expirations | `uv run schwab expirations AAPL` |
| Price history | `uv run schwab history AAPL --daily --from 2025-01-01` |
| Market movers | `uv run schwab movers --index SPX` |
| Market hours | `uv run schwab hours --market equity` |
| Search instruments | `uv run schwab search AAPL --projection fundamental` |
| Instrument by CUSIP | `uv run schwab instrument 037833100` |

### Account

| Task | Command |
|------|---------|
| Check auth | `uv run schwab auth` |
| List accounts | `uv run schwab accounts` |
| Positions | `uv run schwab positions` |
| Balances | `uv run schwab balances` |
| Orders | `uv run schwab orders` |
| Orders (filtered) | `uv run schwab orders --status filled --days 30` |
| Transactions | `uv run schwab transactions --type TRADE` |

### Order Execution (CLI)

| Task | Command |
|------|---------|
| Preview order | `uv run schwab order --action BUY --symbol AAPL --qty 10 --type LIMIT --price 150` |
| Execute order | `uv run schwab order --action BUY --symbol AAPL --qty 10 --type LIMIT --price 150 --confirm` |
| Cancel order | `uv run schwab cancel --order-id 123456 --confirm` |
| Replace order | `uv run schwab replace --order-id 123456 --data '{...}' --confirm` |
| Server preview | `uv run schwab preview --data '{...}'` |

### Order Execution (Raw JSON — schwab-api)

For complex multi-leg/OCO/trigger orders:

| Task | Command |
|------|---------|
| Place order | `uv run schwab-api place --data '{...}' --confirm` |
| Preview order | `uv run schwab-api preview --data '{...}'` |
| Cancel order | `uv run schwab-api cancel --order-id 123456 --confirm` |
| Replace order | `uv run schwab-api replace --order-id 123456 --data '{...}' --confirm` |

### Global Flags

- `--raw` — JSON output (on any command)
- `--account ID` — account identifier: index (`1`, `2`), account number, or hash prefix (on account commands)

---

## Order Safety Rules

1. **Always preview first** — run without `--confirm` to see what would happen
2. **Check the quote** — `uv run schwab quote SYMBOL` before any order
3. **Confirm with the user** — never execute an order without explicit user approval

Automatic safety limits: 10,000 shares max, 100 contracts max, 20% limit price deviation warning.

---

## Config Resolution

Config is found in this order:
1. `SCHWAB_AGENT_DIR` environment variable
2. Walk up from CWD looking for `config.json` with `client_id` or `callback_url`
3. `~/.config/schwab-agent/`

This means commands work from any directory when `SCHWAB_AGENT_DIR` is set.

---

## Token Lifecycle

- Access tokens: 30 min (auto-refreshed by schwab-py, no action needed)
- Refresh tokens: 7 days (re-authentication required after expiry)
- Re-auth requires ngrok + schwab-auth running simultaneously
