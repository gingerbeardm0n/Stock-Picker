"""
Trading Data Models
===================
Shared dataclasses used by entry_engine, exit_engine, patterns, and the simulator.

Config objects (A/B/C correspond to optimizer categories):
    ScannerConfig  — Category A: stock selection / 5-pillar thresholds
    EntryConfig    — Category B: pattern detection thresholds + R/R gate
    ExitConfig     — Category C: exit signal thresholds (already existed)
"""

from dataclasses import dataclass, field
from datetime import datetime


# ── Category A: Scanner / 5-Pillar thresholds ─────────────────────────────────

@dataclass
class ScannerConfig:
    """
    Category A parameters — stock selection and Ross Cameron's 5 Pillars.

    These are the gates applied BEFORE pattern detection. Changing them controls
    which stocks are even considered for entry.

    Defaults match the published strategy (min_relative_volume=5x, etc.).
    """
    min_price: float = 1.0              # Pillar 1: minimum price
    max_price: float = 20.0             # Pillar 1: maximum price
    min_premarket_gain: float = 10.0    # Pillar 2: % gain vs prior close
    min_relative_volume: float = 5.0    # Pillar 3: rel-vol multiplier minimum
    min_buying_volume: float = 50_000   # Pillar 3: absolute buying-volume floor
    max_float: int = 20_000_000         # Pillar 4: max float shares
    max_market_cap: int = 500_000_000   # Pillar 4 (extended): max market cap
    max_spread: float = 0.15            # Time check: max bid-ask spread
    min_last_5min_volume: int = 100_000 # Time check: min volume in last 5 minutes
    min_last_1min_volume: int = 10_000  # Time check: min volume in last 1 minute

    # Gate toggles (feature selection)
    enable_price_range: bool = True
    enable_premarket_gain: bool = True
    enable_relative_volume: bool = True
    enable_buying_volume: bool = False
    enable_float_filter: bool = True    # Pillar 4: float <= 20M shares. Graceful degradation if no data.
    enable_market_cap_filter: bool = False
    enable_spread_filter: bool = False
    enable_last_5min_volume: bool = False
    enable_last_1min_volume: bool = False


# ── Category B: Entry / Pattern thresholds ────────────────────────────────────

@dataclass
class EntryConfig:
    """
    Category B parameters — entry logic and pattern detection thresholds.

    Controls how strictly each chart pattern is validated.
    Defaults match the current hand-tuned implementation.
    """
    min_rr_ratio: float = 2.0           # Gate 5: minimum reward/risk to enter
    stop_buffer: float = 0.076          # $ below pattern low for all stop prices (Trial 193)

    # Gate toggles (feature selection)
    enable_ema9: bool = False
    enable_macd: bool = True   # MACD line (EMA12-EMA26) > 0 = front-side gate. Exempt: gap-and-go.
    enable_trend: bool = True
    enable_rr: bool = True
    enable_gap_and_go: bool = True      # Gap and Go — #1 pattern by frequency (1,177 trades, 69% win rate)
    enable_vwap_reclaim: bool = True    # VWAP Reclaim — highest win rate (153 trades, 75% win rate)
    enable_bull_flag: bool = False      # Trial 193: disabled (micro_pullback+dip_buy+flat_top only)
    enable_micro_pullback: bool = True
    enable_abcd: bool = False           # Trial 193: disabled
    enable_dip_buy: bool = True
    enable_flat_top: bool = True

    # ── Gap and Go ─────────────────────────────────────────────────────────────
    # Source: concept_gap_and_go.md — break of premarket high at open
    # MACD is NOT required for this pattern (96% of trades = unknown MACD state)
    gap_and_go_breakout_vol_min: float = 1.5   # Breakout bar >= 1.5x recent avg vol (concept page spec)
    gap_and_go_max_bars_since_open: int = 15   # Only fire within first 15 mins of open (before 9:45am)

    # ── VWAP Reclaim ───────────────────────────────────────────────────────────
    # Source: concept_pattern_playbook.md section 6 — highest win rate of all patterns
    # Stock dips below VWAP, then 1m candle closes above VWAP on volume.
    # Stop: close back below VWAP. Valid before 11am only.
    vwap_reclaim_lookback: int = 5          # Bars to look back for "was below VWAP"
    vwap_reclaim_min_below: int = 1         # Min bars below VWAP required before reclaim
    vwap_reclaim_breakout_vol_min: float = 1.2  # Reclaim bar >= 1.2x recent avg vol

    # ── Bull Flag ──────────────────────────────────────────────────────────────
    bull_flag_light_vol: float = 0.70        # Flag bars: volume < X × pole avg
    bull_flag_pole_vol_min: float = 0.80     # Pole: must have >= X × reference avg
    bull_flag_breakout_vol_min: float = 0.80 # Breakout: must have >= X × pole avg

    # ── Micro Pullback ─────────────────────────────────────────────────────────
    micro_pb_green_pct: float = 0.60    # Trend phase: min fraction of green bars
    micro_pb_light_vol: float = 0.70    # Pause bars: volume < X × trend avg
    micro_pb_swing_tol: float = 0.98    # Pause low must not break trend low by > (1-X)

    # ── ABCD ───────────────────────────────────────────────────────────────────
    abcd_min_pullback_pct: float = 0.15  # B must be >= X% below A price
    abcd_d_light_vol: float = 0.80       # D bars: volume < X × C-phase avg

    # ── Dip Buy ────────────────────────────────────────────────────────────────
    dip_buy_light_vol: float = 0.65      # Pullback bars: volume < X × ref avg

    # ── Flat Top ───────────────────────────────────────────────────────────────
    flat_top_resistance_tol: float = 0.03   # Highs within $X = same resistance
    flat_top_vol_increase_tol: float = 1.20 # Volume "increase" threshold ratio


