"""
Entry Engine
============
Decides whether to enter a position on the current bar.

Call evaluate_entry() once per bar per symbol when looking for new trades.
It applies all gates in order (fast rejects first) and returns an EntrySignal
if everything checks out, or None if any gate fails.

Gate order (matches Ross Cameron's pre-entry checklist):
    1. Trading window (9:30 AM - 11:00 AM ET)
    2. Ross Cameron's 5 Pillars
    3. Technical confirmation (EMA-9, MACD, trending up)
    4. Pattern detection (Bull Flag → Micro Pullback → ABCD → Dip Buy → Flat Top)
    5. Risk/Reward validation (≥ 2:1)
"""

from __future__ import annotations
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytz
from datetime import datetime

from trading.models import PatternSignal, EntrySignal, ScannerConfig, EntryConfig
from trading.indicators import (
    calculate_ema,
    calculate_macd,
    get_current_ema,
    is_trending_up,
    volume_on_up_bars_dominates,
    estimate_buy_sell_volume,
)
from trading.patterns import (
    detect_gap_and_go,
    detect_bull_flag,
    detect_micro_pullback,
    detect_abcd_pattern,
    detect_dip_buy,
    detect_flat_top_breakout,
)

ET = pytz.timezone('US/Eastern')

# Module-level defaults — used when config=None is passed (backward compatible)
_SCANNER_DEFAULTS = ScannerConfig()
_ENTRY_DEFAULTS = EntryConfig()

# Trading window (fixed by strategy, not tuned)
TRADING_START_HOUR = 9
TRADING_START_MINUTE = 30   # 9:30 AM ET
TRADING_END_HOUR = 11       # 11:00 AM ET (no new entries after 11)


# ── Gap and Go helpers ────────────────────────────────────────────────────────

