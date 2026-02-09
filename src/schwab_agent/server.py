"""
Schwab OAuth Server
-------------------
Handles OAuth authentication with Schwab's API.

Usage:
    uv run schwab-auth [--port PORT]

Then visit http://localhost:8000 to authenticate.
"""

import json
import time
import base64
import argparse
from datetime import datetime
from urllib.parse import urlencode
from flask import Flask, request, redirect, jsonify
import httpx

from . import config

flask_app = Flask(__name__)

SCHWAB_AUTH_URL = "https://api.schwabapi.com/v1/oauth/authorize"
SCHWAB_TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"


def load_tokens() -> dict | None:
    token_path = config.get_token_path()
    if not token_path.exists():
        return None
    with open(token_path) as f:
        data = json.load(f)
        return data.get("token", data)


def load_tokens_raw() -> dict | None:
    token_path = config.get_token_path()
    if not token_path.exists():
        return None
    with open(token_path) as f:
        return json.load(f)


def save_tokens(tokens: dict):
    """Save tokens in schwab-py compatible format."""
    token_path = config.get_token_path()
    tokens["creation_timestamp"] = int(time.time())
    with open(token_path, "w") as f:
        json.dump(tokens, f, indent=2)
    print(f"  Tokens saved to {token_path.resolve()}")


def get_basic_auth(client_id: str, client_secret: str) -> str:
    credentials = f"{client_id}:{client_secret}"
    encoded = base64.b64encode(credentials.encode()).decode()
    return f"Basic {encoded}"


def get_token_status() -> dict:
    tokens = load_tokens()
    raw = load_tokens_raw()

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


@flask_app.route("/")
def home():
    cfg = config.load_config()
    status = get_token_status()

    status_icon = {
        "valid": "&#x1f7e2;",
        "needs_refresh": "&#x1f7e1;",
        "refresh_expired": "&#x1f534;",
        "missing": "&#x26aa;",
        "unknown_expiry": "&#x1f7e2;",
    }.get(status["status"], "?")

    status_text = {
        "valid": f"Valid until {status.get('access_expires', 'N/A')[:19]}",
        "needs_refresh": "Access expired, will auto-refresh on next use",
        "refresh_expired": "Expired - re-authentication required",
        "missing": "Not authenticated yet",
        "unknown_expiry": "Authenticated (unknown expiry)",
    }.get(status["status"], status["status"])

    refresh_expires = status.get("refresh_expires", "N/A")
    refresh_text = f"<p class='detail'>Refresh token expires: {refresh_expires[:19]}</p>" if refresh_expires != "N/A" else ""

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Schwab OAuth</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                   max-width: 600px; margin: 50px auto; padding: 20px; background: #f5f5f5; }}
            h1 {{ color: #333; }}
            .card {{ background: white; padding: 20px; border-radius: 8px; margin: 15px 0;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
            .status {{ color: #666; font-size: 14px; }}
            .detail {{ color: #999; font-size: 12px; margin-top: 4px; }}
            .btn {{ display: inline-block; padding: 10px 20px; border-radius: 4px; text-decoration: none;
                   margin-right: 8px; font-size: 14px; color: white; }}
            .btn-primary {{ background: #0066cc; }}
            .btn-primary:hover {{ background: #0052a3; }}
            .btn-secondary {{ background: #6c757d; }}
            .btn-secondary:hover {{ background: #5a6268; }}
            .info {{ background: #e7f3ff; padding: 15px; border-radius: 8px; margin-top: 20px; font-size: 14px; }}
            code {{ background: #eee; padding: 2px 6px; border-radius: 3px; }}
        </style>
    </head>
    <body>
        <h1>Schwab OAuth</h1>
        <div class="card">
            <h3>{status_icon} Authentication Status</h3>
            <p class="status">{status_text}</p>
            {refresh_text}
            <br>
            <a href="/login" class="btn btn-primary">Authenticate</a>
            <a href="/refresh" class="btn btn-secondary">Refresh Token</a>
        </div>
        <div class="info">
            <strong>Callback URL:</strong> <code>{cfg['callback_url']}</code>
        </div>
    </body>
    </html>
    """


@flask_app.route("/login")
def login():
    cfg = config.load_config()
    params = {
        "client_id": cfg["client_id"],
        "redirect_uri": cfg["callback_url"],
    }
    auth_url = f"{SCHWAB_AUTH_URL}?{urlencode(params)}"
    print(f"\n  Starting OAuth flow")
    print(f"  Redirecting to: {auth_url[:80]}...")
    return redirect(auth_url)


@flask_app.route("/callback")
def callback():
    code = request.args.get("code")
    error = request.args.get("error")

    if error:
        return jsonify({"error": error, "description": request.args.get("error_description")}), 400
    if not code:
        return jsonify({"error": "Missing authorization code"}), 400

    print(f"\n  Received callback with authorization code")
    cfg = config.load_config()

    headers = {
        "Authorization": get_basic_auth(cfg["client_id"], cfg["client_secret"]),
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": cfg["callback_url"],
    }

    resp = httpx.post(SCHWAB_TOKEN_URL, headers=headers, data=data)

    if resp.status_code == 200:
        tokens = resp.json()
        save_tokens(tokens)
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Success</title>
            <style>
                body { font-family: -apple-system, sans-serif; max-width: 600px; margin: 50px auto;
                       padding: 20px; text-align: center; }
                .success { color: #28a745; font-size: 64px; }
            </style>
        </head>
        <body>
            <div class="success">&#x2713;</div>
            <h1>Authenticated Successfully</h1>
            <p>Tokens saved. You can close this window.</p>
            <p><a href="/">&#8592; Back</a></p>
        </body>
        </html>
        """
    else:
        print(f"  Token exchange failed: {resp.status_code}")
        print(f"  {resp.text}")
        return jsonify({"error": "Token exchange failed", "details": resp.text}), 500


@flask_app.route("/refresh")
def refresh():
    tokens = load_tokens()
    if not tokens or not tokens.get("refresh_token"):
        return jsonify({"error": "No refresh token. Please authenticate first."}), 400

    cfg = config.load_config()
    headers = {
        "Authorization": get_basic_auth(cfg["client_id"], cfg["client_secret"]),
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {
        "grant_type": "refresh_token",
        "refresh_token": tokens["refresh_token"],
    }

    resp = httpx.post(SCHWAB_TOKEN_URL, headers=headers, data=data)

    if resp.status_code == 200:
        new_tokens = resp.json()
        save_tokens(new_tokens)
        return jsonify({"status": "success", "expires_in": new_tokens.get("expires_in")})
    else:
        return jsonify({"error": "Refresh failed", "details": resp.text}), 500


@flask_app.route("/status")
def status():
    cfg = config.load_config()
    return jsonify({"callback_url": cfg["callback_url"], **get_token_status()})


def main():
    parser = argparse.ArgumentParser(description="Schwab OAuth Server")
    parser.add_argument("--port", type=int, default=8000, help="Port to run on")
    args = parser.parse_args()

    print("=" * 50)
    print("Schwab OAuth Server")
    print("=" * 50)

    cfg = config.load_config()
    print(f"\nCallback URL: {cfg['callback_url']}")

    tok_status = get_token_status()
    icon = "OK" if tok_status["valid"] else "EXPIRED" if tok_status["exists"] else "MISSING"
    print(f"  Token status: {icon} ({tok_status['status']})")

    print(f"\nServer: http://localhost:{args.port}")
    print("=" * 50)

    flask_app.run(host="0.0.0.0", port=args.port, debug=False)
