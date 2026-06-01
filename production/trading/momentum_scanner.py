"""
Momentum Scanner — shared intraday discovery criteria (high-day-momo).

`qualifies_momentum` is a PURE function: no DB, no I/O, no side-effects.
Called identically from:
  - Orchestrator._scan_for_entry  (scanner mode, sim)
  - live_scanner._run_intraday_momentum_scan  (live runtime)

Keeping ONE implementation here prevents sim/live discovery divergence.

Gates (all must pass):
  G1  rel_vol >= cfg.min_relative_volume        (default 5x)
  G2  price >= high_of_day * (1 - cfg.hod_tol)  (at or near new high-of-day)
  G3  9:30 ET <= et_time < cfg.scan_end_hour     (default 9:30-11:00)
  G4  float_shares <= cfg.max_float              (default 20M; skipped if float unknown)
  G5  cfg.min_price <= price <= cfg.max_price     (default $1-$20)
  G6  (price - prior_close) / prior_close * 100 >= cfg.min_intraday_gain (default 5%)

Corpus references: "high-day-momo" appears 2,978 times across 1,799-session corpus.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from trading.models import MomentumScanConfig


def qualifies_momentum(
    *,
    price: float,
    prior_close: float,
    high_of_day: float,
    rel_vol: float,
    float_shares: float | None,
    et_time: datetime,
    cfg,
) -> bool:
    """
    Return True iff a symbol passes all intraday momentum scanner gates.

    Parameters
    ----------
    price       : Current bar close price.
    prior_close : Prior session close (for gain % calculation).
    high_of_day : Highest price seen so far today (time-forward, no lookahead).
    rel_vol     : Relative volume vs historical average at this time of day.
    float_shares: Shares outstanding (None = unknown -> G4 skipped gracefully).
    et_time     : Bar timestamp in US/Eastern timezone.
    cfg         : MomentumScanConfig instance.
    """
    # G5: price range
    if price < cfg.min_price or price > cfg.max_price:
        return False

    # G6: intraday gain vs prior close
    if prior_close <= 0:
        return False
    gain_pct = (price - prior_close) / prior_close * 100.0
    if gain_pct < cfg.min_intraday_gain:
        return False

    # G2: at or near new high-of-day
    # high_of_day = running max high seen so far (time-forward, no lookahead).
    # hod_tol=0.0  -> price must be >= high_of_day exactly.
    # hod_tol=0.02 -> within 2% below HOD still qualifies.
    hod_threshold = high_of_day * (1.0 - cfg.hod_tol)
    if price < hod_threshold:
        return False

    # G1: relative volume
    if rel_vol < cfg.min_relative_volume:
        return False

    # G3: time window [9:30 ET, scan_end_hour) exclusive upper bound
    hour = et_time.hour
    minute = et_time.minute
    if hour < 9 or (hour == 9 and minute < 30):
        return False
    if hour >= cfg.scan_end_hour:
        return False

    # G4: float filter (graceful degradation: skip if float unknown)
    if float_shares is not None and float_shares > cfg.max_float:
        return False

    return True
