#!/usr/bin/env python3
"""
Schwab OAuth Server
-------------------
Multi-app OAuth server supporting separate authentication for market data and trading APIs.

Usage:
    schwab-server [--port PORT]

Then visit:
    http://localhost:8000/login/market   - Authenticate market data app
    http://localhost:8000/login/trading   - Authenticate trading app
"""

import json
import sys
import time
import base64
import argparse
from datetime import datetime
from urllib.parse import urlencode

import httpx
from flask import Flask, abort, request, redirect, jsonify

from . import config
from . import remote_authority

app = Flask(__name__)

# Tailscale Funnel exposes the whole 443 listener publicly (the funnel flag is
# per host:port, not per path), so the app itself must gate access. Only the
# OAuth callback needs to be public — Schwab redirects the user's browser
# there. Tailnet clients are identified by the identity headers Tailscale
# Serve injects; funnel (public) traffic never carries them.
PUBLIC_PATHS = {"/callback"}


@app.before_request
def _restrict_to_tailnet():
    if request.path in PUBLIC_PATHS:
        return
    if request.headers.get("Tailscale-User-Login"):
        return  # tailnet client via Tailscale Serve
    if request.remote_addr == "127.0.0.1" and not request.headers.get("X-Forwarded-For"):
        return  # direct local access (goliath itself or an ssh tunnel)
    abort(404)

SCHWAB_AUTH_URL = "https://api.schwabapi.com/v1/oauth/authorize"
SCHWAB_TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"


def load_tokens(app_name: str) -> dict | None:
    """Load tokens for an app, handling nested format."""
    path = config.get_token_path(app_name)
    if not path.exists():
        return None
    with open(path) as f:
        data = json.load(f)
        return data.get("token", data)


def load_tokens_raw(app_name: str) -> dict | None:
    """Load raw token file including metadata."""
    path = config.get_token_path(app_name)
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def wrap_tokens(tokens: dict, creation_timestamp: int | None = None) -> dict:
    """Wrap raw OAuth tokens in the metadata format expected by schwab-py."""
    if "token" in tokens:
        return tokens

    token = {k: v for k, v in tokens.items() if k != "creation_timestamp"}
    return {
        "creation_timestamp": creation_timestamp or tokens.get("creation_timestamp") or int(time.time()),
        "token": token,
    }


def save_tokens(app_name: str, tokens: dict, creation_timestamp: int | None = None):
    """Save tokens in schwab-py's metadata-wrapped format."""
    path = config.get_token_path(app_name)
    with open(path, "w") as f:
        json.dump(wrap_tokens(tokens, creation_timestamp=creation_timestamp), f, indent=2)
    print(f"  Tokens saved to {path}", file=sys.stderr)


def get_basic_auth(client_id: str, client_secret: str) -> str:
    """Create Basic Auth header value."""
    credentials = f"{client_id}:{client_secret}"
    encoded = base64.b64encode(credentials.encode()).decode()
    return f"Basic {encoded}"


def load_auth_meta() -> dict:
    path = config.get_auth_meta_path()
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def record_full_auth(app_name: str, timestamp: int | None = None) -> None:
    """Record a real browser/OAuth login. Refreshes must never call this."""
    meta = load_auth_meta()
    meta[app_name] = {"auth_timestamp": int(timestamp or time.time())}
    path = config.get_auth_meta_path()
    with open(path, "w") as f:
        json.dump(meta, f, indent=2)


def get_auth_timestamp(app_name: str) -> int | None:
    """Unix time of the last full OAuth login, or None if never recorded."""
    entry = load_auth_meta().get(app_name) or {}
    ts = entry.get("auth_timestamp")
    return int(ts) if ts else None


def get_token_status(app_name: str) -> dict:
    """Get token status for an app."""
    tokens = load_tokens(app_name)
    raw = load_tokens_raw(app_name)

    if not tokens:
        return {"exists": False, "valid": False, "status": "missing"}

    if raw and "creation_timestamp" in raw:
        created = raw["creation_timestamp"]
        expires_in = tokens.get("expires_in", 1800)
        access_expires = datetime.fromtimestamp(created + expires_in)

        # Schwab refresh tokens hard-expire 7 days after the original OAuth
        # login; refreshing the access token does NOT extend that window. Use
        # the recorded full-auth time, falling back to creation_timestamp for
        # tokens predating auth_meta.json (that fallback over-estimates the
        # window when refreshes have happened since login).
        authed = get_auth_timestamp(app_name) or created
        refresh_expires = datetime.fromtimestamp(authed + 7 * 24 * 3600)
        refresh_age_days = (time.time() - authed) / 86400

        base = {
            "access_expires": access_expires.isoformat(),
            "refresh_expires": refresh_expires.isoformat(),
            "refresh_age_days": round(refresh_age_days, 2),
        }
        if datetime.now() > refresh_expires:
            return {"exists": True, "valid": False, "status": "refresh_expired", **base}
        elif datetime.now() > access_expires:
            return {"exists": True, "valid": True, "status": "needs_refresh", **base}
        else:
            return {"exists": True, "valid": True, "status": "valid", **base}

    return {"exists": True, "valid": True, "status": "unknown_expiry"}


