#!/usr/bin/env python3
"""
Simple test script to verify Alpaca API credentials
"""
import os
from dotenv import load_dotenv
from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest

# Load environment variables
load_dotenv()

api_key = os.getenv('ALPACA_API_KEY')
secret_key = os.getenv('ALPACA_SECRET_KEY')

print("=" * 60)
print("ALPACA API TEST")
print("=" * 60)
print(f"\n✓ API Key loaded: {api_key[:8]}...{api_key[-4:]}")
print(f"✓ Secret Key loaded: {secret_key[:8]}...{secret_key[-4:]}")

# Test Trading API (for account info)
print("\n" + "=" * 60)
print("Testing Trading API (Account Info)...")
print("=" * 60)
try:
    trading_client = TradingClient(api_key, secret_key, paper=True)
    account = trading_client.get_account()
    print(f"✅ SUCCESS! Account Status: {account.status}")
    print(f"   Account Number: {account.account_number}")
    print(f"   Buying Power: ${account.buying_power}")
except Exception as e:
    print(f"❌ FAILED: {type(e).__name__}: {e}")

# Test Market Data API
print("\n" + "=" * 60)
print("Testing Market Data API (Stock Quote)...")
print("=" * 60)
try:
    data_client = StockHistoricalDataClient(api_key, secret_key)
    request = StockLatestQuoteRequest(symbol_or_symbols="AAPL")
    quote = data_client.get_stock_latest_quote(request)
    print(f"✅ SUCCESS! Got quote for AAPL")
    print(f"   Bid: ${quote['AAPL'].bid_price}")
    print(f"   Ask: ${quote['AAPL'].ask_price}")
except Exception as e:
    print(f"❌ FAILED: {type(e).__name__}: {e}")
    print("\n💡 This likely means you need to:")
    print("   1. Accept the Market Data Agreement in your Alpaca dashboard")
    print("   2. Enable 'Market Data' subscription (free for paper trading)")
    print("   3. Wait a few minutes for API keys to activate")

print("\n" + "=" * 60)
print("Test complete!")
print("=" * 60)
