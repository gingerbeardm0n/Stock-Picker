"""
Chart Pattern Detectors
========================
Each function receives an ordered list of bars (oldest → newest, including the
current bar as the last element) and an indicators dict, and returns a
PatternSignal if the pattern is detected, or None if not.

Bar dict format: {time, symbol, open, high, low, close, volume, ...}

Pattern priority (data-derived from 5,010 trades across 1,800 Ross Cameron sessions):
    0. Gap and Go         ⭐⭐⭐⭐⭐  1,177 trades, 69% win rate  ← #1 by frequency
    0b.VWAP Reclaim       ⭐⭐⭐⭐⭐   153 trades, 75% win rate  ← highest win rate
    1. Bull Flag          ⭐⭐⭐⭐⭐
    2. Micro Pullback     ⭐⭐⭐⭐    387 trades, 70% win rate
    3. ABCD               ⭐⭐⭐⭐
    4. Dip Buy (3 Tricks) ⭐⭐⭐
    5. Flat Top Breakout  ⭐⭐⭐

"Light volume" definition used throughout:
    A bar is "light volume" if its volume < 50% of the mean of the 5 bars
    immediately before it.
"""

from __future__ import annotations
from trading.models import PatternSignal, EntryConfig
from trading.indicators import average_volume, is_light_volume

# Used when no config is passed (all callers work unchanged)
_DEFAULTS = EntryConfig()


def _is_green(bar: dict) -> bool:
    return float(bar['close']) > float(bar['open'])


def _is_red(bar: dict) -> bool:
    return float(bar['close']) < float(bar['open'])


def _close(bar: dict) -> float:
    return float(bar['close'])


def _open(bar: dict) -> float:
    return float(bar['open'])


def _high(bar: dict) -> float:
    return float(bar['high'])


def _low(bar: dict) -> float:
    return float(bar['low'])


def _vol(bar: dict) -> float:
    return float(bar['volume'])


# ── 0. Gap and Go ─────────────────────────────────────────────────────────────

def detect_gap_and_go(bars: list[dict], indicators: dict,
                      config: EntryConfig | None = None) -> PatternSignal | None:
    """
    Gap and Go — Break of premarket high at the open.

    Ross Cameron's highest-frequency pattern: 1,177 trades (23% of all trades),
    69% win rate. Source: concept_gap_and_go.md built from 1,800 session analysis.

    Prerequisites (checked before calling, in entry_engine Gate 2):
        - Stock has gapped up 20%+ premarket on a catalyst (min_premarket_gain)
        - High relative volume (min_relative_volume)

    Pattern structure:
        Premarket : Stock gaps up, establishes a premarket high
        Open      : Price approaches/tests premarket high level
        Entry     : Current 1m bar CLOSES above premarket high on volume spike

    Note on MACD: NOT required for this pattern (96% of gap-and-go trades have
    unknown/missing MACD state). Do NOT apply the blanket MACD gate to this pattern.

    Args:
        bars        : All bars so far (oldest → newest, includes premarket bars first).
        indicators  : Must contain 'premarket_high' (float | None), computed by
                      entry_engine._get_premarket_high() from bars before 9:30am ET.
                      Also uses 'market_open_bar_count' (int | None) to limit
                      how long after open gap-and-go is valid.
        config      : EntryConfig with gap_and_go_* thresholds.

    Entry : Current bar close
    Stop  : Just below the premarket high that was broken (the level becomes support)
    Target: 2:1 and 3:1 R/R from entry
    """
    cfg = config if config is not None else _DEFAULTS

    if len(bars) < 2:
        return None

    # Need premarket_high from indicators (computed in entry_engine)
    premarket_high = indicators.get('premarket_high')
    if premarket_high is None or premarket_high <= 0:
        return None

    # Only valid within the first N bars after 9:30am open
    # Prevents late-session false triggers as price naturally exceeds premarket levels
    market_open_bar_count = indicators.get('market_open_bar_count')
    if (market_open_bar_count is not None
            and market_open_bar_count > cfg.gap_and_go_max_bars_since_open):
        return None

    current = bars[-1]

    # Must be a green bar (momentum continuation)
    if not _is_green(current):
        return None

    # Current bar must CLOSE above the premarket high (the break)
    if _close(current) <= premarket_high:
        return None

    # Volume confirmation: breakout bar must exceed recent average volume
    # Concept page spec: "volume on that candle > 1.5x average candle volume"
    recent_bars = bars[-6:-1]  # up to 5 bars before current
    if len(recent_bars) >= 3:
        avg_vol = sum(_vol(b) for b in recent_bars) / len(recent_bars)
        if avg_vol > 0 and _vol(current) < avg_vol * cfg.gap_and_go_breakout_vol_min:
            return None

    # ── Build signal ──────────────────────────────────────────────────────
    entry = _close(current)
    # Stop just below premarket high — the broken level becomes support
    stop = premarket_high - cfg.stop_buffer
    stop_dist = entry - stop
    if stop_dist <= 0:
        return None

    target1 = entry + stop_dist * 2
    target2 = entry + stop_dist * 3

    reasoning = (
        f"Gap and Go: premarket high ${premarket_high:.2f} broken, "
        f"entry ${entry:.2f}, stop ${stop:.2f} (below PM high), "
        f"vol {_vol(current):,.0f}"
    )
    return PatternSignal(
        pattern_type='GAP_AND_GO',
        confidence=5,
        entry_price=entry,
        stop_price=stop,
        target1=target1,
        target2=target2,
        reasoning=reasoning,
    )


# ── 0b. VWAP Reclaim ──────────────────────────────────────────────────────────

