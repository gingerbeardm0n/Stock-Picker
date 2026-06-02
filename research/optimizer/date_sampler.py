"""
date_sampler.py — Stratified random day sampler for Optuna trials.

Loads all available trading days from DB (once), groups by ISO week,
then each trial draws N random days per week using the trial number as seed.

This gives each trial a different random slice of the full date range,
preventing overfitting to specific day ordering while covering all market
regimes (bull, bear, chop, recovery) in every trial.

Method: "Stratified Stochastic Subsampling" — similar to Build Alpha's
Randomized OOS and Lopez de Prado's CPCV, but applied to the optimizer
itself rather than just validation.

Created: 2026-06-02
References:
  - Build Alpha "Randomized Out of Sample" (buildalpha.com)
  - Lopez de Prado "Probability of Backtest Overfitting" (SSRN 2326253)
  - Harbourfronts "Parameter Plateau" concept (2026)

Usage:
    sampler = DateSampler.from_db(min_symbols=500)
    # or
    sampler = DateSampler.from_db(
        pool_start='2021-01-01', pool_end='2025-12-31',
        holdout_start='2026-01-01', min_symbols=500,
    )

    # Each trial gets different days:
    days_trial_0 = sampler.sample(seed=0, days_per_week=2)
    days_trial_1 = sampler.sample(seed=1, days_per_week=2)
    days_trial_2 = sampler.sample(seed=2, days_per_week=2)
    # All different random selections, but all cover every week
"""
from __future__ import annotations

import random
import sys
import os
from collections import defaultdict
from datetime import date, datetime
from typing import Optional

sys.path.insert(0, os.path.abspath('production'))


class DateSampler:
    """Stratified random day sampler grouped by ISO week."""

    def __init__(
        self,
        weeks: dict[tuple[int, int], list[date]],
        holdout_dates: list[date] | None = None,
        min_days_per_week: int = 2,
    ):
        """
        Parameters
        ----------
        weeks : {(iso_year, iso_week): [date, ...]} — available trading days per week.
        holdout_dates : dates reserved for final validation (never sampled).
        min_days_per_week : skip weeks with fewer days than this (can't sample 2 from 1).
        """
        # Filter weeks that have enough days to sample from
        self.weeks = {
            wk: sorted(days) for wk, days in weeks.items()
            if len(days) >= min_days_per_week
        }
        self.holdout_dates = set(holdout_dates or [])
        self._week_keys = sorted(self.weeks.keys())

        # Stats
        total_days = sum(len(d) for d in self.weeks.values())
        print(f"[DateSampler] {len(self._week_keys)} weeks, {total_days} pool days, "
              f"{len(self.holdout_dates)} holdout days")

    @classmethod
    def from_db(
        cls,
        pool_start: str = '2021-01-01',
        pool_end: str = '2025-12-31',
        holdout_start: str | None = '2026-01-01',
        holdout_end: str | None = None,
        min_symbols: int = 500,
        min_days_per_week: int = 2,
    ) -> 'DateSampler':
        """
        Build sampler by querying TimescaleDB for available trading days.

        Parameters
        ----------
        pool_start/pool_end : date range for the training pool.
        holdout_start/holdout_end : date range reserved for holdout (never sampled).
        min_symbols : minimum distinct symbols on a day to be considered valid.
        min_days_per_week : weeks with fewer valid days are excluded.
        """
        from utils.query_helpers import StockDataDB

        pool_s = datetime.strptime(pool_start, '%Y-%m-%d').date()
        pool_e = datetime.strptime(pool_end, '%Y-%m-%d').date()

        print(f"[DateSampler] Querying DB for trading days {pool_start} to {pool_end} "
              f"with >= {min_symbols} symbols...")

        with StockDataDB(socket_timeout=300) as db:
            cur = db.conn.cursor()
            cur.execute("SET statement_timeout = '300s'")
            cur.execute("""
                SELECT time::date as trade_date, COUNT(DISTINCT symbol) as sym_count
                FROM stock_candles_1m
                WHERE time >= %s AND time < %s
                GROUP BY trade_date
                HAVING COUNT(DISTINCT symbol) >= %s
                ORDER BY trade_date
            """, (pool_start, str(pool_e + __import__('datetime').timedelta(days=1)), min_symbols))
            rows = cur.fetchall()

        print(f"[DateSampler] Found {len(rows)} valid trading days")

        # Group by ISO week
        weeks: dict[tuple[int, int], list[date]] = defaultdict(list)
        for d, sym_count in rows:
            if pool_s <= d <= pool_e:
                iso = d.isocalendar()
                weeks[(iso[0], iso[1])].append(d)

        # Load holdout dates if specified
        holdout_dates = []
        if holdout_start:
            ho_s = datetime.strptime(holdout_start, '%Y-%m-%d').date()
            ho_e = datetime.strptime(holdout_end, '%Y-%m-%d').date() if holdout_end else date(2099, 12, 31)
            with StockDataDB(socket_timeout=300) as db:
                cur = db.conn.cursor()
                cur.execute("SET statement_timeout = '300s'")
                cur.execute("""
                    SELECT time::date as trade_date
                    FROM stock_candles_1m
                    WHERE time >= %s AND time < %s
                    GROUP BY trade_date
                    HAVING COUNT(DISTINCT symbol) >= %s
                    ORDER BY trade_date
                """, (holdout_start, str(ho_e + __import__('datetime').timedelta(days=1)), min_symbols))
                holdout_dates = [r[0] for r in cur.fetchall()]

            print(f"[DateSampler] {len(holdout_dates)} holdout days ({holdout_start} onward)")

        return cls(
            weeks=dict(weeks),
            holdout_dates=holdout_dates,
            min_days_per_week=min_days_per_week,
        )

    @classmethod
    def from_cache(cls, dates: list[date], min_days_per_week: int = 2) -> 'DateSampler':
        """
        Build sampler from an explicit list of dates (no DB query needed).
        Useful when dates were already cached or loaded from a file.
        """
        weeks: dict[tuple[int, int], list[date]] = defaultdict(list)
        for d in dates:
            iso = d.isocalendar()
            weeks[(iso[0], iso[1])].append(d)
        return cls(weeks=dict(weeks), min_days_per_week=min_days_per_week)

    def sample(self, seed: int, days_per_week: int = 2) -> list[date]:
        """
        Draw `days_per_week` random days from each week, seeded by `seed`.

        Returns sorted list of dates. Different seeds → different selections.
        Same seed → identical selection (reproducible).
        """
        rng = random.Random(seed)
        sampled = []
        for wk in self._week_keys:
            available = self.weeks[wk]
            n = min(days_per_week, len(available))
            picks = rng.sample(available, n)
            sampled.extend(picks)
        return sorted(sampled)

    def get_holdout_dates(self) -> list[date]:
        """Return sorted holdout dates for final validation."""
        return sorted(self.holdout_dates)

    @property
    def total_weeks(self) -> int:
        return len(self._week_keys)

    @property
    def total_pool_days(self) -> int:
        return sum(len(d) for d in self.weeks.values())

    def stats(self, days_per_week: int = 2) -> dict:
        """Return summary statistics for display."""
        sample_size = sum(min(days_per_week, len(self.weeks[wk])) for wk in self._week_keys)
        return {
            'total_weeks': self.total_weeks,
            'total_pool_days': self.total_pool_days,
            'holdout_days': len(self.holdout_dates),
            'days_per_trial': sample_size,
            'sample_pct': round(sample_size / self.total_pool_days * 100, 1),
        }


