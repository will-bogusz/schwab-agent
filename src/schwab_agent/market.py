"""Normalized Schwab market-data helpers."""

from __future__ import annotations

import json
import math
import os
from datetime import datetime, time as dtime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def now_et() -> datetime:
    return datetime.now(ET)


def ms_to_iso(value: Any) -> str | None:
    if value in (None, 0, ""):
        return None
    try:
        return datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc).astimezone(ET).isoformat()
    except Exception:
        return None


def age_seconds(value: Any) -> float | None:
    if value in (None, 0, ""):
        return None
    try:
        ts = float(value) / 1000
        return max(0.0, datetime.now(timezone.utc).timestamp() - ts)
    except Exception:
        return None


def is_us_plain_symbol(symbol: str) -> bool:
    s = symbol.upper()
    return bool(s) and "." not in s and " " not in s and not s.isdigit()


def _num(*values):
    for value in values:
        if value is None:
            continue
        try:
            if isinstance(value, float) and math.isnan(value):
                continue
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _int(*values):
    n = _num(*values)
    return int(n) if n is not None else None


def _pct(change: float | None, prev: float | None) -> float | None:
    if change is None or not prev:
        return None
    return change / prev * 100


def infer_session_label(quote: dict, regular: dict, extended: dict) -> str:
    """Return REG, PM, AH, or STALE for the best available Schwab mark."""
    now = now_et()
    q_age = age_seconds(
        extended.get("tradeTime") or quote.get("tradeTime") or regular.get("regularMarketTradeTime")
    )
    if q_age is not None and q_age > 18 * 3600:
        return "STALE"

    ext_price = _num(extended.get("lastPrice"), extended.get("mark"))
    ext_time = _num(extended.get("tradeTime"))
    reg_time = _num(regular.get("regularMarketTradeTime"), quote.get("regularMarketTradeTime"))
    if ext_price is not None and ext_time and (not reg_time or ext_time > reg_time):
        if now.time() < dtime(9, 30):
            return "PM"
        if now.time() >= dtime(16, 0):
            return "AH"
        return "EXT"
    return "REG"


def normalize_quote(symbol: str, payload: dict, source: str = "schwab") -> dict:
    quote = payload.get("quote") or payload
    regular = payload.get("regular") or {}
    extended = payload.get("extended") or {}
    reference = payload.get("reference") or {}
    fundamental = payload.get("fundamental") or {}

    regular_last = _num(
        regular.get("regularMarketLastPrice"),
        quote.get("regularMarketLastPrice"),
        quote.get("lastPrice"),
    )
    extended_last = _num(extended.get("lastPrice"), extended.get("mark"))
    session = infer_session_label(quote, regular, extended)

    if session in {"PM", "AH", "EXT"} and extended_last is not None:
        best_price = extended_last
    else:
        best_price = _num(quote.get("mark"), regular_last, quote.get("lastPrice"))

    previous_close = _num(
        quote.get("closePrice"),
        regular.get("regularMarketPreviousClose"),
        fundamental.get("previousClose"),
    )
    change = _num(
        quote.get("netChange"),
        regular.get("regularMarketNetChange"),
        None if best_price is None or previous_close is None else best_price - previous_close,
    )
    change_pct = _num(
        quote.get("netPercentChange"),
        quote.get("markPercentChange"),
        regular.get("regularMarketPercentChange"),
        _pct(change, previous_close),
    )
    bid = _num(quote.get("bidPrice"))
    ask = _num(quote.get("askPrice"))
    spread = (ask - bid) if bid is not None and ask is not None else None
    mid = ((bid + ask) / 2) if bid is not None and ask is not None else None

    best_time = (
        extended.get("tradeTime")
        if session in {"PM", "AH", "EXT"} and extended.get("tradeTime")
        else quote.get("tradeTime") or regular.get("regularMarketTradeTime")
    )

    return {
        "symbol": symbol,
        "description": reference.get("description"),
        "asset_type": reference.get("assetType"),
        "exchange": reference.get("exchangeName") or reference.get("exchange"),
        "source": source,
        "session": session,
        "price": best_price,
        "regular_price": regular_last,
        "extended_price": extended_last,
        "previous_close": previous_close,
        "change": change,
        "change_pct": change_pct,
        "bid": bid,
        "ask": ask,
        "bid_size": _int(quote.get("bidSize")),
        "ask_size": _int(quote.get("askSize")),
        "mid": mid,
        "spread": spread,
        "spread_pct": (spread / mid * 100) if spread is not None and mid else None,
        "open": _num(quote.get("openPrice"), regular.get("regularMarketOpen")),
        "high": _num(quote.get("highPrice"), regular.get("regularMarketDayHigh")),
        "low": _num(quote.get("lowPrice"), regular.get("regularMarketDayLow")),
        "volume": _int(quote.get("totalVolume"), regular.get("regularMarketVolume")),
        "trade_time": ms_to_iso(best_time),
        "quote_time": ms_to_iso(quote.get("quoteTime")),
        "age_seconds": age_seconds(best_time or quote.get("quoteTime")),
        "stale": session == "STALE",
        "reference": reference,
        "fundamental": fundamental,
        "raw": payload,
    }