def detect_vwap_reclaim(bars: list[dict], indicators: dict,
                        config: EntryConfig | None = None) -> PatternSignal | None:
    """
    VWAP Reclaim — highest win rate of all patterns.

    153 trades, 75% win rate. Source: concept_pattern_playbook.md section 6.

    Setup: stock gapped up at open (gap-and-go or news pop), dipped back below
    VWAP (sellers took control), then buyers step back in and price closes a
    1-minute candle above VWAP on above-average volume.

    Key distinction from dip-buy:
        - dip-buy: price dips but stays above VWAP, bounces off EMA-9 / support
        - vwap-reclaim: price actually breaks BELOW VWAP, then reclaims it

    Note on MACD: Not required (2.6% of trades recorded MACD positive).
    Note on time: Only valid before 11am. After 11am, VWAP reclaims lack
    the morning momentum needed to sustain the move (concept page rule).

    Args:
        bars        : All bars so far (oldest → newest). Market-hours bars define VWAP.
        indicators  : Must contain 'vwap' (float | None), computed by
                      entry_engine._calculate_vwap() from 9:30am bars.
        config      : EntryConfig with vwap_reclaim_* thresholds.

    Entry : Current bar close (the reclaim candle close)
    Stop  : Just below VWAP (close back below VWAP = signal invalidated)
    Target: 2:1 and 3:1 R/R from entry
    """
    cfg = config if config is not None else _DEFAULTS

    vwap = indicators.get('vwap')
    if vwap is None or vwap <= 0:
        return None

    if len(bars) < cfg.vwap_reclaim_lookback + 1:
        return None

    current = bars[-1]

    # Current bar must close ABOVE VWAP (the reclaim)
    if _close(current) <= vwap:
        return None

    # Must be green bar (buyer momentum on reclaim)
    if not _is_green(current):
        return None

    # Lookback window: bars BEFORE current bar
    lookback_bars = bars[-(cfg.vwap_reclaim_lookback + 1):-1]

    # Must have had at least N bars BELOW VWAP recently (confirming the dip happened)
    # Uses close price as the relevant level (not high/low)
    bars_below_vwap = sum(1 for b in lookback_bars if _close(b) < vwap)
    if bars_below_vwap < cfg.vwap_reclaim_min_below:
        return None

    # Volume confirmation: reclaim bar should exceed recent average
    if len(lookback_bars) >= 3:
        avg_vol = sum(_vol(b) for b in lookback_bars) / len(lookback_bars)
        if avg_vol > 0 and _vol(current) < avg_vol * cfg.vwap_reclaim_breakout_vol_min:
            return None

    # ── Build signal ──────────────────────────────────────────────────────
    entry = _close(current)
    # Stop just below VWAP — close back below = pattern invalidated
    stop = vwap - cfg.stop_buffer
    stop_dist = entry - stop
    if stop_dist <= 0:
        return None

    target1 = entry + stop_dist * 2
    target2 = entry + stop_dist * 3

    reasoning = (
        f"VWAP Reclaim: VWAP ${vwap:.2f} reclaimed after {bars_below_vwap} bar(s) below, "
        f"entry ${entry:.2f}, stop ${stop:.2f} (below VWAP), "
        f"vol {_vol(current):,.0f}"
    )
    return PatternSignal(
        pattern_type='VWAP_RECLAIM',
        confidence=5,
        entry_price=entry,
        stop_price=stop,
        target1=target1,
        target2=target2,
        reasoning=reasoning,
    )


# ── 1. Bull Flag ──────────────────────────────────────────────────────────────

def detect_bull_flag(bars: list[dict], indicators: dict,
                     config: EntryConfig | None = None) -> PatternSignal | None:
    """
    Bull Flag — Highest reliability pattern (5 stars).

    Structure (reading bars right to left from current):
        Current bar  : Green breakout, closes above flag resistance, high volume
        Flag phase   : 2-3 red bars on light volume, none breaks flagpole low
        Flagpole     : 1-3 strong green bars with high volume before the flag

    Entry : Current bar close
    Stop  : Flag low - stop_buffer
    Target: Flagpole height projected from entry
    """
    cfg = config if config is not None else _DEFAULTS
    if len(bars) < 6:
        return None

    current = bars[-1]

    # Current bar must be green (breakout candle)
    if not _is_green(current):
        return None

    # ── Find flag phase (2-3 red bars before current) ─────────────────────
    # Try 3-bar flag first, then 2-bar flag
    for flag_len in (3, 2):
        flag_start = len(bars) - 1 - flag_len
        if flag_start < 0:
            continue

        flag_bars = bars[flag_start: len(bars) - 1]

        # All flag bars must be red
        if not all(_is_red(b) for b in flag_bars):
            continue

        flag_high = max(_high(b) for b in flag_bars)
        flag_low = min(_low(b) for b in flag_bars)

        # Current bar must close ABOVE flag resistance (flag_high)
        if _close(current) <= flag_high:
            continue

        # ── Find flagpole (1-3 green bars before flag) ────────────────────
        pole_end = flag_start
        for pole_len in (3, 2, 1):
            pole_start = pole_end - pole_len
            if pole_start < 0:
                continue

            pole_bars = bars[pole_start:pole_end]

            # All pole bars must be green
            if not all(_is_green(b) for b in pole_bars):
                continue

            # Pole bars should have above-average volume
            # Use prior bars as reference (bars before the pole)
            ref_bars = bars[:pole_start] if pole_start > 0 else pole_bars
            avg_ref_vol = average_volume(ref_bars, lookback=5) if ref_bars else _vol(pole_bars[0])
            pole_avg_vol = sum(_vol(b) for b in pole_bars) / len(pole_bars)

            # Pole must have meaningful volume
            if avg_ref_vol > 0 and pole_avg_vol < avg_ref_vol * cfg.bull_flag_pole_vol_min:
                continue

            pole_high = max(_high(b) for b in pole_bars)
            pole_low = min(_low(b) for b in pole_bars)

            # Flag low must be ABOVE pole low (support holding)
            if flag_low < pole_low:
                continue

            # Flag bars must be on light volume relative to the pole
            flag_light = all(
                is_light_volume(b, pole_bars, threshold=cfg.bull_flag_light_vol)
                for b in flag_bars
            )
            if not flag_light:
                continue

            # Volume on breakout must match or exceed pole average
            if _vol(current) < pole_avg_vol * cfg.bull_flag_breakout_vol_min:
                continue

            # ── Build signal ───────────────────────────────────────────────
            entry = _close(current)
            stop = flag_low - cfg.stop_buffer
            stop_dist = entry - stop
            if stop_dist <= 0:
                continue

            flagpole_height = pole_high - pole_low
            target1 = entry + stop_dist * 2
            target2 = entry + stop_dist * 3

            reasoning = (
                f"Bull Flag: pole ${pole_low:.2f}→${pole_high:.2f} (+${flagpole_height:.2f}), "
                f"flag ${flag_low:.2f}-${flag_high:.2f}, breakout ${entry:.2f}"
            )
            return PatternSignal(
                pattern_type='BULL_FLAG',
                confidence=5,
                entry_price=entry,
                stop_price=stop,
                target1=target1,
                target2=target2,
                reasoning=reasoning,
            )

    return None


