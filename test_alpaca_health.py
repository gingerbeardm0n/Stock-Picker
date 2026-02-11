#!/usr/bin/env python3
"""
Alpaca API Health Check
Tests that all required Alpaca API endpoints are working correctly.
"""

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockSnapshotRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from datetime import datetime, timedelta
from config import Config
import sys

def test_authentication():
    """Test 1: API authentication"""
    print("=" * 60)
    print("TEST 1: Authentication")
    print("=" * 60)
    try:
        client = TradingClient(
            Config.ALPACA_API_KEY,
            Config.ALPACA_SECRET_KEY,
            paper=Config.ALPACA_PAPER_TRADING
        )
        account = client.get_account()
        print(f"✓ Authentication successful")
        print(f"  Account: {account.account_number}")
        print(f"  Status: {account.status}")
        return True
    except Exception as e:
        print(f"✗ Authentication failed: {e}")
        return False

def test_get_assets():
    """Test 2: Get tradable assets"""
    print("\n" + "=" * 60)
    print("TEST 2: Get Tradable Assets")
    print("=" * 60)
    try:
        client = TradingClient(
            Config.ALPACA_API_KEY,
            Config.ALPACA_SECRET_KEY,
            paper=Config.ALPACA_PAPER_TRADING
        )
        assets = client.get_all_assets()
        active_stocks = [a for a in assets if a.tradable and a.status == 'active']
        print(f"✓ Retrieved {len(active_stocks):,} tradable stocks")
        print(f"  Sample: {', '.join([a.symbol for a in active_stocks[:5]])}")
        return True
    except Exception as e:
        print(f"✗ Failed to get assets: {e}")
        return False

def test_get_snapshots():
    """Test 3: Get stock snapshots"""
    print("\n" + "=" * 60)
    print("TEST 3: Get Stock Snapshots")
    print("=" * 60)
    try:
        client = StockHistoricalDataClient(
            Config.ALPACA_API_KEY,
            Config.ALPACA_SECRET_KEY
        )
        test_symbols = ['AAPL', 'MSFT', 'TSLA']
        request = StockSnapshotRequest(symbol_or_symbols=test_symbols)
        snapshots = client.get_stock_snapshot(request)

        print(f"✓ Retrieved snapshots for {len(snapshots)} symbols")
        for symbol in test_symbols:
            if symbol in snapshots:
                price = snapshots[symbol].latest_trade.price
                print(f"  {symbol}: ${price:.2f}")
        return True
    except Exception as e:
        print(f"✗ Failed to get snapshots: {e}")
        return False

def test_get_daily_bars():
    """Test 4: Get daily bars"""
    print("\n" + "=" * 60)
    print("TEST 4: Get Daily Bars (20 days)")
    print("=" * 60)
    try:
        client = StockHistoricalDataClient(
            Config.ALPACA_API_KEY,
            Config.ALPACA_SECRET_KEY
        )
        end = datetime.now()
        start = end - timedelta(days=25)

        request = StockBarsRequest(
            symbol_or_symbols='AAPL',
            timeframe=TimeFrame.Day,
            start=start,
            end=end
        )
        bars = client.get_stock_bars(request)

        if 'AAPL' in bars.data:
            bar_count = len(bars.data['AAPL'])
            latest = bars.data['AAPL'][-1]
            print(f"✓ Retrieved {bar_count} daily bars")
            print(f"  Latest: {latest.timestamp.date()} - Close: ${latest.close:.2f}")
            return True
        else:
            print("✗ No bars returned")
            return False
    except Exception as e:
        print(f"✗ Failed to get daily bars: {e}")
        return False

def test_get_hour_bars():
    """Test 5: Get hourly premarket bars"""
    print("\n" + "=" * 60)
    print("TEST 5: Get Hour Bars (Premarket)")
    print("=" * 60)
    try:
        client = StockHistoricalDataClient(
            Config.ALPACA_API_KEY,
            Config.ALPACA_SECRET_KEY
        )

        # Get premarket hours from today (4am-9:30am ET)
        import pytz
        et = pytz.timezone('US/Eastern')
        now = datetime.now(et)
        start = now.replace(hour=4, minute=0, second=0, microsecond=0)
        end = now.replace(hour=9, minute=30, second=0, microsecond=0)

        request = StockBarsRequest(
            symbol_or_symbols='AAPL',
            timeframe=TimeFrame.Hour,
            start=start.astimezone(pytz.utc).replace(tzinfo=None),
            end=end.astimezone(pytz.utc).replace(tzinfo=None)
        )
        bars = client.get_stock_bars(request)

        if 'AAPL' in bars.data:
            bar_count = len(bars.data['AAPL'])
            print(f"✓ Retrieved {bar_count} hour bars")
            if bar_count > 0:
                total_volume = sum(bar.volume for bar in bars.data['AAPL'])
                print(f"  Total PM volume: {total_volume:,}")
            return True
        else:
            print("✗ No bars returned")
            return False
    except Exception as e:
        print(f"✗ Failed to get hour bars: {e}")
        return False

def main():
    """Run all health checks"""
    print("\n🏥 ALPACA API HEALTH CHECK")
    print(f"Using {'Paper Trading' if Config.ALPACA_PAPER_TRADING else 'Live Trading'} Account")
    print(f"API Key: {Config.ALPACA_API_KEY[:8]}...{Config.ALPACA_API_KEY[-4:]}\n")

    tests = [
        test_authentication,
        test_get_assets,
        test_get_snapshots,
        test_get_daily_bars,
        test_get_hour_bars
    ]

    results = [test() for test in tests]

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    passed = sum(results)
    total = len(results)
    print(f"Tests passed: {passed}/{total}")

    if passed == total:
        print("\n✓ All tests passed - Alpaca API is working correctly!")
        return 0
    else:
        print(f"\n✗ {total - passed} test(s) failed - Check your API configuration")
        return 1

if __name__ == "__main__":
    sys.exit(main())