# ── Category C: Exit signal thresholds ────────────────────────────────────────

@dataclass
class ExitConfig:
    """
    Configuration for exit_engine.evaluate_exit().

    All fields have strategy-aligned defaults so existing callers work unchanged.
    Pass a custom ExitConfig to change exit behavior (e.g. from Optuna optimizer).

    Categories:
        Scaling     — how aggressively to take profits at each target
        Trailing    — dynamic stop that locks in gains as price rises
        Time        — when to exit based on time of day
        Pressure    — selling volume thresholds
        MACD Flip   — exit on momentum reversal (Phase 3)
        Resistance  — exit when price repeatedly tests prior-day high (Phase 3)
        Volume Dry-up — exit when buying volume collapses (Phase 4)
    """

    # ── Scaling targets ────────────────────────────────────────────────────────
    # Standard 2-level (default): 50% at T1, 25% at T2, remainder on soft signals
    # Advanced 3-level: 25% at T1, 25% at T2, 50% on trailing stop
    target1_ratio: float = 2.19         # R/R for first profit target (Trial 193)
    target2_ratio: float = 3.0          # R/R for second profit target
    target1_qty_pct: float = 0.30       # Fraction of original position to sell at T1 (Trial 193)
    target2_qty_pct: float = 0.25       # Fraction of original position to sell at T2
    ema_cross_qty_pct: float = 0.25     # Fraction to sell on EMA-9 cross (soft exit)

    # ── Trailing stop ──────────────────────────────────────────────────────────
    # Applied to the remainder after T1 fires. 0.0 = disabled.
    # When enabled: trail_stop = highest_price_since_entry - trailing_stop_distance
    # Only activates after at least T1 has fired (some shares already sold).
    trailing_stop_distance: float = 0.262  # Trial 193: 26.2-cent trailing stop; 0.0 = disabled

    # ── Time decay ────────────────────────────────────────────────────────────
    time_decay_hour: int = 12            # Primary: exit profitable positions after 12 PM ET
    # Early exit: if no "major gains" by early_time_decay_hour:early_time_decay_minute
    # Set early_time_decay_hour = 0 to disable.
    early_time_decay_hour: int = 0       # 0 = disabled; e.g. 10 = 10:xx AM
    early_time_decay_minute: int = 45    # Minutes past early hour (e.g. 10:45 AM)
    early_time_decay_min_gain_pct: float = 5.0  # Skip early exit if unrealized > this %

    # ── Selling pressure ──────────────────────────────────────────────────────
    enable_selling_pressure: bool = False  # Disabled — fires too early on small moves
    selling_pressure_ratio: float = 2.0  # Exit when selling_vol > buying_vol × ratio
    selling_pressure_qty_pct: float = 0.50  # Fraction to sell on pressure signal

    # ── MACD flip exit (Phase 3) ──────────────────────────────────────────────
    # Fire when MACD histogram flips from positive to negative while profitable.
    enable_macd_flip_exit: bool = False
    macd_flip_qty_pct: float = 0.50     # Fraction to sell on MACD flip

    # ── Resistance / prior-day-high exit (Phase 3) ────────────────────────────
    # Fire when stock tests prior-day high N times (each bounce = likely reversal).
    enable_resistance_exit: bool = False
    resistance_touch_threshold: int = 2  # Exit on Nth touch (2 = exit on 2nd test)
    resistance_exit_qty_pct: float = 0.50   # Fraction to sell on resistance
    resistance_tolerance: float = 0.03  # Within $0.03 of prior-day-high = "touched"

    # ── Volume dry-up exit (Phase 4) ──────────────────────────────────────────
    # Fire when buying volume collapses vs 5-bar average (momentum fading).
    enable_volume_dry_up_exit: bool = False
    volume_dry_up_threshold: float = 0.60  # < 60% of avg = dry
    volume_dry_up_qty_pct: float = 0.50