def _get_premarket_high(bars: list[dict]) -> float | None:
    """
    Find the highest high across all bars timestamped before 9:30am ET.

    Called once per evaluate_entry() call; result passed to detect_gap_and_go()
    via the indicators dict as 'premarket_high'.

    Handles multiple bar timestamp formats:
        - datetime object (with or without tzinfo)
        - ISO-format string ("2026-05-06T07:30:00-04:00")

    Returns None if no premarket bars found (graceful degradation).
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
            # Premarket: strictly before 9:30am ET
            if et.hour < 9 or (et.hour == 9 and et.minute < 30):
                highs.append(float(bar['high']))
        except Exception:
            continue
    return max(highs) if highs else None


def _count_market_open_bars(bars: list[dict]) -> int:
    """
    Count bars timestamped at or after 9:30am ET.

    Used to restrict gap-and-go detection to the opening window only
    (first N bars after open = highest-probability gap-and-go entries).
    """
    count = 0
    for bar in bars:
        t = bar.get('time')
        if t is None:
            continue
        try:
            if hasattr(t, 'astimezone'):
                et = t.astimezone(ET)
            else:
                et = datetime.fromisoformat(str(t)).astimezone(ET)
            at_or_after_open = (
                et.hour > 9 or (et.hour == 9 and et.minute >= 30)
            )
            if at_or_after_open:
                count += 1
        except Exception:
            continue
    return count


# ── Main Entry Point ───────────────────────────────────────────────────────────

def evaluate_entry(
    symbol: str,
    bar_history: list[dict],    # Last 20+ bars for this symbol (oldest first, NOT including current)
    current_bar: dict,          # The bar being evaluated right now
    fundamentals: dict,         # {'float_shares': int, 'market_cap': int} or {}
    prior_close: float | None,  # Previous day's close price
    current_time: datetime,     # UTC datetime of the current bar
    relative_volume: float,     # Pre-calculated relative volume (time-of-day adjusted)
    scanner_config: ScannerConfig | None = None,  # Category A params; None = defaults
    entry_config: EntryConfig | None = None,      # Category B params; None = defaults
) -> EntrySignal | None:
    """
    Full entry evaluation pipeline. Returns EntrySignal if all gates pass, else None.

    Args:
        symbol          : Stock ticker
        bar_history     : Bars BEFORE current_bar (oldest first). Used for indicators
                          and pattern detection. Should contain 20+ bars minimum.
        current_bar     : The bar being evaluated (included at the end for patterns)
        fundamentals    : Float and market cap data (pass {} if unavailable)
        prior_close     : Prior day close for premarket gain calculation
        current_time    : Current bar timestamp (UTC)
        relative_volume : Relative volume already calculated by the caller
        scanner_config  : Category A thresholds (5 Pillars). None = strategy defaults.
        entry_config    : Category B thresholds (patterns, R/R). None = strategy defaults.
    Returns:
        EntrySignal with pattern and pillar data, or None
    """
    scfg = scanner_config if scanner_config is not None else _SCANNER_DEFAULTS
    ecfg = entry_config if entry_config is not None else _ENTRY_DEFAULTS

    # ── Gate 1: Trading window (9:30 AM - 11:00 AM ET) ───────────────────────
    et_time = current_time.astimezone(ET)
    in_window = (
        et_time.hour > TRADING_START_HOUR or
        (et_time.hour == TRADING_START_HOUR and et_time.minute >= TRADING_START_MINUTE)
    ) and et_time.hour < TRADING_END_HOUR

    if not in_window:
        return None

    # ── Gate 2: 5 Pillars ─────────────────────────────────────────────────────
    passes, pillar_data = _check_5_pillars(
        symbol, bar_history, current_bar, fundamentals, prior_close, relative_volume, scfg
    )
    if not passes:
        return None

    # ── Gate 3: Technical confirmation ────────────────────────────────────────
    all_bars_so_far = bar_history + [current_bar]
    prices = [float(b['close']) for b in all_bars_so_far]

    ema9 = get_current_ema(prices, period=9)
    macd_data = calculate_macd(prices)  # None if < 35 bars

    # Compute gap-and-go prerequisites: premarket high and bars-since-open count
    premarket_high = _get_premarket_high(all_bars_so_far)
    market_open_bar_count = _count_market_open_bars(all_bars_so_far)

    indicators = {
        'ema9': ema9,
        'macd_histogram': macd_data['histogram'] if macd_data else None,
        'trending_up': is_trending_up(all_bars_so_far),
        'vol_up_dominates': volume_on_up_bars_dominates(all_bars_so_far),
        # Gap-and-go specific: premarket high level and opening bar count
        'premarket_high': premarket_high,
        'market_open_bar_count': market_open_bar_count,
    }

    current_price = float(current_bar['close'])

    # Price must be above 9 EMA (requires 9+ bars to be valid)
    if ecfg.enable_ema9 and ema9 is not None and current_price < ema9:
        return None

    # MACD histogram must be positive (requires 35+ bars to be valid).
    # NOTE: This gate is disabled by default (enable_macd=False).
    # If re-enabled, be aware it MUST NOT block gap-and-go — that pattern
    # explicitly does not require MACD (96% of gap-and-go trades = unknown MACD
    # state). See concept_gap_and_go.md. Patterns that require MACD (e.g.
    # dip_buy) enforce it internally in their own detector.
    if ecfg.enable_macd and macd_data is not None and indicators['macd_histogram'] <= 0:
        return None

    # Stock must be in an uptrend
    if ecfg.enable_trend and not indicators['trending_up']:
        return None

    # ── Gate 4: Pattern detection ─────────────────────────────────────────────
    # Try patterns in priority order (data-derived from 1,800 session analysis).
    # Gap-and-go first: #1 by frequency (1,177 trades, 23% of all trades, 69% win rate).
    signal: PatternSignal | None = (
        (detect_gap_and_go(all_bars_so_far, indicators, ecfg) if ecfg.enable_gap_and_go else None)   or
        (detect_bull_flag(all_bars_so_far, indicators, ecfg) if ecfg.enable_bull_flag else None)     or
        (detect_micro_pullback(all_bars_so_far, indicators, ecfg) if ecfg.enable_micro_pullback else None) or
        (detect_abcd_pattern(all_bars_so_far, ecfg) if ecfg.enable_abcd else None)                  or
        (detect_dip_buy(all_bars_so_far, indicators, ecfg) if ecfg.enable_dip_buy else None)         or
        (detect_flat_top_breakout(all_bars_so_far, ecfg) if ecfg.enable_flat_top else None)
    )

    if signal is None:
        return None

    # ── Gate 5: Risk/Reward must be ≥ min_rr_ratio ───────────────────────────
    if signal.stop_distance <= 0:
        return None
    if ecfg.enable_rr and signal.risk_reward_ratio < ecfg.min_rr_ratio:
        return None

    # All gates passed — return entry signal
    pillar_data['ema9'] = round(ema9, 4) if ema9 else None
    pillar_data['macd_histogram'] = round(indicators['macd_histogram'], 6) if indicators['macd_histogram'] else None
    pillar_data['pattern'] = signal.pattern_type

    return EntrySignal(
        symbol=symbol,
        pattern=signal,
        pillar_data=pillar_data,
    )


# ── 5 Pillars Check ───────────────────────────────────────────────────────────

def _check_5_pillars(
    symbol: str,
    bar_history: list[dict],
    bar: dict,
    fundamentals: dict,
    prior_close: float | None,
    relative_volume: float,
    config: ScannerConfig | None = None,
) -> tuple[bool, dict]:
    """
    Evaluate all 5 Ross Cameron pillars.

    Returns (passes: bool, data: dict).
    data contains the pillar values for logging even on failure.
    """
    cfg = config if config is not None else _SCANNER_DEFAULTS
    data: dict = {}
    current_price = float(bar['close'])
    data['price'] = current_price

    # Pillar 1: Price range
    if cfg.enable_price_range:
        if current_price < cfg.min_price or current_price > cfg.max_price:
            data['fail_reason'] = f"Price ${current_price:.2f} outside ${cfg.min_price}-${cfg.max_price}"
            return False, data

    # Pillar 2: Up X%+ from prior close
    if prior_close is None or prior_close <= 0:
        data['fail_reason'] = 'No prior close data'
        return False, data

    pct_change = ((current_price - prior_close) / prior_close) * 100
    data['pct_change'] = round(pct_change, 2)

    if cfg.enable_premarket_gain:
        if pct_change < cfg.min_premarket_gain:
            data['fail_reason'] = f"Gain {pct_change:.1f}% < {cfg.min_premarket_gain}% min"
            return False, data

    # Pillar 3: Relative volume
    data['rel_vol'] = round(relative_volume, 2)
    if cfg.enable_relative_volume:
        if relative_volume < cfg.min_relative_volume:
            data['fail_reason'] = f"Rel vol {relative_volume:.1f}x < {cfg.min_relative_volume}x min"
            return False, data

    # Time/volume checks (entry liquidity)
    recent_bars = (bar_history + [bar])[-5:]
    last_5min_vol = sum(float(b['volume']) for b in recent_bars) if recent_bars else 0
    last_1min_vol = float(bar.get('volume', 0) or 0)
    data['vol_5min'] = int(last_5min_vol)
    data['vol_1min'] = int(last_1min_vol)

    if cfg.enable_last_5min_volume:
        if last_5min_vol < cfg.min_last_5min_volume:
            data['fail_reason'] = f"5-min vol {last_5min_vol:,.0f} < {cfg.min_last_5min_volume:,.0f}"
            return False, data

    if cfg.enable_last_1min_volume:
        if last_1min_vol < cfg.min_last_1min_volume:
            data['fail_reason'] = f"1-min vol {last_1min_vol:,.0f} < {cfg.min_last_1min_volume:,.0f}"
            return False, data

    # Spread filter (if available)
    spread = bar.get('spread')
    if spread is None:
        bid = bar.get('bid')
        ask = bar.get('ask')
        if bid is not None and ask is not None:
            try:
                spread = float(ask) - float(bid)
            except (TypeError, ValueError):
                spread = None
    data['spread'] = round(float(spread), 4) if spread is not None else None

    if cfg.enable_spread_filter:
        if spread is None:
            data['fail_reason'] = "No spread data"
            return False, data
        if spread > cfg.max_spread:
            data['fail_reason'] = f"Spread ${spread:.2f} > ${cfg.max_spread:.2f} max"
            return False, data

    # Volume direction: must be buying, not selling
    buying_vol, selling_vol = estimate_buy_sell_volume(
        bar['open'], bar['high'], bar['low'], bar['close'], bar['volume']
    )
    data['buying_vol'] = round(buying_vol)
    data['selling_vol'] = round(selling_vol)

    if cfg.enable_buying_volume:
        if selling_vol > buying_vol or buying_vol < cfg.min_buying_volume:
            data['fail_reason'] = f"Selling pressure: buying {buying_vol:,.0f} vs selling {selling_vol:,.0f}"
            return False, data

    # Pillar 4: Float (skip if no data — graceful degradation)
    float_shares = fundamentals.get('float_shares')
    if cfg.enable_float_filter and float_shares:
        data['float_shares'] = float_shares
        if float_shares > cfg.max_float:
            data['fail_reason'] = f"Float {float_shares/1e6:.1f}M > {cfg.max_float/1e6:.0f}M max"
            return False, data

    # Market cap
    market_cap = fundamentals.get('market_cap')
    if cfg.enable_market_cap_filter and market_cap:
        data['market_cap'] = market_cap
        if market_cap > cfg.max_market_cap:
            data['fail_reason'] = f"Mkt cap ${market_cap/1e6:.0f}M > ${cfg.max_market_cap/1e6:.0f}M max"
            return False, data

    # Pillar 5: News catalyst — not yet implemented; pass through for now
    # TODO: integrate news_fetcher here
    data['news_check'] = 'SKIPPED'

    return True, data
