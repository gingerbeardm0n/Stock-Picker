#!/usr/bin/env python3
"""
Fetch Stock Fundamentals (Float + Market Cap) from Finnhub
Stores results in stock_fundamentals table in TimescaleDB.

Float and market cap rarely change, so this runs weekly (or manually on demand).
Free Finnhub tier: 60 API calls/min — script throttles to 55/min to stay safe.

Usage:
    python services/fetch_fundamentals.py            # all symbols in stocks_1_to_20.txt
    python services/fetch_fundamentals.py --test 20  # first 20 symbols only (for testing)
    python services/fetch_fundamentals.py --symbol AAPL  # single symbol
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import psycopg2
from psycopg2.extras import execute_values
import requests
import time
import logging
import argparse
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ── Config ─────────────────────────────────────────────────────────────────────

DB_CONN = os.getenv('TIMESCALE_CONNECTION_STRING',
                    'postgresql://postgres:yourpassword@localhost:5432/stockdata')

FINNHUB_API_KEY = os.getenv('FINNHUB_API_KEY', '')
FINNHUB_URL = 'https://finnhub.io/api/v1/stock/profile2'

STOCKS_FILE = os.path.join(os.path.dirname(__file__), '../database/stocks_1_to_20.txt')
CALLS_PER_MIN = 55          # Stay safely under free tier's 60/min limit
SLEEP_BETWEEN = 60 / CALLS_PER_MIN  # ~1.09 seconds per call

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s [%(levelname)-8s] %(message)s')
logger = logging.getLogger(__name__)


# ── Database ───────────────────────────────────────────────────────────────────

def get_db():
    return psycopg2.connect(DB_CONN)


def ensure_table(conn):
    """Create stock_fundamentals table if it doesn't exist."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS stock_fundamentals (
                symbol       TEXT        PRIMARY KEY,
                float_shares BIGINT,
                market_cap   BIGINT,
                company_name TEXT,
                industry     TEXT,
                updated_at   TIMESTAMPTZ DEFAULT NOW()
            );
        """)
    conn.commit()
    logger.info("stock_fundamentals table ready")


def upsert_batch(conn, rows):
    """
    Upsert a batch of fundamentals rows.
    rows: list of (symbol, float_shares, market_cap, company_name, industry)
    """
    with conn.cursor() as cur:
        execute_values(cur, """
            INSERT INTO stock_fundamentals
                (symbol, float_shares, market_cap, company_name, industry)
            VALUES %s
            ON CONFLICT (symbol) DO UPDATE SET
                float_shares = EXCLUDED.float_shares,
                market_cap   = EXCLUDED.market_cap,
                company_name = EXCLUDED.company_name,
                industry     = EXCLUDED.industry,
                updated_at   = NOW()
        """, rows)
    conn.commit()


# ── Finnhub API ────────────────────────────────────────────────────────────────

def fetch_profile(symbol, api_key):
    """
    Fetch company profile from Finnhub.
    Returns (float_shares, market_cap, company_name, industry) or None on failure.

    Finnhub fields:
      shareOutstanding  = float shares in millions → multiply by 1e6 for shares
      marketCapitalization = market cap in millions USD → multiply by 1e6
    """
    try:
        resp = requests.get(
            FINNHUB_URL,
            params={'symbol': symbol, 'token': api_key},
            timeout=10
        )

        if resp.status_code == 429:
            logger.warning(f"  {symbol}: Rate limited — sleeping 60s")
            time.sleep(60)
            # Retry once
            resp = requests.get(
                FINNHUB_URL,
                params={'symbol': symbol, 'token': api_key},
                timeout=10
            )

        if resp.status_code != 200:
            logger.warning(f"  {symbol}: HTTP {resp.status_code}")
            return None

        data = resp.json()

        if not data or 'shareOutstanding' not in data:
            return None  # No fundamental data for this symbol

        # Convert from millions to shares/dollars
        float_shares = int(data.get('shareOutstanding', 0) * 1_000_000) or None
        market_cap   = int(data.get('marketCapitalization', 0) * 1_000_000) or None
        company_name = data.get('name', '')
        industry     = data.get('finnhubIndustry', '')

        return (float_shares, market_cap, company_name, industry)

    except requests.RequestException as e:
        logger.warning(f"  {symbol}: Request error: {e}")
        return None


# ── Main ───────────────────────────────────────────────────────────────────────

def load_symbols():
    if not os.path.exists(STOCKS_FILE):
        logger.error(f"Symbol file not found: {STOCKS_FILE}")
        return []
    with open(STOCKS_FILE) as f:
        return [line.strip() for line in f if line.strip()]


def run(symbols, api_key):
    if not api_key:
        logger.error("FINNHUB_API_KEY is not set in .env — cannot fetch fundamentals")
        logger.error("Get a free API key at https://finnhub.io")
        sys.exit(1)

    conn = get_db()
    ensure_table(conn)

    total    = len(symbols)
    success  = 0
    no_data  = 0
    errors   = 0
    batch    = []
    BATCH_SIZE = 50  # Upsert every 50 symbols

    logger.info("=" * 60)
    logger.info("  FUNDAMENTALS FETCHER")
    logger.info("=" * 60)
    logger.info(f"  Symbols  : {total:,}")
    logger.info(f"  Rate     : {CALLS_PER_MIN}/min ({SLEEP_BETWEEN:.2f}s/call)")
    logger.info(f"  Est. time: {total / CALLS_PER_MIN:.0f} minutes")
    logger.info("=" * 60)

    start = time.time()

    for i, symbol in enumerate(symbols, 1):
        result = fetch_profile(symbol, api_key)

        if result is not None:
            float_shares, market_cap, company_name, industry = result
            batch.append((symbol, float_shares, market_cap, company_name, industry))
            success += 1
            if i <= 5 or i % 50 == 0:
                float_str = f"{float_shares/1e6:.1f}M" if float_shares else "N/A"
                cap_str   = f"${market_cap/1e6:.0f}M" if market_cap else "N/A"
                logger.info(f"  [{i:>4}/{total}] {symbol:<8}  float={float_str:<10} mktcap={cap_str}")
        else:
            no_data += 1
            logger.debug(f"  [{i:>4}/{total}] {symbol}: no data")

        # Upsert batch
        if len(batch) >= BATCH_SIZE:
            upsert_batch(conn, batch)
            logger.info(f"  [Batch flush] {BATCH_SIZE} rows inserted (symbol #{i}/{total})")
            batch = []

        # Progress every 500 symbols
        if i % 500 == 0:
            elapsed = time.time() - start
            rate = i / elapsed * 60
            remaining = (total - i) / (rate / 60) if rate > 0 else 0
            logger.info(f"  Progress: {i}/{total} ({i/total*100:.0f}%) | "
                        f"~{remaining/60:.0f} min remaining")

        # Throttle to stay within free tier
        time.sleep(SLEEP_BETWEEN)

    # Flush remaining batch
    if batch:
        upsert_batch(conn, batch)

    conn.close()

    elapsed = time.time() - start
    logger.info("")
    logger.info("=" * 60)
    logger.info("  DONE")
    logger.info(f"  Total    : {total:,} symbols")
    logger.info(f"  Success  : {success:,}")
    logger.info(f"  No data  : {no_data:,}")
    logger.info(f"  Errors   : {errors:,}")
    logger.info(f"  Elapsed  : {elapsed/60:.1f} minutes")
    logger.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(description='Fetch stock fundamentals from Finnhub')
    parser.add_argument('--test', type=int, metavar='N',
                        help='Only fetch first N symbols (for testing)')
    parser.add_argument('--symbol', type=str,
                        help='Fetch a single symbol only')
    args = parser.parse_args()

    if args.symbol:
        symbols = [args.symbol.upper()]
    else:
        symbols = load_symbols()
        if not symbols:
            logger.error("No symbols found in stocks_1_to_20.txt")
            sys.exit(1)
        if args.test:
            symbols = symbols[:args.test]
            logger.info(f"TEST MODE: Only fetching first {len(symbols)} symbols")

    api_key = os.getenv('FINNHUB_API_KEY', '')
    run(symbols, api_key)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\n[STOPPED] Fetch cancelled by user")
    except Exception as e:
        logger.exception(f"[FATAL] {e}")
