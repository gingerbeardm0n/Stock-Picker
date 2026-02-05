import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Alpaca API credentials
    ALPACA_API_KEY = os.getenv('ALPACA_API_KEY', 'PKZFIDXKFLX4VRQISD6U3BGTLA')
    ALPACA_SECRET_KEY = os.getenv('ALPACA_SECRET_KEY', '2YcCyqVdRK1etYkYz9aSbRPbgKtVLNTTx3emcH2JWDdN')
    ALPACA_BASE_URL = 'https://paper-api.alpaca.markets/v2'  # Paper trading

    # Scanner criteria (Ross Cameron style)
    SCANNER_CRITERIA = {
        'min_price': 1.0,
        'max_price': 10.0,
        'min_premarket_volume': 100000,
        'min_premarket_gain_pct': 10.0,
        'max_float': 50000000,  # 50M shares
        'min_relative_volume': 2.0,  # 2x average volume
        'min_avg_volume': 100000,
        'max_avg_volume': 5000000
    }

    # Update frequency
    SCAN_INTERVAL = 60  # seconds
