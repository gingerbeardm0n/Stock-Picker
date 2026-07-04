"""
Quick smoke test — buy 1 share of SPY, then immediately market-sell it.
Run from repo root: python research/test_alpaca_paper_order.py

Works premarket (4am-9:30am ET) and during market hours.
Extended hours uses limit orders (market orders blocked premarket by Alpaca).
"""
import os, time
from dotenv import load_dotenv
load_dotenv("production/.env.paper")

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest

KEY = os.environ["APCA_PAPER_KEY_ID"]
SECRET = os.environ["APCA_PAPER_SECRET_KEY"]
client = TradingClient(KEY, SECRET, paper=True)
data_client = StockHistoricalDataClient(
    os.environ["APCA_API_KEY_ID"], os.environ["APCA_API_SECRET_KEY"]
)

# Show balance
acct = client.get_account()
print(f"Account equity: ${float(acct.equity):,.2f}  buying_power: ${float(acct.buying_power):,.2f}")

# Cancel any open orders from prior runs
open_orders = client.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN))
if open_orders:
    print(f"\nCancelling {len(open_orders)} open order(s) from prior run...")
    client.cancel_orders()
    time.sleep(2)

# Get current SPY quote for limit price
quote = data_client.get_stock_latest_quote(StockLatestQuoteRequest(symbol_or_symbols="SPY"))
ask = float(quote["SPY"].ask_price)
bid = float(quote["SPY"].bid_price)
mid = round((ask + bid) / 2, 2)
print(f"\nSPY bid={bid}  ask={ask}  using limit={mid + 0.10:.2f} (mid+0.10 to ensure fill)")
limit_price = round(mid + 0.10, 2)

# Buy 1 share
print("\nPlacing BUY 1 SPY (limit, extended_hours)...")
buy = client.submit_order(LimitOrderRequest(
    symbol="SPY",
    qty=1,
    side=OrderSide.BUY,
    time_in_force=TimeInForce.DAY,
    limit_price=limit_price,
    extended_hours=True,
))
print(f"  Buy order id: {buy.id}  status: {buy.status}")

# Poll until filled
print("Polling until filled (max 60s)...")
filled = False
for _ in range(20):
    time.sleep(3)
    order = client.get_order_by_id(buy.id)
    print(f"  status: {order.status}  filled_avg_price: {order.filled_avg_price}")
    if order.status in ("filled", "partially_filled"):
        filled = True
        break

if not filled:
    print("  Not filled after 60s — aborting. Market may not be open yet.")
    raise SystemExit(1)

# Sell 1 share (limit slightly below mid to ensure fill)
sell_limit = round(mid - 0.10, 2)
print(f"\nPlacing SELL 1 SPY (limit={sell_limit:.2f}, extended_hours)...")
sell = client.submit_order(LimitOrderRequest(
    symbol="SPY",
    qty=1,
    side=OrderSide.SELL,
    time_in_force=TimeInForce.DAY,
    limit_price=sell_limit,
    extended_hours=True,
))
print(f"  Sell order id: {sell.id}  status: {sell.status}")

for _ in range(10):
    time.sleep(3)
    order2 = client.get_order_by_id(sell.id)
    print(f"  status: {order2.status}  filled_avg_price: {order2.filled_avg_price}")
    if order2.status in ("filled", "partially_filled"):
        break

print("\nDone. Alpaca paper broker working.")
