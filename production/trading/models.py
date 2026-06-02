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
    min_premarket_gain: float = 5.0     # Pillar 2: % gain vs prior close (matches MomentumScanConfig)
    min_relative_volume: float = 5.0    # Pillar 3: rel-vol multiplier minimum
    min_buying_volume: float = 50_000   # Pillar 3: absolute buying-volume floor
    max_float: int = 20_000_000         # Pillar 4: max float shares
    max_market_cap: int = 500_000_000   # Pillar 4 (extended): max market cap
    scan_end_hour: int = 11             # ET hour; no new entries after this (matches MomentumScanConfig)
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
    enable_ema9: bool = True             # Price > EMA-9 = trend confirmation at entry
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
    # GAP-07/08/10: new patterns from concept page corpus analysis
    enable_red_to_green: bool = True    # Red-to-Green reclaim — 66.2% win rate / 71 trades
    enable_whole_dollar: bool = True    # Whole Dollar Break — 64.3% win rate / 112 trades
    enable_orb: bool = True             # Opening Range Breakout — 70.8% win rate / 48 trades

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

    # ── VWAP Break/Curl ────────────────────────────────────────────────────────
    # Source: concept_entry_trigger_taxonomy.md — 78.1% win rate, highest dollar EV
    # Anticipatory VWAP entry: fires at or before the full reclaim candle.
    #   Break variant: previous bar closed below VWAP, current is first bar above.
    #   Curl variant:  price still below VWAP but approaching within tolerance,
    #                  last 3 bars show successively higher closes (momentum curl).
    # Entry is EARLIER than vwap_reclaim (which requires confirmed hold above).
    enable_vwap_break_curl: bool = True
    vwap_break_curl_lookback: int = 4        # Bars to look back for below-VWAP setup
    vwap_curl_tolerance: float = 0.015       # Curl fires when within 1.5% of VWAP
    vwap_break_vol_min: float = 1.1          # Break/curl bar volume >= 1.1× recent avg

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
    dip_buy_light_vol: float = 0.65      # Legacy — retained for Optuna compat; no longer used in detector
    dip_buy_support_tolerance: float = 0.08  # Dip low must be within X% of a named support level

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
    time_decay_hour: int = 11            # Primary: exit profitable positions after 11 AM ET (RC: 11am = dead zone)
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
    macd_flip_qty_pct: float = 0.75     # Fraction to sell on MACD flip (concept: "close 75%+")

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


# ── Category E: Add-on / Pyramid mechanics ───────────────────────────────────

@dataclass
class AddOnConfig:
    """
    Category E parameters — add-on (pyramid) mechanics.

    Controls when and how much to add to an existing profitable position.
    Source: concept_add_on_mechanics.md — 2,593 add-on trades across 1,049 sessions.
    Add-ons present in 52.3% of all Ross Cameron trades.
    """
    # ── Gate toggles ───────────────────────────────────────────────────────────
    enable_new_high: bool = True          # Gate 1: add on new session high break (42.8% of add triggers)
    enable_micro_pb_add: bool = True      # Gate 2: add on micro-pullback resumption (26.4%)
    enable_vwap_retest: bool = True       # Gate 3: add on VWAP hold from above (6.5%)
    enable_whole_dollar_add: bool = True  # Gate 4: add on whole-dollar break + positive MACD
    # Note: Gate 5 (halt-resume add, 6.6%) requires halt feed — not implementable in backtest.

    # ── Preconditions ──────────────────────────────────────────────────────────
    max_add_ons: int = 4                  # Max additions per trade (rarely > 4 in corpus)
    time_cutoff_hour: int = 10            # Add-on window: only before 10:30 ET
    time_cutoff_minute: int = 30

    # ── Sizing (fraction of initial_shares at each tier) ───────────────────────
    add_pct_tier1: float = 0.25           # Add 1: 25% of initial position
    add_pct_tier2: float = 0.25           # Add 2: 25%
    add_pct_tier3: float = 0.20           # Add 3: 20%
    add_pct_tier4: float = 0.10           # Add 4: 10% (rare; only on halting-up momentum)
    hot_market_multiplier: float = 1.25   # Scale add size by this in HOT temperature

    # ── Stop adjustment ────────────────────────────────────────────────────────
    stop_buffer: float = 0.076            # $ below breakout/pullback-low for updated stop


# ── Intraday Momentum Scanner config ─────────────────────────────────────────

