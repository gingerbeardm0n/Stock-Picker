import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Alpaca API credentials
    ALPACA_API_KEY = os.getenv('ALPACA_API_KEY', '')
    ALPACA_SECRET_KEY = os.getenv('ALPACA_SECRET_KEY', '')
    ALPACA_BASE_URL = 'https://api.alpaca.markets'  # Live trading (data access)
    ALPACA_PAPER_TRADING = False  # Set to True if using paper trading keys

    # Finnhub API key (free tier — get at finnhub.io, used for float + market cap)
    FINNHUB_API_KEY = os.getenv('FINNHUB_API_KEY', '')

    # Scanner criteria — Ross Cameron's 5 Pillars (v2 Page 4-5)
    SCANNER_CRITERIA = {
        'min_price': 2.0,               # Ross v2 p4: $2-$20 sweet spot
        'max_price': 20.0,
        'min_premarket_volume': 100000,  # Absolute PM shares (4am-9:30am)
        'min_premarket_gain_pct': 10.0,  # Ross v2 p4: up 10%+ from prior close
        'min_relative_volume': 5.0,      # Ross v2 p4: 5x min, 10x+ preferred
        'max_float': 20000000,           # Ross v2 p4: <20M shares (Pillar 4)
        'max_market_cap': 500000000,     # Ross v2 p5: <$500M small/micro-cap
        'max_spread': 0.15              # Ross v2 p9: <10-15 cents spread
    }

    # Update frequency
    SCAN_INTERVAL = 60  # seconds

    # Testing / Simulation
    # Set to a datetime string (YYYY-MM-DD HH:MM) to simulate that time for testing
    # Example: '2024-02-05 09:15' to simulate 9:15am on Feb 5, 2024
    SIMULATION_TIME = None  # None = use real-time

    # Debug test stocks (100 high-volume stocks under $20 for testing)
    DEBUG_STOCKS = [
        # Auto/Transportation ($1-$10)
        'F', 'NIO', 'LCID', 'RIVN', 'RIDE', 'GOEV', 'FSR', 'WKHS', 'NKLA', 'HYLN',

        # Energy/Clean Tech ($1-$10)
        'PLUG', 'FCEL', 'CHPT', 'BLNK', 'CLNE', 'GEVO', 'BEEM', 'TELL', 'REI', 'BE',

        # Telecom/Media ($1-$10)
        'NOK', 'ERIC', 'VEON', 'ATUS', 'VIV', 'TIGO', 'TDS',

        # Finance/Fintech ($1-$10)
        'SOFI', 'UPST', 'LC', 'UWMC', 'RKT', 'OPEN', 'CLOV', 'ROOT', 'BEAM',

        # Biotech/Pharma ($1-$10)
        'SAVA', 'OCGN', 'VXRT', 'BNGO', 'ONTX', 'SNDL', 'NVAX', 'VERU', 'OBSV', 'ADMA',

        # Retail/Consumer ($1-$10)
        'AMC', 'BBBY', 'GME', 'KOSS', 'EXPR', 'FIZZ', 'BARK', 'IMMP',

        # Tech/Software ($1-$10)
        'SNAP', 'PLTR', 'BB', 'WISH', 'SPCE', 'DKNG', 'SKLZ', 'BRZE', 'AI', 'BBAI',

        # Crypto/Blockchain ($1-$10)
        'MARA', 'RIOT', 'BTBT', 'CAN', 'MOGO', 'SOS', 'EBON', 'MGTI', 'GREE',

        # Industrials ($1-$10)
        'WBA', 'AAL', 'UAL', 'CCL', 'SAVE', 'JBLU', 'ALK', 'HA', 'AZUL',

        # Other High Volume ($1-$10)
        'MULN', 'XPEV', 'LI', 'BABA', 'JD', 'PDD', 'BIDU', 'IQ', 'VIPS', 'BILI'
    ]
