"""
rel_vol_live.py — live relative-volume parity helper (Gap #1).

The simulators compute relative volume from the `rel_vol_cum_cache` table
(today's cumulative volume at 9:25 ET ÷ 30-day average at the same minute) and
enforce `min_relative_volume`. The live runners run on Render with no DB access,
so they fetch a precomputed baseline (the denominator, per symbol) from a raw
file on the dedicated `data` branch and divide live quote volume by it.

This module holds the pure pieces so both runners share identical semantics and
they can be unit-tested without a network or DB:

    fetch_rel_vol_baseline()  — GET the baseline JSON, graceful fallback to None
    compute_rel_vol()         — quote_volume / baseline[symbol], sim fallback 10.0

See docs/REL_VOL_LIVE_PARITY_DESIGN.md.
"""

from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)

# Sim semantics: a symbol with no 30-day history (recent IPO, ticker change)
# defaults to 10.0 rel-vol so the filter never blocks it. The live fallback
# (no baseline file, or symbol missing from the baseline) matches this exactly.
DEFAULT_REL_VOL = 10.0

BASELINE_URL = (
    "https://raw.githubusercontent.com/gingerbeardm0n/Stock-Picker/"
    "data/data/rel_vol_baseline.json"
)
FETCH_TIMEOUT_S = 5


def fetch_rel_vol_baseline(url: str = BASELINE_URL) -> dict | None:
    """Fetch the rel-vol baseline JSON from the data branch.

    Returns the parsed dict ({"as_of", "minute_of_day", "baselines": {...}}) on
    success, or None on any failure (network, timeout, bad JSON). Callers treat
    None as "no baseline available" → DEFAULT_REL_VOL for every symbol.
    """
    try:
        r = requests.get(url, timeout=FETCH_TIMEOUT_S)
        r.raise_for_status()
        data = r.json()
        baselines = data.get("baselines")
        if not isinstance(baselines, dict):
            logger.warning("Rel-vol baseline fetched but has no 'baselines' dict — ignoring.")
            return None
        logger.info(
            "Rel-vol baseline loaded: %d symbols, as_of=%s, minute_of_day=%s",
            len(baselines), data.get("as_of", "?"), data.get("minute_of_day", "?"),
        )
        return data
    except Exception as e:  # noqa: BLE001 — any failure → fallback, never crash the session
        logger.warning(
            "Rel-vol baseline fetch FAILED (%s) — falling back to rel_vol=%.1f for "
            "ALL symbols; the min_relative_volume filter will be a no-op this session.",
            e, DEFAULT_REL_VOL,
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