@app.route("/")
def home():
    """Home page showing status of all apps."""
    cfg = config.load_config()

    apps_html = ""
    for app_name in config.VALID_APPS:
        status = get_token_status(app_name)
        status_icon = {
            "valid": "🟢",
            "needs_refresh": "🟡",
            "refresh_expired": "🔴",
            "missing": "⚪",
            "unknown_expiry": "🟢",
        }.get(status["status"], "❓")

        status_text = {
            "valid": f"Valid until {status.get('access_expires', 'N/A')[:19]}",
            "needs_refresh": "Access expired, will auto-refresh",
            "refresh_expired": "Re-authentication required",
            "missing": "Not authenticated",
            "unknown_expiry": "Authenticated (unknown expiry)",
        }.get(status["status"], status["status"])

        apps_html += f"""
        <div class="app-card">
            <h3>{status_icon} {app_name.title()}</h3>
            <p class="status">{status_text}</p>
            <a href="/login/{app_name}" class="btn">Authenticate</a>
            <a href="/refresh/{app_name}" class="btn btn-secondary">Refresh</a>
        </div>
        """

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Schwab OAuth Server</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                   max-width: 800px; margin: 50px auto; padding: 20px; background: #f5f5f5; }}
            h1 {{ color: #333; }}
            .app-card {{ background: white; padding: 20px; border-radius: 8px; margin: 15px 0;
                        box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
            .app-card h3 {{ margin-top: 0; }}
            .status {{ color: #666; font-size: 14px; }}
            .btn {{ display: inline-block; padding: 8px 16px; border-radius: 4px; text-decoration: none;
                   margin-right: 8px; font-size: 14px; }}
            .btn {{ background: #0066cc; color: white; }}
            .btn:hover {{ background: #0052a3; }}
            .btn-secondary {{ background: #6c757d; }}
            .btn-secondary:hover {{ background: #5a6268; }}
            .info {{ background: #e7f3ff; padding: 15px; border-radius: 8px; margin-top: 20px; }}
            code {{ background: #eee; padding: 2px 6px; border-radius: 3px; }}
        </style>
    </head>
    <body>
        <h1>Schwab OAuth Server</h1>
        {apps_html}
        <div class="info">
            <strong>Callback URL:</strong> <code>{cfg['callback_url']}</code>
        </div>
    </body>
    </html>
    """


@app.route("/login/<app_name>")
def login(app_name: str):
    """Start OAuth flow for an app."""
    if app_name not in config.VALID_APPS:
        return jsonify({"error": f"Invalid app. Must be one of: {config.VALID_APPS}"}), 400

    app_config = config.get_app_config(app_name)

    params = {
        "client_id": app_config["client_id"],
        "redirect_uri": app_config["callback_url"],
        "state": app_name,
    }

    auth_url = f"{SCHWAB_AUTH_URL}?{urlencode(params)}"
    print(f"\n  Starting OAuth for '{app_name}'")
    print(f"  Redirecting to: {auth_url[:80]}...")

    return redirect(auth_url)


@app.route("/callback")
def callback():
    """Handle OAuth callback."""
    code = request.args.get("code")
    state = request.args.get("state")
    error = request.args.get("error")

    if error:
        return jsonify({"error": error, "description": request.args.get("error_description")}), 400

    if not code:
        return jsonify({"error": "Missing authorization code"}), 400

    # Require a valid state — silent fallback to "market" could let a trading-app
    # auth code overwrite market tokens if state is tampered or absent.
    if not state or state not in config.VALID_APPS:
        return jsonify({
            "error": "Invalid or missing OAuth state parameter",
            "expected": list(config.VALID_APPS),
            "got": state,
        }), 400
    app_name = state
    print(f"\n  Received callback for '{app_name}'")

    app_config = config.get_app_config(app_name)

    headers = {
        "Authorization": get_basic_auth(app_config["client_id"], app_config["client_secret"]),
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": app_config["callback_url"],
    }

    resp = httpx.post(SCHWAB_TOKEN_URL, headers=headers, data=data)

    if resp.status_code == 200:
        tokens = resp.json()
        save_tokens(app_name, tokens)
        record_full_auth(app_name)

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Success</title>
            <style>
                body {{ font-family: -apple-system, sans-serif; max-width: 600px; margin: 50px auto;
                       padding: 20px; text-align: center; }}
                .success {{ color: #28a745; font-size: 64px; }}
            </style>
        </head>
        <body>
            <div class="success">✓</div>
            <h1>{app_name.title()} App Authenticated</h1>
            <p>Tokens saved. You can close this window.</p>
            <p><a href="/">← Back</a></p>
        </body>
        </html>
        """
    else:
        print(f"  Token exchange failed: {resp.status_code}")
        print(f"  {resp.text}")
        return jsonify({"error": "Token exchange failed", "details": resp.text}), 500


@app.route("/refresh/<app_name>")
def refresh(app_name: str):
    """Refresh tokens for an app."""
    result = refresh_tokens(app_name)
    status_code = 200 if result.get("status") == "success" else 400
    return jsonify(result), status_code


def refresh_tokens(app_name: str) -> dict:
    """Refresh tokens for an app without requiring the Flask request path."""
    if app_name not in config.VALID_APPS:
        return {"status": "error", "app": app_name, "error": f"Invalid app. Must be one of: {config.VALID_APPS}"}

    if remote_authority.remote_enabled():
        return remote_authority.refresh_on_authority(app_name)

    tokens = load_tokens(app_name)
    if not tokens or not tokens.get("refresh_token"):
        return {"status": "error", "app": app_name, "error": "No refresh token. Please authenticate first."}

    app_config = config.get_app_config(app_name)

    headers = {
        "Authorization": get_basic_auth(app_config["client_id"], app_config["client_secret"]),
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {
        "grant_type": "refresh_token",
        "refresh_token": tokens["refresh_token"],
    }

    resp = httpx.post(SCHWAB_TOKEN_URL, headers=headers, data=data)

    if resp.status_code == 200:
        new_tokens = resp.json()
        # creation_timestamp tracks the latest token issuance so access-token
        # expiry math stays correct. The 7-day refresh window is tracked
        # separately in auth_meta.json (written only on full OAuth login) —
        # Schwab does not extend the refresh window on refresh, even when the
        # response echoes a refresh_token.
        if not new_tokens.get("refresh_token"):
            new_tokens["refresh_token"] = tokens["refresh_token"]
        save_tokens(app_name, new_tokens, creation_timestamp=int(time.time()))
        return {"status": "success", "app": app_name, "expires_in": new_tokens.get("expires_in")}
    return {"status": "error", "app": app_name, "error": "Refresh failed", "details": resp.text}


@app.route("/status")
def status():
    """Return status of all apps as JSON."""
    cfg = config.load_config()
    result = {
        "callback_url": cfg["callback_url"],
        "apps": {},
    }

    for app_name in config.VALID_APPS:
        result["apps"][app_name] = get_token_status(app_name)
        result["apps"][app_name]["client_id_set"] = bool(
            cfg["apps"].get(app_name, {}).get("client_id")
        )

    return jsonify(result)


def main():
    parser = argparse.ArgumentParser(description="Schwab OAuth Server")
    parser.add_argument("--port", type=int, default=8000, help="Port to run on")
    args = parser.parse_args()

    print("=" * 50)
    print("Schwab OAuth Server")
    print("=" * 50)

    cfg = config.load_config()
    print(f"\nCallback URL: {cfg['callback_url']}")

    for app_name in config.VALID_APPS:
        st = get_token_status(app_name)
        icon = "✓" if st["valid"] else "✗"
        print(f"  {icon} {app_name}: {st['status']}")

    print(f"\nServer: http://localhost:{args.port}")
    print("=" * 50)

    # Bind to localhost only — expose via SSH tunnel (see CLAUDE.md OAuth Flow).
    # 0.0.0.0 would put /refresh/<app> on every network interface during auth.
    app.run(host="127.0.0.1", port=args.port, debug=False)


def refresh_main():
    """CLI entry point for cron/systemd/launchd token keepalive."""
    parser = argparse.ArgumentParser(description="Refresh Schwab OAuth tokens")
    parser.add_argument(
        "--app",
        choices=[*config.VALID_APPS, "all"],
        default="all",
        help="App to refresh (default: all)",
    )
    args = parser.parse_args()

    apps = list(config.VALID_APPS) if args.app == "all" else [args.app]
    ok = True
    for app_name in apps:
        result = refresh_tokens(app_name)
        if result.get("status") == "success":
            print(f"{app_name}: refreshed ({result.get('expires_in')}s access token)")
        else:
            ok = False
            print(f"{app_name}: refresh failed - {result.get('error')}")
            if result.get("details"):
                print(result["details"])
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
