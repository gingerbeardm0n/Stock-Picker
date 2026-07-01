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


class TradierRelVol:
    """Single-feed rel-vol: numerator AND denominator both from Tradier timesales.

    rel_vol = (today's cumulative premarket volume 4am→now)
              / (avg of the same cumulative-at-this-minute over the last N trading days)

    Both sides come from Tradier consolidated 1-min timesales, so they measure the same
    fraction of the market at the same time-of-day cut — the ratio actually means "trading
    above its own typical pace by now." Self-heals for any new gapper (no prebuilt baseline).

    N defaults to 5 because Tradier free-tier 1-min timesales only reaches ~6 trading days
    back (see memory rel-vol-lookback-research — revisit once Ross Cameron's true lookback
    is confirmed).

    One timesales range-fetch per symbol (whole window in a single call), cached per session.
    """

    def __init__(self, tradier_feed, lookback_days: int = 5):
        self._feed = tradier_feed
        self._lookback = lookback_days
        self._cache: dict[str, float] = {}   # symbol -> rel_vol (computed this session)
        self._lock = threading.Lock()

    def compute(
        self, symbol: str, now_et, cutoff_minute: int | None = None
    ) -> float | None:
        """Return rel_vol for `symbol` at `now_et` (tz-aware ET), or None if no history.

        cutoff_minute: minute-of-day ET to measure cumulative volume through, on BOTH
        today and every prior day (so they compare apples-to-apples). Default = now's
        minute (scalp premarket scan). VWAP pins this to 565 (9:25 ET) to match its
        9:25 baseline basis regardless of the actual scan clock. Never measures past
        the current wall-clock minute (can't see the future).

        None → caller falls back to DEFAULT_REL_VOL=10.0. Cached per symbol per session.
        """
        import pytz
        ET = pytz.timezone('America/New_York')
        now_et = now_et.astimezone(ET)

        with self._lock:
            if symbol in self._cache:
                return self._cache[symbol]

        now_minute = now_et.hour * 60 + now_et.minute
        if cutoff_minute is None:
            cutoff_minute = now_minute
        else:
            cutoff_minute = min(cutoff_minute, now_minute)  # don't measure the future
        if cutoff_minute < 240:          # before 4am ET — nothing to measure
            return None

        # Fetch one wide window (2x lookback calendar days to clear weekends/holidays).
        from datetime import timedelta as _td
        start_et = (now_et - _td(days=self._lookback * 2)).replace(
            hour=4, minute=0, second=0, microsecond=0)
        try:
            bars = self._feed._fetch_timesales(
                symbol,
                start_et.strftime('%Y-%m-%d %H:%M'),
                now_et.strftime('%Y-%m-%d %H:%M'),
            )
        except Exception as e:
            logger.debug("TradierRelVol fetch failed for %s: %s", symbol, e)
            return None
        if not bars:
            return None

        # Bucket per ET date, summing only minutes in [4am, cutoff_minute] (same time-of-day
        # window every day) so today and history are compared apples-to-apples.
        from collections import defaultdict
        by_day: dict = defaultdict(int)
        for b in bars:
            et = b.time.astimezone(ET)
            mod = et.hour * 60 + et.minute
            if 240 <= mod <= cutoff_minute:
                by_day[et.date()] += b.volume

        today = now_et.date()
        numerator = by_day.get(today, 0)
        prior_days = sorted(d for d in by_day if d < today)[-self._lookback:]
        prior_vols = [by_day[d] for d in prior_days if by_day[d] > 0]
        if not prior_vols:
            return None
        denominator = sum(prior_vols) / len(prior_vols)
        if denominator <= 0:
            return None

        rel_vol = numerator / denominator
        with self._lock:
            self._cache[symbol] = rel_vol
        return rel_vol

    def invalidate(self, symbol: str | None = None) -> None:
        """Drop cached value(s) so the next compute() re-fetches (numerator grows intraday)."""
        with self._lock:
            if symbol is None:
                self._cache.clear()
            else:
                self._cache.pop(symbol, None)


