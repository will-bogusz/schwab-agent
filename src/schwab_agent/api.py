"""
Schwab Raw Order API
--------------------
Subcommand-based escape hatch for raw JSON order operations.
For complex multi-leg/OCO/trigger orders that can't be expressed via CLI flags.

Usage:
    uv run schwab-api place --data '{...}' [--account X] [--confirm]
    uv run schwab-api preview --data '{...}' [--account X]
    uv run schwab-api cancel --order-id 123 [--account X] [--confirm]
    uv run schwab-api replace --order-id 123 --data '{...}' [--account X] [--confirm]
"""

import json
import sys
import argparse

from .client import get_client, resolve_account
from .orders import safety_check, format_order_preview
from .output import emit, emit_error


def _resolve_account(client, args):
    return resolve_account(client, getattr(args, "account", None))


def cmd_place(args):
    """Place an order from raw JSON."""
    client = get_client()
    account_hash = _resolve_account(client, args)

    order_dict = json.loads(args.data)

    # Safety check
    try:
        warnings = safety_check(order_dict, client)
    except ValueError as e:
        emit_error(str(e))

    # Preview
    print(format_order_preview(order_dict))
    if warnings:
        print("\n  WARNINGS:")
        for w in warnings:
            print(f"    - {w}")

    if not args.confirm:
        print("\n  DRY RUN — add --confirm to execute\n")
        return

    resp = client.place_order(account_hash, order_dict)
    if resp.status_code in (200, 201):
        order_id = resp.headers.get("Location", "").split("/")[-1]
        print(f"\n  Order submitted. ID: {order_id}")
    else:
        print(f"\n  Failed: {resp.status_code} — {resp.text}")
        sys.exit(1)


def cmd_preview(args):
    """Server-side order preview from raw JSON."""
    client = get_client()
    account_hash = _resolve_account(client, args)

    order_dict = json.loads(args.data)

    try:
        warnings = safety_check(order_dict, client)
    except ValueError as e:
        emit_error(str(e))

    print(format_order_preview(order_dict))
    if warnings:
        print("\n  WARNINGS:")
        for w in warnings:
            print(f"    - {w}")

    resp = client.preview_order(account_hash, order_dict)
    resp.raise_for_status()
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
    """Replace (modify) an existing order from raw JSON."""
    client = get_client()
    account_hash = _resolve_account(client, args)

    order_dict = json.loads(args.data)

    try:
        warnings = safety_check(order_dict, client)
    except ValueError as e:
        emit_error(str(e))

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


def main():
    parser = argparse.ArgumentParser(
        description="Schwab Raw Order API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  uv run schwab-api place --data '{"orderType":"MARKET",...}' --confirm
  uv run schwab-api preview --data '{"orderType":"LIMIT",...}'
  uv run schwab-api cancel --order-id 123456 --confirm
  uv run schwab-api replace --order-id 123456 --data '{...}' --confirm
        """,
    )
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # --- place ---
    p = subparsers.add_parser("place", help="Place an order from raw JSON")
    p.add_argument("--data", "-d", required=True, help="Order JSON")
    p.add_argument("--account", help="Account identifier")
    p.add_argument("--confirm", action="store_true", help="Execute the order")
    p.set_defaults(func=cmd_place)

    # --- preview ---
    p = subparsers.add_parser("preview", help="Server-side order preview")
    p.add_argument("--data", "-d", required=True, help="Order JSON")
    p.add_argument("--account", help="Account identifier")
    p.set_defaults(func=cmd_preview)

    # --- cancel ---
    p = subparsers.add_parser("cancel", help="Cancel an order")
    p.add_argument("--order-id", required=True, help="Order ID to cancel")
    p.add_argument("--account", help="Account identifier")
    p.add_argument("--confirm", action="store_true", help="Execute the cancellation")
    p.set_defaults(func=cmd_cancel)

    # --- replace ---
    p = subparsers.add_parser("replace", help="Replace (modify) an order")
    p.add_argument("--order-id", required=True, help="Order ID to replace")
    p.add_argument("--data", "-d", required=True, help="New order JSON")
    p.add_argument("--account", help="Account identifier")
    p.add_argument("--confirm", action="store_true", help="Execute the replacement")
    p.set_defaults(func=cmd_replace)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    try:
        args.func(args)
    except json.JSONDecodeError as e:
        emit_error(f"Invalid JSON: {e}")
    except Exception as e:
        emit_error(str(e))


if __name__ == "__main__":
    main()
