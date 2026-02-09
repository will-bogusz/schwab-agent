"""
Schwab CLI
----------
Full-coverage CLI for the Schwab API via schwab-py.

Usage:
    uv run schwab <command> [options]

Global flags:
    --raw               JSON output
    --account ID        Account identifier (index, number, or hash prefix)
"""

import json
import sys
import argparse
from datetime import datetime, timedelta

from . import config
from .client import get_client, get_account_hashes, resolve_account
from .output import emit, emit_error, fmt_currency, fmt_percent, fmt_table


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_account(client, args):
    """Resolve account from args."""
    return resolve_account(client, getattr(args, "account", None))


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_quote(args):
    """Get quotes for symbols."""
    client = get_client()

    kwargs = {}
    if args.fields:
        fields = [client.Quote.Fields[f.upper()] for f in args.fields]
        kwargs["fields"] = fields

    if len(args.symbols) == 1:
        resp = client.get_quote(args.symbols[0], **kwargs)
    else:
        resp = client.get_quotes(args.symbols, **kwargs)
    resp.raise_for_status()
    data = resp.json()

    if args.raw:
        emit(data, raw=True)
        return

    for symbol, quote_data in data.items():
        quote = quote_data.get("quote", quote_data)
        ref = quote_data.get("reference", {})

        print(f"\n{'=' * 50}")
        print(f"  {symbol} - {ref.get('description', 'N/A')}")
        print(f"{'=' * 50}")

        last = quote.get("lastPrice", quote.get("mark"))
        change = quote.get("netChange", 0)
        change_pct = quote.get("netPercentChange", 0)

        print(f"  Last:     {fmt_currency(last)}")
        print(f"  Change:   {fmt_currency(change)} ({fmt_percent(change_pct)})")
        print(f"  Bid/Ask:  {fmt_currency(quote.get('bidPrice'))} / {fmt_currency(quote.get('askPrice'))}")
        print(f"  Volume:   {quote.get('totalVolume', 0):,}")
        print(f"  High:     {fmt_currency(quote.get('highPrice'))}")
        print(f"  Low:      {fmt_currency(quote.get('lowPrice'))}")

        fundamental = quote_data.get("fundamental")
        if fundamental:
            print(f"\n  Fundamental:")
            for key in ("peRatio", "divYield", "eps", "marketCap"):
                val = fundamental.get(key)
                if val is not None:
                    print(f"    {key}: {val}")


def cmd_positions(args):
    """Show account positions."""
    client = get_client()
    account_hash = _resolve_account(client, args)

    resp = client.get_account(account_hash, fields=[client.Account.Fields.POSITIONS])
    resp.raise_for_status()
    data = resp.json()

    if args.raw:
        emit(data, raw=True)
        return

    positions = data.get("securitiesAccount", {}).get("positions", [])
    if not positions:
        print("No positions found.")
        return

    headers = ["Symbol", "Qty", "Avg Cost", "Mkt Value", "P/L", "P/L %"]
    rows = []
    total_value = total_pl = 0

    for pos in positions:
        symbol = pos.get("instrument", {}).get("symbol", "N/A")
        qty = pos.get("longQuantity", 0) - pos.get("shortQuantity", 0)
        avg_cost = pos.get("averagePrice", 0)
        mkt_value = pos.get("marketValue", 0)
        pl = pos.get("currentDayProfitLoss", 0)
        pl_pct = pos.get("currentDayProfitLossPercentage", 0)

        total_value += mkt_value
        total_pl += pl

        rows.append([
            symbol,
            f"{qty:.2f}",
            fmt_currency(avg_cost),
            fmt_currency(mkt_value),
            fmt_currency(pl),
            fmt_percent(pl_pct),
        ])

    rows.append(["TOTAL", "", "", fmt_currency(total_value), fmt_currency(total_pl), ""])
    print()
    print(fmt_table(headers, rows, "<>>>>>"))


