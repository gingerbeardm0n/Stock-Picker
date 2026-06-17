"""
Config
======
Loads broker credentials from .env.paper or .env.live based on TRADING_MODE,
then exposes factory methods for creating the active broker + data feed.

Switching brokers requires only a one-line change in .env.paper / .env.live:
    BROKER=tradier   (default — use Tradier sandbox / live)
    BROKER=alpaca    (restore Alpaca — requires pip install alpaca-py)

.env.paper  — paper trading credentials
.env.live   — live trading credentials (requires TRADING_MODE=LIVE)

Tradier env vars:
    TRADIER_TOKEN=<paper or live token>
    TRADIER_ACCOUNT_ID=<account id>

Alpaca env vars (if BROKER=alpaca):
    APCA_API_KEY_ID=<key>
    APCA_API_SECRET_KEY=<secret>
    APCA_API_BASE_URL=https://paper-api.alpaca.markets  (paper)
                     or https://api.alpaca.markets       (live)
"""

import os
from dotenv import load_dotenv

# ── Layer 1: enforce trading mode before loading anything else ─────────────────

trading_mode = os.getenv('TRADING_MODE', 'PAPER').upper()

if trading_mode == 'PAPER':
    env_file = '.env.paper'
elif trading_mode == 'LIVE':
    env_file = '.env.live'
else:
    raise ValueError(
        f"ERROR: TRADING_MODE='{trading_mode}' is not valid.\n"
        f"Allowed values: PAPER (default) or LIVE.\n\n"
        f"  Windows cmd:        set TRADING_MODE=LIVE\n"
        f"  Windows PowerShell: $env:TRADING_MODE='LIVE'\n"
        f"  bash/git bash:      export TRADING_MODE=LIVE"
    )

load_dotenv(env_file)


