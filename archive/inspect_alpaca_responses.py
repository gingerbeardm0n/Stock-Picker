#!/usr/bin/env python3
"""
Alpaca API Response Inspector
Calls all Alpaca endpoints we use and prints the EXACT raw JSON responses.
This helps us design the TimescaleDB schema by seeing the actual data structure.
"""

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockSnapshotRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from datetime import datetime, timedelta
from config import Config
import json
import pytz

def print_section(title):
    """Print a formatted section header"""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80 + "\n")

def print_json(obj, title=""):
    """Pretty print object as JSON"""
    if title:
        print(f"\n--- {title} ---")

    # Convert Alpaca objects to dict for JSON serialization
    if hasattr(obj, '__dict__'):
        obj_dict = {}
        for key, value in obj.__dict__.items():
            if hasattr(value, '__dict__'):
                obj_dict[key] = value.__dict__
            elif isinstance(value, datetime):
                obj_dict[key] = value.isoformat()
            else:
                obj_dict[key] = value
        print(json.dumps(obj_dict, indent=2, default=str))
    else:
        print(json.dumps(obj, indent=2, default=str))

def inspect_trading_client():
    """Inspect Trading API responses"""
    print_section("1. TRADING CLIENT - Account Info")

    client = TradingClient(
        Config.ALPACA_API_KEY,
        Config.ALPACA_SECRET_KEY,
        paper=Config.ALPACA_PAPER_TRADING
    )

    # Get account
    account = client.get_account()
    print_json(account, "Account Object")

    print_section("2. TRADING CLIENT - Asset List")

    # Get all assets (just show first 3)
    assets = client.get_all_assets()
    active_stocks = [a for a in assets if a.tradable and a.status == 'active']

    print(f"\nTotal active stocks: {len(active_stocks)}")
    print("\nFirst 3 assets:")
    for asset in active_stocks[:3]:
        print_json(asset, f"Asset: {asset.symbol}")

def inspect_snapshot():
    """Inspect Snapshot API response"""
    print_section("3. SNAPSHOT - Current Price Data")

    client = StockHistoricalDataClient(
        Config.ALPACA_API_KEY,
        Config.ALPACA_SECRET_KEY
    )

    test_symbols = ['AAPL', 'TSLA', 'NVDA']
    request = StockSnapshotRequest(symbol_or_symbols=test_symbols)
    snapshots = client.get_stock_snapshot(request)

    print(f"Requested symbols: {test_symbols}")
    print(f"Returned: {len(snapshots)} snapshots\n")

    for symbol, snapshot in snapshots.items():
        print_json(snapshot, f"Snapshot: {symbol}")

        # Also show the nested objects explicitly
        if snapshot.latest_trade:
            print(f"\n  latest_trade attributes:")
            for attr in dir(snapshot.latest_trade):
                if not attr.startswith('_'):
                    print(f"    {attr}: {getattr(snapshot.latest_trade, attr, None)}")

        if snapshot.latest_quote:
            print(f"\n  latest_quote attributes:")
            for attr in dir(snapshot.latest_quote):
                if not attr.startswith('_'):
                    print(f"    {attr}: {getattr(snapshot.latest_quote, attr, None)}")

        break  # Just show one in detail

def inspect_daily_bars():
    """Inspect Daily Bars API response"""
    print_section("4. DAILY BARS - Historical Volume Data")

    client = StockHistoricalDataClient(
        Config.ALPACA_API_KEY,
        Config.ALPACA_SECRET_KEY
    )

    end = datetime.now()
    start = end - timedelta(days=25)

    request = StockBarsRequest(
        symbol_or_symbols=['AAPL'],
        timeframe=TimeFrame.Day,
        start=start,
        end=end
    )
    bars = client.get_stock_bars(request)

    print(f"Requested: 20 days of daily bars for AAPL")
    print(f"Returned: {len(bars.data.get('AAPL', []))} bars\n")

    if 'AAPL' in bars.data and len(bars.data['AAPL']) > 0:
        # Show first bar in detail
        first_bar = bars.data['AAPL'][0]
        print_json(first_bar, "First Daily Bar")

        # Show attributes
        print(f"\nBar attributes:")
        for attr in dir(first_bar):
            if not attr.startswith('_'):
                print(f"  {attr}: {getattr(first_bar, attr, None)}")

        # Show last bar
        last_bar = bars.data['AAPL'][-1]
        print_json(last_bar, "Last Daily Bar")