def cmd_balances(args):
    """Show account balances."""
    client = get_client()
    account_hash = _resolve_account(client, args)

    resp = client.get_account(account_hash)
    resp.raise_for_status()
    data = resp.json()

    if args.raw:
        emit(data, raw=True)
        return

    balances = data.get("securitiesAccount", {}).get("currentBalances", {})

    print(f"\n{'=' * 40}")
    print(f"  Account Balances")
    print(f"{'=' * 40}")
    print(f"  Cash:              {fmt_currency(balances.get('cashBalance'))}")
    print(f"  Available Funds:   {fmt_currency(balances.get('availableFunds'))}")
    print(f"  Buying Power:      {fmt_currency(balances.get('buyingPower'))}")
    print(f"  Equity:            {fmt_currency(balances.get('equity'))}")
    print(f"  Long Mkt Value:    {fmt_currency(balances.get('longMarketValue'))}")
    print(f"  Account Value:     {fmt_currency(balances.get('liquidationValue'))}")


def cmd_orders(args):
    """Show orders."""
    client = get_client()

    days = args.days or 60
    end = datetime.now()
    start = end - timedelta(days=days)

    kwargs = {"from_entered_datetime": start, "to_entered_datetime": end}

    if args.status:
        try:
            kwargs["status"] = client.Order.Status[args.status.upper()]
        except KeyError:
            aliases = {
                "pending": "PENDING_ACTIVATION",
                "working": "WORKING",
                "filled": "FILLED",
                "canceled": "CANCELED",
            }
            status_name = aliases.get(args.status.lower(), args.status.upper())
            kwargs["status"] = client.Order.Status[status_name]

    if args.max:
        kwargs["max_results"] = args.max

    if args.all_accounts:
        resp = client.get_orders_for_all_linked_accounts(**kwargs)
    else:
        account_hash = _resolve_account(client, args)
        resp = client.get_orders_for_account(account_hash, **kwargs)

    resp.raise_for_status()
    orders = resp.json()

    if args.raw:
        emit(orders, raw=True)
        return

    if not orders:
        print("No orders found.")
        return

    headers = ["Order ID", "Status", "Symbol", "Side", "Qty", "Price", "Type"]
    rows = []

    for order in orders:
        order_id = str(order.get("orderId", "N/A"))[:10]
        status = order.get("status", "N/A")
        order_type = order.get("orderType", "N/A")

        legs = order.get("orderLegCollection", [])
        if legs:
            leg = legs[0]
            symbol = leg.get("instrument", {}).get("symbol", "N/A")
            side = leg.get("instruction", "N/A")[:4]
            qty = leg.get("quantity", 0)
        else:
            symbol, side, qty = "N/A", "N/A", 0

        price = order.get("price", order.get("stopPrice", "MKT"))
        if isinstance(price, (int, float)):
            price = fmt_currency(price)

        rows.append([order_id, status, symbol, side, qty, price, order_type])

    print()
    print(fmt_table(headers, rows, "<<<<<>>"))


def cmd_options(args):
    """Get option chain for a symbol."""
    client = get_client()

    kwargs = {}
    if args.calls:
        kwargs["contract_type"] = client.Options.ContractType.CALL
    elif args.puts:
        kwargs["contract_type"] = client.Options.ContractType.PUT

    if args.expiry:
        kwargs["from_date"] = datetime.strptime(args.expiry.replace("-", ""), "%Y%m%d")
        kwargs["to_date"] = kwargs["from_date"]
    if args.strike:
        kwargs["strike"] = float(args.strike)
    if args.strikes:
        kwargs["strike_count"] = int(args.strikes)
    if args.strategy:
        kwargs["strategy"] = client.Options.Strategy[args.strategy.upper()]
    if args.range:
        kwargs["strike_range"] = client.Options.StrikeRange[args.range.upper().replace("-", "_")]
    if args.include_quote:
        kwargs["include_underlying_quote"] = True

    resp = client.get_option_chain(args.symbol, **kwargs)
    resp.raise_for_status()
    data = resp.json()

    if args.raw:
        emit(data, raw=True)
        return

    print(f"\n{'=' * 50}")
    print(f"  Option Chain: {args.symbol}")
    print(f"{'=' * 50}")
    print(f"  Underlying: {fmt_currency(data.get('underlyingPrice'))}")
    print(f"  Status: {data.get('status')}")

    call_map = data.get("callExpDateMap", {})
    put_map = data.get("putExpDateMap", {})

    print(f"  Call Expirations: {len(call_map)}")
    print(f"  Put Expirations: {len(put_map)}")

    if call_map:
        print(f"\n  Available Call Expirations:")
        for exp in list(call_map.keys())[:5]:
            print(f"    {exp}")
        if len(call_map) > 5:
            print(f"    ... and {len(call_map) - 5} more")