# ── 2. Micro Pullback ─────────────────────────────────────────────────────────

def detect_micro_pullback(bars: list[dict], indicators: dict,
                          config: EntryConfig | None = None) -> PatternSignal | None:
    """
    Micro Pullback / First Candle to New High — 4 stars.

    Structure:
        Trend phase : 3+ green bars, higher closes (strong uptrend)
        Pause phase : 1-2 bars with lower close on light volume (not a reversal)
        Current bar : Green, closes ABOVE the high of the pause phase

    Entry : Current bar close
    Stop  : Lowest low of pause phase - stop_buffer
    """
    cfg = config if config is not None else _DEFAULTS
    if len(bars) < 5:
        return None

    current = bars[-1]
    if not _is_green(current):
        return None

    # Try 2-bar pause first, then 1-bar pause
    for pause_len in (2, 1):
        pause_start = len(bars) - 1 - pause_len
        trend_end = pause_start
        trend_start = max(0, trend_end - 4)

        if trend_end <= trend_start:
            continue

        pause_bars = bars[pause_start:pause_start + pause_len]
        trend_bars = bars[trend_start:trend_end]

        if len(trend_bars) < 2:
            continue

        # Trend phase: majority green and higher closes
        green_in_trend = sum(1 for b in trend_bars if _is_green(b))
        if green_in_trend < len(trend_bars) * cfg.micro_pb_green_pct:
            continue

        # Trend must be going up (last close of trend > first close of trend)
        if _close(trend_bars[-1]) <= _close(trend_bars[0]):
            continue

        # Pause phase: closes lower than trend end, light volume
        if any(_close(b) >= _close(trend_bars[-1]) for b in pause_bars):
            continue  # Not a pullback if close is still near trend high

        # Pause must be on light volume
        if not all(is_light_volume(b, trend_bars, threshold=cfg.micro_pb_light_vol)
                   for b in pause_bars):
            continue

        # Pause must NOT break the most recent swing low of the trend
        trend_swing_low = min(_low(b) for b in trend_bars)
        pause_low = min(_low(b) for b in pause_bars)
        if pause_low < trend_swing_low * cfg.micro_pb_swing_tol:
            continue

        # Current bar must close ABOVE the pause phase high
        pause_high = max(_high(b) for b in pause_bars)
        if _close(current) <= pause_high:
            continue

        # ── Build signal ───────────────────────────────────────────────────
        entry = _close(current)
        stop = pause_low - cfg.stop_buffer
        stop_dist = entry - stop
        if stop_dist <= 0:
            continue

        target1 = entry + stop_dist * 2
        target2 = entry + stop_dist * 3

        reasoning = (
            f"Micro Pullback: trend ${_close(trend_bars[0]):.2f}→${_close(trend_bars[-1]):.2f}, "
            f"pause low ${pause_low:.2f}, breakout ${entry:.2f}"
        )
        return PatternSignal(
            pattern_type='MICRO_PULLBACK',
            confidence=4,
            entry_price=entry,
            stop_price=stop,
            target1=target1,
            target2=target2,
            reasoning=reasoning,
        )

    return None


# ── 3. ABCD Pattern ───────────────────────────────────────────────────────────

