"""
VWAP Engine — Entry/Exit Logic for VWAP Reclaim Strategy
=========================================================
Pure functions, no DB / broker coupling — same architecture as scalp_engine.py.
The simulator and the live runner both call these exact functions, so backtest
and live behavior cannot diverge.

VWAP calc and reclaim conditions copied (not imported) from
entry_engine._calculate_vwap / patterns.detect_vwap_reclaim to decouple this
pipeline from the monolith's EntryConfig sprawl.
"""

from __future__ import annotations
import logging
from datetime import datetime
import pytz

from trading.vwap_models import (
    VwapReclaimConfig, ENTRY_WINDOW_START, ENTRY_WINDOW_END,
)

logger = logging.getLogger(__name__)

ET = pytz.timezone('US/Eastern')


def _bar_et(bar: dict) -> datetime | None:
    """Get a bar's time as ET datetime, or None."""
    t = bar.get('_et') or bar.get('time')
    if t is None:
        return None
    try:
        if hasattr(t, 'astimezone'):
            return t.astimezone(ET)
        return datetime.fromisoformat(str(t)).astimezone(ET)
    except Exception:
        return None


def in_entry_window(bar: dict) -> bool:
    """True if the bar's ET time is inside the fixed 10:00-11:30 entry window."""
    et = _bar_et(bar)
    if et is None:
        return False
    minutes = et.hour * 60 + et.minute
    start = ENTRY_WINDOW_START[0] * 60 + ENTRY_WINDOW_START[1]
    end = ENTRY_WINDOW_END[0] * 60 + ENTRY_WINDOW_END[1]
    return start <= minutes <= end


class VwapAccumulator:
    """
    O(1) running session VWAP.

    VWAP = sum(typical_price x volume) / sum(volume), market-hours bars only
    (9:30 ET onward — standard intraday VWAP resets at the open).
    Feed bars in chronological order via update(); read .value anytime.
    """

    def __init__(self):
        self._tpv = 0.0
        self._vol = 0.0

    def update(self, bar: dict) -> None:
        et = _bar_et(bar)
        if et is None:
            return
        if et.hour < 9 or (et.hour == 9 and et.minute < 30):
            return  # premarket bars excluded
        vol = float(bar.get('volume', 0) or 0)
        if vol <= 0:
            return
        typical = (float(bar['high']) + float(bar['low']) + float(bar['close'])) / 3.0
        self._tpv += typical * vol
        self._vol += vol

    @property
    def value(self) -> float | None:
        if self._vol <= 0:
            return None
        return self._tpv / self._vol


def calculate_vwap(bars: list[dict]) -> float | None:
    """One-shot session VWAP over a bar list (convenience wrapper)."""
    acc = VwapAccumulator()
    for b in bars:
        acc.update(b)
    return acc.value


def evaluate_entry(
    candidate: dict,
    bars: list[dict],
    vwap: float | None,
    config: VwapReclaimConfig,
) -> dict | None:
    """
    Decide whether the CURRENT (last) bar is a valid VWAP reclaim entry.

    Conditions (from concept_vwap_reclaim.md decision rules):
      1. Bar is inside the 10:00-11:30 ET entry window
      2. VWAP is known (>= 30 min of session bars)
      3. Current bar closes ABOVE VWAP, and is green
      4. >= min_bars_below closes below VWAP in the lookback (the test happened)
      5. Reclaim bar volume >= reclaim_vol_mult x lookback average

    Args:
        candidate: ranked gapper dict (symbol, gap_pct, news_tier, ...)
        bars:      session bars so far, oldest -> newest (last = current bar)
        vwap:      running session VWAP as of the current bar
        config:    VwapReclaimConfig

    Returns entry signal {entry_price, stop_price, vwap, reason} or None.
    """
    if vwap is None or vwap <= 0:
        return None
    if len(bars) < config.lookback_bars + 1:
        return None

    current = bars[-1]

    if not in_entry_window(current):
        return None

    close = float(current['close'])
    bar_open = float(current['open'])

    # Reclaim: close above VWAP on a green bar
    if close <= vwap:
        return None
    if close <= bar_open:
        return None

    # The test: enough closes below VWAP in the lookback window
    lookback = bars[-(config.lookback_bars + 1):-1]
    below = sum(1 for b in lookback if float(b['close']) < vwap)
    if below < config.min_bars_below:
        return None

    # Volume confirmation: buyers returning with conviction, not drift
    if len(lookback) >= 3:
        avg_vol = sum(float(b.get('volume', 0) or 0) for b in lookback) / len(lookback)
        if avg_vol > 0 and float(current.get('volume', 0) or 0) < avg_vol * config.reclaim_vol_mult:
            return None

    stop_price = vwap - config.stop_vwap_offset

    if config.entry_mode == 'reclaim_close':
        entry_price = close
    else:  # 'reclaim_high_break' — buy the break of the reclaim bar's high
        entry_price = float(current['high']) + 0.01

    if entry_price - stop_price <= 0:
        return None

    return {
        'entry_price': entry_price,
        'stop_price': stop_price,
        'vwap': vwap,
        'reason': (
            f"VWAP_RECLAIM {candidate.get('symbol', '?')}: "
            f"close {close:.2f} > VWAP {vwap:.2f}, "
            f"{below} bar(s) below in lookback ({config.entry_mode})"
        ),
    }


def evaluate_exit(
    entry_price: float,
    stop_price: float,
    highest_since_entry: float,
    current_bar: dict,
    bars_held: int,
    config: VwapReclaimConfig,
) -> dict | None:
    """
    Decide whether to exit on this bar.

    Unlike the scalp (percent stop from entry), the reclaim stop is the
    VWAP-anchored stop_price fixed at entry: close back below VWAP = the
    reclaim failed, the thesis is dead.

    Exit priority:
        1. Stop loss (bar low touches the VWAP-anchored stop)
        2. Profit target
        3. Trailing stop (if enabled)
        4. Time stop (max_hold_bars)

    Returns exit signal {exit_price, reason, exit_type} or None.
    """
    price = float(current_bar['close'])
    bar_low = float(current_bar['low'])
    bar_high = float(current_bar['high'])

    # 1. Stop loss — VWAP-anchored
    if bar_low <= stop_price:
        return {
            'exit_price': stop_price,
            'reason': f"STOP_LOSS at {stop_price:.2f} (below entry VWAP)",
            'exit_type': 'stop_loss',
        }

    # 2. Profit target
    target_price = entry_price * (1 + config.profit_target_pct / 100)
    if bar_high >= target_price:
        return {
            'exit_price': target_price,
            'reason': f"PROFIT_TARGET at {target_price:.2f} (+{config.profit_target_pct}%)",
            'exit_type': 'profit_target',
        }

    # 3. Trailing stop
    if config.trailing_stop_pct > 0 and highest_since_entry > entry_price:
        trail_price = highest_since_entry * (1 - config.trailing_stop_pct / 100)
        if bar_low <= trail_price:
            return {
                'exit_price': trail_price,
                'reason': (
                    f"TRAILING_STOP at {trail_price:.2f} "
                    f"(trail {config.trailing_stop_pct}% from {highest_since_entry:.2f})"
                ),
                'exit_type': 'trailing_stop',
            }

    # 4. Time stop
    if bars_held >= config.max_hold_bars:
        return {
            'exit_price': price,
            'reason': f"TIME_STOP after {bars_held} bars",
            'exit_type': 'time_stop',
        }

    return None