@dataclass
class PatternSignal:
    """
    A detected chart pattern with a specific entry setup.
    Returned by each pattern detector in patterns.py.
    """
    pattern_type: str    # 'GAP_AND_GO', 'VWAP_RECLAIM', 'BULL_FLAG', 'MICRO_PULLBACK', 'ABCD', 'DIP_BUY', 'FLAT_TOP'
    confidence: int      # 1-5 stars (matching strategy doc reliability rating)
    entry_price: float   # Suggested entry (current bar close)
    stop_price: float    # Pattern-specific stop loss (NOT just bar low - $0.01)
    target1: float       # First profit target (2:1 R/R minimum)
    target2: float       # Second profit target (3:1 R/R)
    reasoning: str       # Human-readable explanation for logs/debugging
                         # e.g. "Flagpole $5.00→$6.50, flag $6.20-$6.35, breakout $6.40"

    @property
    def stop_distance(self) -> float:
        return self.entry_price - self.stop_price

    @property
    def reward_distance(self) -> float:
        return self.target1 - self.entry_price

    @property
    def risk_reward_ratio(self) -> float:
        if self.stop_distance <= 0:
            return 0
        return self.reward_distance / self.stop_distance


@dataclass
class EntrySignal:
    """
    A confirmed entry signal — all gates passed (5 pillars, technicals, pattern, R/R).
    Returned by entry_engine.evaluate_entry().
    """
    symbol: str
    pattern: PatternSignal
    pillar_data: dict = field(default_factory=dict)  # rel_vol, pct_change, float, etc.


@dataclass
class ExitSignal:
    """
    An exit instruction — close some or all shares.
    Returned by exit_engine.evaluate_exit().
    """
    reason: str    # 'STOP_HIT', 'TRAILING_STOP',
                   # 'TARGET_1', 'TARGET_2',
                   # 'EMA_CROSS', 'TIME_DECAY', 'EARLY_TIME_DECAY',
                   # 'SELLING_PRESSURE', 'MACD_FLIP',
                   # 'RESISTANCE_TOUCH', 'VOLUME_DRY_UP',
                   # 'FULLY_SCALED'
    price: float   # Exit price (current bar close)
    qty: int       # Number of shares to exit
    move_stop_to_breakeven: bool = False  # Set True on TARGET_1 to move stop
    new_stop_price: float | None = None  # Optional stop adjustment (tighten stop)
