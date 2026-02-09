"""
Order Building & Safety
-----------------------
Wraps schwab-py's OrderBuilder and pre-built templates.
Replaces the hand-rolled schemas/ directory.

All enum values come from schwab-py — no hand-maintained sets.
"""

from datetime import datetime

from schwab.orders.common import (
    Duration,
    EquityInstruction,
    OptionInstruction,
    OrderStrategyType,
    OrderType,
    Session,
    StopPriceLinkBasis,
    StopPriceLinkType,
)
from schwab.orders.equities import (
    equity_buy_limit,
    equity_buy_market,
    equity_buy_to_cover_limit,
    equity_buy_to_cover_market,
    equity_sell_limit,
    equity_sell_market,
    equity_sell_short_limit,
    equity_sell_short_market,
)
from schwab.orders.generic import OrderBuilder
from schwab.orders.options import (
    OptionSymbol,
    option_buy_to_close_limit,
    option_buy_to_close_market,
    option_buy_to_open_limit,
    option_buy_to_open_market,
    option_sell_to_close_limit,
    option_sell_to_close_market,
    option_sell_to_open_limit,
    option_sell_to_open_market,
)

# Safety limits
MAX_EQUITY_QUANTITY = 10_000
MAX_OPTION_CONTRACTS = 100
LARGE_EQUITY_THRESHOLD = 1_000
MAX_LIMIT_DEVIATION_PERCENT = 20

_EQUITY_ACTIONS = {inst.name for inst in EquityInstruction}
_OPTION_ACTIONS = {inst.name for inst in OptionInstruction}

# Template dispatch: (action, order_type) -> function
_EQUITY_TEMPLATES = {
    ("BUY", "MARKET"): equity_buy_market,
    ("BUY", "LIMIT"): equity_buy_limit,
    ("SELL", "MARKET"): equity_sell_market,
    ("SELL", "LIMIT"): equity_sell_limit,
    ("SELL_SHORT", "MARKET"): equity_sell_short_market,
    ("SELL_SHORT", "LIMIT"): equity_sell_short_limit,
    ("BUY_TO_COVER", "MARKET"): equity_buy_to_cover_market,
    ("BUY_TO_COVER", "LIMIT"): equity_buy_to_cover_limit,
}

_OPTION_TEMPLATES = {
    ("BUY_TO_OPEN", "MARKET"): option_buy_to_open_market,
    ("BUY_TO_OPEN", "LIMIT"): option_buy_to_open_limit,
    ("BUY_TO_CLOSE", "MARKET"): option_buy_to_close_market,
    ("BUY_TO_CLOSE", "LIMIT"): option_buy_to_close_limit,
    ("SELL_TO_OPEN", "MARKET"): option_sell_to_open_market,
    ("SELL_TO_OPEN", "LIMIT"): option_sell_to_open_limit,
    ("SELL_TO_CLOSE", "MARKET"): option_sell_to_close_market,
    ("SELL_TO_CLOSE", "LIMIT"): option_sell_to_close_limit,
}


