#!/usr/bin/env python3
"""
Schwab Order API
----------------
Subcommand-based order tool for raw JSON order operations.
Escape hatch for complex multi-leg/OCO/trigger orders.

Usage:
    schwab-api place --data '{...}' [--account X] [--confirm]
    schwab-api preview --data '{...}' [--account X]
    schwab-api cancel --order-id 123 [--account X] [--confirm]
    schwab-api replace --order-id 123 --data '{...}' [--account X] [--confirm]
"""

import json
import sys
import argparse

from . import config
from .client import get_client, resolve_account
from .orders import safety_check, format_order_preview


def cmd_place(args):
    """Place an order from raw JSON."""
    client = get_client(args.app or "trading")
    account_hash = resolve_account(client, args.account)

    order = json.loads(args.data)

    # Safety check
    warnings = safety_check(order, client)

    print(format_order_preview(order))
    if warnings:
        print("\n  WARNINGS:")
        for w in warnings:
            print(f"    - {w}")

    if not args.confirm:
        print("\n  DRY RUN — add --confirm to execute\n")
        result = {"status": "PREVIEW", "order": order}
        if warnings:
            result["warnings"] = warnings
        print(json.dumps(result, indent=2, default=str))
        return

    resp = client.place_order(account_hash, order)
    if resp.status_code in (200, 201):
        order_id = resp.headers.get("Location", "").split("/")[-1]
        print(f"\n  Order submitted. ID: {order_id}")
        print(json.dumps({"status": "SUCCESS", "order_id": order_id}, indent=2))
    else:
        print(f"\n  Failed: {resp.status_code} — {resp.text}")
        print(json.dumps({"status": "FAILED", "error": resp.text}, indent=2))
        sys.exit(1)


def cmd_preview(args):
    """Server-side order preview from raw JSON."""
    client = get_client(args.app or "trading")
    account_hash = resolve_account(client, args.account)

    order = json.loads(args.data)

    warnings = safety_check(order, client)

    print(format_order_preview(order))
    if warnings:
        print("\n  WARNINGS:")
        for w in warnings:
            print(f"    - {w}")

    resp = client.preview_order(account_hash, order)
    resp.raise_for_status()
    print(json.dumps(resp.json(), indent=2, default=str))


def cmd_cancel(args):
    """Cancel an order."""
    client = get_client(args.app or "trading")
    account_hash = resolve_account(client, args.account)

    if not args.confirm:
        print(f"\n  Would cancel order {args.order_id}")
        print("  DRY RUN — add --confirm to execute\n")
        print(json.dumps({"status": "PREVIEW", "order_id": args.order_id}, indent=2))
        return

    resp = client.cancel_order(args.order_id, account_hash)
    if resp.status_code in (200, 201):
        print(f"\n  Order {args.order_id} cancelled.")
        print(json.dumps({"status": "SUCCESS", "order_id": args.order_id}, indent=2))
    else:
        print(f"\n  Failed: {resp.status_code} — {resp.text}")
        print(json.dumps({"status": "FAILED", "error": resp.text}, indent=2))
        sys.exit(1)


def cmd_replace(args):
    """Replace an order with raw JSON."""
    client = get_client(args.app or "trading")
    account_hash = resolve_account(client, args.account)

    order = json.loads(args.data)

    warnings = safety_check(order, client)

    print(format_order_preview(order))
    if warnings:
        print("\n  WARNINGS:")
        for w in warnings:
            print(f"    - {w}")

    if not args.confirm:
        print(f"\n  Would replace order {args.order_id}")
        print("  DRY RUN — add --confirm to execute\n")
        result = {"status": "PREVIEW", "order_id": args.order_id, "order": order}
        if warnings:
            result["warnings"] = warnings
        print(json.dumps(result, indent=2, default=str))
        return

    resp = client.replace_order(args.order_id, account_hash, order)
    if resp.status_code in (200, 201):
        new_id = resp.headers.get("Location", "").split("/")[-1]
        print(f"\n  Order replaced. New ID: {new_id}")
        print(json.dumps({"status": "SUCCESS", "order_id": new_id}, indent=2))
    else:
        print(f"\n  Failed: {resp.status_code} — {resp.text}")
        print(json.dumps({"status": "FAILED", "error": resp.text}, indent=2))
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Schwab Order API — raw JSON order operations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  schwab-api place --data '{"orderType":"LIMIT","price":"150.00",...}' --confirm
  schwab-api preview --data '{"orderType":"LIMIT","price":"150.00",...}'
  schwab-api cancel --order-id 12345 --confirm
  schwab-api replace --order-id 12345 --data '{...}' --confirm
        """,
    )
    parser.add_argument("--app", choices=config.VALID_APPS, help="Override app (default: trading)")
    parser.add_argument("--account", help="Account identifier")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # place
    p = subparsers.add_parser("place", help="Place an order from JSON")
    p.add_argument("--data", "-d", required=True, help="Order JSON")
    p.add_argument("--confirm", action="store_true", help="Execute the order")
    p.set_defaults(func=cmd_place)

    # preview
    p = subparsers.add_parser("preview", help="Server-side order preview")
    p.add_argument("--data", "-d", required=True, help="Order JSON")
    p.set_defaults(func=cmd_preview)

    # cancel
    p = subparsers.add_parser("cancel", help="Cancel an order")
    p.add_argument("--order-id", required=True, help="Order ID to cancel")
    p.add_argument("--confirm", action="store_true", help="Execute the cancellation")
    p.set_defaults(func=cmd_cancel)

    # replace
    p = subparsers.add_parser("replace", help="Replace (modify) an order")
    p.add_argument("--order-id", required=True, help="Order ID to replace")
    p.add_argument("--data", "-d", required=True, help="New order JSON")
    p.add_argument("--confirm", action="store_true", help="Execute the replacement")
    p.set_defaults(func=cmd_replace)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    try:
        args.func(args)
    except json.JSONDecodeError as e:
        print(f"Invalid JSON: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
