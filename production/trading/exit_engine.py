"""
Exit Engine
===========
Decides whether and how to exit (or scale out of) an open position.

Call evaluate_exit() once per bar while a position is open.
Returns an ExitSignal if action is needed, or None to hold.

Exit priority (checked in order, first match wins):
    1. Hard stop          — price hit stop loss                  → exit all
    2. Trailing stop      — price fell from peak by trail dist   → exit all remaining
    3. Target 1           — hit T1 R/R ratio                    → scale out (default 50%)
    4. Target 2           — hit T2 R/R ratio                    → scale out (default 25%)
    5. EMA-9 cross        — close below EMA while profitable     → exit remaining
    6. MACD flip          — histogram crosses zero (Phase 3)     → scale out (if enabled)
    7. Resistance touch   — N-th test of prior-day high (Ph. 3) → scale out (if enabled)
    8. Early time decay   — before 11 AM, no major gains (Ph. 4)→ exit if enabled
    9. Time decay         — after 12 PM ET, profitable           → exit remaining
   10. Selling pressure   — selling vol > buying vol × ratio     → scale out
   11. Volume dry-up      — buying vol collapsed vs avg (Ph. 4)  → scale out (if enabled)

Configuration via ExitConfig dataclass (all fields have strategy-aligned defaults).
Passing config=None uses all defaults (backward compatible).
"""

from __future__ import annotations
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytz
from datetime import datetime

from trading.models import ExitSignal, ExitConfig
from trading.indicators import estimate_buy_sell_volume

ET = pytz.timezone('US/Eastern')

# Default config instance — used when config=None is passed
_DEFAULTS = ExitConfig()