def build_order(
    action: str,
    symbol: str,
    quantity: int,
    order_type: str = "MARKET",
    price: float | None = None,
    stop_price: float | None = None,
    duration: str = "DAY",
    session: str = "NORMAL",
    stop_price_link_basis: str | None = None,
    stop_price_link_type: str | None = None,
    stop_price_offset: float | None = None,
) -> OrderBuilder:
    """
    Build an order using schwab-py templates and OrderBuilder.

    For MARKET/LIMIT: delegates to schwab-py's pre-built templates.
    For STOP/STOP_LIMIT/TRAILING_STOP/etc: builds via OrderBuilder.

    Args:
        action: BUY, SELL, SELL_SHORT, BUY_TO_COVER (equity)
                BUY_TO_OPEN, BUY_TO_CLOSE, SELL_TO_OPEN, SELL_TO_CLOSE (option)
        symbol: Equity ticker or option symbol string.
        quantity: Number of shares or contracts.
        order_type: MARKET, LIMIT, STOP, STOP_LIMIT, TRAILING_STOP, etc.
        price: Limit price (required for LIMIT, STOP_LIMIT).
        stop_price: Stop trigger price (required for STOP, STOP_LIMIT).
        duration: DAY, GOOD_TILL_CANCEL, etc.
        session: NORMAL, AM, PM, SEAMLESS.
        stop_price_link_basis: For TRAILING_STOP (e.g., LAST, BID, ASK).
        stop_price_link_type: For TRAILING_STOP (VALUE or PERCENT).
        stop_price_offset: For TRAILING_STOP.

    Returns:
        schwab-py OrderBuilder instance.
    """
    action = action.upper()
    order_type = order_type.upper()
    is_equity = action in _EQUITY_ACTIONS
    is_option = action in _OPTION_ACTIONS

    if not is_equity and not is_option:
        raise ValueError(
            f"Invalid action '{action}'. "
            f"Equity: {sorted(_EQUITY_ACTIONS)}, "
            f"Option: {sorted(_OPTION_ACTIONS)}"
        )

    # Validate order_type is a valid schwab-py enum
    try:
        OrderType[order_type]
    except KeyError:
        valid = [t.name for t in OrderType]
        raise ValueError(f"Invalid order_type '{order_type}'. Valid: {valid}")

    # Try template dispatch for MARKET/LIMIT
    templates = _EQUITY_TEMPLATES if is_equity else _OPTION_TEMPLATES
    template_fn = templates.get((action, order_type))

    if template_fn:
        if order_type == "MARKET":
            builder = template_fn(symbol, quantity)
        else:  # LIMIT
            if price is None:
                raise ValueError(f"LIMIT orders require --price")
            builder = template_fn(symbol, quantity, price)

        # Override duration/session if non-default
        if duration != "DAY":
            builder.set_duration(Duration[duration])
        if session != "NORMAL":
            builder.set_session(Session[session])

        return builder

    # Manual build for STOP, STOP_LIMIT, TRAILING_STOP, etc.
    builder = OrderBuilder()
    builder.set_order_type(OrderType[order_type])
    builder.set_session(Session[session])
    builder.set_duration(Duration[duration])
    builder.set_order_strategy_type(OrderStrategyType.SINGLE)

    if price is not None:
        builder.set_price(str(price))
    if stop_price is not None:
        builder.set_stop_price(str(stop_price))
    if stop_price_offset is not None:
        builder.set_stop_price_offset(str(stop_price_offset))
    if stop_price_link_basis is not None:
        builder.set_stop_price_link_basis(StopPriceLinkBasis[stop_price_link_basis.upper()])
    if stop_price_link_type is not None:
        builder.set_stop_price_link_type(StopPriceLinkType[stop_price_link_type.upper()])

    if is_equity:
        builder.add_equity_leg(EquityInstruction[action], symbol, quantity)
    else:
        builder.add_option_leg(OptionInstruction[action], symbol, quantity)

    # Validate required fields for the order type
    if order_type == "STOP" and stop_price is None:
        raise ValueError("STOP orders require --stop-price")
    if order_type == "STOP_LIMIT":
        if price is None:
            raise ValueError("STOP_LIMIT orders require --price")
        if stop_price is None:
            raise ValueError("STOP_LIMIT orders require --stop-price")
    if order_type == "TRAILING_STOP" and stop_price_offset is None:
        raise ValueError("TRAILING_STOP orders require --stop-price-offset")

    return builder


def build_option_symbol(
    underlying: str, expiry: str, right: str, strike: float
) -> str:
    """
    Build an OCC option symbol string using schwab-py's OptionSymbol.

    Args:
        underlying: Underlying ticker (e.g., "AAPL").
        expiry: Expiration date as "YYYYMMDD" or "YYYY-MM-DD".
        right: "C", "P", "CALL", or "PUT".
        strike: Strike price.

    Returns:
        Option symbol string (e.g., "AAPL  250321C00150000").
    """
    expiry_clean = expiry.replace("-", "")
    expiry_date = datetime.strptime(expiry_clean, "%Y%m%d")

    contract_type = "C" if right.upper().startswith("C") else "P"

    opt = OptionSymbol(underlying, expiry_date, contract_type, str(strike))
    return opt.build()