class HybridRelVol:
    """Rel-vol matching the simulator's 30-day denominator: today's cumulative
    volume (Tradier, real-time) over a 30-day average at the same minute-of-day
    (Alpaca historical minute bars, same source `rel_vol_cum_cache` was built
    from — free tier, 7+ years back, no same-day SIP clamp issue since we only
    need PRIOR days here).

    Tradier's free tier only reaches ~6 trading days back for premarket
    timesales, which was the reason TradierRelVol defaulted to a 5-day
    denominator (see rel-vol-lookback-research memory: Ross Cameron's own
    material names 7/14/30-day windows and states a preference for longer,
    the sim/`rel_vol_cum_cache` build already uses 30 days). Splitting the
    numerator and denominator across two data sources closes that gap without
    needing a paid tier.
    """

    def __init__(self, tradier_feed, alpaca_feed, lookback_days: int = 30):
        self._tradier = tradier_feed
        self._alpaca = alpaca_feed
        self._lookback = lookback_days
        self._raw_bars: dict[str, list] = {}   # symbol -> concatenated historical bars
        self._fetch_failed: set[str] = set()    # symbols with no Alpaca history (don't retry)
        self._cache: dict[str, float] = {}      # symbol -> rel_vol (computed this session)
        self._lock = threading.Lock()

    def _numerator(self, symbol: str, now_et, cutoff_minute: int) -> float | None:
        """Today's cumulative volume 4am ET -> cutoff_minute, via Tradier timesales."""
        start_et = now_et.replace(hour=4, minute=0, second=0, microsecond=0)
        try:
            bars = self._tradier._fetch_timesales(
                symbol,
                start_et.strftime('%Y-%m-%d %H:%M'),
                now_et.strftime('%Y-%m-%d %H:%M'),
            )
        except Exception as e:
            logger.debug("HybridRelVol numerator fetch failed for %s: %s", symbol, e)
            return None
        if not bars:
            return None

        import pytz
        ET = pytz.timezone('America/New_York')
        total = 0
        for b in bars:
            et = b.time.astimezone(ET)
            mod = et.hour * 60 + et.minute
            if 240 <= mod <= cutoff_minute:
                total += b.volume
        return total

    def _ensure_history(self, symbols: list[str]) -> None:
        missing = [s for s in symbols if s not in self._raw_bars and s not in self._fetch_failed]
        if not missing:
            return
        bars_by_sym = self._alpaca.get_historical_minute_bars(
            missing, lookback_days=self._lookback)
        with self._lock:
            for s in missing:
                bars = bars_by_sym.get(s)
                if bars:
                    self._raw_bars[s] = bars
                else:
                    self._fetch_failed.add(s)

    def _denominator(self, symbol: str, cutoff_minute: int) -> float | None:
        """30-day average cumulative volume at the same minute-of-day, via Alpaca history."""
        self._ensure_history([symbol])
        bars = self._raw_bars.get(symbol)
        if not bars:
            return None

        import pytz
        ET = pytz.timezone('America/New_York')
        by_day: dict = defaultdict(int)
        for b in bars:
            et = b.time.astimezone(ET)
            mod = et.hour * 60 + et.minute
            if 240 <= mod <= cutoff_minute:
                by_day[et.date()] += b.volume

        vols = sorted(by_day.items())[-self._lookback:]
        vols = [v for _d, v in vols if v > 0]
        if not vols:
            return None
        return sum(vols) / len(vols)

    def compute(
        self, symbol: str, now_et, cutoff_minute: int | None = None
    ) -> float | None:
        """Same signature/semantics as TradierRelVol.compute() — drop-in replacement.

        None -> caller falls back to DEFAULT_REL_VOL=10.0. Cached per symbol per session.
        """
        import pytz
        ET = pytz.timezone('America/New_York')
        now_et = now_et.astimezone(ET)

        with self._lock:
            if symbol in self._cache:
                return self._cache[symbol]

        now_minute = now_et.hour * 60 + now_et.minute
        if cutoff_minute is None:
            cutoff_minute = now_minute
        else:
            cutoff_minute = min(cutoff_minute, now_minute)
        if cutoff_minute < 240:
            return None

        numerator = self._numerator(symbol, now_et, cutoff_minute)
        if numerator is None:
            return None
        denominator = self._denominator(symbol, cutoff_minute)
        if not denominator or denominator <= 0:
            return None

        rel_vol = numerator / denominator
        with self._lock:
            self._cache[symbol] = rel_vol
        return rel_vol

    def invalidate(self, symbol: str | None = None) -> None:
        """Drop cached rel_vol (not history) so the next compute() re-fetches today's
        numerator. Historical denominator bars stay cached for the whole session."""
        with self._lock:
            if symbol is None:
                self._cache.clear()
            else:
                self._cache.pop(symbol, None)


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