# ── CLI test ─────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Test date sampler')
    parser.add_argument('--pool-start', default='2021-01-01')
    parser.add_argument('--pool-end', default='2025-12-31')
    parser.add_argument('--holdout-start', default='2026-01-01')
    parser.add_argument('--min-symbols', type=int, default=500)
    parser.add_argument('--days-per-week', type=int, default=2)
    parser.add_argument('--show-samples', type=int, default=3,
                        help='Number of sample draws to show (default: 3)')
    args = parser.parse_args()

    sampler = DateSampler.from_db(
        pool_start=args.pool_start,
        pool_end=args.pool_end,
        holdout_start=args.holdout_start,
        min_symbols=args.min_symbols,
    )

    stats = sampler.stats(args.days_per_week)
    print(f"\n=== SAMPLER STATS ===")
    print(f"  Pool: {stats['total_pool_days']} days across {stats['total_weeks']} weeks")
    print(f"  Holdout: {stats['holdout_days']} days")
    print(f"  Days per trial: {stats['days_per_trial']} ({stats['sample_pct']}% of pool)")

    for i in range(args.show_samples):
        days = sampler.sample(seed=i, days_per_week=args.days_per_week)
        # Show date range and count by year
        from collections import Counter
        by_year = Counter(d.year for d in days)
        year_str = ', '.join(f"{y}:{n}" for y, n in sorted(by_year.items()))
        print(f"\n  Sample seed={i}: {len(days)} days [{days[0]} .. {days[-1]}]")
        print(f"    By year: {year_str}")

        # Show overlap with previous sample
        if i > 0:
            prev = sampler.sample(seed=i-1, days_per_week=args.days_per_week)
            overlap = len(set(days) & set(prev))
            print(f"    Overlap with seed={i-1}: {overlap}/{len(days)} ({overlap/len(days):.0%})")