def inspect_hour_bars():
    """Inspect Hour Bars API response (for premarket)"""
    print_section("5. HOUR BARS - Premarket Volume Data")

    client = StockHistoricalDataClient(
        Config.ALPACA_API_KEY,
        Config.ALPACA_SECRET_KEY
    )

    # Get 14 days of hour bars
    end = datetime.now()
    start = end - timedelta(days=14)

    request = StockBarsRequest(
        symbol_or_symbols=['AAPL'],
        timeframe=TimeFrame.Hour,
        start=start,
        end=end
    )
    bars = client.get_stock_bars(request)

    print(f"Requested: 14 days of hour bars for AAPL")
    print(f"Returned: {len(bars.data.get('AAPL', []))} bars\n")

    if 'AAPL' in bars.data and len(bars.data['AAPL']) > 0:
        # Show first bar in detail
        first_bar = bars.data['AAPL'][0]
        print_json(first_bar, "First Hour Bar")

        # Show a few bars with timestamps to see time pattern
        print(f"\nFirst 10 hour bars (to see time pattern):")
        for i, bar in enumerate(bars.data['AAPL'][:10]):
            et = pytz.timezone('US/Eastern')
            timestamp_et = bar.timestamp.astimezone(et)
            print(f"  {i+1}. {timestamp_et.strftime('%Y-%m-%d %H:%M %Z')} - "
                  f"Vol: {bar.volume:,} - Close: ${bar.close:.2f}")

def inspect_batch_responses():
    """Inspect batch API responses"""
    print_section("6. BATCH REQUESTS - Multiple Symbols")

    client = StockHistoricalDataClient(
        Config.ALPACA_API_KEY,
        Config.ALPACA_SECRET_KEY
    )

    test_symbols = ['AAPL', 'TSLA', 'NVDA', 'AMD', 'MSFT']

    # Batch snapshots
    print(f"Batch snapshot request for {len(test_symbols)} symbols:")
    request = StockSnapshotRequest(symbol_or_symbols=test_symbols)
    snapshots = client.get_stock_snapshot(request)

    print(f"Returned: {len(snapshots)} snapshots")
    print(f"Symbols: {list(snapshots.keys())}\n")

    # Show structure of batch response
    print("Batch response structure:")
    print(f"  Type: {type(snapshots)}")
    print(f"  Keys: {list(snapshots.keys())[:3]}...")
    print(f"  Sample value type: {type(list(snapshots.values())[0])}")

    # Batch daily bars
    print(f"\nBatch daily bars request for {len(test_symbols)} symbols:")
    end = datetime.now()
    start = end - timedelta(days=20)

    request = StockBarsRequest(
        symbol_or_symbols=test_symbols,
        timeframe=TimeFrame.Day,
        start=start,
        end=end
    )
    bars = client.get_stock_bars(request)

    print(f"Returned data for: {len(bars.data)} symbols")
    for symbol, symbol_bars in bars.data.items():
        print(f"  {symbol}: {len(symbol_bars)} bars")

def main():
    """Run all inspections"""
    print("\n")
    print("+" + "=" * 78 + "+")
    print("|" + " " * 20 + "ALPACA API RESPONSE INSPECTOR" + " " * 29 + "|")
    print("|" + " " * 15 + "Showing EXACT raw responses for database design" + " " * 15 + "|")
    print("+" + "=" * 78 + "+")

    print(f"\nUsing {'Paper Trading' if Config.ALPACA_PAPER_TRADING else 'Live Trading'} Account")
    print(f"API Key: {Config.ALPACA_API_KEY[:8]}...{Config.ALPACA_API_KEY[-4:]}")

    try:
        inspect_trading_client()
        inspect_snapshot()
        inspect_daily_bars()
        inspect_hour_bars()
        inspect_batch_responses()

        print_section("INSPECTION COMPLETE")
        print("[OK] All API responses captured above")
        print("[OK] Use this data to design your TimescaleDB schema")
        print("\nNext steps:")
        print("  1. Review the JSON structures above")
        print("  2. Design database tables based on these fields")
        print("  3. Create TimescaleDB schema with appropriate data types")

    except Exception as e:
        print(f"\n[ERROR] Error during inspection: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
