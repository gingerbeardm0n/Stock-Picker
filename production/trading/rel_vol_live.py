"""
rel_vol_live.py — live relative-volume parity helper (Gap #1).

The simulators compute relative volume from the `rel_vol_cum_cache` table
(today's cumulative volume at 9:25 ET ÷ 30-day average at the same minute) and
enforce `min_relative_volume`. The live runners fetch a precomputed baseline
(the denominator, per symbol) and divide live quote volume by it.

Source priority:
  1. Neon PostgreSQL (NEON_CONNECTION_STRING env var) — primary, always fresh
  2. GitHub data branch JSON (GITHUB_TOKEN env var)  — backup
  3. DEFAULT_REL_VOL=10.0 fallback                   — filter becomes no-op

    fetch_rel_vol_baseline()  — loads from Neon → JSON → fallback None
    compute_rel_vol()         — quote_volume / baseline[symbol], sim fallback 10.0

See docs/REL_VOL_LIVE_PARITY_DESIGN.md.
"""

from __future__ import annotations

import logging
import os
import threading
from collections import defaultdict

import requests

logger = logging.getLogger(__name__)

DEFAULT_REL_VOL = 10.0

BASELINE_URL = (
    "https://raw.githubusercontent.com/gingerbeardm0n/Stock-Picker/"
    "data/data/rel_vol_baseline.json"
)
FETCH_TIMEOUT_S = 5


def _fetch_from_neon() -> dict | None:
    """Load rel_vol baselines from Neon PostgreSQL. Returns dict or None."""
    conn_str = os.getenv("NEON_CONNECTION_STRING", "")
    if not conn_str:
        return None
    try:
        import psycopg2
        conn = psycopg2.connect(conn_str, connect_timeout=5)
        cur = conn.cursor()
        cur.execute(
            "SELECT symbol, avg_volume, as_of, float_shares FROM rel_vol_baselines"
        )
        rows = cur.fetchall()
        conn.close()
        if not rows:
            logger.warning("Neon rel_vol_baselines table is empty")
            return None
        baselines = {sym: avg_vol for sym, avg_vol, _d, _fs in rows}
        floats = {sym: int(fs) for sym, _v, _d, fs in rows if fs is not None}
        as_of = rows[0][2].isoformat() if rows else "unknown"
        logger.info(
            "Rel-vol baseline loaded from Neon: %d symbols, %d floats, as_of=%s",
            len(baselines), len(floats), as_of,
        )
        return {"as_of": as_of, "minute_of_day": 565, "baselines": baselines, "floats": floats}
    except Exception as e:
        logger.warning("Neon rel_vol fetch FAILED (%s) — trying JSON fallback", e)
        return None


def _fetch_from_github(url: str) -> dict | None:
    """Load rel_vol baseline JSON from GitHub data branch. Returns dict or None."""
    try:
        headers = {}
        token = os.getenv("GITHUB_TOKEN", "")
        if token:
            headers["Authorization"] = f"token {token}"
        r = requests.get(url, timeout=FETCH_TIMEOUT_S, headers=headers)
        r.raise_for_status()
        data = r.json()
        baselines = data.get("baselines")
        if not isinstance(baselines, dict):
            logger.warning("Rel-vol JSON fetched but has no 'baselines' dict — ignoring.")
            return None
        logger.info(
            "Rel-vol baseline loaded from GitHub JSON: %d symbols, as_of=%s",
            len(baselines), data.get("as_of", "?"),
        )
        return data
    except Exception as e:
        logger.warning("Rel-vol GitHub JSON fetch FAILED (%s)", e)
        return None


def fetch_rel_vol_baseline(url: str = BASELINE_URL) -> dict | None:
    """Fetch rel-vol baseline: Neon → GitHub JSON → None (no-op fallback).

    Returns {"as_of", "minute_of_day", "baselines": {sym: avg_vol}, "floats": {}}
    or None if all sources fail (callers fall back to DEFAULT_REL_VOL=10.0).
    """
    # 1. Try Neon (primary)
    data = _fetch_from_neon()
    if data:
        return data

    # 2. Try GitHub JSON (backup)
    data = _fetch_from_github(url)
    if data:
        return data

    # 3. Full fallback
    logger.warning(
        "Rel-vol baseline unavailable from ALL sources — falling back to rel_vol=%.1f "
        "for ALL symbols; the min_relative_volume filter will be a no-op this session.",
        DEFAULT_REL_VOL,
    )
    return None