def fetch_missing_floats(symbols: list[str], floats: dict[str, int]) -> dict[str, int]:
    """Fetch float_shares via yfinance for `symbols` not already in `floats`.

    Weekly bulk refresh (build_baseline_cloud.py, GitHub Actions daily 4:30pm ET)
    covers symbols already in the Neon rel_vol_baselines table. This covers the
    gap: a brand-new gapper never seen before has no baseline row at all, so its
    float silently stays None and the max_float filter no-ops for it — exactly
    the micro-float pump candidates that filter exists to catch.

    Only ever called with the current scan's short-listed candidates (post gap/
    news/rel-vol filtering, typically <20 symbols) — cheap even at yfinance's
    ~1.2s/request rate limit. Mutates and returns `floats` in place. Writes
    fetched values back to Neon (+ registers the symbol in active_symbols) so
    the nightly job picks it up for a real avg_volume baseline next run instead
    of re-fetching float forever.
    """
    missing = [s for s in symbols if s not in floats]
    if not missing:
        return floats

    try:
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance not installed — cannot live-fetch float for %s", missing)
        return floats

    import time as _time
    fetched: dict[str, int] = {}
    for sym in missing:
        try:
            info = yf.Ticker(sym).info
            raw = info.get("floatShares")
            if raw and raw > 0:
                fetched[sym] = int(raw)
                floats[sym] = int(raw)
        except Exception as e:
            logger.debug("Live float fetch failed for %s: %s", sym, e)
        _time.sleep(1.2)  # yfinance rate limit, ~50 req/min

    if fetched:
        logger.info(
            "Live float fetch: %d/%d new symbol(s) resolved (%s)",
            len(fetched), len(missing), ", ".join(fetched),
        )
        _upsert_floats_to_neon(fetched)
    return floats


def _upsert_floats_to_neon(floats: dict[str, int]) -> None:
    """Best-effort write-back so a live-fetched float isn't re-fetched every scan.

    New symbol -> placeholder avg_volume=0 (nothing live reads avg_volume from
    Neon anymore, HybridRelVol replaced that path) + registered in active_symbols
    so tonight's build_baseline_cloud.py computes a real avg_volume for it.
    Existing symbol -> only float_shares/float_fetched_at touched, avg_volume
    left untouched.
    """
    conn_str = os.getenv("NEON_CONNECTION_STRING", "")
    if not conn_str or not floats:
        return
    try:
        import psycopg2
        from psycopg2.extras import execute_values
        from datetime import date

        conn = psycopg2.connect(conn_str, connect_timeout=5)
        cur = conn.cursor()

        baseline_rows = [(sym, 0.0, date.today(), fs) for sym, fs in floats.items()]
        execute_values(cur, """
            INSERT INTO rel_vol_baselines (symbol, avg_volume, as_of, float_shares, float_fetched_at)
            VALUES %s
            ON CONFLICT (symbol) DO UPDATE SET
                float_shares = EXCLUDED.float_shares,
                float_fetched_at = now()
        """, baseline_rows, template="(%s, %s, %s, %s, now())")

        symbol_rows = [(sym, date.today()) for sym in floats]
        execute_values(cur, """
            INSERT INTO active_symbols (symbol, added_on)
            VALUES %s
            ON CONFLICT (symbol) DO UPDATE SET updated_at = now()
        """, symbol_rows)

        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning("Float write-back to Neon failed: %s", e)