@dataclass
class MomentumScanConfig:
    """
    Configuration for the intraday high-day-momo scanner.

    Used by qualifies_momentum() — called identically from both the sim
    (Orchestrator._scan_for_entry, scanner mode) and the live runner
    (_run_intraday_momentum_scan), ensuring sim/live discovery parity.

    All fields are Optuna-tunable (Category A).

    Gates:
      G1  min_relative_volume  — rel-vol minimum (corpus: 5x)
      G2  hod_tol              — tolerance below high-of-day to still qualify (0 = strict)
      G3  scan_end_hour        — ET hour after which scanner goes quiet (corpus: 11 AM)
      G4  max_float            — maximum float shares (corpus: 20M)
      G5  min_price/max_price  — price range (corpus: $1-$20)
      G6  min_intraday_gain    — % gain vs prior close (intraday default 5% < premarket 10%)
    """
    min_price: float = 1.0
    max_price: float = 20.0
    min_relative_volume: float = 5.0
    max_float: int = 20_000_000
    min_intraday_gain: float = 5.0   # % gain from prior close (vs ScannerConfig.min_premarket_gain=10%)
    hod_tol: float = 0.0             # fraction below HOD that still qualifies (0.02 = within 2%)
    scan_end_hour: int = 11          # ET hour; window is [9:30, scan_end_hour) exclusive


# ── Category D: Market Temperature thresholds ────────────────────────────────

@dataclass
class MarketTemperatureConfig:
    """
    Category D parameters — market temperature detection and per-regime overrides.

    Detection thresholds control how premarket signals are classified into
    HOT / NEUTRAL / COLD / CHOP. The per-temperature param overrides let Optuna
    tune position sizing and trade limits per regime independently.

    Source: concept_market_temperature.md §6
    """
    # ── Detection thresholds ──────────────────────────────────────────────────
    hot_gapper_threshold: float = 50.0    # Leading gapper % → HOT (with enough symbols)
    warm_gapper_threshold: float = 20.0   # Leading gapper % → NEUTRAL (below = COLD)
    hot_symbols_min: int = 3              # Min qualifying symbols on scanner → HOT
    cold_symbols_max: int = 2             # Max qualifying symbols → COLD (above = NEUTRAL)

    # ── Per-temperature position size overrides ───────────────────────────────
    # Set to 0.0 to use the built-in defaults from market_temperature._PARAMS
    hot_max_position_pct: float = 20.0
    neutral_max_position_pct: float = 15.0
    cold_max_position_pct: float = 10.0
    chop_max_position_pct: float = 5.0



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
class ScoringConfig:
    """
    Category F parameters — composite entry score weights and temperature thresholds.

    Each component contributes points (0 to max) to a 0-100 total score.
    Temperature sets the minimum score to enter and the base position size.
    All weights are Optuna-tunable — defaults are corpus-informed starting points.

    Source: concept_news_catalyst.md, concept_entry_trigger_taxonomy.md,
            concept_float_analysis.md, concept_market_temperature.md
    """
    # ── Pattern base points (max 25) ──────────────────────────────────────────
    # Ordered by corpus win rate (entry_trigger_taxonomy.md):
    # gap-and-go 78.2%, vwap-break/curl 78.1%, micro-pullback 74.3%, vwap-reclaim 72.0%, ORB 70.8%
    pattern_gap_and_go: int = 25
    pattern_vwap_break_curl: int = 25   # 78.1% win rate — tied with gap-and-go
    pattern_micro_pullback: int = 23
    pattern_vwap_reclaim: int = 22
    pattern_orb: int = 21
    pattern_bull_flag: int = 20
    pattern_flat_top: int = 20
    pattern_red_to_green: int = 18
    pattern_dip_buy: int = 17
    pattern_whole_dollar: int = 17
    pattern_abcd: int = 15
    pattern_default: int = 15          # fallback for any unlisted pattern

    # ── Relative volume magnitude (max 20) ────────────────────────────────────
    # Binary 5x gate remains in ScannerConfig; this grades the MAGNITUDE of vol.
    relvol_pts_100x: int = 20          # 100x+ = institutional panic / squeeze
    relvol_pts_25x: int = 16           # 25-100x = very strong conviction
    relvol_pts_10x: int = 12           # 10-25x = solid
    relvol_pts_5x: int = 8             # 5-10x = meets minimum gate, modest edge

    # ── News catalyst tier (max 20) ───────────────────────────────────────────
    # Source: concept_news_catalyst.md — +12.7pp win rate, 4.4x EV with news
    # NOT a hard gate — no news = 0 pts, not a reject.
    news_tier1_pts: int = 20           # FDA, earnings beat, M&A, short squeeze
    news_tier2_pts: int = 15           # contract, partnership, biotech data
    news_tier3_pts: int = 10           # sector sympathy, social media driven
    news_presence_pts: int = 8         # news present but tier not classified
    news_none_pts: int = 0             # no catalyst (still tradeable, just lower score)
    news_unknown_pts: int = 4          # no data available (backtest / API unavailable)

    # ── Float quality (max 15) ────────────────────────────────────────────────
    # Source: concept_float_analysis.md — sub-5M = maximum squeeze dynamics
    float_sub1m_pts: int = 15          # sub-1M: extreme moves, tight stop required
    float_1m_5m_pts: int = 12          # 1M-5M: core target zone
    float_5m_20m_pts: int = 6          # 5M-20M: acceptable, slower moves
    float_20m_plus_pts: int = 0        # 20M+: strategy's soft ceiling
    float_unknown_pts: int = 6         # unknown float: half credit (graceful degradation)

    # ── Gap % magnitude (max 10) ──────────────────────────────────────────────
    gap_40pct_pts: int = 10            # 40%+ gap = explosive, short-squeeze territory
    gap_20pct_pts: int = 7             # 20-40% = strong
    gap_10pct_pts: int = 4             # 10-20% = meets minimum gate

    # ── MACD state (max 5) ────────────────────────────────────────────────────
    macd_positive_pts: int = 5         # MACD line > 0 = confirmed front-side
    macd_unknown_pts: int = 2          # < 35 bars (early open) — half credit
    macd_negative_pts: int = 0         # back-side; already blocked by entry gate

    # ── Time of day (max 5) ───────────────────────────────────────────────────
    time_930_945_pts: int = 5          # Best window: opening momentum peak
    time_945_1000_pts: int = 4
    time_1000_1030_pts: int = 2
    time_after_1030_pts: int = 0       # Also blocked by entry window gate at 11

    # ── Temperature entry thresholds (min score to enter) ─────────────────────
    threshold_hot: int = 40            # Aggressive: many setups qualify
    threshold_neutral: int = 55        # Base-hit: standard quality
    threshold_cold: int = 70           # Defensive: A+ only
    threshold_chop: int = 80           # Exceptional: near-perfect setup required

    # ── Temperature base position size multipliers ────────────────────────────
    size_hot: float = 1.0              # Full size in hot market
    size_neutral: float = 0.75         # Slightly reduced in neutral
    size_cold: float = 0.50            # Half size on cold days
    size_chop: float = 0.25            # Quarter size on chop days
    # Score bonus: each 10 pts above threshold adds this fraction (capped at +0.5)
    size_bonus_per_10pts: float = 0.10


