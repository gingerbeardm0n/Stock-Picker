"""
Micro-Pullback Engine — Entry/Exit Logic for Strategy #3
=========================================================
Pure functions, no DB / broker coupling — same architecture as scalp_engine.py
and vwap_engine.py. The simulator and the live runner both call these exact
functions, so backtest and live behavior cannot diverge.

The 9-EMA is computed INLINE here (standard exponential formula) rather than
importing indicators.calculate_ema — that function returns a trailing SMA, not
an EMA (known bug in the deprecated monolith path; see docs/PROJECT_HISTORY.md
hygiene notes). Keeping it local also matches the "copy, don't couple" pattern.
"""

from __future__ import annotations
import logging
from datetime import datetime
import pytz

from trading.micro_pullback_models import (
    MicroPullbackConfig, ENTRY_WINDOW_START, ENTRY_WINDOW_END, EMA_PERIOD,
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
    """True if the bar's ET time is inside the fixed 9:40-10:30 entry window."""
    et = _bar_et(bar)
    if et is None:
        return False
    minutes = et.hour * 60 + et.minute
    start = ENTRY_WINDOW_START[0] * 60 + ENTRY_WINDOW_START[1]
    end = ENTRY_WINDOW_END[0] * 60 + ENTRY_WINDOW_END[1]
    return start <= minutes <= end


def ema(closes: list[float], period: int = EMA_PERIOD) -> float | None:
    """Standard exponential moving average of the final bar.

    SMA-seeded (first `period` values), then EMA[i] = close*k + EMA[i-1]*(1-k)
    with k = 2/(period+1). Returns None until there are `period` closes.
    """
    if len(closes) < period:
        return None
    k = 2.0 / (period + 1)
    val = sum(closes[:period]) / period  # SMA seed
    for c in closes[period:]:
        val = c * k + val * (1 - k)
    return val


def evaluate_entry(
    candidate: dict,
    bars: list[dict],
    config: MicroPullbackConfig,
) -> dict | None:
    """
    Decide whether the CURRENT (last) bar completes a valid micro-pullback entry.

    Conditions (from concept_micro_pullback.md decision rules):
      1. Current bar is inside the 9:40-10:30 ET entry window
      2. A prior peak (rip) exists in the lookback window
      3. 1..max_pullback_bars pullback candles between the peak and now
      4. Pullback is shallow (drop from peak <= max_pullback_retrace %)
      5. Pullback volume is lighter than the rip bar (< pullback_vol_ratio x)
      6. Current bar is green, breaks above the pullback high, on EXPANDING volume
         (>= resume_vol_mult x pullback avg)
      7. Price holds at/above the 9-EMA

    Args:
        candidate: ranked gapper dict (symbol, gap_pct, news_tier, ...)
        bars:      session bars so far (9:30+), oldest -> newest (last = current)
        config:    MicroPullbackConfig

    Returns entry signal {entry_price, stop_price, reason} or None.
    """
    if len(bars) < config.lookback_bars + 1:
        return None

    current = bars[-1]
    if not in_entry_window(current):
        return None

    cur_open = float(current['open'])
    cur_close = float(current['close'])
    cur_high = float(current['high'])
    cur_vol = float(current.get('volume', 0) or 0)

    # ── (7) EMA-9 hold — price must close at/above the 9-EMA ────────────────
    closes = [float(b['close']) for b in bars]
    ema9 = ema(closes, EMA_PERIOD)
    if ema9 is None or cur_close < ema9:
        return None

    # ── (2) Find the prior peak (rip) within the lookback, EXCLUDING the
    #        current bar (the current bar is the resumption, not the peak). ──
    window = bars[-(config.lookback_bars + 1):-1]  # excludes current
    if not window:
        return None
    peak_idx_local = max(range(len(window)), key=lambda i: float(window[i]['high']))
    peak_bar = window[peak_idx_local]
    peak_high = float(peak_bar['high'])
    peak_vol = float(peak_bar.get('volume', 0) or 0)

    # ── (3) Pullback = bars strictly after the peak, excluding current ──────
    pullback = window[peak_idx_local + 1:]
    n_pullback = len(pullback)
    if n_pullback < 1 or n_pullback > config.max_pullback_bars:
        return None

    pullback_high = max(float(b['high']) for b in pullback)
    pullback_low = min(float(b['low']) for b in pullback)
    pullback_vols = [float(b.get('volume', 0) or 0) for b in pullback]
    avg_pullback_vol = sum(pullback_vols) / len(pullback_vols)

    # ── (4) Shallow: pullback low didn't drop more than max_pullback_retrace%
    #        below the peak. ────────────────────────────────────────────────
    if peak_high <= 0:
        return None
    drop_pct = (peak_high - pullback_low) / peak_high * 100
    if drop_pct > config.max_pullback_retrace:
        return None

    # ── (5) Pullback volume lighter than the rip (sellers not aggressive) ───
    if peak_vol > 0 and avg_pullback_vol >= peak_vol * config.pullback_vol_ratio:
        return None

    # ── (6) Resumption: green bar, breaks the pullback high, volume expands ─
    if cur_close <= cur_open:
        return None
    if cur_high < pullback_high:
        return None  # hasn't broken the pullback high yet
    if avg_pullback_vol > 0 and cur_vol < avg_pullback_vol * config.resume_vol_mult:
        return None

    # Entry = break of the pullback high (realistic fill — the bar traded there).
    entry_price = pullback_high + 0.01
    stop_price = pullback_low - 0.01  # structural: below the pullback low

    if entry_price - stop_price <= 0:
        return None

    return {
        'entry_price': entry_price,
        'stop_price': stop_price,
        'ema9': ema9,
        'reason': (
            f"MICRO_PULLBACK {candidate.get('symbol', '?')}: "
            f"{n_pullback}-bar pullback ({drop_pct:.1f}% off peak {peak_high:.2f}), "
            f"break {pullback_high:.2f} on {cur_vol/avg_pullback_vol:.1f}x vol, "
            f"close {cur_close:.2f} >= EMA9 {ema9:.2f}"
        ),
    }


def evaluate_exit(
    entry_price: float,
    stop_price: float,
    highest_since_entry: float,
    current_bar: dict,
    bars_held: int,
    config: MicroPullbackConfig,
) -> dict | None:
    """
    Decide whether to exit on this bar.

    The stop is the structural pullback-low stop fixed at entry: a close back
    below the pullback low means the rest became a reversal — thesis dead.

    Exit priority:
        1. Stop loss (bar low touches the pullback-low stop)
        2. Profit target
        3. Trailing stop (if enabled)
        4. Time stop (max_hold_bars)

    Returns exit signal {exit_price, reason, exit_type} or None.
    """
    price = float(current_bar['close'])
    bar_low = float(current_bar['low'])
    bar_high = float(current_bar['high'])

    # 1. Stop loss — structural (pullback low)
    if bar_low <= stop_price:
        return {
            'exit_price': stop_price,
            'reason': f"STOP_LOSS at {stop_price:.2f} (below pullback low)",
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
