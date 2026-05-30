#!/usr/bin/env python3
"""
Live Stock Data Collector
Runs continuously, collecting 1-minute candles into TimescaleDB.

Schedule:
  - 4:00 AM ET each day: refresh stock universe from stocks_1_to_20.txt
  - 4:00 AM - 8:00 PM ET: fetch latest minute bars every 60 seconds
  - Outside hours: sleep and wait

Usage:
  source venv/Scripts/activate
  python data/collector/collect_data.py
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

import psycopg2
from psycopg2.extras import execute_values
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from datetime import datetime, timedelta
from config import Config
from dotenv import load_dotenv
import time
import pytz
import logging
import logging.handlers

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────

DB_CONN = os.getenv('TIMESCALE_CONNECTION_STRING',
                    'postgresql://postgres:yourpassword@localhost:5432/stockdata')

_services_file  = os.path.join(os.path.dirname(__file__), '../../services/stocks_in_price_range.txt')
_database_file  = os.path.join(os.path.dirname(__file__), '../../../database/stocks_1_to_20.txt')
STOCKS_FILE = _services_file if os.path.exists(_services_file) else _database_file
LOG_FILE    = os.path.join(os.path.dirname(__file__), 'collector.log')

MARKET_OPEN_HOUR  = 4   # 4 AM ET (pre-market opens)
MARKET_CLOSE_HOUR = 20  # 8 PM ET (after-hours closes)
COLLECT_INTERVAL  = 60  # seconds between collections
LOOKBACK_MINUTES  = 5   # fetch last N minutes each tick (catches gaps)
BATCH_SIZE        = 500 # symbols per API call

ET = pytz.timezone('America/New_York')

# ── Logging ───────────────────────────────────────────────────────────────────

def setup_logging():
    """Log to both console and a daily rotating file."""
    fmt = logging.Formatter(
        '%(asctime)s [%(levelname)-8s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Rotating file: new file each day, keep 7 days of history
    file_handler = logging.handlers.TimedRotatingFileHandler(
        LOG_FILE, when='midnight', backupCount=7, encoding='utf-8'
    )
    file_handler.setFormatter(fmt)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(console_handler)

logger = logging.getLogger(__name__)

# ── Symbol loading ─────────────────────────────────────────────────────────────

def load_symbols():
    """Load stock universe from stocks_1_to_20.txt"""
    if not os.path.exists(STOCKS_FILE):
        logger.error(f"Symbol file not found: {STOCKS_FILE}")
        logger.error("Run: python production/services/fetch_stocks_in_price_range.py")
        return []

    with open(STOCKS_FILE) as f:
        symbols = [line.strip() for line in f if line.strip()]

    logger.info(f"Loaded {len(symbols):,} symbols from {os.path.basename(STOCKS_FILE)}")
    return symbols

# ── Database ───────────────────────────────────────────────────────────────────

def get_db():
    return psycopg2.connect(DB_CONN, connect_timeout=10)

def insert_bars(bars_by_symbol):
    """Batch insert minute bars into stock_candles_1m."""
    values = []
    for symbol, bars in bars_by_symbol.items():
        for bar in bars:
            values.append((
                bar.timestamp,
                symbol,
                float(bar.open),
                float(bar.high),
                float(bar.low),
                float(bar.close),
                int(bar.volume),
                int(bar.trade_count) if bar.trade_count else None,
                float(bar.vwap) if bar.vwap else None
            ))

    if not values:
        return 0

    conn = get_db()
    cursor = conn.cursor()
    execute_values(
        cursor,
        """
        INSERT INTO stock_candles_1m
            (time, symbol, open, high, low, close, volume, trade_count, vwap)
        VALUES %s
        ON CONFLICT (time, symbol) DO NOTHING
        """,
        values
    )
    conn.commit()
    cursor.close()
    conn.close()
    return len(values)

# ── Data fetching ──────────────────────────────────────────────────────────────

ALPACA_TIMEOUT = 45  # seconds — fail fast if Alpaca hangs

def fetch_and_store(symbols):
    """
    Fetch latest minute bars for all symbols in batches and write to DB.
    Returns (bars_inserted, symbols_with_data, errors).
    """
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

    logger.info(f"  Alpaca API key: ...{Config.ALPACA_API_KEY[-6:] if Config.ALPACA_API_KEY else 'MISSING'}")

    client = StockHistoricalDataClient(
        Config.ALPACA_API_KEY,
        Config.ALPACA_SECRET_KEY
    )

    end   = datetime.now(pytz.utc)
    start = end - timedelta(minutes=LOOKBACK_MINUTES)
    logger.info(f"  Fetching bars {start.strftime('%H:%M')} - {end.strftime('%H:%M')} UTC")

    total_inserted  = 0
    total_symbols   = 0
    total_errors    = 0
    batches         = [symbols[i:i+BATCH_SIZE] for i in range(0, len(symbols), BATCH_SIZE)]

    for batch_num, batch in enumerate(batches, 1):
        try:
            logger.info(f"  Batch {batch_num}/{len(batches)}: calling Alpaca for {len(batch)} symbols...")
            request = StockBarsRequest(
                symbol_or_symbols=batch,
                timeframe=TimeFrame.Minute,
                start=start,
                end=end
            )

            # Wrap API call with timeout so it can't hang forever
            with ThreadPoolExecutor(max_workers=1) as ex:
                future = ex.submit(client.get_stock_bars, request)
                response = future.result(timeout=ALPACA_TIMEOUT)

            logger.info(f"  Batch {batch_num}/{len(batches)}: got data for {len(response.data)} symbols")
            inserted = insert_bars(response.data)
            total_inserted += inserted
            total_symbols  += len(response.data)

        except FuturesTimeout:
            total_errors += 1
            logger.error(f"  Batch {batch_num}/{len(batches)}: TIMED OUT after {ALPACA_TIMEOUT}s — Alpaca not responding")
        except Exception as e:
            total_errors += 1
            logger.warning(f"  Batch {batch_num}/{len(batches)} failed: {type(e).__name__}: {e}")

    return total_inserted, total_symbols, total_errors

# ── Main loop ──────────────────────────────────────────────────────────────────

def main():
    setup_logging()

    logger.info("=" * 70)
    logger.info("  STOCK DATA COLLECTOR - STARTING")
    logger.info("=" * 70)
    logger.info(f"  Database : {DB_CONN.split('@')[-1]}")
    logger.info(f"  Log file : {LOG_FILE}")
    logger.info(f"  Hours    : {MARKET_OPEN_HOUR}:00 - {MARKET_CLOSE_HOUR}:00 ET")
    logger.info(f"  Interval : every {COLLECT_INTERVAL}s")
    logger.info(f"  Batch    : {BATCH_SIZE} symbols/call")
    logger.info("=" * 70)

    symbols = load_symbols()
    if not symbols:
        logger.error("No symbols loaded - exiting.")
        return

    last_day_loaded  = None   # track which date we last refreshed symbols
    iteration        = 0
    session_inserted = 0
    session_errors   = 0
    heartbeat_ticker = 0      # log a heartbeat every 15 min even when idle

    while True:
        now_et    = datetime.now(ET)
        today     = now_et.date()
        hour      = now_et.hour
        in_hours  = MARKET_OPEN_HOUR <= hour < MARKET_CLOSE_HOUR

        # ── Daily symbol refresh at 4am ──────────────────────────────────────
        if hour == MARKET_OPEN_HOUR and today != last_day_loaded:
            logger.info("─" * 50)
            logger.info(f"4 AM refresh - reloading stock universe for {today}")
            symbols = load_symbols()
            last_day_loaded  = today
            session_inserted = 0
            session_errors   = 0
            logger.info("─" * 50)

        # ── Collection tick ──────────────────────────────────────────────────
        if in_hours:
            iteration += 1
            tick_start = time.time()

            logger.info(
                f"[{now_et.strftime('%H:%M')}] Tick #{iteration} | "
                f"symbols={len(symbols):,} | session bars={session_inserted:,}"
            )

            inserted, sym_count, errors = fetch_and_store(symbols)
            session_inserted += inserted
            session_errors   += errors
            elapsed = time.time() - tick_start

            if inserted > 0:
                logger.info(
                    f"  ✅ {inserted:,} bars from {sym_count:,} symbols "
                    f"in {elapsed:.1f}s"
                )
            else:
                logger.warning(
                    f"  ⚠️  0 bars returned (market closed / holiday?) "
                    f"[{elapsed:.1f}s]"
                )

            if errors:
                logger.warning(f"  ❌ {errors} batch error(s) this tick")

            # Sleep for the remainder of the interval
            sleep_for = max(1, COLLECT_INTERVAL - elapsed)
            time.sleep(sleep_for)

        # ── Outside market hours ─────────────────────────────────────────────
        else:
            heartbeat_ticker += 1
            if heartbeat_ticker % 3 == 1:  # every ~15 min
                logger.info(
                    f"[{now_et.strftime('%H:%M')}] Outside market hours. "
                    f"Waiting for {MARKET_OPEN_HOUR}:00 ET. "
                    f"(session total: {session_inserted:,} bars)"
                )
            time.sleep(300)  # check again in 5 minutes


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\n[STOPPED] Collector stopped by user (Ctrl+C)")
    except Exception as e:
        logger.exception(f"[FATAL] Unhandled error: {e}")