@dataclass
class EntryScore:
    """
    Per-signal composite entry score (0–100).
    Computed by scoring_engine.compute_entry_score() after all hard gates pass.
    Drives position sizing and temperature-adjusted entry threshold.
    """
    total: int                  # 0-100 composite score
    components: dict            # breakdown for logging and Optuna analysis

    def passes_threshold(self, temperature_name: str, config: 'ScoringConfig') -> bool:
        """Return True if score meets the minimum for the current temperature."""
        thresholds = {
            'HOT': config.threshold_hot,
            'NEUTRAL': config.threshold_neutral,
            'COLD': config.threshold_cold,
            'CHOP': config.threshold_chop,
        }
        return self.total >= thresholds.get(temperature_name, config.threshold_cold)

    def size_multiplier(self, temperature_name: str, config: 'ScoringConfig') -> float:
        """
        Position size multiplier combining temperature base × score bonus.

        Formula:
            base = temperature base (HOT=1.0, NEUTRAL=0.75, COLD=0.5, CHOP=0.25)
            bonus = floor((score - threshold) / 10) × 0.10, capped at +0.50
        Returns 0.0 if score is below the entry threshold (should not enter).
        """
        if not self.passes_threshold(temperature_name, config):
            return 0.0
        base = {
            'HOT': config.size_hot,
            'NEUTRAL': config.size_neutral,
            'COLD': config.size_cold,
            'CHOP': config.size_chop,
        }.get(temperature_name, config.size_cold)
        thresholds = {
            'HOT': config.threshold_hot,
            'NEUTRAL': config.threshold_neutral,
            'COLD': config.threshold_cold,
            'CHOP': config.threshold_chop,
        }
        threshold = thresholds.get(temperature_name, config.threshold_cold)
        bonus = min(0.50, ((self.total - threshold) // 10) * config.size_bonus_per_10pts)
        return round(base + bonus, 2)


@dataclass
class EntrySignal:
    """
    A confirmed entry signal — all gates passed (5 pillars, technicals, pattern, R/R).
    Returned by entry_engine.evaluate_entry().
    """
    symbol: str
    pattern: PatternSignal
    pillar_data: dict = field(default_factory=dict)  # rel_vol, pct_change, float, etc.
    entry_score: 'EntryScore | None' = None          # composite conviction score (GAP scoring)


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
