#!/usr/bin/env python3
"""
News Backfill for Opening Bell Scalp Strategy
==============================================
Bulk-fetch historical news from Alpaca's News API and store in stock_news table.

Smart backfill: only fetches news for symbols that were gapping 10%+ on each day,
keeping API usage minimal (Alpaca free tier = 200 req/min).

Usage:
    python backfill_news.py --start 2025-01-01 --end 2025-06-30
    python backfill_news.py --start 2025-01-01 --end 2025-06-30 --dry-run
    python backfill_news.py --stats 2025-01-01 2025-06-30
"""

import sys
import os
import time
import argparse
import logging
from datetime import datetime, timedelta, date as dateclass

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from utils.query_helpers import StockDataDB
from backend.news_fetcher import NewsFetcher, classify_news_tier, MAX_SYMBOLS_FOR_SPECIFIC_NEWS

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-5s | %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger(__name__)


def find_gappers_for_date(db: StockDataDB, trade_date, min_gap_pct: float = 10.0):
    """
    Find symbols gapping up >= min_gap_pct on a given date.

    Delegates to db.find_gappers() — the single source of truth for gapper
    discovery, shared with scalp_simulation.py. Ensures news is fetched for
    exactly the same stocks the simulation would consider.
    """
    return db.find_gappers(trade_date, min_gap_pct=min_gap_pct)


def backfill_news_for_date(db: StockDataDB, fetcher: NewsFetcher,
                           trade_date, min_gap_pct: float = 10.0,
                           dry_run: bool = False):
    """
    Backfill news for all gappers on a single trading day.

    Returns (n_gappers, n_articles_inserted).
    """
    # Skip days already backfilled (have any news entries)
    if not dry_run:
        cursor = db.conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM stock_news sn
            JOIN daily_gappers dg ON sn.symbol = dg.symbol
            WHERE dg.trade_date = %s AND dg.gap_pct >= %s
              AND sn.created_at >= (%s::date - interval '48 hours')
              AND sn.created_at <= %s::date + interval '1 day'
        """, [trade_date, min_gap_pct, trade_date, trade_date])
        existing = cursor.fetchone()[0]
        cursor.close()
        if existing > 0:
            return 0, 0  # Already has news data, skip

    gappers = find_gappers_for_date(db, trade_date, min_gap_pct)

    if not gappers:
        return 0, 0

    total_inserted = 0
    for g in gappers:
        symbol = g['symbol']

        if dry_run:
            logger.info(f"  [DRY] {symbol} gap={g['gap_pct']:.1f}% — would fetch news")
            continue

        # Fetch news from Alpaca (48h before market open on trade_date)
        try:
            articles_raw = fetcher.get_news_for_symbol(
                symbol,
                as_of_date=trade_date,
                hours_back=48,
            )
        except Exception as e:
            logger.warning(f"  {symbol}: fetch error — {e}")
            continue

        if not articles_raw:
            continue

        # Classify tier and prepare for DB insert
        tier = classify_news_tier(articles_raw)
        db_articles = []
        for a in articles_raw:
            created_at = a.get('created_at')
            if created_at and isinstance(created_at, str):
                try:
                    created_at = datetime.fromisoformat(created_at)
                except (ValueError, TypeError):
                    continue

            if not created_at:
                continue

            db_articles.append({
                'symbol': symbol,
                'headline': a.get('headline', ''),
                'source': a.get('source'),
                'created_at': created_at,
                'summary': a.get('summary'),
                'url': a.get('url'),
                'symbol_count': a.get('symbol_count'),
                'is_specific': a.get('is_specific', True),
                'news_tier': tier,
            })

        if db_articles:
            n = db.insert_news_batch(db_articles)
            total_inserted += n
            logger.debug(f"  {symbol}: {n} articles (tier={tier})")

        # Rate limit: ~3 req/sec to stay under 200/min
        time.sleep(0.35)

    return len(gappers), total_inserted


def run_backfill(start_date, end_date, min_gap_pct=10.0, dry_run=False):
    """Main backfill loop across date range."""
    logger.info(f"News backfill: {start_date} → {end_date} (min gap {min_gap_pct}%)")
    if dry_run:
        logger.info("[DRY RUN — no API calls or DB writes]")

    with StockDataDB(socket_timeout=0) as db:
        cursor = db.conn.cursor()
        cursor.execute("""
            SELECT DISTINCT time::date FROM stock_candles_1d
            WHERE time::date >= %s AND time::date <= %s
            ORDER BY 1
        """, [start_date, end_date])
        trading_days = [row[0] for row in cursor.fetchall()]
        cursor.close()
        logger.info(f"Found {len(trading_days)} trading days (from stock_candles_1d)")

        fetcher = None if dry_run else NewsFetcher()

        total_gappers = 0
        total_articles = 0
        days_processed = 0

        for trade_date in trading_days:
            n_gappers, n_articles = backfill_news_for_date(
                db, fetcher, trade_date, min_gap_pct, dry_run
            )

            days_processed += 1
            total_gappers += n_gappers
            total_articles += n_articles

            if n_gappers > 0:
                logger.info(
                    f"{trade_date} | {n_gappers} gappers | "
                    f"+{n_articles} articles | "
                    f"({days_processed}/{len(trading_days)})"
                )
            else:
                if days_processed % 20 == 0:
                    logger.info(f"  ...{days_processed}/{len(trading_days)} days processed")

    logger.info("=" * 50)
    logger.info(f"Done. {days_processed} days, {total_gappers} gappers, {total_articles} articles inserted.")
    return total_articles


def show_stats(start_date, end_date):
    """Show news coverage stats for date range."""
    with StockDataDB() as db:
        stats = db.get_news_coverage_stats(start_date, end_date)

    if not stats:
        print("No news data found in range.")
        return

    print(f"{'Date':<12} {'Articles':>8} {'Symbols':>8} {'Catalysts':>10}")
    print("-" * 42)
    for s in stats:
        print(f"{s['news_date']}  {s['article_count']:>8} {s['symbol_count']:>8} {s['catalyst_count']:>10}")
    print("-" * 42)
    total_articles = sum(s['article_count'] for s in stats)
    total_catalysts = sum(s['catalyst_count'] for s in stats)
    print(f"{'TOTAL':<12}  {total_articles:>8} {'':>8} {total_catalysts:>10}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Backfill news for Opening Bell Scalp strategy')
    parser.add_argument('--start', required=True, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', required=True, help='End date (YYYY-MM-DD)')
    parser.add_argument('--min-gap', type=float, default=10.0,
                        help='Minimum gap %% to fetch news for (default 10)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be fetched without calling API')
    parser.add_argument('--stats', action='store_true',
                        help='Show coverage stats instead of backfilling')

    args = parser.parse_args()

    if args.stats:
        show_stats(args.start, args.end)
    else:
        run_backfill(args.start, args.end, args.min_gap, args.dry_run)
