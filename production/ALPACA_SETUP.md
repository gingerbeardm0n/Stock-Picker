# Alpaca Paper Trading Setup (3 Layers of Safety)

## Overview

This project uses **three layers of safety** to ensure you never accidentally trade with real money before you're ready:

1. **Layer 1: Forced Mode Selection** — Must choose PAPER or LIVE before any trading
2. **Layer 2: Separate Credentials** — Each mode has its own `.env` file with different API keys
3. **Layer 3: Runtime Verification** — Code verifies account type matches mode when connecting

## Quick Start

### Step 1: Get Your Alpaca Credentials

1. Go to [Alpaca Markets](https://alpaca.markets)
2. Sign up for a free account (if you haven't)
3. Open the **Paper Trading Dashboard**: https://app.alpaca.markets/paper/dashboard/home
4. Find your API Key and Secret Key
   - Click "View" next to "API Keys"
   - Copy the Key ID and Secret Key

### Step 2: Fill in `.env.paper`

Edit `.env.paper` and replace the placeholders:

```bash
TRADING_MODE=PAPER
APCA_API_KEY_ID=YOUR_PAPER_API_KEY_HERE       # ← Paste your paper API key
APCA_API_SECRET_KEY=YOUR_PAPER_SECRET_KEY_HERE  # ← Paste your paper secret key
APCA_API_BASE_URL=https://paper-api.alpaca.markets
DEBUG=False
```

### Step 3: Test the Connection

Set the environment variable and run the test:

```bash
export TRADING_MODE=PAPER
python production/connect_alpaca.py
```

You should see:
```
======================================================================
ALPACA TRADING CONNECTION TEST
======================================================================

✓ Layer 1-2: Config initialized
  Trading Mode: PAPER
  Base URL: https://paper-api.alpaca.markets

✓ Layer 3: Verifying connection to Alpaca...

======================================================================
✓ Connected to Alpaca PAPER trading account
  Base URL: https://paper-api.alpaca.markets
  Account Cash: $100,000.00
  Buying Power: $400,000.00
======================================================================

✓ All safety checks passed! Safe to trade.
```

---

## The 3 Layers Explained

### Layer 1: Forced Mode Selection

Before any code runs, you **must** set `TRADING_MODE=PAPER` or `TRADING_MODE=LIVE`:

```bash
# Correct way
export TRADING_MODE=PAPER
python my_trading_app.py

# Wrong way (will crash)
python my_trading_app.py
# Error: TRADING_MODE must be set to 'PAPER' or 'LIVE'
```

### Layer 2: Separate Credential Files

Each mode has its own `.env` file:

- **`.env.paper`** — Paper trading credentials (safe to test with)
- **`.env.live`** — Live trading credentials (for real money, fill in later)

The config loader automatically selects the correct file based on `TRADING_MODE`:

```python
# In production/config.py:
if trading_mode == 'PAPER':
    env_file = '.env.paper'  # Load paper credentials
elif trading_mode == 'LIVE':
    env_file = '.env.live'   # Load live credentials
```

**Both files are in `.gitignore`** — they never get committed to git, so your API keys stay secret.

### Layer 3: Runtime Verification

When you call `Config.verify_alpaca_connection()`, it:

1. Connects to Alpaca with the loaded credentials
2. Queries the account to check if it's paper or live
3. **Verifies the account type matches your mode**:
   - If `TRADING_MODE=PAPER` but account is LIVE → 🛑 ERROR, abort
   - If `TRADING_MODE=LIVE` but account is PAPER → 🛑 ERROR, abort
   - If they match → ✓ Safe to proceed

Example:

```python
from config import Config

# This will auto-check on first use
client = Config.verify_alpaca_connection()

# Now safe to trade
# client.submit_order(...)
```

---

## Example: Safe Trading Setup

### Paper Trading (Testing)

```bash
# Set mode
export TRADING_MODE=PAPER

# Run your app
python production/your_trading_app.py
```

Your app will:
1. Load credentials from `.env.paper`
2. Connect to `https://paper-api.alpaca.markets` (simulated trades, no real money)
3. Verify account is paper
4. Proceed with trading

### Live Trading (Real Money)

```bash
# ONLY do this after testing thoroughly on paper

# 1. Get your live API keys from https://app.alpaca.markets/dashboard/home
# 2. Fill them into .env.live
# 3. Set mode
export TRADING_MODE=LIVE

# 4. Run your app
python production/your_trading_app.py
```

Your app will:
1. Load credentials from `.env.live`
2. Connect to `https://api.alpaca.markets` (real trades, real money!)
3. Verify account is live
4. Proceed with trading

---

## Additional Safety: Account Funding

Until you fund your live account with real money, **it has $0 balance**. This provides a final backstop:

- Even if all three layers fail
- And your code connects to live trading
- It can't actually trade without money

So until you're ready:

```bash
# Live account has $0 in it
# Nothing bad can happen even if code connects
```

Only deposit money when you're confident in your strategy.

---

## Troubleshooting

### "TRADING_MODE must be set to 'PAPER' or 'LIVE'"

You forgot to set the environment variable:

```bash
# Fix:
export TRADING_MODE=PAPER
python production/connect_alpaca.py
```

### "Alpaca credentials not found in .env.paper"

You didn't fill in your API key and secret:

1. Open `.env.paper`
2. Replace `YOUR_PAPER_API_KEY_HERE` with your actual key from Alpaca
3. Replace `YOUR_PAPER_SECRET_KEY_HERE` with your actual secret

### "TRADING_MODE=PAPER but base URL is not paper API"

Your `.env.paper` has the wrong URL. It should be:
```
APCA_API_BASE_URL=https://paper-api.alpaca.markets
```

### "Failed to connect to Alpaca"

- Check that your API key is correct (copy from Alpaca again)
- Check that `.env.paper` exists and is readable
- Check that you have `alpaca-trade-api` installed:
  ```bash
  pip install alpaca-trade-api
  ```

---

## Summary

| Layer | What It Does | Failure Mode |
|---|---|---|
| **Layer 1** | Require `TRADING_MODE` env var | Code won't run without it |
| **Layer 2** | Separate `.env` files per mode | Wrong credentials loaded → connection fails |
| **Layer 3** | Verify account type at runtime | Account type mismatch → error, abort |
| **Bonus** | Live account unfunded | Even if all else fails, $0 balance = no loss |

This means you need **multiple things to go wrong simultaneously** to accidentally trade live money when you didn't intend to.

---

## Next Steps

Once you've tested paper trading and are happy with your strategy:

1. Get your live API keys from https://app.alpaca.markets/dashboard/home
2. Fill them into `.env.live`
3. Fund your live account with real money (start small!)
4. Set `export TRADING_MODE=LIVE`
5. Run your app

Good luck! 🚀
