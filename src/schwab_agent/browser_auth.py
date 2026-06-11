#!/usr/bin/env python3
"""
Browser-backed Schwab OAuth fallback.

Normal operation should use refresh tokens. This module is the fallback for
times Schwab forces a fresh login/consent flow. Credentials are loaded from a
chmod-600 env file and are never printed.
"""

from __future__ import annotations

import argparse
import getpass
import os
import re
import shlex
import stat
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

from . import config
from . import remote_authority
from .server import SCHWAB_AUTH_URL, get_auth_timestamp, get_token_status, refresh_tokens

EnvMap = dict[str, str]

# Schwab refresh tokens hard-expire 7 days after full OAuth login. Re-login
# proactively once the token is this old so the cliff is never reached.
REAUTH_AFTER_DAYS = 5.0

# Playwright's headless UA advertises HeadlessChrome, which Schwab's bot
# detection can reject before the login form ever renders.
DESKTOP_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _config_dir_or_home() -> Path:
    try:
        return config.find_config_dir()
    except FileNotFoundError:
        return Path.home() / ".config" / "schwab-agent"


def default_secrets_path() -> Path:
    env_path = os.environ.get("SCHWAB_LOGIN_ENV")
    if env_path:
        return Path(env_path).expanduser()
    return _config_dir_or_home() / "secrets" / "schwab-login.env"


def default_profile_dir() -> Path:
    env_path = os.environ.get("SCHWAB_BROWSER_PROFILE_DIR")
    if env_path:
        return Path(env_path).expanduser()
    return _config_dir_or_home() / ".auth" / "playwright-profile"


def quote_env_value(value: str) -> str:
    return shlex.quote(value)


def write_secrets(path: Path) -> None:
    """Prompt for Schwab credentials and write a private env file."""
    path = path.expanduser()
    username = input("Schwab username: ").strip()
    password = getpass.getpass("Schwab password (hidden): ")

    if not username or not password:
        raise SystemExit("Username and password are required; no file written.")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    content = (
        "# Schwab login fallback credentials.\n"
        "# Created by schwab-secrets; values are intentionally not echoed.\n"
        f"SCHWAB_USERNAME={quote_env_value(username)}\n"
        f"SCHWAB_PASSWORD={quote_env_value(password)}\n"
    )
    path.write_text(content)
    path.chmod(0o600)
    print(f"Wrote {path}")
    print("Mode: 600")
    print("SCHWAB_USERNAME: set")
    print("SCHWAB_PASSWORD: set")


def load_env_file(path: Path) -> EnvMap:
    """Load KEY=value lines from a private env file."""
    path = path.expanduser()
    if not path.exists():
        raise FileNotFoundError(f"Secret file not found: {path}")

    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise PermissionError(f"Secret file must not be group/world accessible: {path} mode {mode:o}")

    result: EnvMap = {}
    for line_no, raw_line in enumerate(path.read_text().splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"Invalid env line {line_no} in {path}")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise ValueError(f"Invalid env key on line {line_no}: {key}")
        if value:
            parts = shlex.split(value, comments=False, posix=True)
            result[key] = parts[0] if parts else ""
        else:
            result[key] = ""
    return result


def load_credentials(path: Path) -> tuple[str, str]:
    env_values = {**os.environ, **load_env_file(path)}
    username = env_values.get("SCHWAB_USERNAME", "")
    password = env_values.get("SCHWAB_PASSWORD", "")
    if not username or not password:
        raise ValueError(f"{path} must define SCHWAB_USERNAME and SCHWAB_PASSWORD")
    return username, password


def build_auth_url(app_name: str) -> str:
    app_config = config.get_app_config(app_name)
    params = {
        "client_id": app_config["client_id"],
        "redirect_uri": app_config["callback_url"],
        "state": app_name,
    }
    return f"{SCHWAB_AUTH_URL}?{urlencode(params)}"


def _frames(page: Page):
    """Main frame plus child frames — Schwab renders login inside an iframe
    on some flow variants, so every lookup must scan all frames."""
    try:
        return [f for f in page.frames if not f.is_detached()]
    except Exception:
        return [page.main_frame]


