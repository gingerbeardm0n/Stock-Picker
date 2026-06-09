"""
Scalp Engine — Entry/Exit Logic for Opening Bell Scalp
======================================================
Unlike the existing entry_engine.py (which scans for chart patterns per bar),
this engine executes a pre-decided trade on a pre-ranked symbol.

Entry: right at 9:30 open or on premarket high break (configurable).
Exit: scalp — tight stop, quick profit target, time stop.
"""

from __future__ import annotations
import logging
from datetime import datetime
import pytz

from trading.scalp_models import ScalpConfig

logger = logging.getLogger(__name__)

ET = pytz.timezone('US/Eastern')


def get_premarket_high(bars: list[dict]) -> float | None:
    """
    Find highest high across bars before 9:30am ET.
    Copied from entry_engine._get_premarket_high (same logic, no coupling).
    """
    highs: list[float] = []
    for bar in bars:
        t = bar.get('time')
        if t is None:
            continue
        try:
            if hasattr(t, 'astimezone'):
                et = t.astimezone(ET)
            else:
                et = datetime.fromisoformat(str(t)).astimezone(ET)
            if et.hour < 9 or (et.hour == 9 and et.minute < 30):
                highs.append(float(bar['high']))
        except Exception:
            continue
    return max(highs) if highs else None


def evaluate_entry(
    candidate: dict,
    current_bar: dict,
    premarket_high: float | None,
    bars_since_open: int,
    config: ScalpConfig,
) -> dict | None:
    """
    Decide whether to enter the scalp trade on this bar.

    Args:
        candidate:       The #1 ranked gapper dict (from scalp_ranker)
        current_bar:     Current OHLCV bar dict (time, open, high, low, close, volume)
        premarket_high:  Max high before 9:30 (None if no premarket data)
        bars_since_open: 0 = first bar at 9:30, 1 = 9:31, etc.
        config:          ScalpConfig

    Returns:
        Entry signal dict or None.
        Signal: {entry_price, stop_price, shares_hint, reason}
    """
    # Time gate: don't wait too long
    if bars_since_open > config.max_entry_bars:
        return None

    price = float(current_bar['close'])
    bar_open = float(current_bar['open'])
    bar_high = float(current_bar['high'])

    if config.entry_mode == 'market_open':
        # Enter on the very first bar at market open
        if bars_since_open == 0:
            entry_price = bar_open  # execute at open price
            stop_price = entry_price * (1 - config.stop_loss_pct / 100)
            return {
                'entry_price': entry_price,
                'stop_price': stop_price,
                'reason': f"MARKET_OPEN scalp on {candidate['symbol']}",
            }

    elif config.entry_mode == 'pm_high_break':
        # Enter when price breaks above premarket high
        if premarket_high is None:
            # No premarket data — fall back to market_open behavior
            if bars_since_open == 0:
                entry_price = bar_open
                stop_price = entry_price * (1 - config.stop_loss_pct / 100)
                return {
                    'entry_price': entry_price,
                    'stop_price': stop_price,
                    'reason': f"PM_HIGH_BREAK (no PM data, fallback open) on {candidate['symbol']}",
                }
            return None

        threshold = premarket_high * (1 + config.min_pm_high_break_pct / 100)
        if bar_high >= threshold:
            # Price broke above PM high on this bar
            entry_price = max(threshold, bar_open)  # realistic fill
            stop_price = entry_price * (1 - config.stop_loss_pct / 100)
            return {
                'entry_price': entry_price,
                'stop_price': stop_price,
                'reason': f"PM_HIGH_BREAK {price:.2f} > PM_HIGH {premarket_high:.2f}",
            }

    elif config.entry_mode == 'first_green':
        # Enter on first green bar (close > open)
        if price > bar_open:
            entry_price = price  # enter at close of green bar
            stop_price = entry_price * (1 - config.stop_loss_pct / 100)
            return {
                'entry_price': entry_price,
                'stop_price': stop_price,
                'reason': f"FIRST_GREEN bar on {candidate['symbol']}",
            }

    return None


def evaluate_exit(
    entry_price: float,
    highest_since_entry: float,
    current_bar: dict,
    bars_held: int,
    config: ScalpConfig,
) -> dict | None:
    """
    Decide whether to exit the scalp trade on this bar.

    Args:
        entry_price:          Price we entered at
        highest_since_entry:  Highest price seen since entry (for trailing stop)
        current_bar:          Current OHLCV bar
        bars_held:            How many bars we've held (0 = same bar as entry)
        config:               ScalpConfig

    Returns:
        Exit signal dict or None.
        Signal: {exit_price, reason, exit_type}

    Exit priority:
        1. Stop loss
        2. Profit target
        3. Trailing stop (if enabled)
        4. Time stop (max hold bars)
    """
    price = float(current_bar['close'])
    bar_low = float(current_bar['low'])

    # 1. Stop loss — check if bar low hit the stop
    stop_price = entry_price * (1 - config.stop_loss_pct / 100)
    if bar_low <= stop_price:
        return {
            'exit_price': stop_price,  # assume fill at stop level
            'reason': f"STOP_LOSS at {stop_price:.2f} ({config.stop_loss_pct}% below entry)",
            'exit_type': 'stop_loss',
        }

    # 2. Profit target — check if bar high hit the target
    target_price = entry_price * (1 + config.profit_target_pct / 100)
    if float(current_bar['high']) >= target_price:
        return {
            'exit_price': target_price,  # assume fill at target level
            'reason': f"PROFIT_TARGET at {target_price:.2f} (+{config.profit_target_pct}%)",
            'exit_type': 'profit_target',
        }

    # 3. Trailing stop (if enabled)
    if config.trailing_stop_pct > 0 and highest_since_entry > entry_price:
        trail_price = highest_since_entry * (1 - config.trailing_stop_pct / 100)
        if bar_low <= trail_price:
            return {
                'exit_price': trail_price,
                'reason': f"TRAILING_STOP at {trail_price:.2f} (trail {config.trailing_stop_pct}% from {highest_since_entry:.2f})",
                'exit_type': 'trailing_stop',
            }

    # 4. Time stop — forced exit after max_hold_bars
    if bars_held >= config.max_hold_bars:
        return {
            'exit_price': price,  # exit at close of current bar
            'reason': f"TIME_STOP after {bars_held} bars",
            'exit_type': 'time_stop',
        }

    return None