def detect_abcd_pattern(bars: list[dict],
                        config: EntryConfig | None = None) -> PatternSignal | None:
    """
    ABCD Pattern — 4 stars.

    Structure:
        A : Swing high (peak of initial rally)
        B : Swing low after A (first pullback, >= abcd_min_pullback_pct of A)
        C : Rally high between B and now (C must be < A)
        D : Current area — secondary dip that must NOT break B low
        Entry: Current bar closes above C resistance

    Entry : Current bar close
    Stop  : B low - stop_buffer
    Target: A high (or 2:1 R/R if A is very far)
    """
    cfg = config if config is not None else _DEFAULTS
    if len(bars) < 15:
        return None

    current = bars[-1]
    if not _is_green(current):
        return None

    # We scan a window of the last 20 bars (excluding current)
    window = bars[-20:-1]
    if len(window) < 10:
        return None

    n = len(window)

    # Find A: highest high in the first half of the window
    a_half = window[:n // 2]
    a_idx = max(range(len(a_half)), key=lambda i: _high(a_half[i]))
    a_high = _high(a_half[a_idx])
    a_price = a_high

    # Find B: lowest low AFTER A
    after_a = window[a_idx + 1: n // 2 + 2]
    if len(after_a) < 2:
        return None
    b_idx_rel = min(range(len(after_a)), key=lambda i: _low(after_a[i]))
    b_bar = after_a[b_idx_rel]
    b_low = _low(b_bar)

    # B must represent a meaningful pullback
    if (a_price - b_low) / a_price < cfg.abcd_min_pullback_pct:
        return None

    # B must be below A
    if b_low >= a_high:
        return None

    # Find C: highest high AFTER B (in second half of window)
    b_abs_idx = a_idx + 1 + b_idx_rel
    after_b = window[b_abs_idx + 1:]
    if len(after_b) < 2:
        return None
    c_idx_rel = max(range(len(after_b)), key=lambda i: _high(after_b[i]))
    c_bar = after_b[c_idx_rel]
    c_high = _high(c_bar)

    # C must be BELOW A (if C >= A it's a new breakout, not ABCD)
    if c_high >= a_high:
        return None

    # C must be ABOVE B (higher structure)
    if c_high <= b_low:
        return None

    # D area: last 3 bars of window (after C)
    c_abs_idx = b_abs_idx + 1 + c_idx_rel
    d_bars = window[c_abs_idx + 1:] if c_abs_idx + 1 < len(window) else []
    if not d_bars:
        return None

    d_low = min(_low(b) for b in d_bars)

    # D must NOT break B low (this is the critical rule)
    if d_low < b_low:
        return None

    # D should be on light volume (secondary dip should be weak selling)
    c_bars_for_ref = after_b[:c_idx_rel + 1] if after_b else []
    if c_bars_for_ref:
        d_light = all(
            is_light_volume(b, c_bars_for_ref, threshold=cfg.abcd_d_light_vol)
            for b in d_bars
        )
        if not d_light:
            return None

    # Current bar must close ABOVE C resistance
    if _close(current) <= c_high:
        return None

    # ── Build signal ──────────────────────────────────────────────────────
    entry = _close(current)
    stop = b_low - cfg.stop_buffer
    stop_dist = entry - stop
    if stop_dist <= 0:
        return None

    # Target = A high if within reason (< 3:1 R/R distance), else 2:1
    if (a_price - entry) >= stop_dist * 2:
        target1 = entry + stop_dist * 2
        target2 = a_price
    else:
        target1 = entry + stop_dist * 2
        target2 = entry + stop_dist * 3

    reasoning = (
        f"ABCD: A=${a_price:.2f}, B=${b_low:.2f}, C=${c_high:.2f}, "
        f"D=${d_low:.2f}, breakout ${entry:.2f}, stop ${stop:.2f}"
    )
    return PatternSignal(
        pattern_type='ABCD',
        confidence=4,
        entry_price=entry,
        stop_price=stop,
        target1=target1,
        target2=target2,
        reasoning=reasoning,
    )


# ── 4. Dip Buy (3 Tricks) ─────────────────────────────────────────────────────

def detect_dip_buy(bars: list[dict], indicators: dict,
                   config: EntryConfig | None = None) -> PatternSignal | None:
    """
    Dip Buy using Ross Cameron's 3 Tricks — 3 stars.

    Requires valid EMA-9 and MACD in indicators dict (needs 26+ bars history).

    The 3 Tricks:
        1. Price above 9 EMA
        2. MACD histogram positive (green bars)
        3. Light volume on the pullback candles

    Current bar: green (first green after the pullback = entry)

    Entry : Current bar close
    Stop  : Lowest low of last 3 bars - stop_buffer
    Note  : This is the "requires skill" pattern — use only when all 3 are confirmed.
    """
    cfg = config if config is not None else _DEFAULTS
    if len(bars) < 8:
        return None

    ema9 = indicators.get('ema9')
    # GAP-04 fix: use MACD line (EMA12 − EMA26), not the histogram.
    # Histogram = MACD line − signal line, which can be negative even on a rising trend.
    # MACD line > 0 confirms upward momentum; histogram > 0 only means faster than signal.
    macd_line = indicators.get('macd_line')

    # Both indicators must be valid
    if ema9 is None or macd_line is None:
        return None

    current = bars[-1]

    # Current bar must be green
    if not _is_green(current):
        return None

    current_price = _close(current)

    # Trick 1: Price above 9 EMA
    if current_price <= ema9:
        return None

    # Trick 2: MACD line positive (bullish momentum — EMA12 > EMA26)
    if macd_line <= 0:
        return None

    # Trick 3: Light volume on last 2-3 pullback bars
    pullback_bars = bars[-4:-1]  # 3 bars before current
    if len(pullback_bars) < 2:
        return None

    ref_bars = bars[-10:-4]  # reference: 6 bars before pullback
    if len(ref_bars) < 3:
        return None

    # Pullback bars should show lower closes (actual dip)
    if not any(_close(b) < _close(bars[-4]) for b in pullback_bars[1:]):
        return None  # No actual dip happened

    # Pullback must be on light volume
    if not all(is_light_volume(b, ref_bars, threshold=cfg.dip_buy_light_vol)
               for b in pullback_bars):
        return None

    # ── Build signal ──────────────────────────────────────────────────────
    entry = current_price
    dip_low = min(_low(b) for b in pullback_bars + [current])
    stop = dip_low - cfg.stop_buffer
    stop_dist = entry - stop
    if stop_dist <= 0:
        return None

    target1 = entry + stop_dist * 2
    target2 = entry + stop_dist * 3

    reasoning = (
        f"Dip Buy (3 Tricks): price ${current_price:.2f} > EMA9 ${ema9:.2f}, "
        f"MACD line {macd_line:.4f}, light vol pullback to ${dip_low:.2f}"
    )
    return PatternSignal(
        pattern_type='DIP_BUY',
        confidence=3,
        entry_price=entry,
        stop_price=stop,
        target1=target1,
        target2=target2,
        reasoning=reasoning,
    )


# ── 5. Flat Top Breakout ──────────────────────────────────────────────────────

def detect_flat_top_breakout(bars: list[dict],
                             config: EntryConfig | None = None) -> PatternSignal | None:
    """
    Flat Top Breakout — 3 stars.

    Structure:
        Consolidation: 2-3 bars touch the same resistance (highs within $flat_top_resistance_tol)
                       Volume equal or decreasing on each touch
        Current bar  : Closes ABOVE the flat top with volume spike

    Entry : Current bar close
    Stop  : Lowest low of consolidation zone - stop_buffer
    """
    cfg = config if config is not None else _DEFAULTS
    if len(bars) < 8:
        return None

    current = bars[-1]
    if not _is_green(current):
        return None

    # Look at last 10 bars (excluding current) for consolidation
    window = bars[-11:-1]
    if len(window) < 5:
        return None

    # Find the flat-top resistance level
    best_resistance = None
    best_touches: list[dict] = []

    for i in range(len(window) - 1):
        candidate_level = _high(window[i])
        touches = [
            b for b in window[i:]
            if abs(_high(b) - candidate_level) <= cfg.flat_top_resistance_tol
        ]
        if len(touches) >= 2 and len(touches) > len(best_touches):
            best_touches = touches
            best_resistance = candidate_level

    if not best_touches or best_resistance is None or len(best_touches) < 2:
        return None

    # Volume must be equal or decreasing across successive touches
    touch_volumes = [_vol(b) for b in best_touches]
    # Allow one increase but not a steady climb
    increases = sum(
        1 for a, b in zip(touch_volumes, touch_volumes[1:])
        if b > a * cfg.flat_top_vol_increase_tol
    )
    if increases >= len(touch_volumes) - 1:
        return None  # Volume is uniformly increasing = not a flat top (breakout already)

    # Current bar must close ABOVE the flat top resistance
    if _close(current) <= best_resistance:
        return None

    # Volume on breakout must exceed the max volume of consolidation touches
    max_consol_vol = max(touch_volumes)
    if _vol(current) <= max_consol_vol:
        return None

    # ── Build signal ──────────────────────────────────────────────────────
    entry = _close(current)
    consol_low = min(_low(b) for b in window)
    stop = consol_low - cfg.stop_buffer
    stop_dist = entry - stop
    if stop_dist <= 0:
        return None

    target1 = entry + stop_dist * 2
    target2 = entry + stop_dist * 3

    reasoning = (
        f"Flat Top Breakout: resistance ${best_resistance:.2f} "
        f"({len(best_touches)} touches), breakout ${entry:.2f}, "
        f"vol {_vol(current):,.0f} > consol max {max_consol_vol:,.0f}"
    )
    return PatternSignal(
        pattern_type='FLAT_TOP',
        confidence=3,
        entry_price=entry,
        stop_price=stop,
        target1=target1,
        target2=target2,
        reasoning=reasoning,
    )


# ── 6. Red-to-Green ──────────────────────────────────────────────────────────

def detect_red_to_green(
    bars: list[dict],
    indicators: dict,
    config: EntryConfig | None = None,
) -> PatternSignal | None:
    """
    Red-to-Green (RTG): stock was below prior close, then reclaims it on this bar.

    Mechanics: prior close acts as resistance-turned-support; the cross triggers
    short covering + fresh long entries → momentum surge.

    Source: concept_front_side_back_side.md — 66.2% win rate / 71 trades.

    Requires indicators['prior_close'] to be populated by evaluate_entry().

    Entry : Current bar close (the reclaim bar)
    Stop  : Low of the prior 2 bars, or prior_close − stop_buffer (whichever is lower)
    """
    cfg = config if config is not None else _DEFAULTS
    prior_close = indicators.get('prior_close')
    if prior_close is None or prior_close <= 0:
        return None

    if len(bars) < 5:
        return None

    current = bars[-1]
    if not _is_green(current):
        return None

    current_price = _close(current)

    # Must be above prior close now
    if current_price <= prior_close:
        return None

    # At least one of the prior 3 bars must have closed below prior close
    lookback = bars[-4:-1]
    if not any(_close(b) < prior_close for b in lookback):
        return None

    # Stop: lower of (recent low − buffer) or (prior_close − buffer)
    recent_low = min(_low(b) for b in lookback + [current])
    stop = min(recent_low - cfg.stop_buffer * 0.5, prior_close - cfg.stop_buffer)

    stop_dist = current_price - stop
    if stop_dist <= 0.01:
        return None

    target1 = current_price + stop_dist * 2
    target2 = current_price + stop_dist * 3

    reasoning = (
        f"Red-to-Green: crossed above prior close ${prior_close:.2f} "
        f"from ${_close(lookback[-1]):.2f}, stop ${stop:.2f}"
    )
    return PatternSignal(
        pattern_type='RED_TO_GREEN',
        confidence=3,
        entry_price=current_price,
        stop_price=stop,
        target1=target1,
        target2=target2,
        reasoning=reasoning,
    )


# ── 7. Whole Dollar Break ─────────────────────────────────────────────────────

def detect_whole_dollar_break(
    bars: list[dict],
    indicators: dict,
    config: EntryConfig | None = None,
) -> PatternSignal | None:
    """
    Whole Dollar Break: price breaks and closes above a whole dollar level ($5, $6, ...).

    Mechanics: whole-dollar levels are psychological magnets for resting orders;
    a confirmed close above triggers short covers and momentum buyers.

    Source: concept_entry_trigger_taxonomy.md — 64.3% win rate / 112 trades.

    Entry : Current bar close (the break bar)
    Stop  : The whole dollar level − stop_buffer (now acts as support)
    """
    cfg = config if config is not None else _DEFAULTS

    if len(bars) < 4:
        return None

    current = bars[-1]
    prev    = bars[-2]

    if not _is_green(current):
        return None

    current_price = _close(current)
    prev_price    = _close(prev)

    # Whole dollar level just below current price
    level = float(int(current_price))   # floor to nearest integer
    if level <= 0:
        return None

    # Current bar must close above the level
    if current_price <= level:
        return None

    # Previous bar must have closed at or below the level (fresh break this bar)
    if prev_price > level:
        return None

    # Break must be close to the level — within 3% (not already extended)
    if (current_price - level) / level > 0.03:
        return None

    stop      = level - cfg.stop_buffer
    stop_dist = current_price - stop
    if stop_dist <= 0.01:
        return None

    target1 = current_price + stop_dist * 2
    target2 = float(int(current_price) + 1)   # next whole dollar as natural resistance

    reasoning = (
        f"Whole Dollar Break: close ${current_price:.2f} above ${level:.0f} "
        f"(prev close ${prev_price:.2f}), stop ${stop:.2f}"
    )
    return PatternSignal(
        pattern_type='WHOLE_DOLLAR',
        confidence=3,
        entry_price=current_price,
        stop_price=stop,
        target1=target1,
        target2=target2,
        reasoning=reasoning,
    )


# ── 8. Opening Range Breakout (ORB) ──────────────────────────────────────────

def detect_opening_range_breakout(
    bars: list[dict],
    indicators: dict,
    config: EntryConfig | None = None,
) -> PatternSignal | None:
    """
    Opening Range Breakout (ORB): price breaks above the high of the first 5 bars
    after market open (9:30–9:34 ET).

    Mechanics: the first 5 minutes of trading establish a congestion zone;
    a close above that zone triggers directional momentum from both shorts
    covering and fresh buyers.

    Source: concept_time_of_day.md — 70.8% win rate / 48 trades.

    Entry : Current bar close (the breakout bar)
    Stop  : Opening range low − stop_buffer
    """
    import pytz as _pytz
    _ET = _pytz.timezone('America/New_York')

    cfg = config if config is not None else _DEFAULTS

    if len(bars) < 6:
        return None

    # Identify market-hours bars (9:30 AM ET onwards)
    market_bars = []
    for b in bars:
        t = b.get('time')
        if t is None or not hasattr(t, 'astimezone'):
            continue
        t_et = t.astimezone(_ET)
        if t_et.hour > 9 or (t_et.hour == 9 and t_et.minute >= 30):
            market_bars.append(b)

    if len(market_bars) < 6:
        return None   # Need opening range bars + at least 1 breakout bar

    # Opening range = first 5 market-open bars
    or_bars = market_bars[:5]
    or_high = max(_high(b) for b in or_bars)
    or_low  = min(_low(b) for b in or_bars)

    current    = bars[-1]
    prev       = bars[-2]

    if not _is_green(current):
        return None

    current_price = _close(current)
    prev_price    = _close(prev)

    # Current bar closes above OR high
    if current_price <= or_high:
        return None

    # Previous bar did NOT close above OR high (fresh break this bar)
    if prev_price > or_high:
        return None

    # Must not be extended — within 5% above OR high
    if (current_price - or_high) / or_high > 0.05:
        return None

    stop      = or_low - cfg.stop_buffer
    stop_dist = current_price - stop

    if stop_dist <= 0.01:
        return None
    if stop_dist > current_price * 0.15:   # Stop too wide (>15% of price) — skip
        return None

    target1 = current_price + stop_dist * 2
    target2 = current_price + stop_dist * 3

    reasoning = (
        f"ORB: close ${current_price:.2f} above opening range high ${or_high:.2f} "
        f"(OR: ${or_low:.2f}–${or_high:.2f}), stop ${stop:.2f}"
    )
    return PatternSignal(
        pattern_type='ORB',
        confidence=3,
        entry_price=current_price,
        stop_price=stop,
        target1=target1,
        target2=target2,
        reasoning=reasoning,
    )


# ── Diagnostic: explain why each pattern rejected ─────────────────────────────

def explain_pattern_rejection(
    bars: list[dict],
    indicators: dict,
    config: EntryConfig | None = None,
) -> dict[str, str]:
    """
    Diagnostic-only function. Runs the same logic as each detect_* function
    but instead of returning None silently, returns the FIRST failing check
    name for every pattern.

    Returns a dict:
        {
            'BULL_FLAG':      'flag_bars_not_all_red',
            'MICRO_PULLBACK': 'pause_heavy_volume',
            'ABCD':           'c_above_a',
            'DIP_BUY':        'no_ema_indicator',
            'FLAT_TOP':       'breakout_vol_too_low',
        }
    'PASS' means the pattern would have fired (detect_* returned a signal).
    """
    cfg = config if config is not None else _DEFAULTS

    results: dict[str, str] = {}

    # ── BULL FLAG ──────────────────────────────────────────────────────────────
    def _explain_bull_flag() -> str:
        if len(bars) < 6:
            return f'too_few_bars({len(bars)}<6)'
        current = bars[-1]
        if not _is_green(current):
            return f'current_not_green(close={_close(current):.2f} open={_open(current):.2f})'

        for flag_len in (3, 2):
            flag_start = len(bars) - 1 - flag_len
            if flag_start < 0:
                continue
            flag_bars = bars[flag_start: len(bars) - 1]
            if not all(_is_red(b) for b in flag_bars):
                non_red = [i for i, b in enumerate(flag_bars) if not _is_red(b)]
                return f'flag_bars_not_all_red(flag_len={flag_len}, non_red_indices={non_red})'
            flag_high = max(_high(b) for b in flag_bars)
            flag_low = min(_low(b) for b in flag_bars)
            if _close(current) <= flag_high:
                return f'current_not_above_flag_high(close={_close(current):.2f} flag_high={flag_high:.2f})'

            pole_end = flag_start
            for pole_len in (3, 2, 1):
                pole_start = pole_end - pole_len
                if pole_start < 0:
                    continue
                pole_bars = bars[pole_start:pole_end]
                if not all(_is_green(b) for b in pole_bars):
                    non_green = [i for i, b in enumerate(pole_bars) if not _is_green(b)]
                    return f'pole_bars_not_all_green(pole_len={pole_len}, non_green_indices={non_green})'
                ref_bars = bars[:pole_start] if pole_start > 0 else pole_bars
                avg_ref_vol = average_volume(ref_bars, lookback=5) if ref_bars else _vol(pole_bars[0])
                pole_avg_vol = sum(_vol(b) for b in pole_bars) / len(pole_bars)
                if avg_ref_vol > 0 and pole_avg_vol < avg_ref_vol * cfg.bull_flag_pole_vol_min:
                    return (f'pole_low_volume(pole_avg={pole_avg_vol:.0f} '
                            f'ref_avg={avg_ref_vol:.0f} '
                            f'need={avg_ref_vol * cfg.bull_flag_pole_vol_min:.0f})')
                pole_high = max(_high(b) for b in pole_bars)
                pole_low = min(_low(b) for b in pole_bars)
                if flag_low < pole_low:
                    return f'flag_below_pole_low(flag_low={flag_low:.2f} pole_low={pole_low:.2f})'
                flag_light = all(
                    is_light_volume(b, pole_bars, threshold=cfg.bull_flag_light_vol)
                    for b in flag_bars
                )
                if not flag_light:
                    vols = [(_vol(b), average_volume(pole_bars, lookback=len(pole_bars))) for b in flag_bars]
                    return f'flag_heavy_volume(bar_vols={[v[0] for v in vols]}, pole_avg={vols[0][1]:.0f}, threshold={cfg.bull_flag_light_vol})'
                if _vol(current) < pole_avg_vol * cfg.bull_flag_breakout_vol_min:
                    return (f'breakout_low_volume(current_vol={_vol(current):.0f} '
                            f'need={pole_avg_vol * cfg.bull_flag_breakout_vol_min:.0f})')
                # If we get here, detect_bull_flag would have returned a signal
                return 'PASS'
            return f'no_valid_pole_found(flag_len={flag_len})'
        return 'no_valid_flag_found'

    results['BULL_FLAG'] = _explain_bull_flag()

    # ── MICRO PULLBACK ─────────────────────────────────────────────────────────
    def _explain_micro_pullback() -> str:
        if len(bars) < 5:
            return f'too_few_bars({len(bars)}<5)'
        current = bars[-1]
        if not _is_green(current):
            return f'current_not_green(close={_close(current):.2f} open={_open(current):.2f})'

        for pause_len in (2, 1):
            pause_start = len(bars) - 1 - pause_len
            trend_end = pause_start
            trend_start = max(0, trend_end - 4)
            if trend_end <= trend_start:
                continue
            pause_bars = bars[pause_start:pause_start + pause_len]
            trend_bars = bars[trend_start:trend_end]
            if len(trend_bars) < 2:
                continue
            green_in_trend = sum(1 for b in trend_bars if _is_green(b))
            if green_in_trend < len(trend_bars) * cfg.micro_pb_green_pct:
                return (f'trend_not_majority_green(green={green_in_trend}/{len(trend_bars)} '
                        f'need={cfg.micro_pb_green_pct*100:.0f}%)')
            if _close(trend_bars[-1]) <= _close(trend_bars[0]):
                return (f'trend_not_rising(first_close={_close(trend_bars[0]):.2f} '
                        f'last_close={_close(trend_bars[-1]):.2f})')
            if any(_close(b) >= _close(trend_bars[-1]) for b in pause_bars):
                return (f'pause_close_too_high(pause_closes={[_close(b) for b in pause_bars]}, '
                        f'trend_end_close={_close(trend_bars[-1]):.2f})')
            if not all(is_light_volume(b, trend_bars, threshold=cfg.micro_pb_light_vol)
                       for b in pause_bars):
                pause_vols = [_vol(b) for b in pause_bars]
                ref_avg = average_volume(trend_bars, lookback=len(trend_bars))
                return (f'pause_heavy_volume(pause_vols={pause_vols}, '
                        f'trend_avg={ref_avg:.0f}, threshold={cfg.micro_pb_light_vol})')
            trend_swing_low = min(_low(b) for b in trend_bars)
            pause_low = min(_low(b) for b in pause_bars)
            if pause_low < trend_swing_low * cfg.micro_pb_swing_tol:
                return (f'pause_breaks_swing_low(pause_low={pause_low:.2f} '
                        f'swing_low={trend_swing_low:.2f} tol={cfg.micro_pb_swing_tol})')
            pause_high = max(_high(b) for b in pause_bars)
            if _close(current) <= pause_high:
                return f'current_not_above_pause_high(close={_close(current):.2f} pause_high={pause_high:.2f})'
            return 'PASS'
        return 'no_valid_pause_found'

    results['MICRO_PULLBACK'] = _explain_micro_pullback()

    # ── ABCD ───────────────────────────────────────────────────────────────────
    def _explain_abcd() -> str:
        if len(bars) < 15:
            return f'too_few_bars({len(bars)}<15)'
        current = bars[-1]
        if not _is_green(current):
            return f'current_not_green(close={_close(current):.2f} open={_open(current):.2f})'
        window = bars[-20:-1]
        if len(window) < 10:
            return f'window_too_small({len(window)}<10)'
        n = len(window)
        a_half = window[:n // 2]
        a_idx = max(range(len(a_half)), key=lambda i: _high(a_half[i]))
        a_high = _high(a_half[a_idx])
        after_a = window[a_idx + 1: n // 2 + 2]
        if len(after_a) < 2:
            return f'no_bars_after_a(after_a_len={len(after_a)})'
        b_idx_rel = min(range(len(after_a)), key=lambda i: _low(after_a[i]))
        b_bar = after_a[b_idx_rel]
        b_low = _low(b_bar)
        if (a_high - b_low) / a_high < cfg.abcd_min_pullback_pct:
            return (f'pullback_too_small(a={a_high:.2f} b={b_low:.2f} '
                    f'pullback={(a_high-b_low)/a_high*100:.1f}% '
                    f'need={cfg.abcd_min_pullback_pct*100:.0f}%)')
        if b_low >= a_high:
            return f'b_not_below_a(b={b_low:.2f} a={a_high:.2f})'
        b_abs_idx = a_idx + 1 + b_idx_rel
        after_b = window[b_abs_idx + 1:]
        if len(after_b) < 2:
            return f'no_bars_after_b(after_b_len={len(after_b)})'
        c_idx_rel = max(range(len(after_b)), key=lambda i: _high(after_b[i]))
        c_bar = after_b[c_idx_rel]
        c_high = _high(c_bar)
        if c_high >= a_high:
            return f'c_above_a(c={c_high:.2f} a={a_high:.2f})'
        if c_high <= b_low:
            return f'c_not_above_b(c={c_high:.2f} b={b_low:.2f})'
        c_abs_idx = b_abs_idx + 1 + c_idx_rel
        d_bars = window[c_abs_idx + 1:] if c_abs_idx + 1 < len(window) else []
        if not d_bars:
            return f'no_d_bars(c_abs_idx={c_abs_idx} window_len={len(window)})'
        d_low = min(_low(b) for b in d_bars)
        if d_low < b_low:
            return f'd_breaks_b_low(d_low={d_low:.2f} b_low={b_low:.2f})'
        c_bars_for_ref = after_b[:c_idx_rel + 1] if after_b else []
        if c_bars_for_ref:
            d_light = all(
                is_light_volume(b, c_bars_for_ref, threshold=cfg.abcd_d_light_vol)
                for b in d_bars
            )
            if not d_light:
                d_vols = [_vol(b) for b in d_bars]
                ref_avg = average_volume(c_bars_for_ref, lookback=len(c_bars_for_ref))
                return (f'd_heavy_volume(d_vols={d_vols}, '
                        f'c_avg={ref_avg:.0f}, threshold={cfg.abcd_d_light_vol})')
        if _close(current) <= c_high:
            return f'current_not_above_c(close={_close(current):.2f} c_high={c_high:.2f})'
        return 'PASS'

    results['ABCD'] = _explain_abcd()

    # ── DIP BUY ────────────────────────────────────────────────────────────────
    def _explain_dip_buy() -> str:
        if len(bars) < 8:
            return f'too_few_bars({len(bars)}<8)'
        ema9 = indicators.get('ema9')
        macd_line = indicators.get('macd_line')
        if ema9 is None:
            return 'no_ema_indicator'
        if macd_line is None:
            return 'no_macd_indicator'
        current = bars[-1]
        if not _is_green(current):
            return f'current_not_green(close={_close(current):.2f} open={_open(current):.2f})'
        current_price = _close(current)
        if current_price <= ema9:
            return f'price_below_ema9(price={current_price:.2f} ema9={ema9:.2f})'
        if macd_line <= 0:
            return f'macd_line_negative(macd_line={macd_line:.4f})'
        pullback_bars = bars[-4:-1]
        if len(pullback_bars) < 2:
            return f'too_few_pullback_bars({len(pullback_bars)}<2)'
        ref_bars = bars[-10:-4]
        if len(ref_bars) < 3:
            return f'too_few_ref_bars({len(ref_bars)}<3)'
        if not any(_close(b) < _close(bars[-4]) for b in pullback_bars[1:]):
            return f'no_actual_dip(pullback_closes={[_close(b) for b in pullback_bars]})'
        if not all(is_light_volume(b, ref_bars, threshold=cfg.dip_buy_light_vol)
                   for b in pullback_bars):
            pb_vols = [_vol(b) for b in pullback_bars]
            ref_avg = average_volume(ref_bars, lookback=len(ref_bars))
            return (f'pullback_heavy_volume(vols={pb_vols}, '
                    f'ref_avg={ref_avg:.0f}, threshold={cfg.dip_buy_light_vol})')
        return 'PASS'

    results['DIP_BUY'] = _explain_dip_buy()

    # ── FLAT TOP ───────────────────────────────────────────────────────────────
    def _explain_flat_top() -> str:
        if len(bars) < 8:
            return f'too_few_bars({len(bars)}<8)'
        current = bars[-1]
        if not _is_green(current):
            return f'current_not_green(close={_close(current):.2f} open={_open(current):.2f})'
        window = bars[-11:-1]
        if len(window) < 5:
            return f'window_too_small({len(window)}<5)'
        best_resistance = None
        best_touches: list[dict] = []
        for i in range(len(window) - 1):
            candidate_level = _high(window[i])
            touches = [
                b for b in window[i:]
                if abs(_high(b) - candidate_level) <= cfg.flat_top_resistance_tol
            ]
            if len(touches) >= 2 and len(touches) > len(best_touches):
                best_touches = touches
                best_resistance = candidate_level
        if not best_touches or best_resistance is None or len(best_touches) < 2:
            all_highs = [_high(b) for b in window]
            return f'no_resistance_level(window_highs={[round(h,2) for h in all_highs]}, tol={cfg.flat_top_resistance_tol})'
        touch_volumes = [_vol(b) for b in best_touches]
        increases = sum(
            1 for a, b in zip(touch_volumes, touch_volumes[1:])
            if b > a * cfg.flat_top_vol_increase_tol
        )
        if increases >= len(touch_volumes) - 1:
            return f'volume_uniformly_increasing(touches={len(best_touches)}, vol_increases={increases})'
        if _close(current) <= best_resistance:
            return f'current_not_above_resistance(close={_close(current):.2f} resistance={best_resistance:.2f})'
        max_consol_vol = max(touch_volumes)
        if _vol(current) <= max_consol_vol:
            return f'breakout_vol_too_low(current_vol={_vol(current):.0f} max_consol_vol={max_consol_vol:.0f})'
        return 'PASS'

    results['FLAT_TOP'] = _explain_flat_top()

    return results
