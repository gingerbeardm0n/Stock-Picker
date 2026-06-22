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