def cmd_auth(args):
    """Check authentication status."""
    print("\n  Authentication Status")
    print("=" * 40)

    token_path = config.get_token_path()
    if not token_path.exists():
        print("  Tokens: MISSING — run schwab-auth to authenticate")
        return

    try:
        client = get_client()

        resp = client.get_account_numbers()
        resp.raise_for_status()
        accounts = resp.json()
        print(f"  Account access: OK ({len(accounts)} account(s))")

        resp = client.get_quote("AAPL")
        resp.raise_for_status()
        print(f"  Market data: OK")

    except Exception as e:
        print(f"  Error: {e}")


def cmd_accounts(args):
    """List all linked accounts."""
    client = get_client()
    accounts = get_account_hashes(client)

    if args.raw:
        emit(accounts, raw=True)
        return

    print("\n  Linked Accounts")
    print("=" * 50)
    for i, acct in enumerate(accounts):
        print(f"  [{i + 1}] {acct['accountNumber']}  {acct['hashValue'][:20]}...")


def cmd_order(args):
    """Place an order via OrderBuilder."""
    from .orders import build_order, build_option_symbol, safety_check, format_order_preview

    client = get_client()
    account_hash = _resolve_account(client, args)

    # Build option symbol if option flags provided
    if args.underlying:
        if not all([args.expiry, args.strike, args.right]):
            emit_error("Option orders require --underlying, --expiry, --strike, --right")
        symbol = build_option_symbol(args.underlying, args.expiry, args.right, float(args.strike))
    else:
        symbol = args.symbol
        if not symbol:
            emit_error("Either --symbol or --underlying (with --expiry, --strike, --right) is required")

    builder = build_order(
        action=args.action,
        symbol=symbol,
        quantity=int(args.qty),
        order_type=args.type or "MARKET",
        price=float(args.price) if args.price else None,
        stop_price=float(args.stop_price) if args.stop_price else None,
        duration=args.duration or "DAY",
        session=args.session or "NORMAL",
        stop_price_link_basis=args.stop_link_basis,
        stop_price_link_type=args.stop_link_type,
        stop_price_offset=float(args.stop_offset) if args.stop_offset else None,
    )

    order_dict = builder.build()

    # Safety check
    warnings = safety_check(order_dict, client)

    # Preview
    print(format_order_preview(order_dict))
    if warnings:
        print("\n  WARNINGS:")
        for w in warnings:
            print(f"    - {w}")

    if not args.confirm:
        print("\n  DRY RUN — add --confirm to execute\n")
        return

    # Execute
    resp = client.place_order(account_hash, order_dict)
    if resp.status_code in (200, 201):
        order_id = resp.headers.get("Location", "").split("/")[-1]
        print(f"\n  Order submitted. ID: {order_id}")
    else:
        print(f"\n  Failed: {resp.status_code} — {resp.text}")
        sys.exit(1)


def cmd_preview(args):
    """Server-side order preview."""
    from .orders import safety_check, format_order_preview

    client = get_client()
    account_hash = _resolve_account(client, args)

    order_dict = json.loads(args.data)

    warnings = safety_check(order_dict, client)

    print(format_order_preview(order_dict))
    if warnings:
        print("\n  WARNINGS:")
        for w in warnings:
            print(f"    - {w}")

    resp = client.preview_order(account_hash, order_dict)
    resp.raise_for_status()

    if args.raw:
        emit(resp.json(), raw=True)
    else:
        print("\n  Server Preview Response:")
        emit(resp.json(), raw=True)


def cmd_cancel(args):
    """Cancel an order."""
    client = get_client()
    account_hash = _resolve_account(client, args)

    if not args.confirm:
        print(f"\n  Would cancel order {args.order_id}")
        print("  DRY RUN — add --confirm to execute\n")
        return

    resp = client.cancel_order(args.order_id, account_hash)
    if resp.status_code in (200, 201):
        print(f"\n  Order {args.order_id} cancelled.")
    else:
        print(f"\n  Failed: {resp.status_code} — {resp.text}")
        sys.exit(1)


