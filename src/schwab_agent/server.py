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
import time
import base64
import argparse
from datetime import datetime
from urllib.parse import urlencode

import httpx
from flask import Flask, request, redirect, jsonify

from . import config

app = Flask(__name__)

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


def save_tokens(app_name: str, tokens: dict):
    """Save tokens in schwab-py compatible format with creation_timestamp."""
    tokens["creation_timestamp"] = int(time.time())
    path = config.get_token_path(app_name)
    with open(path, "w") as f:
        json.dump(tokens, f, indent=2)
    print(f"  Tokens saved to {path}")


def get_basic_auth(client_id: str, client_secret: str) -> str:
    """Create Basic Auth header value."""
    credentials = f"{client_id}:{client_secret}"
    encoded = base64.b64encode(credentials.encode()).decode()
    return f"Basic {encoded}"


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
        refresh_expires = datetime.fromtimestamp(created + 7 * 24 * 3600)

        if datetime.now() > refresh_expires:
            return {"exists": True, "valid": False, "status": "refresh_expired"}
        elif datetime.now() > access_expires:
            return {"exists": True, "valid": True, "status": "needs_refresh"}
        else:
            return {
                "exists": True,
                "valid": True,
                "status": "valid",
                "access_expires": access_expires.isoformat(),
                "refresh_expires": refresh_expires.isoformat(),
            }

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

    app_name = state if state in config.VALID_APPS else "market"
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
    if app_name not in config.VALID_APPS:
        return jsonify({"error": f"Invalid app. Must be one of: {config.VALID_APPS}"}), 400

    tokens = load_tokens(app_name)
    if not tokens or not tokens.get("refresh_token"):
        return jsonify({"error": "No refresh token. Please authenticate first."}), 400

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
        save_tokens(app_name, new_tokens)
        return jsonify({"status": "success", "app": app_name, "expires_in": new_tokens.get("expires_in")})
    else:
        return jsonify({"error": "Refresh failed", "details": resp.text}), 500


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

    app.run(host="0.0.0.0", port=args.port, debug=False)


if __name__ == "__main__":
    main()
