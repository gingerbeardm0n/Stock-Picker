"""
Safe Alpaca Trading Connection with 3 Layers of Safety

USAGE:
  # For paper trading:
  export TRADING_MODE=PAPER
  python production/connect_alpaca.py

  # For live trading (ONLY after testing thoroughly on paper):
  export TRADING_MODE=LIVE
  python production/connect_alpaca.py
"""

import sys
import os

# Add production dir to path so we can import config
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from config import Config


def main():
    """
    Initialize and verify connection to Alpaca.
    This is your entry point for any trading application.
    """

    print("\n" + "="*70)
    print("ALPACA TRADING CONNECTION TEST")
    print("="*70)

    # LAYER 1 + 2: Automatic on import of Config
    print(f"\n✓ Layer 1-2: Config initialized")
    print(f"  Trading Mode: {Config.TRADING_MODE}")
    print(f"  Base URL: {Config.ALPACA_BASE_URL}")

    # LAYER 3: Verify actual connection
    print(f"\n✓ Layer 3: Verifying connection to Alpaca...")
    try:
        client = Config.verify_alpaca_connection()
        print("\n✓ All safety checks passed! Safe to trade.")
        return client

    except ValueError as e:
        print(f"\n✗ Configuration error:\n{e}")
        sys.exit(1)

    except RuntimeError as e:
        print(f"\n✗ Critical safety violation:\n{e}")
        sys.exit(1)


if __name__ == "__main__":
    client = main()

    # Example: Query some basic account info
    account = client.get_account()
    print(f"\nAccount Summary:")
    print(f"  Equity: ${float(account.equity):,.2f}")
    print(f"  Cash: ${float(account.cash):,.2f}")
    print(f"  Buying Power: ${float(account.buying_power):,.2f}")
    print(f"  Day Trading Buying Power: ${float(account.daytrading_buying_power):,.2f}")