def cmd_replace(args):
    """Replace (modify) an existing order."""
    from .orders import safety_check, format_order_preview

    client = get_client()
    account_hash = _resolve_account(client, args)

    order_dict = json.loads(args.data)

    warnings = safety_check(order_dict, client)

    print(format_order_preview(order_dict))
    if warnings:
        print("\n  WARNINGS:")
        for w in warnings:
            print(f"    - {w}")

    if not args.confirm:
        print(f"\n  Would replace order {args.order_id}")
        print("  DRY RUN — add --confirm to execute\n")
        return

    resp = client.replace_order(args.order_id, account_hash, order_dict)
    if resp.status_code in (200, 201):
        new_id = resp.headers.get("Location", "").split("/")[-1]
        print(f"\n  Order replaced. New ID: {new_id}")
    else:
        print(f"\n  Failed: {resp.status_code} — {resp.text}")
        sys.exit(1)


def cmd_expirations(args):
    """Get option expiration chain."""
    client = get_client()

    resp = client.get_option_expiration_chain(args.symbol)
    resp.raise_for_status()
    data = resp.json()

    if args.raw:
        emit(data, raw=True)
        return

    expirations = data.get("expirationList", [])
    if not expirations:
        print(f"No expirations found for {args.symbol}.")
        return

    print(f"\n  Option Expirations: {args.symbol}")
    print("=" * 40)
    for exp in expirations:
        date = exp.get("expirationDate", "N/A")
        exp_type = exp.get("optionRoots", "")
        dte = exp.get("daysToExpiration", "")
        print(f"  {date}  DTE: {dte}  {exp_type}")


def cmd_history(args):
    """Get price history for a symbol."""
    client = get_client()

    kwargs = {}

    # Shortcuts
    if args.daily:
        kwargs["frequency_type"] = client.PriceHistory.FrequencyType.DAILY
    elif args.weekly:
        kwargs["frequency_type"] = client.PriceHistory.FrequencyType.WEEKLY
    elif args.minute:
        kwargs["frequency_type"] = client.PriceHistory.FrequencyType.MINUTE

    if args.period_type:
        kwargs["period_type"] = client.PriceHistory.PeriodType[args.period_type.upper()]
    if args.period:
        kwargs["period"] = client.PriceHistory.Period[args.period.upper()]
    if args.freq_type:
        kwargs["frequency_type"] = client.PriceHistory.FrequencyType[args.freq_type.upper()]
    if args.freq:
        kwargs["frequency"] = client.PriceHistory.Frequency[args.freq.upper()]

    if getattr(args, "from", None):
        kwargs["start_datetime"] = datetime.strptime(getattr(args, "from"), "%Y-%m-%d")
    if args.to:
        kwargs["end_datetime"] = datetime.strptime(args.to, "%Y-%m-%d")
    if args.extended_hours:
        kwargs["need_extended_hours_data"] = True

    resp = client.get_price_history(args.symbol, **kwargs)
    resp.raise_for_status()
    data = resp.json()

    if args.raw:
        emit(data, raw=True)
        return

    candles = data.get("candles", [])
    if not candles:
        print("No price data found.")
        return

    print(f"\n  Price History: {args.symbol} ({len(candles)} bars)")

    headers = ["Date", "Open", "High", "Low", "Close", "Volume"]
    rows = []
    for c in candles[-20:]:
        dt = datetime.fromtimestamp(c["datetime"] / 1000).strftime("%Y-%m-%d %H:%M")
        rows.append([
            dt,
            fmt_currency(c.get("open")),
            fmt_currency(c.get("high")),
            fmt_currency(c.get("low")),
            fmt_currency(c.get("close")),
            f"{c.get('volume', 0):,}",
        ])

    print(fmt_table(headers, rows, "<>>>>>"))
    if len(candles) > 20:
        print(f"\n  ... showing last 20 of {len(candles)} bars. Use --raw for all.")


