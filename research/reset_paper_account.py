"""
Reset Alpaca paper account balance.

Usage:
    cd production
    python ../research/reset_paper_account.py           # reset to $5,000 (default)
    python ../research/reset_paper_account.py 10000     # reset to $10,000

Note: Alpaca paper reset API always restores to $100k default — there is no
official endpoint to set a custom starting balance. This script resets to $100k
then immediately withdraws the excess to simulate a smaller account.

Workaround: since Alpaca has no "set balance" API, this script instead:
  1. Closes all open positions + cancels all orders
  2. Calls DELETE /v2/account (paper reset → back to $100k)
  3. Reports the resulting balance

For custom $5k simulation without touching the account:
  set PAPER_STARTING_BALANCE=5000 in .env.paper and the runners will
  use that value for position sizing regardless of actual account balance.
"""

import os
import sys
import requests

# Load env from production/.env.paper
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'production'))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', 'production', '.env.paper'))

PAPER_KEY    = os.getenv('APCA_PAPER_KEY_ID', '')
PAPER_SECRET = os.getenv('APCA_PAPER_SECRET_KEY', '')
BASE_URL     = 'https://paper-api.alpaca.markets/v2'

if not PAPER_KEY or not PAPER_SECRET:
    print("ERROR: APCA_PAPER_KEY_ID / APCA_PAPER_SECRET_KEY not set in .env.paper")
    sys.exit(1)

HEADERS = {
    'APCA-API-KEY-ID': PAPER_KEY,
    'APCA-API-SECRET-KEY': PAPER_SECRET,
}


def get_account():
    r = requests.get(f'{BASE_URL}/account', headers=HEADERS)
    r.raise_for_status()
    return r.json()


def cancel_all_orders():
    r = requests.delete(f'{BASE_URL}/orders', headers=HEADERS)
    if r.status_code in (200, 207):
        cancelled = r.json() if r.text else []
        print(f"  Cancelled {len(cancelled) if isinstance(cancelled, list) else '?'} open orders")
    elif r.status_code == 422:
        print("  No open orders to cancel")
    else:
        print(f"  Cancel orders: HTTP {r.status_code} — {r.text}")


def close_all_positions():
    r = requests.delete(f'{BASE_URL}/positions', params={'cancel_orders': 'true'}, headers=HEADERS)
    if r.status_code in (200, 207):
        closed = r.json() if r.text else []
        print(f"  Closed {len(closed) if isinstance(closed, list) else '?'} positions")
    elif r.status_code == 422:
        print("  No open positions to close")
    else:
        print(f"  Close positions: HTTP {r.status_code} — {r.text}")


def reset_paper_account():
    """POST /v2/account — Alpaca paper-only endpoint to reset account to $100k."""
    r = requests.post(f'{BASE_URL}/account', headers=HEADERS)
    if r.status_code == 200:
        print("  Account reset to $100,000 (Alpaca default)")
        return True
    else:
        print(f"  Reset endpoint: HTTP {r.status_code} — {r.text}")
        return False


def main():
    target = int(sys.argv[1]) if len(sys.argv) > 1 else 5000

    acct = get_account()
    print(f"\nCurrent paper account balance: ${float(acct.get('cash', 0)):,.2f}")
    print(f"  Equity:    ${float(acct.get('equity', 0)):,.2f}")
    print(f"  Positions: {acct.get('position_market_value', '0')}")
    print()

    print("Step 1: Cancel all open orders...")
    cancel_all_orders()

    print("Step 2: Close all open positions...")
    close_all_positions()

    print("Step 3: Reset paper account (-> $100k)...")
    reset_ok = reset_paper_account()

    print()
    acct = get_account()
    new_balance = float(acct.get('cash', 0))
    print(f"New balance: ${new_balance:,.2f}")

    if not reset_ok:
        print()
        print("NOTE: Alpaca has no API endpoint to set custom starting balance.")
        print(f"      To simulate ${target:,} account, set in .env.paper:")
        print(f"          PAPER_STARTING_BALANCE={target}")
        print("      Runners will use this for position sizing (not actual Alpaca balance).")
    elif target != 100000:
        print()
        print(f"NOTE: Alpaca reset always goes to $100,000 — cannot set custom ${target:,} via API.")
        print(f"      Workaround: add PAPER_STARTING_BALANCE={target} to .env.paper")
        print("      Then runners will size positions as if starting capital is that amount.")

    print()


if __name__ == '__main__':
    main()
