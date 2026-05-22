"""
Add-On Engine (GAP-03)
======================
Evaluates whether an open profitable position should be pyramided (scaled up).

Call evaluate_add_on() once per bar while a position is open and profitable.
Returns an AddOnSignal if conditions are met, or None to hold current size.

Add-on frequency in corpus: 52.3% of all trades (2,593 add-on events across
1,049 sessions). Source: concept_add_on_mechanics.md.

Trigger priority (checked in order, first match wins):
    1. NEW_HIGH        — current bar breaks above session high watermark (42.8% of triggers)
    2. MICRO_PB_ADD    — pullback to EMA-9 then resumes higher (26.4%)
    3. VWAP_RETEST     — price touched VWAP from above, now holding above (6.5%)
    4. WHOLE_DOLLAR    — bar crosses a whole-dollar level with positive MACD
    -- HALT_RESUME     — NOT IMPLEMENTED (no halt feed in backtest data)

Preconditions (all must pass before any gate is evaluated):
    - Position is profitable (current price > entry price)
    - Current time is before 10:30 AM ET (morning momentum window only)
    - add_on_count < max_add_ons (default 4)
    - If add_on_count > 0: t1_hit must be True (T1 partial taken before 2nd+ add)

Configuration via AddOnConfig dataclass (all fields have strategy-aligned defaults).
Passing config=None uses all defaults (backward compatible).
"""

from __future__ import annotations
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytz
from dataclasses import dataclass
from datetime import datetime

from trading.models import AddOnConfig

ET = pytz.timezone('US/Eastern')

# Default config instance — used when config=None is passed
_DEFAULTS = AddOnConfig()


@dataclass
class AddOnSignal:
    """
    An add-on instruction — buy more shares to pyramid the position.
    Returned by evaluate_add_on() when conditions are met.
    """
    reason: str       # 'NEW_HIGH', 'MICRO_PB_ADD', 'VWAP_RETEST', 'WHOLE_DOLLAR_ADD'
    qty: int          # Shares to add
    price: float      # Entry price for the add (current bar close)
    new_stop: float   # Updated stop loss after add (always >= current stop)