def evaluate_exit(
    position,               # Trade object (from trading/trading_engine.py)
    current_bar: dict,      # Current minute bar for the position's symbol
    indicators: dict,       # See keys below
    current_time: datetime, # UTC timestamp of the current bar
    config: ExitConfig | None = None,
    temperature=None,       # TemperatureState | None — COLD/CHOP exits full position at T1
) -> ExitSignal | None:
    """
    Evaluate whether the current position should be exited or scaled.

    Args:
        position     : Open Trade object with entry_price, stop_loss, shares, etc.
        current_bar  : Current OHLCV bar for the position symbol.
        indicators   : Dict with any of:
                         'ema9'               — current EMA-9 value (float | None)
                         'macd_histogram'     — current bar histogram (float | None)
                         'macd_histogram_prev'— prior bar histogram (float | None)
                         'prior_day_high'     — prior trading day's high (float | None)
                         'avg_buy_vol_5bar'   — avg buying volume of last 5 bars (float | None)
        current_time : Current UTC timestamp.
        config       : ExitConfig with all thresholds. None = use all defaults.

    Returns:
        ExitSignal with reason, price, qty, and optional flags — or None (hold).
    """
    cfg = config if config is not None else _DEFAULTS

    current_price = float(current_bar['close'])
    et_time = current_time.astimezone(ET)
    shares_remaining = position.shares_remaining

    if shares_remaining <= 0:
        return None

    # ── 1. Hard stop (ALWAYS first — unconditional) ────────────────────────────
    if current_price <= position.stop_loss:
        return ExitSignal(
            reason='STOP_HIT',
            price=current_price,
            qty=shares_remaining,
        )

    # ── 2. Trailing stop ───────────────────────────────────────────────────────
    # Only activates after at least T1 has fired (some shares already sold).
    # Ensures the trail_stop is meaningful (i.e. above the hard stop).
    if cfg.trailing_stop_distance > 0 and shares_remaining < position.shares:
        trail_stop = position.highest_price_since_entry - cfg.trailing_stop_distance
        if trail_stop > position.stop_loss and current_price <= trail_stop:
            return ExitSignal(
                reason='TRAILING_STOP',
                price=current_price,
                qty=shares_remaining,
            )

    # ── 3. Target 1 ────────────────────────────────────────────────────────────
    # Scale out target1_qty_pct of original position; move stop to breakeven.
    # Use original_stop_loss (not stop_loss) — stop_loss moves to breakeven after T1,
    # which would zero out the stop distance and corrupt T2 calculation.
    #
    # COLD/CHOP exception (concept_market_temperature.md §4):
    # On cold or chop days, exit the FULL position at T1. Do not hold for T2.
    # Ross: "Take profits at first target, do not hold for T2 or T3."
    stop_distance = position.entry_price - position.original_stop_loss
    t1_price = position.entry_price + stop_distance * cfg.target1_ratio
    if current_price >= t1_price and shares_remaining == position.shares:
        from trading.market_temperature import Temperature
        cold_day = (
            temperature is not None and
            temperature.temperature in (Temperature.COLD, Temperature.CHOP)
        )
        if cold_day:
            return ExitSignal(
                reason='TARGET_1_COLD',
                price=current_price,
                qty=shares_remaining,  # Full exit on cold day
            )
        qty = max(1, int(position.shares * cfg.target1_qty_pct))
        return ExitSignal(
            reason='TARGET_1',
            price=current_price,
            qty=qty,
            move_stop_to_breakeven=True,
        )

    # ── 4. Target 2 ────────────────────────────────────────────────────────────
    # Scale out target2_qty_pct of original position (from the post-T1 remainder).
    t2_price = position.entry_price + stop_distance * cfg.target2_ratio
    t1_qty = int(position.shares * cfg.target1_qty_pct)
    after_t1_shares = position.shares - t1_qty
    if (current_price >= t2_price
            and 0 < shares_remaining <= after_t1_shares):
        qty = max(1, int(position.shares * cfg.target2_qty_pct))
        qty = min(qty, shares_remaining)
        return ExitSignal(
            reason='TARGET_2',
            price=current_price,
            qty=qty,
        )

    # ── Soft exits — only triggered when the position is profitable ────────────
    unrealized_pnl = shares_remaining * (current_price - position.entry_price)
    in_profit = unrealized_pnl > 0

    # ── 5. EMA-9 close cross ───────────────────────────────────────────────────
    # Close below EMA-9 while profitable = trend has reversed.
    ema9 = indicators.get('ema9')
    if in_profit and ema9 is not None and current_price < ema9:
        qty = max(1, int(shares_remaining * cfg.ema_cross_qty_pct))
        # Tighten stop to breakeven (or higher if already tightened)
        new_stop = max(position.stop_loss, position.entry_price)
        return ExitSignal(
            reason='EMA_CROSS',
            price=current_price,
            qty=qty,
            new_stop_price=new_stop,
        )

    # ── 6. MACD histogram flip (Phase 3) ──────────────────────────────────────
    # Fire when histogram crosses from positive to negative while profitable.
    if cfg.enable_macd_flip_exit and in_profit:
        macd_now = indicators.get('macd_histogram')
        macd_prev = indicators.get('macd_histogram_prev')
        if (macd_prev is not None and macd_now is not None
                and macd_prev > 0 and macd_now <= 0):
            # Tighten stop only (no immediate sell)
            qty = 0
            new_stop = max(position.stop_loss, position.entry_price)
            return ExitSignal(
                reason='MACD_FLIP',
                price=current_price,
                qty=qty,
                new_stop_price=new_stop,
            )

    # ── 7. Resistance touch (Phase 3) ─────────────────────────────────────────
    # Track touches of prior-day high. Exit on N-th test (likely reversal).
    if cfg.enable_resistance_exit and in_profit:
        prior_high = indicators.get('prior_day_high')
        if prior_high and prior_high > 0:
            bar_high = float(current_bar['high'])
            if bar_high >= prior_high - cfg.resistance_tolerance:
                position.resistance_touches += 1
                if position.resistance_touches >= cfg.resistance_touch_threshold:
                    qty = max(1, int(shares_remaining * cfg.resistance_exit_qty_pct))
                    return ExitSignal(
                        reason='RESISTANCE_TOUCH',
                        price=current_price,
                        qty=qty,
                    )

    # ── 8. Early time decay (Phase 4) ─────────────────────────────────────────
    # Before the main 11 AM cutoff, exit if position has no major gains yet.
    # "No major gains" = unrealized % < early_time_decay_min_gain_pct.
    if cfg.early_time_decay_hour > 0 and in_profit:
        early_hour = cfg.early_time_decay_hour
        early_min = cfg.early_time_decay_minute
        if et_time.hour == early_hour and et_time.minute >= early_min:
            unrealized_pct = (current_price - position.entry_price) / position.entry_price * 100
            if unrealized_pct < cfg.early_time_decay_min_gain_pct:
                return ExitSignal(
                    reason='EARLY_TIME_DECAY',
                    price=current_price,
                    qty=shares_remaining,
                )

    # ── 9. Time decay — after 12:00 PM ET ─────────────────────────────────────
    # Exit open positions before the midday cutoff.
    if in_profit and et_time.hour >= cfg.time_decay_hour:
        return ExitSignal(
            reason='TIME_DECAY',
            price=current_price,
            qty=shares_remaining,
        )

    # ── 10. Selling pressure ───────────────────────────────────────────────────
    # Heavy selling on a profitable position = "give back half" risk.
    if cfg.enable_selling_pressure and in_profit:
        buying_vol, selling_vol = estimate_buy_sell_volume(
            current_bar['open'], current_bar['high'],
            current_bar['low'], current_bar['close'],
            current_bar['volume'],
        )
        if selling_vol > buying_vol * cfg.selling_pressure_ratio:
            qty = max(1, int(shares_remaining * cfg.selling_pressure_qty_pct))
            return ExitSignal(
                reason='SELLING_PRESSURE',
                price=current_price,
                qty=qty,
            )

    # ── 11. Volume dry-up (Phase 4) ───────────────────────────────────────────
    # Buying volume collapsed vs recent average = buyers stepping away.
    if cfg.enable_volume_dry_up_exit and in_profit:
        avg_buy_vol = indicators.get('avg_buy_vol_5bar')
        if avg_buy_vol and avg_buy_vol > 0:
            buying_vol, _ = estimate_buy_sell_volume(
                current_bar['open'], current_bar['high'],
                current_bar['low'], current_bar['close'],
                current_bar['volume'],
            )
            if buying_vol < avg_buy_vol * cfg.volume_dry_up_threshold:
                qty = max(1, int(shares_remaining * cfg.volume_dry_up_qty_pct))
                return ExitSignal(
                    reason='VOLUME_DRY_UP',
                    price=current_price,
                    qty=qty,
                )

    return None  # Hold
