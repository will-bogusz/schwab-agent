"""Intraday technical snapshots from Schwab price history."""

from __future__ import annotations

from datetime import datetime
from statistics import fmean
from zoneinfo import ZoneInfo

from .market import normalize_quote

ET = ZoneInfo("America/New_York")


def _ema(values: list[float], span: int) -> float | None:
    if len(values) < span:
        return None
    alpha = 2 / (span + 1)
    ema = fmean(values[:span])
    for value in values[span:]:
        ema = value * alpha + ema * (1 - alpha)
    return ema


def _sma(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return fmean(values[-window:])


def _vwap(candles: list[dict]) -> float | None:
    total_dollars = 0.0
    total_volume = 0.0
    for candle in candles:
        volume = candle.get("volume") or 0
        if not volume:
            continue
        typical = ((candle.get("high") or 0) + (candle.get("low") or 0) + (candle.get("close") or 0)) / 3
        total_dollars += typical * volume
        total_volume += volume
    return total_dollars / total_volume if total_volume else None


def _parse_candles(data: dict) -> list[dict]:
    candles = []
    for candle in data.get("candles", []):
        c = dict(candle)
        dt = datetime.fromtimestamp(c["datetime"] / 1000, tz=ET)
        c["datetime_iso"] = dt.isoformat()
        c["et_time"] = dt
        candles.append(c)
    return candles


def fetch_technical_snapshot(client, symbol: str) -> dict:
    minute_kwargs = {
        "period_type": client.PriceHistory.PeriodType.DAY,
        "period": client.PriceHistory.Period.TEN_DAYS,
        "frequency_type": client.PriceHistory.FrequencyType.MINUTE,
        "frequency": client.PriceHistory.Frequency.EVERY_FIVE_MINUTES,
        "need_extended_hours_data": True,
        "need_previous_close": True,
    }
    daily_kwargs = {
        "period_type": client.PriceHistory.PeriodType.YEAR,
        "period": client.PriceHistory.Period.ONE_YEAR,
        "frequency_type": client.PriceHistory.FrequencyType.DAILY,
        "frequency": client.PriceHistory.Frequency.DAILY,
        "need_extended_hours_data": False,
        "need_previous_close": True,
    }

    minute_resp = client.get_price_history(symbol, **minute_kwargs)
    minute_resp.raise_for_status()
    daily_resp = client.get_price_history(symbol, **daily_kwargs)
    daily_resp.raise_for_status()

    minute = _parse_candles(minute_resp.json())
    daily = _parse_candles(daily_resp.json())
    closes = [float(c["close"]) for c in daily if c.get("close") is not None]
    minute_closes = [float(c["close"]) for c in minute if c.get("close") is not None]

    latest_intraday_date = minute[-1]["et_time"].date() if minute else datetime.now(ET).date()
    today_bars = [c for c in minute if c["et_time"].date() == latest_intraday_date]
    regular_bars = [
        c for c in today_bars
        if (c["et_time"].hour > 9 or (c["et_time"].hour == 9 and c["et_time"].minute >= 30))
        and c["et_time"].hour < 16
    ]
    extended_bars = today_bars

    last = minute_closes[-1] if minute_closes else (closes[-1] if closes else None)
    day_high = max((c.get("high") for c in regular_bars if c.get("high") is not None), default=None)
    day_low = min((c.get("low") for c in regular_bars if c.get("low") is not None), default=None)
    ext_high = max((c.get("high") for c in extended_bars if c.get("high") is not None), default=None)
    ext_low = min((c.get("low") for c in extended_bars if c.get("low") is not None), default=None)
    total_volume = sum(c.get("volume") or 0 for c in regular_bars)

    quote_payload = None
    try:
        quote_resp = client.get_quote(symbol, fields=[
            client.Quote.Fields.QUOTE,
            client.Quote.Fields.EXTENDED,
            client.Quote.Fields.REGULAR,
            client.Quote.Fields.REFERENCE,
        ])
        quote_resp.raise_for_status()
        raw_quote = quote_resp.json()
        quote_payload = normalize_quote(symbol, raw_quote.get(symbol) or raw_quote)
        last = quote_payload.get("price") or last
        day_high = quote_payload.get("high") or day_high
        day_low = quote_payload.get("low") or day_low
    except Exception:
        pass

    return {
        "symbol": symbol,
        "as_of": datetime.now(ET).isoformat(),
        "last": last,
        "latest_intraday_bar_date": latest_intraday_date.isoformat(),
        "day_high": day_high,
        "day_low": day_low,
        "extended_high": ext_high,
        "extended_low": ext_low,
        "volume": total_volume,
        "vwap": _vwap(regular_bars or today_bars),
        "sma_5d": _sma(closes, 5),
        "sma_10d": _sma(closes, 10),
        "sma_20d": _sma(closes, 20),
        "sma_50d": _sma(closes, 50),
        "sma_200d": _sma(closes, 200),
        "ema_5d": _ema(closes, 5),
        "ema_10d": _ema(closes, 10),
        "ema_20d": _ema(closes, 20),
        "ema_50d": _ema(closes, 50),
        "ema_200d": _ema(closes, 200),
        "bars_5m": len(minute),
        "daily_bars": len(daily),
        "quote": quote_payload,
    }