def evaluate_add_on(
    position,               # Trade object (trading_engine.Trade)
    current_bar: dict,      # Current minute bar for the position's symbol
    bar_history: list,      # Recent bar history (oldest first, excluding current bar)
    indicators: dict,       # Keys: 'ema9', 'macd_line', 'vwap' (all optional)
    current_time: datetime, # UTC timestamp of the current bar
    config: AddOnConfig | None = None,
    temperature=None,       # TemperatureState | None — HOT = larger add sizes
) -> AddOnSignal | None:
    """
    Evaluate whether the open position should be pyramided this bar.

    Args:
        position     : Open Trade object with entry_price, shares, add_on_count, etc.
        current_bar  : Current OHLCV bar dict for the position's symbol.
        bar_history  : List of recent bar dicts (excluding current bar — no lookahead).
        indicators   : Dict with optional keys:
                         'ema9'       — current EMA-9 value (float | None)
                         'macd_line'  — current MACD line: EMA12 − EMA26 (float | None)
                         'vwap'       — current VWAP value (float | None)
        current_time : UTC-aware datetime of the bar being evaluated.
        config       : AddOnConfig controlling thresholds. None = use defaults.
        temperature  : TemperatureState | None — HOT market scales add size up.

    Returns:
        AddOnSignal if an add should be executed, None to hold current size.
    """
    cfg = config if config is not None else _DEFAULTS

    # ── Preconditions ──────────────────────────────────────────────────────────

    # 1. Only add to profitable positions — never pyramid a loser
    current_price = float(current_bar['close'])
    if current_price <= position.entry_price:
        return None

    # 2. Morning window only: adds before 10:30 ET (concept page: morning momentum)
    et_time = current_time.astimezone(ET)
    if (et_time.hour > cfg.time_cutoff_hour or
            (et_time.hour == cfg.time_cutoff_hour and et_time.minute >= cfg.time_cutoff_minute)):
        return None

    # 3. Max add-ons per trade
    if position.add_on_count >= cfg.max_add_ons:
        return None

    # 4. After first add: require T1 partial taken (scaled out first, then add again)
    #    First add (add_on_count == 0): only profitability required.
    if position.add_on_count >= 1 and not position.t1_hit:
        return None

    # ── Compute add size ───────────────────────────────────────────────────────
    add_pcts = [cfg.add_pct_tier1, cfg.add_pct_tier2, cfg.add_pct_tier3, cfg.add_pct_tier4]
    add_pct = add_pcts[min(position.add_on_count, len(add_pcts) - 1)]

    # HOT temperature: scale up add size per concept page (25–50% more in hot market)
    if temperature is not None:
        try:
            from trading.market_temperature import Temperature
            if temperature.temperature == Temperature.HOT:
                add_pct *= cfg.hot_market_multiplier
        except ImportError:
            pass

    qty = max(1, int(position.initial_shares * add_pct))

    # ── Resolve optional indicators ────────────────────────────────────────────
    ema9 = indicators.get('ema9')
    macd_line = indicators.get('macd_line')

    # VWAP: use provided value, or estimate from bar history (close-weighted)
    vwap = indicators.get('vwap')
    if vwap is None and bar_history:
        total_vol = sum(float(b['volume']) for b in bar_history if float(b.get('volume', 0)) > 0)
        if total_vol > 0:
            vwap = sum(float(b['close']) * float(b['volume']) for b in bar_history) / total_vol

    # ── Gate 1: NEW_HIGH — break above session high watermark ─────────────────
    # Most common add trigger (42.8%). Fire when current bar's high exceeds the
    # highest price seen since entry. New stop trails to just below breakout level.
    if cfg.enable_new_high:
        bar_high = float(current_bar.get('high', current_bar['close']))
        if bar_high > position.session_high_at_add:
            new_stop = max(position.stop_loss,
                           position.session_high_at_add - cfg.stop_buffer)
            return AddOnSignal(
                reason='NEW_HIGH',
                qty=qty,
                price=current_price,
                new_stop=new_stop,
            )

    # ── Gate 2: MICRO_PB_ADD — pullback to EMA-9 then resumes ────────────────
    # 26.4% of add triggers. Requires:
    #   - Recent bar(s) closed below EMA-9 (pullback to support)
    #   - Current bar closes above EMA-9 (resumption)
    #   - Current price above entry (still profitable)
    if cfg.enable_micro_pb_add and ema9 is not None and len(bar_history) >= 2:
        prev_bar = bar_history[-1]
        prev2_bar = bar_history[-2]
        pulled_back = (float(prev_bar['close']) < ema9 or
                       float(prev2_bar['close']) < ema9)
        resumed_above_ema = current_price > ema9
        if pulled_back and resumed_above_ema:
            # Stop below the pullback low
            pullback_low = min(
                float(prev_bar.get('low', prev_bar['close'])),
                float(prev2_bar.get('low', prev2_bar['close'])),
            )
            new_stop = pullback_low - cfg.stop_buffer
            if new_stop > position.stop_loss:
                return AddOnSignal(
                    reason='MICRO_PB_ADD',
                    qty=qty,
                    price=current_price,
                    new_stop=new_stop,
                )

    # ── Gate 3: VWAP_RETEST — price tested VWAP from above, now holding ───────
    # 6.5% of add triggers. Requires:
    #   - Recent bar(s) touched or briefly breached VWAP from above
    #   - Current bar closes above VWAP (confirmed hold)
    if cfg.enable_vwap_retest and vwap is not None and len(bar_history) >= 2:
        prev_close = float(bar_history[-1]['close'])
        prev2_close = float(bar_history[-2]['close'])
        # "Near VWAP recently" = within 0.2% above or any amount below VWAP
        near_vwap_recently = (
            prev_close <= vwap * 1.002 or
            prev2_close <= vwap * 1.002
        )
        holding_above_vwap = current_price > vwap
        if near_vwap_recently and holding_above_vwap:
            new_stop = vwap - cfg.stop_buffer
            if new_stop > position.stop_loss:
                return AddOnSignal(
                    reason='VWAP_RETEST',
                    qty=qty,
                    price=current_price,
                    new_stop=new_stop,
                )

    # ── Gate 4: WHOLE_DOLLAR_ADD — whole-dollar break with positive MACD ──────
    # Overlaps with NEW_HIGH but specifically fires on whole-dollar psychological levels
    # when MACD confirms front-side momentum.
    if cfg.enable_whole_dollar_add and macd_line is not None and macd_line > 0:
        if len(bar_history) >= 1:
            prev_close = float(bar_history[-1]['close'])
            floor_current = int(current_price)
            floor_prev = int(prev_close)
            # Crossed a whole-dollar boundary this bar
            if floor_current > floor_prev:
                whole_dollar = float(floor_current)
                new_stop = whole_dollar - cfg.stop_buffer
                if new_stop > position.stop_loss:
                    return AddOnSignal(
                        reason='WHOLE_DOLLAR_ADD',
                        qty=qty,
                        price=current_price,
                        new_stop=new_stop,
                    )

    return None