class Config:
    # ── Layer 2: credentials + broker selection ────────────────────────────────

    TRADING_MODE = trading_mode

    # Active broker — set BROKER= in .env.paper / .env.live
    BROKER = os.getenv('BROKER', 'tradier').lower()

    # ── Tradier credentials ────────────────────────────────────────────────────
    TRADIER_PAPER_TOKEN      = os.getenv('TRADIER_PAPER_TOKEN', '')
    TRADIER_PRODUCTION_TOKEN = os.getenv('TRADIER_PRODUCTION_TOKEN', '')
    TRADIER_ACCOUNT_ID       = os.getenv('TRADIER_ACCOUNT_ID', '')
    # Backward-compat: legacy TRADIER_TOKEN key still works if new keys absent
    TRADIER_TOKEN = TRADIER_PAPER_TOKEN or os.getenv('TRADIER_TOKEN', '')

    # ── Alpaca credentials (optional — only needed if BROKER=alpaca) ──────────
    ALPACA_API_KEY    = os.getenv('APCA_API_KEY_ID', '')
    ALPACA_SECRET_KEY = os.getenv('APCA_API_SECRET_KEY', '')
    ALPACA_BASE_URL   = os.getenv('APCA_API_BASE_URL', '')

    # ── Other API keys ─────────────────────────────────────────────────────────
    FINNHUB_API_KEY = os.getenv('FINNHUB_API_KEY', '')
    MARKETAUX_API_KEY = os.getenv('MARKETAUX_API_KEY', '')

    # ── Scanner criteria — Ross Cameron's 5 Pillars ───────────────────────────
    SCANNER_CRITERIA = {
        'min_price':             2.0,
        'max_price':             20.0,
        'min_premarket_volume':  100000,
        'min_premarket_gain_pct': 10.0,
        'min_relative_volume':   5.0,
        'max_float':             20000000,
        'max_market_cap':        500000000,
        'max_spread':            0.15,
    }

    SCAN_INTERVAL   = 60     # seconds
    SIMULATION_TIME = None   # None = real-time

    DEBUG_STOCKS = [
        'F', 'NIO', 'LCID', 'RIVN', 'RIDE', 'GOEV', 'FSR', 'WKHS', 'NKLA', 'HYLN',
        'PLUG', 'FCEL', 'CHPT', 'BLNK', 'CLNE', 'GEVO', 'BEEM', 'TELL', 'REI', 'BE',
        'NOK', 'ERIC', 'VEON', 'ATUS', 'VIV', 'TIGO', 'TDS',
        'SOFI', 'UPST', 'LC', 'UWMC', 'RKT', 'OPEN', 'CLOV', 'ROOT', 'BEAM',
        'SAVA', 'OCGN', 'VXRT', 'BNGO', 'ONTX', 'SNDL', 'NVAX', 'VERU', 'OBSV', 'ADMA',
        'AMC', 'BBBY', 'GME', 'KOSS', 'EXPR', 'FIZZ', 'BARK', 'IMMP',
        'SNAP', 'PLTR', 'BB', 'WISH', 'SPCE', 'DKNG', 'SKLZ', 'BRZE', 'AI', 'BBAI',
        'MARA', 'RIOT', 'BTBT', 'CAN', 'MOGO', 'SOS', 'EBON', 'MGTI', 'GREE',
        'WBA', 'AAL', 'UAL', 'CCL', 'SAVE', 'JBLU', 'ALK', 'HA', 'AZUL',
        'MULN', 'XPEV', 'LI', 'BABA', 'JD', 'PDD', 'BIDU', 'IQ', 'VIPS', 'BILI',
    ]

    # ── Factory methods ────────────────────────────────────────────────────────

    @classmethod
    def get_broker(cls):
        """
        Create and return the active BrokerInterface implementation.
        Broker is determined by BROKER= in the active .env file.

        Returns a connected, ready-to-use BrokerInterface.
        Raises ValueError if required credentials are missing.
        """
        if cls.BROKER == 'tradier':
            return cls._make_tradier_broker()
        if cls.BROKER == 'alpaca':
            return cls._make_alpaca_broker()
        raise ValueError(
            f"Unknown BROKER='{cls.BROKER}' in {env_file}.\n"
            f"Valid values: tradier (default), alpaca"
        )

    @classmethod
    def get_data_feed(cls):
        """
        Create and return the active DataFeedInterface implementation.
        Uses the same BROKER= setting as get_broker().

        Returns a DataFeedInterface instance.
        Raises ValueError if required credentials are missing.
        """
        if cls.BROKER == 'tradier':
            return cls._make_tradier_data_feed()
        if cls.BROKER == 'alpaca':
            return cls._make_alpaca_data_feed()
        raise ValueError(
            f"Unknown BROKER='{cls.BROKER}' in {env_file}.\n"
            f"Valid values: tradier (default), alpaca"
        )

    # ── Private broker constructors ────────────────────────────────────────────

    @classmethod
    def _make_tradier_broker(cls):
        from trading.broker.tradier import TradierBroker
        sandbox = (cls.TRADING_MODE == 'PAPER')
        token   = cls.TRADIER_PAPER_TOKEN if sandbox else cls.TRADIER_PRODUCTION_TOKEN
        if not token or not cls.TRADIER_ACCOUNT_ID:
            raise ValueError(
                f"ERROR: Tradier credentials not found in {env_file}.\n"
                f"Paper mode needs TRADIER_PAPER_TOKEN + TRADIER_ACCOUNT_ID.\n"
                f"Live mode needs TRADIER_PRODUCTION_TOKEN + TRADIER_ACCOUNT_ID."
            )
        broker  = TradierBroker(
            token=token,
            account_id=cls.TRADIER_ACCOUNT_ID,
            sandbox=sandbox,
        )
        # Verify connection and print account info
        try:
            balance = broker.get_account_balance()
            print("\n" + "=" * 70)
            print(f"[OK] Connected to Tradier {'sandbox (paper)' if sandbox else 'LIVE'}")
            print(f"  Account:  {cls.TRADIER_ACCOUNT_ID}")
            print(f"  Balance:  ${balance:,.2f}")
            print("=" * 70 + "\n")
        except Exception as e:
            raise RuntimeError(
                f"Failed to connect to Tradier:\n{e}\n\n"
                f"Check TRADIER_TOKEN and TRADIER_ACCOUNT_ID in {env_file}"
            )
        return broker

    @classmethod
    def _make_tradier_data_feed(cls):
        from trading.broker.tradier import TradierDataFeed
        # Data feed always uses production token for real market data.
        # Falls back to paper token (15-min delayed) if production not set.
        token = cls.TRADIER_PRODUCTION_TOKEN or cls.TRADIER_PAPER_TOKEN
        if not token:
            raise ValueError(
                f"ERROR: No Tradier token found in {env_file}.\n"
                f"Set TRADIER_PRODUCTION_TOKEN for real market data."
            )
        # sandbox=False when using production token (real market data endpoint)
        sandbox = not bool(cls.TRADIER_PRODUCTION_TOKEN)
        return TradierDataFeed(
            token=token,
            sandbox=sandbox,
        )

    @classmethod
    def _make_alpaca_broker(cls):
        from trading.broker.alpaca import AlpacaBroker
        if not cls.ALPACA_API_KEY or not cls.ALPACA_SECRET_KEY:
            raise ValueError(
                f"ERROR: Alpaca credentials not found in {env_file}.\n"
                f"Add APCA_API_KEY_ID and APCA_API_SECRET_KEY."
            )
        # URL sanity check: paper mode should not hit live API
        if cls.TRADING_MODE == 'PAPER' and cls.ALPACA_BASE_URL and \
                'paper-api' not in cls.ALPACA_BASE_URL:
            raise ValueError(
                f"ERROR: TRADING_MODE=PAPER but APCA_API_BASE_URL is not paper API.\n"
                f"Got: {cls.ALPACA_BASE_URL}\n"
                f"Expected: https://paper-api.alpaca.markets"
            )
        if cls.ALPACA_BASE_URL:
            os.environ['APCA_API_BASE_URL'] = cls.ALPACA_BASE_URL
        is_paper = (cls.TRADING_MODE == 'PAPER')
        broker = AlpacaBroker(api_key=cls.ALPACA_API_KEY, secret_key=cls.ALPACA_SECRET_KEY,
                              paper=is_paper)
        try:
            balance = broker.get_account_balance()
            print("\n" + "=" * 70)
            print(f"[OK] Connected to Alpaca {cls.TRADING_MODE}")
            print(f"  Balance: ${balance:,.2f}")
            print("=" * 70 + "\n")
        except Exception as e:
            raise RuntimeError(f"Failed to connect to Alpaca:\n{e}")
        return broker

    @classmethod
    def _make_alpaca_data_feed(cls):
        from trading.broker.alpaca import AlpacaDataFeed
        if not cls.ALPACA_API_KEY or not cls.ALPACA_SECRET_KEY:
            raise ValueError(
                f"ERROR: Alpaca credentials not found in {env_file}."
            )
        return AlpacaDataFeed(
            api_key=cls.ALPACA_API_KEY,
            secret_key=cls.ALPACA_SECRET_KEY,
        )

    # ── Legacy helper — kept for any scripts still calling it ─────────────────

    @classmethod
    def verify_alpaca_connection(cls):
        """
        Deprecated: use Config.get_broker() instead.
        Kept for backward compatibility with scripts that still call this directly.
        """
        import warnings
        warnings.warn(
            "Config.verify_alpaca_connection() is deprecated. "
            "Use Config.get_broker() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return cls._make_alpaca_broker()