def safety_check(order_dict: dict, client=None) -> list[str]:
    """
    Check order for safety issues.

    Args:
        order_dict: Order as dict (from OrderBuilder.build()).
        client: Optional schwab client for price deviation checks.

    Returns:
        List of warning strings. Raises ValueError for hard limit violations.
    """
    warnings = []

    for leg in order_dict.get("orderLegCollection", []):
        inst = leg.get("instrument", {})
        symbol = inst.get("symbol", "")
        asset_type = inst.get("assetType", "")
        qty = leg.get("quantity", 0)
        instruction = leg.get("instruction", "")

        # Hard limits
        if asset_type == "EQUITY" and qty > MAX_EQUITY_QUANTITY:
            raise ValueError(
                f"Quantity {qty} exceeds max {MAX_EQUITY_QUANTITY} shares"
            )
        if asset_type == "OPTION" and qty > MAX_OPTION_CONTRACTS:
            raise ValueError(
                f"Contracts {qty} exceeds max {MAX_OPTION_CONTRACTS}"
            )

        # Soft warnings
        if asset_type == "EQUITY" and qty > LARGE_EQUITY_THRESHOLD:
            warnings.append(f"Large order: {qty} shares of {symbol}")
        if instruction == "SELL_SHORT":
            warnings.append(f"SHORT SALE: {qty} shares of {symbol}")
        if instruction == "SELL_TO_OPEN":
            warnings.append(f"OPTION WRITE: {qty} contracts — understand the risk")

    # Price deviation check
    if client and order_dict.get("orderType") == "LIMIT":
        try:
            limit = float(order_dict.get("price", 0))
            symbol = (
                order_dict.get("orderLegCollection", [{}])[0]
                .get("instrument", {})
                .get("symbol")
            )
            if symbol and limit > 0:
                resp = client.get_quote(symbol)
                if resp.status_code == 200:
                    current = (
                        resp.json()
                        .get(symbol, {})
                        .get("quote", {})
                        .get("lastPrice", 0)
                    )
                    if current > 0:
                        deviation = abs(limit - current) / current * 100
                        if deviation > MAX_LIMIT_DEVIATION_PERCENT:
                            warnings.append(
                                f"Limit ${limit:.2f} is {deviation:.1f}% from "
                                f"current ${current:.2f}"
                            )
        except Exception:
            pass

    return warnings


def format_order_preview(order_dict: dict) -> str:
    """Format an order dict as a human-readable preview."""
    lines = ["=" * 60, "  ORDER PREVIEW", "=" * 60]

    lines.append(f"  Type:     {order_dict.get('orderType', 'UNKNOWN')}")
    lines.append(f"  Session:  {order_dict.get('session', 'UNKNOWN')}")
    lines.append(f"  Duration: {order_dict.get('duration', 'UNKNOWN')}")

    if "price" in order_dict:
        lines.append(f"  Price:    ${float(order_dict['price']):,.2f}")
    if "stopPrice" in order_dict:
        lines.append(f"  Stop:     ${float(order_dict['stopPrice']):,.2f}")
    if "stopPriceOffset" in order_dict:
        lines.append(f"  Offset:   {order_dict['stopPriceOffset']}")

    legs = order_dict.get("orderLegCollection", [])
    if legs:
        lines.append("")
        lines.append("  Legs:")
        for i, leg in enumerate(legs):
            inst = leg.get("instrument", {})
            symbol = inst.get("symbol", "???")
            instruction = leg.get("instruction", "???")
            qty = leg.get("quantity", 0)
            asset_type = inst.get("assetType", "")
            label = f"contract{'s' if qty != 1 else ''}" if asset_type == "OPTION" else "shares"
            lines.append(f"    [{i + 1}] {instruction} {qty} {symbol} ({label})")

    lines.extend(["", "=" * 60])
    return "\n".join(lines)
