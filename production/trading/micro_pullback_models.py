"""
Micro-Pullback Models — Strategy #3 Configuration
==================================================
14 tunable parameters for the Micro-Pullback strategy.
Deliberately minimal to avoid overfitting — same budget as the Opening Bell
Scalp (14) and VWAP Reclaim (13); the 126-param monolith is the cautionary tale
(see docs/ANTI_OVERFITTING_PLAYBOOK.md).

Corpus grounding (concept_micro_pullback.md):
  - 74.3% win rate, +$3,560 avg result (RC stats, 350 trades) — #3 of all patterns
  - Best window 9:45-10:30 ET; after 10:30 "micro" becomes "macro" reversal
  - Fills the 9:40-10:00 hole between the scalp (caps ~9:50) and VWAP (starts 10:00)
  - Float 1M-10M ideal; sub-1M violent, >50M too slow
  - Pattern: prior momentum -> 1-3 candle shallow pullback on LIGHTER volume ->
    resumption breaks the pullback high on EXPANDING volume, price holds EMA-9
"""

from dataclasses import dataclass, asdict


# Fixed (non-tunable) strategy constants — corpus priors, locked per the
# anti-overfitting playbook (method 2.9, cut degrees of freedom).
ENTRY_WINDOW_START = (9, 40)    # ET — right after the scalp's open window
ENTRY_WINDOW_END = (10, 30)     # ET — after 10:30 the pullback becomes a reversal
WATCH_TOP_N = 10                # watch top-N ranked gappers (sealed validation = arm 10)
# KNOWN PARITY GAP: the live runner is single-position while the sealed
# validation allowed up to 3 concurrent. Live therefore trades a conservative
# subset of the validated behavior. Left as-is deliberately — the strategy is
# UNDER-REVIEW for live viability (fill-aware re-opt failed its sealed test,
# see docs/SIM_FILL_MODEL_DESIGN.md); convert to multi-position only if it
# earns its way out of review.
EMA_PERIOD = 9                  # Ross's 9-period EMA (fixed, not tuned)


@dataclass
class MicroPullbackConfig:
    """
    Micro-Pullback configuration.

    The strategy: a morning gapper with news makes a strong leg up, pauses for
    1-3 candles on decreasing volume (a rest, not a reversal), holds the 9-EMA,
    then a green candle breaks back above the pullback high on expanding volume.
    Enter the break; stop just below the pullback low (structural, like VWAP's
    VWAP-anchored stop).

    Parameter groups:
        Screening (4 tuned + news lock): which stocks qualify
        Setup (5):  what counts as a valid micro-pullback
        Exit (3):   how/when to exit (stop is structural = pullback low)
        Sizing (2): position size
    """

    # ── Screening ──────────────────────────────────────────────────────────
    min_gap_pct: float = 10.0           # Minimum gap % vs prior close
    min_relative_volume: float = 3.0    # Minimum relative volume at 9:25
    max_price: float = 20.0             # Maximum stock price
    max_float: int = 20_000_000         # Maximum float shares (pattern likes 1-10M)
    require_news: bool = True           # LOCKED True — catalyst is the core edge

    # ── Setup (the micro-pullback definition) ──────────────────────────────
    lookback_bars: int = 9              # Bars to search for the prior leg's peak
    max_pullback_bars: int = 3          # Max consecutive pullback candles (1-3 = "micro")
    max_pullback_retrace: float = 5.0   # Max % the pullback may drop below the peak (shallow)
    pullback_vol_ratio: float = 0.8     # Pullback avg vol must be < this x the rip-bar vol
    resume_vol_mult: float = 1.2        # Resumption bar vol >= this x pullback avg (expansion)

    # ── Exit ───────────────────────────────────────────────────────────────
    profit_target_pct: float = 5.0      # Take profit at X% gain
    max_hold_bars: int = 20             # Force exit after N bars
    trailing_stop_pct: float = 0.0      # 0 = disabled

    # ── Position sizing ────────────────────────────────────────────────────
    risk_pct: float = 2.0               # % of account to risk
    max_position_pct: float = 30.0      # Max % of account in one position

    # ── Sim entry fill model (docs/SIM_FILL_MODEL_DESIGN.md) ───────────────
    # 'perfect' keeps historical results reproducible; live-parity diagnostic
    # runs use 'marketable_limit'. Ignored by the live runners.
    fill_model: str = 'perfect'         # 'perfect' | 'marketable_limit'
    entry_headroom_pct: float = 0.25    # marketable-limit headroom above signal
    entry_slippage_pct: float = 0.0     # flat extra slippage on any fill
    market_fallback_pct: float = 0.0    # 0=off; 0.5=live behavior (market retry if ask ≤ signal×1.005)

    def to_dict(self) -> dict:
        """Serialize to dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> 'MicroPullbackConfig':
        """Construct from dict, ignoring unknown keys."""
        valid = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in valid})