class RealtimeRelVolCache:
    """
    Session-level cache: compute real-time rel-vol baseline for gapper symbols
    absent from the Neon/GitHub baseline (new tickers not yet accumulated).

    For each unknown symbol, fetches lookback_days of 4am-12pm minute bars via
    Alpaca and computes avg cumulative volume up to the current time-of-day.
    Cache persists for the full session — safe to call on every scan cycle.

    Usage:
        cache = RealtimeRelVolCache()
        cache.enrich_missing(unknown_symbols, datetime.now(ET), alpaca_feed)
        rv = cache.compute_rel_vol(symbol, quote_volume)  # None if still missing
    """

    def __init__(self):
        self._baselines: dict[str, float] = {}   # symbol -> avg_cumvol
        self._lock = threading.Lock()

    def enrich_missing(
        self,
        symbols: list[str],
        current_time,             # timezone-aware datetime (ET preferred)
        alpaca_feed,              # AlpacaDataFeed instance
        lookback_days: int = 30,
    ) -> None:
        """
        Blocking. Fetches 30-day historical bars and computes baselines for all
        `symbols` not yet cached. Logs one line per symbol with result.
        """
        import pytz
        ET_tz = pytz.timezone('America/New_York')

        missing = [s for s in symbols if s not in self._baselines]
        if not missing:
            return

        logger.info(
            "Real-time rel-vol: fetching %d-day history for %d new symbol(s): %s",
            lookback_days, len(missing), missing,
        )
        bars_by_sym = alpaca_feed.get_historical_minute_bars(
            missing, lookback_days=lookback_days)

        # Count bars up to current time-of-day (match what quote_volume covers)
        tod = current_time.astimezone(ET_tz).time()

        for sym in missing:
            bars = bars_by_sym.get(sym)
            if not bars:
                logger.warning(
                    "  %s: no historical bars returned — keeping 10.0 fallback", sym)
                continue

            # Sum cumulative volume per calendar day up to tod
            day_vols: dict = defaultdict(int)
            for bar in bars:
                bar_et = bar.time.astimezone(ET_tz)
                if bar_et.time() <= tod:
                    day_vols[bar_et.date()] += bar.volume

            if not day_vols:
                logger.warning(
                    "  %s: no bars before %s — keeping 10.0 fallback", sym, tod)
                continue

            recent = sorted(day_vols.keys(), reverse=True)[:lookback_days]
            avg_vol = sum(day_vols[d] for d in recent) / len(recent)

            with self._lock:
                self._baselines[sym] = avg_vol

            logger.info(
                "  %s: realtime baseline=%.0f avg_vol (%d days, cutoff %s)",
                sym, avg_vol, len(recent), tod.strftime("%H:%M"),
            )

    def compute_rel_vol(
        self,
        symbol: str,
        quote_volume: float | None,
    ) -> float | None:
        """
        Returns rel_vol if this symbol's baseline is cached, else None.
        Caller should fall back to DEFAULT_REL_VOL=10.0 on None.
        """
        base = self._baselines.get(symbol)
        if base is None or base <= 0:
            return None
        if quote_volume is None or quote_volume <= 0:
            return DEFAULT_REL_VOL
        return quote_volume / base


def compute_rel_vol(
    symbol: str,
    quote_volume: float | None,
    baselines: dict | None,
) -> float:
    """Compute live relative volume for one symbol.

    rel_vol = quote_volume / baseline[symbol]   when baseline > 0 and volume known
            = DEFAULT_REL_VOL (10.0)            when no baseline file, symbol
                                                missing from baseline, baseline<=0,
                                                or quote_volume is unknown/<=0

    The fallbacks all collapse to the sim's no-history default so a missing
    baseline degrades gracefully to current live behavior.
    """
    if not baselines:
        return DEFAULT_REL_VOL
    base = baselines.get(symbol)
    if not base or base <= 0:
        return DEFAULT_REL_VOL
    if quote_volume is None or quote_volume <= 0:
        return DEFAULT_REL_VOL
    return quote_volume / base
