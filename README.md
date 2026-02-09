# schwab-agent

AI-agent-friendly interface to your Schwab brokerage account. Get quotes, view positions, and place orders — from the command line or through an AI assistant like Claude.

Designed to be driven by AI agents (with a setup wizard in `CLAUDE.md`) or used directly as a CLI. Built on the [schwab-py](https://github.com/alexgolec/schwab-py) library.

## Prerequisites

### Python 3.10+

<details>
<summary>Mac</summary>

```bash
brew install python
```
</details>

<details>
<summary>Windows</summary>

Download from https://www.python.org/downloads/ and run the installer.

Check "Add Python to PATH" during installation.
</details>

<details>
<summary>Linux (Ubuntu/Debian)</summary>

```bash
sudo apt update && sudo apt install python3 python3-pip
```
</details>

Verify: `python3 --version` (should be 3.10 or higher)

### uv (Python package manager)

<details>
<summary>Mac</summary>

```bash
brew install uv
```
</details>

<details>
<summary>Windows</summary>

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```
</details>

<details>
<summary>Linux</summary>

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```
</details>

Verify: `uv --version`

### ngrok (HTTPS tunnel for OAuth)

<details>
<summary>Mac</summary>

```bash
brew install ngrok
```
</details>

<details>
<summary>Windows</summary>

Download from https://ngrok.com/download and add to PATH, or:
```powershell
choco install ngrok
```
</details>

<details>
<summary>Linux</summary>

```bash
curl -sSL https://ngrok-agent.s3.amazonaws.com/ngrok.asc \
  | sudo tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null \
  && echo "deb https://ngrok-agent.s3.amazonaws.com buster main" \
  | sudo tee /etc/apt/sources.list.d/ngrok.list \
  && sudo apt update && sudo apt install ngrok
```
</details>

Verify: `ngrok version`

## Setup

### 1. Clone and install

```bash
git clone <this-repo-url>
cd schwab-agent
uv sync
```

### 2. Create a Schwab developer account and app

The Schwab developer portal uses a **separate account** from your regular Schwab brokerage login.

1. Go to https://developer.schwab.com/ and create a developer account (or sign in if you already have one)
2. Go to https://developer.schwab.com/dashboard/apps and click **Create App**
3. Fill in the form:
   - **API Products**: select **both** "Accounts and Trading Production" **and** "Market Data Production"
   - **App Name**: anything your end users would recognize (e.g., "Trading Tools")
   - **App Description**: optional, for your own reference
   - **Callback URL**: leave blank for now — you'll fill this in after step 3 (ngrok setup)
4. After creation, note your **App Key** (this is your client ID) and **Secret**

> **Important:** Schwab does **not** auto-approve apps. After creating your app, you'll need to wait for Schwab to approve it. This can take anywhere from a few minutes to a couple of days. You'll see a "Ready" status on the dashboard when approved. Until then, API calls will return 403 errors.

### 3. Set up ngrok

Schwab requires an HTTPS callback URL for OAuth. ngrok provides one for free.

1. Sign up at https://dashboard.ngrok.com/signup (free)
2. Copy your auth token from the dashboard and connect it:
   ```bash
   ngrok config add-authtoken YOUR_AUTH_TOKEN
   ```
3. Go to https://dashboard.ngrok.com/domains and click **New Domain** to claim your free static domain (e.g., `something.ngrok-free.app`)
4. **Go back to the Schwab developer portal** and update your app's callback URL to:
   ```
   https://YOUR-DOMAIN.ngrok-free.app/callback
   ```

### 4. Configure

```bash
cp config.example.json config.json
```

Edit `config.json` with your credentials:

```json
{
  "client_id": "your Schwab App Key",
  "client_secret": "your Schwab Secret",
  "callback_url": "https://YOUR-DOMAIN.ngrok-free.app/callback"
}
```

### 5. Authenticate

This needs two terminals running simultaneously.

**Terminal 1** — start ngrok:
```bash
ngrok http 8000 --url=YOUR-DOMAIN.ngrok-free.app
```

**Terminal 2** — start the auth server:
```bash
uv run schwab-auth
```

Then:
1. Open http://localhost:8000 in your browser
2. Click **Authenticate**
3. Log into Schwab and authorize the app
4. You should see a green checkmark — tokens are saved automatically

You can now stop both ngrok and the auth server (Ctrl+C).

### 6. Verify

```bash
uv run schwab auth
```

Should show `Account access: OK` and `Market data: OK`.

## Usage

### Market data

```bash
# Stock quotes
uv run schwab quote AAPL GOOGL MSFT

# Quote with fundamental data
uv run schwab quote AAPL --fields fundamental

# Option chain
uv run schwab options AAPL
uv run schwab options AAPL --calls --expiry 20250321 --strikes 5

# Option expirations
uv run schwab expirations AAPL

# Price history
uv run schwab history AAPL --daily --from 2025-01-01
uv run schwab history AAPL --minute --from 2025-06-01

# Market movers
uv run schwab movers --index SPX

# Market hours
uv run schwab hours --market equity

# Search instruments
uv run schwab search AAPL --projection fundamental

# Instrument by CUSIP
uv run schwab instrument 037833100
```

### Account data

```bash
# List linked accounts
uv run schwab accounts

# Positions
uv run schwab positions
uv run schwab positions --account 1    # specific account by index

# Balances
uv run schwab balances

# Recent orders
uv run schwab orders
uv run schwab orders --status filled --days 30
uv run schwab orders --all-accounts

# Transactions
uv run schwab transactions
uv run schwab transactions --type TRADE --from 2025-01-01

# Raw JSON output (any command)
uv run schwab positions --raw
```

### Placing orders (CLI)

The `order` subcommand uses schwab-py's OrderBuilder for safe order construction. **All orders are previewed by default** — nothing executes without `--confirm`.

```bash
# Preview a market buy
uv run schwab order --action BUY --symbol AAPL --qty 10

# Preview a limit buy
uv run schwab order --action BUY --symbol AAPL --qty 10 --type LIMIT --price 150

# Execute it (add --confirm)
uv run schwab order --action BUY --symbol AAPL --qty 10 --type LIMIT --price 150 --confirm

# Stop order
uv run schwab order --action SELL --symbol AAPL --qty 10 --type STOP --stop-price 140

# Option order
uv run schwab order --action BUY_TO_OPEN --underlying AAPL --expiry 20250321 --strike 150 --right C --qty 1 --type LIMIT --price 5.00

# Cancel an order
uv run schwab cancel --order-id 123456 --confirm

# Replace (modify) an order
uv run schwab replace --order-id 123456 --data '{"orderType":"LIMIT","price":"155",...}' --confirm

# Server-side preview
uv run schwab preview --data '{"orderType":"LIMIT",...}'
```

#### Order types

| Type | Required flags |
|------|---------------|
| `MARKET` | — |
| `LIMIT` | `--price` |
| `STOP` | `--stop-price` |
| `STOP_LIMIT` | `--price` + `--stop-price` |
| `TRAILING_STOP` | `--stop-offset` |

#### Instructions

| Asset | Instructions |
|-------|-------------|
| Equity | `BUY`, `SELL`, `BUY_TO_COVER`, `SELL_SHORT` |
| Options | `BUY_TO_OPEN`, `BUY_TO_CLOSE`, `SELL_TO_OPEN`, `SELL_TO_CLOSE` |

### Placing orders (raw JSON — schwab-api)

For complex multi-leg, OCO, or trigger orders that can't be expressed through CLI flags, use `schwab-api` with raw JSON:

```bash
# Preview
uv run schwab-api place --data '{
  "orderType": "LIMIT", "session": "NORMAL", "price": "150.00",
  "duration": "DAY", "orderStrategyType": "SINGLE",
  "orderLegCollection": [{"instruction": "BUY", "quantity": 10,
    "instrument": {"symbol": "AAPL", "assetType": "EQUITY"}}]
}'

# Execute (add --confirm)
uv run schwab-api place --data '{...}' --confirm

# Server-side preview
uv run schwab-api preview --data '{...}'

# Cancel
uv run schwab-api cancel --order-id 123456 --confirm

# Replace
uv run schwab-api replace --order-id 123456 --data '{...}' --confirm
```

### Multi-account support

If you have multiple linked accounts, use `--account` to target a specific one:

```bash
# By 1-based index
uv run schwab positions --account 1

# By account number
uv run schwab positions --account 12345678

# By hash prefix
uv run schwab positions --account ABC

# List all accounts to see what's available
uv run schwab accounts
```

Without `--account`, the first linked account is used.

### Safety limits

These are enforced automatically before any order is submitted:

- Max 10,000 equity shares per order
- Max 100 option contracts per order
- Warning if limit price deviates >20% from current market price
- Warnings for large orders (>1,000 shares), short sales, and option writes

## Re-authentication

Schwab tokens work like this:
- **Access tokens** last 30 minutes — refreshed automatically, no action needed
- **Refresh tokens** last 7 days — after that, you need to re-authenticate

When commands start failing with auth errors, re-authenticate:

1. `ngrok http 8000 --url=YOUR-DOMAIN.ngrok-free.app` (terminal 1)
2. `uv run schwab-auth` (terminal 2)
3. Open http://localhost:8000, click Authenticate, log into Schwab
4. Stop both after success

## Alternative: Tailscale Funnel

If you have an always-on machine (home server, NAS, etc.) with [Tailscale](https://tailscale.com), you can use Tailscale Funnel instead of ngrok for a permanent HTTPS callback URL.

1. Install Tailscale on the always-on machine
2. Enable Funnel: `tailscale funnel 9000`
3. Note the stable URL (e.g., `https://machine-name.tail12345.ts.net`)
4. Set your Schwab app callback URL to `https://machine-name.tail12345.ts.net/callback`
5. When authenticating, tunnel from your local machine:
   ```bash
   ssh -R 9000:localhost:8000 -N that-machine
   ```
6. Then run `uv run schwab-auth` locally and authenticate as usual

This eliminates the need to run ngrok for each re-authentication.

## Configuration

Config is found automatically in this order:
1. `SCHWAB_AGENT_DIR` environment variable (set to directory containing `config.json`)
2. Walk up from current directory looking for `config.json`
3. `~/.config/schwab-agent/`

This means you can run commands from any directory by setting `SCHWAB_AGENT_DIR`.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `No tokens found` | Run the authentication flow (see Setup step 5) |
| `401 Unauthorized` | Refresh token expired (>7 days). Re-authenticate. |
| `403 Forbidden` | Schwab app not approved yet (check status at https://developer.schwab.com/dashboard/apps — needs "Ready" status), or missing API product permissions. |
| `Connection refused` during OAuth | Make sure ngrok is running before starting the auth server. |
| ngrok `ERR_NGROK_3200` | Auth token not set. Run `ngrok config add-authtoken YOUR_TOKEN`. |
| `Token exchange failed` | Auth code expired (~30 sec). Try again — complete the Schwab login quickly. |
| `Cannot find schwab-agent config` | Set `SCHWAB_AGENT_DIR` or run from the project directory. |

## File reference

| File | Purpose |
|------|---------|
| `config.json` | API credentials and callback URL (gitignored) |
| `config.example.json` | Template for config.json |
| `tokens.json` | OAuth tokens (gitignored, auto-managed) |
| `src/schwab_agent/config.py` | Config resolution and loading |
| `src/schwab_agent/client.py` | API client factory with multi-account support |
| `src/schwab_agent/cli.py` | CLI with 18 commands (`uv run schwab`) |
| `src/schwab_agent/api.py` | Raw JSON order API (`uv run schwab-api`) |
| `src/schwab_agent/orders.py` | Order building via schwab-py OrderBuilder |
| `src/schwab_agent/output.py` | Output formatting helpers |
| `src/schwab_agent/server.py` | OAuth authentication server (`uv run schwab-auth`) |