def _first_visible(page: Page, selectors: list[str]):
    for frame in _frames(page):
        for selector in selectors:
            try:
                loc = frame.locator(selector).first
                if loc.count() and loc.is_visible(timeout=750):
                    return loc
            except Exception:
                continue
    return None


def _fill_first_visible(page: Page, selectors: list[str], value: str) -> bool:
    loc = _first_visible(page, selectors)
    if not loc:
        return False
    loc.fill(value)
    return True


def _click_first_visible(page: Page, selectors: list[str], timeout_ms: int = 1_000) -> bool:
    for frame in _frames(page):
        for selector in selectors:
            try:
                loc = frame.locator(selector).first
                if loc.count() and loc.is_visible(timeout=timeout_ms):
                    loc.click()
                    return True
            except Exception:
                continue
    return False


def _click_role_button(page: Page, names: list[str], timeout_ms: int = 1_000) -> bool:
    for frame in _frames(page):
        for name in names:
            try:
                loc = frame.get_by_role("button", name=re.compile(name, re.I)).first
                if loc.count() and loc.is_visible(timeout=timeout_ms):
                    loc.click()
                    return True
            except Exception:
                continue
    return False


def _looks_authenticated(page: Page) -> bool:
    # The success page is served by our own OAuth server at /callback.
    try:
        if "/callback" in (page.url or "") and "code=" in page.url:
            return True
    except Exception:
        pass
    try:
        return page.get_by_text(re.compile(r"(App Authenticated|Tokens saved|Authenticated)", re.I)).first.is_visible(
            timeout=500
        )
    except Exception:
        return False


def debug_dir() -> Path:
    return default_profile_dir().parent / "debug"


def _capture_debug(page: Page, app_name: str, reason: str) -> None:
    """Persist screenshot + URL + HTML so a failed headless run is diagnosable."""
    try:
        out = debug_dir()
        out.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        base = out / f"{app_name}_{reason}_{stamp}"
        page.screenshot(path=str(base.with_suffix(".png")), full_page=True)
        info = [f"url: {page.url}", f"title: {page.title()}", ""]
        for frame in _frames(page):
            info.append(f"frame: {frame.url}")
        base.with_suffix(".txt").write_text("\n".join(info) + "\n\n" + page.content()[:50_000])
        print(f"{app_name}: debug capture -> {base}.png/.txt")
    except Exception as exc:
        print(f"{app_name}: debug capture failed: {exc}")


def _maybe_fill_login(page: Page, username: str, password: str) -> bool:
    user_filled = _fill_first_visible(
        page,
        [
            "input[autocomplete='username']",
            "input[name='username']",
            "input[name='loginId']",
            "input[id='loginId']",
            "input[id*='user']",
            "input[id*='login']",
            "input[type='email']",
            "input[type='text']",
        ],
        username,
    )
    password_filled = _fill_first_visible(
        page,
        [
            "input[autocomplete='current-password']",
            "input[name='password']",
            "input[id='password']",
            "input[id*='pass']",
            "input[type='password']",
        ],
        password,
    )
    if not (user_filled or password_filled):
        return False
    _click_role_button(page, ["log in", "sign in", "continue", "submit", "next"]) or _click_first_visible(
        page,
        [
            "button[type='submit']",
            "input[type='submit']",
            "button:has-text('Log in')",
            "button:has-text('Sign in')",
            "button:has-text('Continue')",
        ],
    )
    return True


def _maybe_accept_consent(page: Page) -> bool:
    clicked = False
    checkbox_selectors = [
        "input[type='checkbox']",
        "[role='checkbox']",
    ]
    for selector in checkbox_selectors:
        locators = page.locator(selector)
        try:
            for i in range(min(locators.count(), 10)):
                loc = locators.nth(i)
                if loc.is_visible(timeout=250):
                    checked = loc.is_checked() if selector == "input[type='checkbox']" else False
                    if not checked:
                        loc.click()
                        clicked = True
        except PlaywrightTimeoutError:
            continue

    button_clicked = _click_role_button(
        page,
        ["accept", "agree", "authorize", "allow", "continue", "submit", "done", "yes"],
        timeout_ms=750,
    ) or _click_first_visible(
        page,
        [
            "button:has-text('Accept')",
            "button:has-text('Agree')",
            "button:has-text('Authorize')",
            "button:has-text('Allow')",
            "button:has-text('Continue')",
            "button:has-text('Submit')",
            "button[type='submit']",
        ],
        timeout_ms=750,
    )
    return clicked or button_clicked


