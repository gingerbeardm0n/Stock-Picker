#!/usr/bin/env python3
"""
Order Smoke Test
================
Buys 1 share of a known small-cap stock, then immediately sells it.
Purpose: verify the full order → fill → sell pipeline works end-to-end
against the paper trading account.

Usage:
    export TRADING_MODE=PAPER
    python production/tests/test_order_smoke.py

Expected outcome:
    - Buy fills within a few seconds
    - Sell fills within a few seconds
    - Net P&L ≈ $0 ± bid-ask spread (typically $0.01-0.05 on liquid names)
    - Both orders visible on paper.alpaca.markets order history

This script does NOT use LiveScanner or entry signals — it's a pure
plumbing test for OrderExecutor.
"""

import sys
import os
import time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config import Config
from trading.order_manager import OrderExecutor
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockSnapshotRequest
from alpaca.trading.enums import OrderStatus


# Well-known high-volume names in the $1-20 range — good liquidity, fast fills
CANDIDATE_SYMBOLS = ['SNDL', 'PLUG', 'NOK', 'F', 'SOFI', 'NIO', 'PLTR', 'BB']
FILL_TIMEOUT_SECS = 30


def find_liquid_symbol(data_client) -> tuple[str, float] | tuple[None, None]:
    """
    Check snapshots for CANDIDATE_SYMBOLS and return the first one
    with a valid ask price in $1-$20 range.
    """
    request = StockSnapshotRequest(symbol_or_symbols=CANDIDATE_SYMBOLS)
    try:
        snapshots = data_client.get_stock_snapshot(request)
    except Exception as e:
        print(f"[ERROR] Could not fetch snapshots: {e}")
        return None, None

    for symbol in CANDIDATE_SYMBOLS:
        snap = snapshots.get(symbol)
        if not snap:
            continue
        # Try latest_quote.ask_price first; fall back to latest_trade.price
        ask = None
        if snap.latest_quote and snap.latest_quote.ask_price:
            ask = float(snap.latest_quote.ask_price)
        elif snap.latest_trade and snap.latest_trade.price:
            ask = float(snap.latest_trade.price)
        if ask and 1.0 <= ask <= 20.0:
            return symbol, ask

    return None, None


def wait_for_fill(executor: OrderExecutor, order_id: str,
                  timeout: int = FILL_TIMEOUT_SECS) -> object | None:
    """Poll Alpaca until filled, cancelled, or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        order = executor.get_order(order_id)
        if order.status == OrderStatus.FILLED:
            return order
        if order.status in (OrderStatus.CANCELED, OrderStatus.EXPIRED,
                            OrderStatus.REJECTED):
            print(f"  [!] Order ended with status: {order.status}")
            return None
        time.sleep(0.5)
    return None


def main():
    print("\n" + "=" * 60)
    print("  ORDER SMOKE TEST")
    print("  Buy 1 share → immediately sell 1 share")
    print("=" * 60)

    # ── Connect ────────────────────────────────────────────────────────────────
    client = Config.verify_alpaca_connection()
    data_client = StockHistoricalDataClient(
        Config.ALPACA_API_KEY,
        Config.ALPACA_SECRET_KEY,
    )
    executor = OrderExecutor(client)

    # ── Find a liquid symbol with a live ask price ─────────────────────────────
    print("\nFinding a liquid symbol in $1-$20 range...")
    symbol, ask = find_liquid_symbol(data_client)

    if not symbol:
        print("[ERROR] Could not find a valid ask price for any candidate symbol.")
        print("        Is the market open? (Regular hours: 9:30am-4pm ET)")
        print("        You can still test after-hours but fills may be slow.")
        return

    print(f"  Found: {symbol} @ ask ${ask:.2f}")

    # ── Confirm ────────────────────────────────────────────────────────────────
    print(f"\nPlacing TWO orders against your {Config.TRADING_MODE} account:")
    print(f"  1. BUY  1 share of {symbol} (limit: ${ask + 0.10:.2f})")
    print(f"  2. SELL 1 share of {symbol} (market)")

    # ── BUY ───────────────────────────────────────────────────────────────────
    print(f"\n[1/2] Placing BUY order: 1 share of {symbol}...")
    buy_order = executor.place_entry(symbol, shares=1, ask_price=ask)
    buy_id = str(buy_order.id)
    print(f"      Order ID: {buy_id}")
    print(f"      Waiting for fill (up to {FILL_TIMEOUT_SECS}s)...")

    filled_buy = wait_for_fill(executor, buy_id)
    if filled_buy is None:
        print(f"[FAIL] Buy order did not fill. Cancelling...")
        executor.cancel_order(buy_id)
        print("       No shares were purchased. Safe to exit.")
        return

    buy_fill_price = float(filled_buy.filled_avg_price)
    print(f"      [OK] Filled @ ${buy_fill_price:.4f}")

    # ── SELL ──────────────────────────────────────────────────────────────────
    print(f"\n[2/2] Placing SELL order: 1 share of {symbol}...")
    sell_order = executor.place_exit_market(symbol, shares=1, reason='SMOKE_TEST')
    sell_id = str(sell_order.id)
    print(f"      Order ID: {sell_id}")
    print(f"      Waiting for fill (up to {FILL_TIMEOUT_SECS}s)...")

    filled_sell = wait_for_fill(executor, sell_id)
    if filled_sell is None:
        print(f"[FAIL] Sell order did not fill!")
        print(f"       YOU MAY HAVE 1 OPEN SHARE OF {symbol} ON YOUR PAPER ACCOUNT.")
        print(f"       Check paper.alpaca.markets → Positions to confirm.")
        return

    sell_fill_price = float(filled_sell.filled_avg_price)
    print(f"      [OK] Filled @ ${sell_fill_price:.4f}")

    # ── Summary ───────────────────────────────────────────────────────────────
    pnl = sell_fill_price - buy_fill_price
    print("\n" + "=" * 60)
    print("  SMOKE TEST COMPLETE")
    print("=" * 60)
    print(f"  Symbol:     {symbol}")
    print(f"  Buy fill:   ${buy_fill_price:.4f}")
    print(f"  Sell fill:  ${sell_fill_price:.4f}")
    print(f"  Net P&L:    ${pnl:+.4f}  (bid-ask spread cost)")
    print(f"  Buy  ID:    {buy_id}")
    print(f"  Sell ID:    {sell_id}")
    if abs(pnl) < 2.0:
        print(f"\n  RESULT: PASS - orders are working correctly")
    else:
        print(f"\n  RESULT: UNUSUAL P&L — check Alpaca dashboard")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[STOPPED] Cancelled. Check Alpaca dashboard for any open positions.")
    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
