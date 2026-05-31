#!/usr/bin/env python3
"""
Cancel existing stop order and place a new limit sell order.

Usage:
    python production/cancel_stop_and_sell.py ANY 1.86 10587
"""

import sys
import os
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

from config import Config
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import LimitOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderStatus

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)-8s] %(message)s'
)
logger = logging.getLogger(__name__)

def cancel_and_sell(symbol: str, target_price: float, qty: int):
    """
    Cancel all existing orders for symbol, then place a new limit sell order.

    Args:
        symbol: Stock symbol (e.g., 'ANY')
        target_price: Sell limit price (e.g., 1.86)
        qty: Number of shares to sell
    """

    # Set environment for Alpaca SDK
    os.environ['APCA_API_BASE_URL'] = Config.ALPACA_BASE_URL

    # Initialize trading client
    trading_client = TradingClient(
        api_key=Config.ALPACA_API_KEY,
        secret_key=Config.ALPACA_SECRET_KEY
    )

    try:
        # Get all open orders for this symbol
        logger.info(f"Checking for existing orders on {symbol}...")
        orders = trading_client.get_orders(status=OrderStatus.OPEN)
        symbol_orders = [o for o in orders if o.symbol == symbol]

        if symbol_orders:
            logger.info(f"Found {len(symbol_orders)} open order(s) for {symbol}")
            for order in symbol_orders:
                logger.info(f"  Cancelling order {order.id} ({order.order_type} {order.side} {order.qty} @ limit ${order.limit_price if order.limit_price else 'N/A'})")
                trading_client.cancel_order_by_id(order.id)
                logger.info(f"    ✓ Cancelled")
        else:
            logger.info(f"No open orders found for {symbol}")

        # Wait a moment for Alpaca to release the shares
        import time
        time.sleep(0.5)

        # Now place the new limit sell order
        logger.info(f"")
        logger.info(f"Placing limit sell order for {symbol}")
        logger.info(f"  Qty: {qty:,} shares")
        logger.info(f"  Limit price: ${target_price:.2f}")

        order = trading_client.submit_order(LimitOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.SELL,
            limit_price=target_price,
            time_in_force=TimeInForce.DAY,
        ))

        logger.info(f"✓ LIMIT SELL ORDER PLACED")
        logger.info(f"  Order ID: {order.id}")
        logger.info(f"  Symbol: {order.symbol}")
        logger.info(f"  Qty: {order.qty} shares")
        logger.info(f"  Limit price: ${order.limit_price}")
        logger.info(f"  Status: {order.status}")
        logger.info("")
        logger.info(f"Order will auto-fill when {symbol} reaches ${target_price:.2f} or higher")

        return True

    except Exception as e:
        logger.error(f"Error: {e}")
        return False


if __name__ == '__main__':
    if len(sys.argv) != 4:
        print("Usage: python cancel_stop_and_sell.py SYMBOL TARGET_PRICE QTY")
        print("Example: python cancel_stop_and_sell.py ANY 1.86 10587")
        sys.exit(1)

    symbol = sys.argv[1].upper()
    target_price = float(sys.argv[2])
    qty = int(sys.argv[3])

    success = cancel_and_sell(symbol, target_price, qty)
    sys.exit(0 if success else 1)
