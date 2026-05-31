#!/usr/bin/env python3
"""
Manual limit sell order — places a sell limit order immediately at breakeven.
Run from command line to place a limit sell order that fills when price reaches target.

Usage:
    python production/manual_sell_breakeven.py ANY 1.86 10587
"""

import sys
import os
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

from config import Config
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import LimitOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)-8s] %(message)s'
)
logger = logging.getLogger(__name__)

def place_limit_sell(symbol: str, target_price: float, qty: int):
    """
    Place a limit sell order immediately at target price.
    Order will auto-fill when symbol reaches that price.

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

    logger.info(f"Placing limit sell order for {symbol}")
    logger.info(f"  Qty: {qty:,} shares")
    logger.info(f"  Limit price: ${target_price:.2f}")

    try:
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
        logger.info(f"You can close this script — the order is now live on the market")

        return True

    except Exception as e:
        logger.error(f"Failed to place limit sell order: {e}")
        return False


if __name__ == '__main__':
    if len(sys.argv) != 4:
        print("Usage: python manual_sell_breakeven.py SYMBOL TARGET_PRICE QTY")
        print("Example: python manual_sell_breakeven.py ANY 1.86 10587")
        sys.exit(1)

    symbol = sys.argv[1].upper()
    target_price = float(sys.argv[2])
    qty = int(sys.argv[3])

    success = place_limit_sell(symbol, target_price, qty)
    sys.exit(0 if success else 1)
