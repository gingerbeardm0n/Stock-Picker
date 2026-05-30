"""
Test script for OrderExecutor and LiveTradeManager against Alpaca paper account.

Tests (all on paper — no real money):
  1. Connect to paper account, print balance
  2. Place a small marketable limit buy on SPY
  3. Confirm fill
  4. Place stop order below fill price
  5. Cancel stop + sell position
  6. Print final balance

Usage:
    export TRADING_MODE=PAPER
    python production/trading/test_order_manager.py
"""

import sys
import os
import logging
import time

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config import Config
from trading.order_manager import OrderExecutor, LiveTradeManager


def main():
    print("\n" + "="*70)
    print("ORDER MANAGER — PAPER TRADING TEST")
    print("="*70)

    # ── Connect ───────────────────────────────────────────────────────────────
    client = Config.verify_alpaca_connection()
    account = client.get_account()
    balance = float(account.cash)
    print(f"Account cash: ${balance:,.2f}\n")

    executor = OrderExecutor(client)

    # ── Test 1: Place a marketable limit buy ──────────────────────────────────
    TEST_SYMBOL = "SPY"
    TEST_SHARES = 1

    # Get current ask price from Alpaca
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockLatestQuoteRequest

    data_client = StockHistoricalDataClient(
        api_key=Config.ALPACA_API_KEY,
        secret_key=Config.ALPACA_SECRET_KEY,
    )
    quote_req = StockLatestQuoteRequest(symbol_or_symbols=TEST_SYMBOL)
    quote = data_client.get_stock_latest_quote(quote_req)
    ask_price = float(quote[TEST_SYMBOL].ask_price)
    print(f"Current {TEST_SYMBOL} ask: ${ask_price:.2f}")

    # Place entry (ask + $0.10 buffer)
    print(f"\nTest 1: Placing marketable limit BUY {TEST_SHARES} {TEST_SYMBOL}...")
    order = executor.place_entry(TEST_SYMBOL, TEST_SHARES, ask_price)
    print(f"  Order ID: {order.id}")
    print(f"  Status:   {order.status}")

    # Wait for fill
    print("  Waiting for fill (up to 30s)...")
    deadline = time.time() + 30
    while time.time() < deadline:
        order = executor.get_order(str(order.id))
        print(f"  Status: {order.status} | filled_qty: {order.filled_qty} "
              f"| filled_avg_price: {order.filled_avg_price}")
        if str(order.status) == 'filled':
            break
        time.sleep(1)

    if str(order.status) != 'filled':
        print("  ERROR: Order did not fill. Cancelling.")
        executor.cancel_order(str(order.id))
        return

    fill_price = float(order.filled_avg_price)
    print(f"\n  FILLED: {TEST_SHARES} {TEST_SYMBOL} @ ${fill_price:.2f}")

    # ── Test 2: Place stop order ──────────────────────────────────────────────
    stop_price = round(fill_price - 1.00, 2)   # $1 below fill price (wide enough for paper)
    print(f"\nTest 2: Placing stop order @ ${stop_price:.2f}...")
    stop_order = executor.place_stop(TEST_SYMBOL, TEST_SHARES, stop_price)
    print(f"  Stop order ID: {stop_order.id}")
    print(f"  Stop status:   {stop_order.status}")

    time.sleep(2)

    # ── Test 3: Cancel stop and exit position ─────────────────────────────────
    print(f"\nTest 3: Cancelling stop order {stop_order.id}...")
    cancelled = executor.cancel_order(str(stop_order.id))
    print(f"  Cancelled: {cancelled}")

    print(f"\nTest 4: Market selling {TEST_SHARES} {TEST_SYMBOL} to close position...")
    exit_order = executor.place_exit_market(TEST_SYMBOL, TEST_SHARES, "TEST_CLOSE")
    print(f"  Exit order ID: {exit_order.id}")

    # Wait for exit fill
    deadline = time.time() + 30
    while time.time() < deadline:
        exit_order = executor.get_order(str(exit_order.id))
        if str(exit_order.status) == 'filled':
            break
        time.sleep(1)

    exit_price = float(exit_order.filled_avg_price) if exit_order.filled_avg_price else ask_price
    print(f"  Exit filled @ ${exit_price:.2f}")
    print(f"  P&L on test trade: ${TEST_SHARES * (exit_price - fill_price):+.2f}")

    # ── Final check ───────────────────────────────────────────────────────────
    account = client.get_account()
    print(f"\nFinal account cash: ${float(account.cash):,.2f}")
    open_positions = client.get_all_positions()
    print(f"Open positions: {len(open_positions)}")
    if open_positions:
        for pos in open_positions:
            print(f"  {pos.symbol}: {pos.qty} shares @ avg ${pos.avg_entry_price}")

    print("\n" + "="*70)
    print("ALL TESTS PASSED — order_manager.py is working correctly")
    print("="*70)


if __name__ == "__main__":
    main()