def normalize_stream_equity(symbol: str, item: dict, source: str = "schwab-stream") -> dict:
    """Normalize level-one streaming fields into the quote model subset."""
    bid = _num(item.get("BID_PRICE"))
    ask = _num(item.get("ASK_PRICE"))
    mark = _num(item.get("MARK"), item.get("LAST_PRICE"))
    close = _num(item.get("CLOSE_PRICE"))
    change = _num(item.get("NET_CHANGE"))
    mid = ((bid + ask) / 2) if bid is not None and ask is not None else None
    spread = (ask - bid) if bid is not None and ask is not None else None
    trade_time = item.get("TRADE_TIME_MILLIS") or item.get("REGULAR_MARKET_TRADE_MILLIS")
    return {
        "symbol": symbol,
        "description": item.get("DESCRIPTION"),
        "asset_type": "EQUITY",
        "exchange": item.get("EXCHANGE_NAME"),
        "source": source,
        "session": "REG",
        "price": mark,
        "regular_price": _num(item.get("REGULAR_MARKET_LAST_PRICE"), mark),
        "extended_price": None,
        "previous_close": close,
        "change": change,
        "change_pct": _num(item.get("NET_CHANGE_PERCENT"), item.get("REGULAR_MARKET_CHANGE_PERCENT"), _pct(change, close)),
        "bid": bid,
        "ask": ask,
        "bid_size": _int(item.get("BID_SIZE")),
        "ask_size": _int(item.get("ASK_SIZE")),
        "mid": mid,
        "spread": spread,
        "spread_pct": (spread / mid * 100) if spread is not None and mid else None,
        "open": _num(item.get("OPEN_PRICE")),
        "high": _num(item.get("HIGH_PRICE")),
        "low": _num(item.get("LOW_PRICE")),
        "volume": _int(item.get("TOTAL_VOLUME")),
        "trade_time": ms_to_iso(trade_time),
        "quote_time": ms_to_iso(item.get("QUOTE_TIME_MILLIS")),
        "age_seconds": age_seconds(trade_time or item.get("QUOTE_TIME_MILLIS")),
        "stale": False,
        "reference": {},
        "fundamental": {},
        "raw": item,
    }


def format_price(value: float | None, currency: str = "USD") -> str:
    if value is None:
        return "--"
    prefix = {"USD": "$", "CAD": "C$", "EUR": "EUR ", "KRW": "KRW "}.get(currency, "$")
    if abs(value) < 1:
        return f"{prefix}{value:,.4f}"
    return f"{prefix}{value:,.2f}"


def format_pct(value: float | None) -> str:
    if value is None:
        return "--"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f}%"


def format_age(seconds: float | None) -> str:
    if seconds is None:
        return "--"
    if seconds < 90:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds // 60)}m"
    return f"{seconds / 3600:.1f}h"


def normalized_quote_rows(quotes: dict[str, dict]) -> list[list[str]]:
    rows = []
    for symbol, data in quotes.items():
        rows.append([
            symbol,
            data.get("session") or "--",
            format_price(data.get("price")),
            format_pct(data.get("change_pct")),
            f"{format_price(data.get('bid'))}/{format_price(data.get('ask'))}",
            format_pct(data.get("spread_pct")),
            f"{data.get('volume'):,}" if data.get("volume") is not None else "--",
            format_age(data.get("age_seconds")),
            data.get("source", "schwab"),
        ])
    return rows


def cache_dir(default_root: Path | None = None) -> Path:
    raw = os.environ.get("SCHWAB_LIVE_CACHE_DIR")
    if raw:
        return Path(raw).expanduser()
    root = default_root or Path.cwd().parent
    return root / "artifacts" / "schwab" / "live"


def read_cached_quotes(symbols: list[str], max_age_seconds: int = 10, root: Path | None = None) -> dict[str, dict]:
    path = cache_dir(root) / "quotes.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except Exception:
        return {}
    generated_at = data.get("generated_at_epoch")
    if not generated_at:
        return {}
    try:
        if datetime.now(timezone.utc).timestamp() - float(generated_at) > max_age_seconds:
            return {}
    except Exception:
        return {}
    quotes = data.get("quotes") or {}
    return {s: quotes[s] for s in symbols if s in quotes}


def write_json_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True, default=str))
    tmp.replace(path)
