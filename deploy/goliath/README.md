# Goliath Schwab OAuth Host

This is the preferred always-on shape if `goliath` should own Schwab auth and
the local Mac should act as a client.

```text
Schwab OAuth
  ├── Schwab callback URL
  │     https://goliath.tailffd98c.ts.net/callback
  ├── Tailscale Serve on goliath
  │     / -> http://127.0.0.1:9000
  ├── schwab-oauth.service
  │     runs `schwab-server --port 9000`
  ├── schwab-refresh.timer
  │     runs `schwab-auth-keepalive --app all --browser-fallback --headless`
  │     every 12 hours
  ├── schwab-stream-cache.service
  │     read-only level-one quote/account activity cache
  ├── browser login fallback
  │     refresh first, then Playwright login only if refresh fails
  ├── token store on goliath
  │     /home/will/tmp/schwab/tokens_market.json
  │     /home/will/tmp/schwab/tokens_trading.json
  └── local Mac clients
        auto-refresh on goliath and sync copied token files down
```

Goliath is the single token authority. Schwab rotates refresh tokens, so local
machines should not independently refresh copied token files. With the goliath
callback URL in `config.json`, local `schwab` commands automatically detect
that they are not running on goliath, call goliath's `/refresh/<app>` endpoint
when needed, and copy the rotated token file down over SSH.

## Migration

1. Put the Schwab package, `config.json`, and current token files at
   `/home/will/tmp/schwab` on `goliath`.
2. Install Python deps there with the local preferred package manager.
   `uv` is preferred if installed:

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh  # if uv is not installed
   cd /home/will/tmp/schwab
   uv sync
   uv run playwright install chromium
   ```

3. Write the Schwab browser-login fallback secret. This prompts for username
   and password without echoing the password, writes a chmod-600 env file, and
   never prints the values:

   ```bash
   cd /home/will/tmp/schwab
   uv run schwab-secrets write
   ```

   Default secret path:

   ```text
   /home/will/tmp/schwab/secrets/schwab-login.env
   ```

4. Stop the old reverse tunnel that currently binds `127.0.0.1:9000` on
   `goliath`.
5. Install the user services:

   ```bash
   mkdir -p ~/.config/systemd/user
   cp deploy/goliath/schwab-oauth.service ~/.config/systemd/user/
   cp deploy/goliath/schwab-refresh.service ~/.config/systemd/user/
   cp deploy/goliath/schwab-refresh.timer ~/.config/systemd/user/
   cp deploy/goliath/schwab-stream-cache.service ~/.config/systemd/user/
   systemctl --user daemon-reload
   systemctl --user enable --now schwab-oauth.service schwab-refresh.timer schwab-stream-cache.service
   ```

6. Verify:

   ```bash
   systemctl --user status schwab-oauth.service schwab-refresh.timer schwab-stream-cache.service
   curl -sS http://127.0.0.1:9000/status
   cd /home/will/tmp/schwab && uv run schwab auth
   ls -l /home/will/tmp/trading/artifacts/schwab/live/
   ```

7. From the local Mac, verify token authority and sync:

   ```bash
   cd ~/tmp/trading/schwab
   uv run schwab token-sync --status
   uv run schwab token-sync --app all --refresh
   uv run schwab auth
   ```

## Full Re-Auth Fallback

The refresh timer should keep tokens alive indefinitely as long as Schwab keeps
rotating refresh tokens. If refresh fails because Schwab forces a new consent
flow, the timer runs the browser-login fallback automatically using:

```bash
uv run schwab-auth-keepalive --app all --browser-fallback --headless
```

For first-time setup or MFA troubleshooting, use the goliath login URLs directly
or run the fallback headed from an environment where a browser window is visible:

```bash
open https://goliath.tailffd98c.ts.net/login/market
open https://goliath.tailffd98c.ts.net/login/trading
uv run schwab-browser-auth --app all --headed
```

If Schwab asks for MFA in headless mode, the command exits and reports that MFA
is required. Rerun headed or supply `SCHWAB_MFA_CODE` for that single attempt.