def cmd_transactions(args):
    """Get account transactions."""
    client = get_client()
    account_hash = _resolve_account(client, args)

    kwargs = {}
    if args.type:
        kwargs["transaction_types"] = client.Transactions.TransactionType[args.type.upper()]
    if args.symbol:
        kwargs["symbol"] = args.symbol
    if getattr(args, "from", None):
        kwargs["start_date"] = datetime.strptime(getattr(args, "from"), "%Y-%m-%d")
    if args.to:
        kwargs["end_date"] = datetime.strptime(args.to, "%Y-%m-%d")

    resp = client.get_transactions(account_hash, **kwargs)
    resp.raise_for_status()
    data = resp.json()

    if args.raw:
        emit(data, raw=True)
        return

    if not data:
        print("No transactions found.")
        return

    headers = ["Date", "Type", "Description", "Amount"]
    rows = []
    for txn in data[:30]:
        date = txn.get("transactionDate", "")[:10]
        txn_type = txn.get("type", "N/A")
        desc = txn.get("description", "N/A")[:40]
        amount = txn.get("netAmount", 0)
        rows.append([date, txn_type, desc, fmt_currency(amount)])

    print()
    print(fmt_table(headers, rows, "<<<>"))
    if len(data) > 30:
        print(f"\n  ... showing first 30 of {len(data)} transactions. Use --raw for all.")


def cmd_movers(args):
    """Get market movers."""
    client = get_client()

    index = client.Movers.Index[args.index.upper().replace("$", "")]
    kwargs = {}
    if args.sort:
        kwargs["sort_order"] = client.Movers.SortOrder[args.sort.upper()]
    if args.frequency:
        kwargs["frequency"] = client.Movers.Frequency[args.frequency.upper()]

    resp = client.get_movers(index, **kwargs)
    resp.raise_for_status()
    data = resp.json()

    if args.raw:
        emit(data, raw=True)
        return

    screeners = data.get("screeners", [])
    if not screeners:
        print("No movers found.")
        return

    headers = ["Symbol", "Description", "Last", "Change %", "Volume"]
    rows = []
    for m in screeners:
        rows.append([
            m.get("symbol", "N/A"),
            m.get("description", "N/A")[:30],
            fmt_currency(m.get("lastPrice")),
            fmt_percent(m.get("netPercentChange")),
            f"{m.get('totalVolume', 0):,}",
        ])

    print()
    print(fmt_table(headers, rows, "<<>>>"))


def cmd_hours(args):
    """Get market hours."""
    client = get_client()

    markets = [client.MarketHours.Market[m.upper()] for m in (args.market or ["EQUITY"])]

    kwargs = {}
    if args.date:
        kwargs["date"] = datetime.strptime(args.date, "%Y-%m-%d")

    resp = client.get_market_hours(markets, **kwargs)
    resp.raise_for_status()
    data = resp.json()

    if args.raw:
        emit(data, raw=True)
        return

    for market_type, market_data in data.items():
        for name, details in market_data.items():
            print(f"\n  {name}")
            print(f"    Market: {details.get('marketType', 'N/A')}")
            print(f"    Open:   {details.get('isOpen', False)}")
            for session_name, session_hours in details.get("sessionHours", {}).items():
                for h in session_hours:
                    print(f"    {session_name}: {h.get('start', '')} — {h.get('end', '')}")


def cmd_search(args):
    """Search for instruments."""
    client = get_client()

    projection = client.Instrument.Projection[args.projection.upper().replace("-", "_")]
    resp = client.get_instruments(args.query, projection)
    resp.raise_for_status()
    data = resp.json()

    if args.raw:
        emit(data, raw=True)
        return

    instruments = data.get("instruments", [])
    if not instruments:
        print("No instruments found.")
        return

    headers = ["Symbol", "Description", "Type", "Exchange"]
    rows = []
    for inst in instruments:
        rows.append([
            inst.get("symbol", "N/A"),
            inst.get("description", "N/A")[:40],
            inst.get("assetType", "N/A"),
            inst.get("exchange", "N/A"),
        ])

    print()
    print(fmt_table(headers, rows, "<<<<"))


def cmd_instrument(args):
    """Get instrument by CUSIP."""
    client = get_client()

    resp = client.get_instrument_by_cusip(args.cusip)
    resp.raise_for_status()
    data = resp.json()

    if args.raw:
        emit(data, raw=True)
        return

    print(f"\n  Instrument: {data.get('symbol', 'N/A')}")
    print(f"  Description: {data.get('description', 'N/A')}")
    print(f"  Type: {data.get('assetType', 'N/A')}")
    print(f"  Exchange: {data.get('exchange', 'N/A')}")
    print(f"  CUSIP: {data.get('cusip', 'N/A')}")


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def _add_raw(parser):
    parser.add_argument("--raw", action="store_true", help="Output raw JSON")


