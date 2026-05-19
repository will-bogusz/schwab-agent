"""Option-chain normalization and simple convexity scenario evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable


@dataclass
class OptionLeg:
    symbol: str
    expiry: str
    dte: int | None
    strike: float
    right: str
    bid: float | None
    ask: float | None
    mark: float | None
    last: float | None
    iv: float | None
    delta: float | None
    gamma: float | None
    theta: float | None
    vega: float | None
    volume: int | None
    open_interest: int | None


def _num(value):
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _int(value):
    n = _num(value)
    return int(n) if n is not None else None


def _mid(bid, ask, mark, last):
    bid = _num(bid)
    ask = _num(ask)
    if bid is not None and ask is not None and ask >= bid and ask > 0:
        return (bid + ask) / 2
    return _num(mark, last)


def flatten_chain(chain: dict, right: str = "CALL") -> list[OptionLeg]:
    exp_map = chain.get("callExpDateMap" if right == "CALL" else "putExpDateMap", {})
    legs = []
    for exp_key, strikes in exp_map.items():
        exp = exp_key.split(":")[0]
        dte = _int(exp_key.split(":")[1]) if ":" in exp_key else None
        for strike_key, contracts in strikes.items():
            for contract in contracts:
                legs.append(
                    OptionLeg(
                        symbol=contract.get("symbol"),
                        expiry=exp,
                        dte=dte,
                        strike=_num(contract.get("strikePrice") or strike_key),
                        right=right,
                        bid=_num(contract.get("bid")),
                        ask=_num(contract.get("ask")),
                        mark=_mid(contract.get("bid"), contract.get("ask"), contract.get("mark"), contract.get("last")),
                        last=_num(contract.get("last")),
                        iv=_num(contract.get("volatility")),
                        delta=_num(contract.get("delta")),
                        gamma=_num(contract.get("gamma")),
                        theta=_num(contract.get("theta")),
                        vega=_num(contract.get("vega")),
                        volume=_int(contract.get("totalVolume")),
                        open_interest=_int(contract.get("openInterest")),
                    )
                )
    return sorted(legs, key=lambda leg: (leg.expiry, leg.strike))


def _liquidity_score(leg: OptionLeg) -> float:
    mark = leg.mark or 0
    spread = ((leg.ask or 0) - (leg.bid or 0)) if leg.ask is not None and leg.bid is not None else 999
    spread_pct = spread / mark if mark else 99
    return (leg.open_interest or 0) / 1000 + (leg.volume or 0) / 500 - spread_pct * 2


def _call_value_at(strike: float, target: float) -> float:
    return max(0.0, target - strike)


def evaluate_calls(
    chain: dict,
    target_pcts: Iterable[float],
    max_expiries: int = 6,
    min_dte: int = 30,
    max_dte: int = 420,
) -> dict:
    underlying = _num(chain.get("underlyingPrice"))
    calls = [
        leg for leg in flatten_chain(chain, "CALL")
        if leg.mark and leg.strike and underlying
        and (leg.dte is None or min_dte <= leg.dte <= max_dte)
    ]
    expiries = []
    for leg in calls:
        if leg.expiry not in expiries:
            expiries.append(leg.expiry)
    expiries = expiries[:max_expiries]
    calls = [leg for leg in calls if leg.expiry in expiries]

    outright = []
    for leg in calls:
        ask_debit = leg.ask or leg.mark
        if not ask_debit:
            continue
        scenarios = {}
        for pct in target_pcts:
            target = underlying * (1 + pct / 100)
            value = _call_value_at(leg.strike, target)
            scenarios[f"+{pct:g}%"] = {
                "target": target,
                "value": value,
                "pnl": value - ask_debit,
                "return_pct": ((value - ask_debit) / ask_debit * 100) if ask_debit else None,
            }
        outright.append({
            "type": "call",
            "expiry": leg.expiry,
            "dte": leg.dte,
            "strike": leg.strike,
            "symbol": leg.symbol,
            "debit": ask_debit,
            "breakeven": leg.strike + ask_debit,
            "iv": leg.iv,
            "delta": leg.delta,
            "theta": leg.theta,
            "volume": leg.volume,
            "open_interest": leg.open_interest,
            "spread_pct": (((leg.ask or 0) - (leg.bid or 0)) / leg.mark * 100) if leg.mark and leg.ask is not None and leg.bid is not None else None,
            "liquidity_score": _liquidity_score(leg),
            "scenarios": scenarios,
        })

    spreads = []
    by_expiry: dict[str, list[OptionLeg]] = {}
    for leg in calls:
        by_expiry.setdefault(leg.expiry, []).append(leg)
    for expiry, legs in by_expiry.items():
        legs = sorted(legs, key=lambda l: l.strike)
        for long in legs:
            for short in legs:
                if short.strike <= long.strike:
                    continue
                width = short.strike - long.strike
                if not (underlying * 0.05 <= width <= underlying * 0.75):
                    continue
                debit = (long.ask or long.mark or 0) - (short.bid or short.mark or 0)
                if debit <= 0:
                    continue
                scenarios = {}
                for pct in target_pcts:
                    target = underlying * (1 + pct / 100)
                    value = min(width, max(0.0, target - long.strike))
                    scenarios[f"+{pct:g}%"] = {
                        "target": target,
                        "value": value,
                        "pnl": value - debit,
                        "return_pct": ((value - debit) / debit * 100) if debit else None,
                    }
                spreads.append({
                    "type": "call_spread",
                    "expiry": expiry,
                    "dte": long.dte,
                    "long_strike": long.strike,
                    "short_strike": short.strike,
                    "width": width,
                    "debit": debit,
                    "max_value": width,
                    "max_return_pct": ((width - debit) / debit * 100) if debit else None,
                    "breakeven": long.strike + debit,
                    "long_symbol": long.symbol,
                    "short_symbol": short.symbol,
                    "liquidity_score": _liquidity_score(long) + _liquidity_score(short),
                    "scenarios": scenarios,
                })

    outright = sorted(outright, key=lambda r: (r["expiry"], -r["liquidity_score"]))[:40]
    spreads = sorted(spreads, key=lambda r: (r["expiry"], -r["liquidity_score"]))[:60]
    return {
        "as_of": datetime.now().isoformat(),
        "symbol": chain.get("symbol"),
        "underlying_price": underlying,
        "target_pcts": list(target_pcts),
        "outright_calls": outright,
        "call_spreads": spreads,
    }
