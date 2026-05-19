#!/usr/bin/env python3
"""Read-only Schwab streaming cache daemon."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from schwab.streaming import StreamClient

from .client import get_client
from .market import cache_dir, write_json_atomic


def _symbols(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [s.strip().upper() for s in raw.replace("\n", ",").split(",") if s.strip()]


def _load_watchlist(path: str | None) -> list[str]:
    if not path:
        return []
    p = Path(path).expanduser()
    if not p.exists():
        return []
    return _symbols(p.read_text())


def _field_values(enum_cls, names: list[str]):
    return [enum_cls[name] for name in names if hasattr(enum_cls, name)]


async def run_stream(args):
    client = get_client(args.app)
    stream = StreamClient(client)
    out_dir = cache_dir(Path.cwd().parent if Path.cwd().name == "schwab" else Path.cwd())

    equities = sorted(set(_symbols(args.symbols) + _load_watchlist(args.watchlist)))
    options = sorted(set(_symbols(args.options) + _load_watchlist(args.options_watchlist)))
    state = {
        "generated_at": None,
        "generated_at_epoch": None,
        "quotes": {},
        "options": {},
        "account_activity": [],
    }

    def flush():
        state["generated_at"] = datetime.now(timezone.utc).isoformat()
        state["generated_at_epoch"] = time.time()
        write_json_atomic(out_dir / "quotes.json", state)

    async def periodic_flush():
        while True:
            flush()
            await asyncio.sleep(args.flush_seconds)

    def handle_equity(msg):
        for item in msg.get("content", []):
            symbol = item.get("key") or item.get("1")
            if not symbol:
                continue
            state["quotes"][symbol] = item

    def handle_option(msg):
        for item in msg.get("content", []):
            symbol = item.get("key") or item.get("0")
            if not symbol:
                continue
            state["options"][symbol] = item

    def handle_activity(msg):
        state["account_activity"].append({
            "received_at": datetime.now(timezone.utc).isoformat(),
            "message": msg,
        })
        state["account_activity"] = state["account_activity"][-200:]

    stream.add_level_one_equity_handler(handle_equity)
    stream.add_level_one_option_handler(handle_option)
    stream.add_account_activity_handler(handle_activity)

    await stream.login()

    if equities:
        fields = _field_values(StreamClient.LevelOneEquityFields, [
            "SYMBOL", "BID_PRICE", "ASK_PRICE", "LAST_PRICE", "BID_SIZE", "ASK_SIZE",
            "TOTAL_VOLUME", "HIGH_PRICE", "LOW_PRICE", "CLOSE_PRICE", "OPEN_PRICE",
            "NET_CHANGE", "MARK", "QUOTE_TIME_MILLIS", "TRADE_TIME_MILLIS",
            "REGULAR_MARKET_LAST_PRICE", "REGULAR_MARKET_TRADE_MILLIS",
            "NET_CHANGE_PERCENT", "REGULAR_MARKET_CHANGE_PERCENT",
            "POST_MARKET_NET_CHANGE", "POST_MARKET_NET_CHANGE_PERCENT",
        ])
        await stream.level_one_equity_subs(equities, fields=fields)

    if options:
        fields = _field_values(StreamClient.LevelOneOptionFields, [
            "SYMBOL", "BID_PRICE", "ASK_PRICE", "LAST_PRICE", "TOTAL_VOLUME",
            "OPEN_INTEREST", "VOLATILITY", "DELTA", "GAMMA", "THETA", "VEGA",
            "MARK", "QUOTE_TIME_MILLIS", "TRADE_TIME_MILLIS", "UNDERLYING_PRICE",
        ])
        await stream.level_one_option_subs(options, fields=fields)

    if args.account_activity:
        await stream.account_activity_sub()

    flush()
    asyncio.create_task(periodic_flush())
    while True:
        await stream.handle_message()


def main():
    parser = argparse.ArgumentParser(description="Read-only Schwab streaming cache")
    parser.add_argument("--app", default="trading", choices=["market", "trading"])
    parser.add_argument("--symbols", help="Comma-separated equity symbols")
    parser.add_argument("--watchlist", help="File containing equity symbols")
    parser.add_argument("--options", help="Comma-separated option symbols")
    parser.add_argument("--options-watchlist", help="File containing option symbols")
    parser.add_argument("--account-activity", action="store_true", help="Subscribe to account activity")
    parser.add_argument("--flush-seconds", type=int, default=2)
    args = parser.parse_args()
    asyncio.run(run_stream(args))


if __name__ == "__main__":
    main()