def _add_account(parser):
    parser.add_argument("--account", help="Account identifier (index, number, or hash prefix)")


def _add_confirm(parser):
    parser.add_argument("--confirm", action="store_true", help="Execute (required for mutations)")


def main():
    parser = argparse.ArgumentParser(
        description="Schwab CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # --- quote ---
    p = subparsers.add_parser("quote", help="Get stock quotes")
    p.add_argument("symbols", nargs="+", help="Stock symbols")
    p.add_argument("--fields", nargs="+", help="Quote fields (quote, fundamental, extended, reference, regular)")
    _add_raw(p)
    p.set_defaults(func=cmd_quote)

    # --- positions ---
    p = subparsers.add_parser("positions", help="Show account positions")
    _add_raw(p)
    _add_account(p)
    p.set_defaults(func=cmd_positions)

    # --- balances ---
    p = subparsers.add_parser("balances", help="Show account balances")
    _add_raw(p)
    _add_account(p)
    p.set_defaults(func=cmd_balances)

    # --- orders ---
    p = subparsers.add_parser("orders", help="Show orders")
    p.add_argument("--status", help="Filter by status (pending, working, filled, canceled, or any Schwab status)")
    p.add_argument("--all-accounts", action="store_true", help="Show orders for all linked accounts")
    p.add_argument("--max", type=int, help="Maximum number of orders to return")
    p.add_argument("--days", type=int, help="Look back N days (default: 60)")
    _add_raw(p)
    _add_account(p)
    p.set_defaults(func=cmd_orders)

    # --- options ---
    p = subparsers.add_parser("options", help="Get option chain")
    p.add_argument("symbol", help="Underlying symbol")
    p.add_argument("--calls", action="store_true", help="Only show calls")
    p.add_argument("--puts", action="store_true", help="Only show puts")
    p.add_argument("--expiry", help="Filter by expiration date (YYYYMMDD or YYYY-MM-DD)")
    p.add_argument("--strike", help="Filter by specific strike price")
    p.add_argument("--strikes", help="Number of strikes around ATM")
    p.add_argument("--strategy", help="Strategy type (single, analytical, covered, vertical, etc.)")
    p.add_argument("--range", help="Strike range (in-the-money, near-the-money, out-of-the-money, etc.)")
    p.add_argument("--include-quote", action="store_true", help="Include underlying quote data")
    _add_raw(p)
    p.set_defaults(func=cmd_options)

    # --- auth ---
    p = subparsers.add_parser("auth", help="Check authentication status")
    p.set_defaults(func=cmd_auth)

    # --- accounts ---
    p = subparsers.add_parser("accounts", help="List linked accounts")
    _add_raw(p)
    p.set_defaults(func=cmd_accounts)

    # --- order ---
    p = subparsers.add_parser("order", help="Place an order")
    p.add_argument("--action", required=True, help="BUY, SELL, SELL_SHORT, BUY_TO_COVER, BUY_TO_OPEN, etc.")
    p.add_argument("--symbol", help="Equity symbol (e.g., AAPL)")
    p.add_argument("--qty", required=True, help="Quantity (shares or contracts)")
    p.add_argument("--type", help="Order type (MARKET, LIMIT, STOP, STOP_LIMIT, TRAILING_STOP)")
    p.add_argument("--price", help="Limit price")
    p.add_argument("--stop-price", help="Stop trigger price")
    p.add_argument("--duration", help="Duration (DAY, GOOD_TILL_CANCEL, etc.)")
    p.add_argument("--session", help="Session (NORMAL, AM, PM, SEAMLESS)")
    p.add_argument("--underlying", help="Option: underlying symbol")
    p.add_argument("--expiry", help="Option: expiration (YYYYMMDD or YYYY-MM-DD)")
    p.add_argument("--strike", help="Option: strike price")
    p.add_argument("--right", help="Option: C/P or CALL/PUT")
    p.add_argument("--stop-offset", help="Trailing stop offset")
    p.add_argument("--stop-link-basis", help="Trailing stop link basis (LAST, BID, ASK, etc.)")
    p.add_argument("--stop-link-type", help="Trailing stop link type (VALUE, PERCENT)")
    _add_raw(p)
    _add_account(p)
    _add_confirm(p)
    p.set_defaults(func=cmd_order)

    # --- preview ---
    p = subparsers.add_parser("preview", help="Server-side order preview")
    p.add_argument("--data", "-d", required=True, help="Order JSON")
    _add_raw(p)
    _add_account(p)
    p.set_defaults(func=cmd_preview)

    # --- cancel ---
    p = subparsers.add_parser("cancel", help="Cancel an order")
    p.add_argument("--order-id", required=True, help="Order ID to cancel")
    _add_account(p)
    _add_confirm(p)
    p.set_defaults(func=cmd_cancel)

    # --- replace ---
    p = subparsers.add_parser("replace", help="Replace (modify) an order")
    p.add_argument("--order-id", required=True, help="Order ID to replace")
    p.add_argument("--data", "-d", required=True, help="New order JSON")
    _add_raw(p)
    _add_account(p)
    _add_confirm(p)
    p.set_defaults(func=cmd_replace)

    # --- expirations ---
    p = subparsers.add_parser("expirations", help="Get option expiration chain")
    p.add_argument("symbol", help="Underlying symbol")
    _add_raw(p)
    p.set_defaults(func=cmd_expirations)

    # --- history ---
    p = subparsers.add_parser("history", help="Get price history")
    p.add_argument("symbol", help="Symbol")
    p.add_argument("--period-type", help="Period type (day, month, year, year_to_date)")
    p.add_argument("--period", help="Period (one_day, five_days, six_months, etc.)")
    p.add_argument("--freq-type", help="Frequency type (minute, daily, weekly, monthly)")
    p.add_argument("--freq", help="Frequency (every_minute, every_five_minutes, etc.)")
    p.add_argument("--from", dest="from", help="Start date (YYYY-MM-DD)")
    p.add_argument("--to", help="End date (YYYY-MM-DD)")
    p.add_argument("--extended-hours", action="store_true", help="Include extended hours data")
    p.add_argument("--daily", action="store_true", help="Shortcut: daily bars")
    p.add_argument("--weekly", action="store_true", help="Shortcut: weekly bars")
    p.add_argument("--minute", action="store_true", help="Shortcut: minute bars")
    _add_raw(p)
    p.set_defaults(func=cmd_history)

    # --- transactions ---
    p = subparsers.add_parser("transactions", help="Get account transactions")
    p.add_argument("--type", help="Transaction type (TRADE, DIVIDEND_OR_INTEREST, etc.)")
    p.add_argument("--symbol", help="Filter by symbol")
    p.add_argument("--from", dest="from", help="Start date (YYYY-MM-DD)")
    p.add_argument("--to", help="End date (YYYY-MM-DD)")
    _add_raw(p)
    _add_account(p)
    p.set_defaults(func=cmd_transactions)

    # --- movers ---
    p = subparsers.add_parser("movers", help="Get market movers")
    p.add_argument("--index", default="SPX", help="Index ($DJI, $COMPX, $SPX, etc.)")
    p.add_argument("--sort", help="Sort order (volume, trades, percent_change_up, percent_change_down)")
    p.add_argument("--frequency", help="Frequency (zero, one, five, ten, thirty, sixty)")
    _add_raw(p)
    p.set_defaults(func=cmd_movers)

    # --- hours ---
    p = subparsers.add_parser("hours", help="Get market hours")
    p.add_argument("--market", nargs="+", help="Market types (equity, option, bond, future, forex)")
    p.add_argument("--date", help="Date (YYYY-MM-DD)")
    _add_raw(p)
    p.set_defaults(func=cmd_hours)

    # --- search ---
    p = subparsers.add_parser("search", help="Search for instruments")
    p.add_argument("query", help="Search query (symbol or description)")
    p.add_argument("--projection", default="symbol-search",
                   help="Projection (symbol-search, symbol-regex, description-search, description-regex, search, fundamental)")
    _add_raw(p)
    p.set_defaults(func=cmd_search)

    # --- instrument ---
    p = subparsers.add_parser("instrument", help="Get instrument by CUSIP")
    p.add_argument("cusip", help="CUSIP identifier")
    _add_raw(p)
    p.set_defaults(func=cmd_instrument)

    # --- Parse and dispatch ---
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    try:
        args.func(args)
    except KeyError as e:
        emit_error(f"Invalid enum value: {e}")
    except Exception as e:
        emit_error(str(e))


if __name__ == "__main__":
    main()