def _mfa_visible(page: Page) -> bool:
    selectors = [
        "input[name*='otp']",
        "input[id*='otp']",
        "input[name*='code']",
        "input[id*='code']",
        "input[autocomplete='one-time-code']",
        "text=/verification code/i",
        "text=/multi-factor/i",
        "text=/security code/i",
    ]
    return _first_visible(page, selectors) is not None


def _maybe_fill_mfa(page: Page, code: str | None) -> bool:
    if not code:
        return False
    if not _fill_first_visible(
        page,
        [
            "input[autocomplete='one-time-code']",
            "input[name*='otp']",
            "input[id*='otp']",
            "input[name*='code']",
            "input[id*='code']",
            "input[type='tel']",
            "input[type='text']",
        ],
        code,
    ):
        return False
    _click_role_button(page, ["verify", "submit", "continue", "next"]) or _click_first_visible(
        page, ["button[type='submit']", "button:has-text('Verify')", "button:has-text('Continue')"]
    )
    return True


def authenticate_app(
    app_name: str,
    secrets_path: Path,
    profile_dir: Path,
    headless: bool,
    timeout_seconds: int,
    mfa_code: str | None = None,
) -> bool:
    """Authenticate one Schwab app through a persistent browser profile."""
    if app_name not in config.VALID_APPS:
        raise ValueError(f"Invalid app '{app_name}'. Must be one of: {config.VALID_APPS}")

    username, password = load_credentials(secrets_path)
    profile_dir = profile_dir.expanduser()
    profile_dir.mkdir(parents=True, exist_ok=True)

    deadline = time.monotonic() + timeout_seconds
    auth_url = build_auth_url(app_name)

    print(f"{app_name}: starting browser OAuth fallback")
    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(
            str(profile_dir),
            headless=headless,
            viewport={"width": 1280, "height": 900},
            user_agent=DESKTOP_UA if headless else None,
            args=["--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
        )
        page = browser.pages[0] if browser.pages else browser.new_page()
        page.goto(auth_url, wait_until="domcontentloaded")

        while time.monotonic() < deadline:
            if _looks_authenticated(page):
                # Give the callback page a moment to finish the token exchange.
                try:
                    page.wait_for_load_state("networkidle", timeout=10_000)
                except PlaywrightTimeoutError:
                    pass
                browser.close()
                if remote_authority.remote_enabled():
                    synced = remote_authority.sync_from_authority(app_name)
                    if synced.get("status") != "success":
                        print(f"{app_name}: authenticated on authority, but local token sync failed: {synced.get('error')}")
                        return False
                print(f"{app_name}: authenticated")
                return True

            _maybe_fill_login(page, username, password)
            if _mfa_visible(page):
                if _maybe_fill_mfa(page, mfa_code or os.environ.get("SCHWAB_MFA_CODE")):
                    page.wait_for_load_state("domcontentloaded", timeout=10_000)
                elif headless:
                    _capture_debug(page, app_name, "mfa")
                    browser.close()
                    print(f"{app_name}: MFA required; rerun headed or provide SCHWAB_MFA_CODE.")
                    return False
                else:
                    print(f"{app_name}: MFA required; complete it in the browser window.")

            _maybe_accept_consent(page)
            try:
                page.wait_for_load_state("domcontentloaded", timeout=1_500)
            except PlaywrightTimeoutError:
                pass
            time.sleep(1)

        _capture_debug(page, app_name, "timeout")
        browser.close()
    print(f"{app_name}: browser auth timed out after {timeout_seconds}s")
    return False


def _app_list(value: str) -> list[str]:
    return list(config.VALID_APPS) if value == "all" else [value]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run browser-backed Schwab OAuth login fallback")
    parser.add_argument("--app", choices=[*config.VALID_APPS, "all"], default="all")
    parser.add_argument("--secrets", type=Path, default=default_secrets_path())
    parser.add_argument("--profile-dir", type=Path, default=default_profile_dir())
    parser.add_argument("--timeout", type=int, default=180, help="Timeout per app in seconds")
    parser.add_argument("--mfa-code", help="One-time MFA code, if Schwab asks for it")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--headless", action="store_true", help="Run browser headless")
    mode.add_argument("--headed", action="store_true", help="Show browser window")
    args = parser.parse_args()

    headless = True if args.headless else False
    if args.headed:
        headless = False

    ok = True
    for app_name in _app_list(args.app):
        ok = authenticate_app(
            app_name,
            secrets_path=args.secrets,
            profile_dir=args.profile_dir,
            headless=headless,
            timeout_seconds=args.timeout,
            mfa_code=args.mfa_code,
        ) and ok
    raise SystemExit(0 if ok else 1)


def _refresh_token_age_days(app_name: str) -> float | None:
    authed = get_auth_timestamp(app_name)
    if authed:
        return (time.time() - authed) / 86400
    status = get_token_status(app_name)
    age = status.get("refresh_age_days")
    return float(age) if age is not None else None


def _write_health(results: dict[str, dict]) -> None:
    """Persist keepalive outcomes so status tooling and local CLIs can warn."""
    import json

    path = config.get_auth_health_path()
    payload = {
        "updated": int(time.time()),
        "updated_iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "apps": results,
    }
    try:
        path.write_text(json.dumps(payload, indent=2))
    except OSError as exc:
        print(f"warning: could not write {path}: {exc}")


def keepalive_main() -> None:
    parser = argparse.ArgumentParser(description="Refresh Schwab tokens, with optional browser-login fallback")
    parser.add_argument("--app", choices=[*config.VALID_APPS, "all"], default="all")
    parser.add_argument("--browser-fallback", action="store_true", help="Run browser login if refresh fails")
    parser.add_argument("--secrets", type=Path, default=default_secrets_path())
    parser.add_argument("--profile-dir", type=Path, default=default_profile_dir())
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument(
        "--reauth-after-days",
        type=float,
        default=REAUTH_AFTER_DAYS,
        help="Proactively re-login once the refresh token is this old (7-day hard expiry)",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--headless", action="store_true")
    mode.add_argument("--headed", action="store_true")
    args = parser.parse_args()

    headless = True if args.headless else False
    if args.headed:
        headless = False

    health: dict[str, dict] = {}
    need_login: list[str] = []
    for app_name in _app_list(args.app):
        result = refresh_tokens(app_name)
        age = _refresh_token_age_days(app_name)
        entry = {"refresh_token_age_days": round(age, 2) if age is not None else None}
        if result.get("status") == "success":
            print(f"{app_name}: refreshed ({result.get('expires_in')}s access token)")
            entry["refresh"] = "ok"
            # Refreshing works today, but the 7-day window is finite —
            # re-login proactively instead of waiting for the cliff.
            if args.browser_fallback and age is not None and age >= args.reauth_after_days:
                print(f"{app_name}: refresh token is {age:.1f}d old; proactive re-login")
                need_login.append(app_name)
        else:
            print(f"{app_name}: refresh failed - {result.get('error')}")
            entry["refresh"] = "failed"
            entry["error"] = str(result.get("error"))
            need_login.append(app_name)
        health[app_name] = entry

    if not need_login:
        _write_health(health)
        raise SystemExit(0)

    if not args.browser_fallback:
        _write_health(health)
        raise SystemExit(1)

    ok = True
    for app_name in need_login:
        success = authenticate_app(
            app_name,
            secrets_path=args.secrets,
            profile_dir=args.profile_dir,
            headless=headless,
            timeout_seconds=args.timeout,
        )
        health[app_name]["browser_auth"] = "ok" if success else "failed"
        if success:
            health[app_name]["refresh_token_age_days"] = 0.0
        ok = success and ok

    _write_health(health)
    raise SystemExit(0 if ok else 1)


def secrets_main() -> None:
    parser = argparse.ArgumentParser(description="Manage Schwab browser-login secret file")
    sub = parser.add_subparsers(dest="command", required=True)
    write = sub.add_parser("write", help="Prompt for credentials and write a chmod-600 env file")
    write.add_argument("--path", type=Path, default=default_secrets_path())
    show = sub.add_parser("path", help="Print the default secret path")
    show.add_argument("--path", type=Path, default=default_secrets_path())
    args = parser.parse_args()

    if args.command == "write":
        write_secrets(args.path)
    elif args.command == "path":
        print(args.path.expanduser())
    else:
        raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
