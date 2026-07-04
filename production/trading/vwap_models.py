"""
VWAP Models — VWAP Reclaim Strategy Configuration
==================================================
13 tunable parameters for the VWAP Reclaim strategy.
Deliberately minimal to avoid overfitting (the Opening Bell Scalp's 14-param
budget is the proven template; the main system's 126 params are the cautionary
tale — see docs/ANTI_OVERFITTING_PLAYBOOK.md).

Corpus grounding (concept_vwap_reclaim.md):
  - 72.0% win rate, +$6,920 avg result (RC stats, 50 trades)
  - VWAP family (reclaim + break/curl + other) = 3 of top 6 trigger slots
  - Best window 10:00-11:00 ET; pre-10:00 VWAP unreliable, post-noon fails
  - Do NOT gate on MACD (2.6% relevance per corpus)
  - News catalyst required: no-news reclaims are tier-3
"""

from dataclasses import dataclass, asdict


# Fixed (non-tunable) strategy constants — strong corpus priors, locked
# per anti-overfitting playbook method 2.9 (cut degrees of freedom).
ENTRY_WINDOW_START = (10, 0)    # ET — VWAP needs ≥30 min of bars to be meaningful
ENTRY_WINDOW_END = (11, 30)     # ET — post-noon reclaims on morning runners fail
WATCH_TOP_N = 10                # watch top-N ranked gappers (sealed validation = arm 10)
MAX_CONCURRENT = 3              # max simultaneous positions (sealed validation = max 3)


@dataclass
class VwapReclaimConfig:
    """
    VWAP Reclaim configuration.

    The strategy: morning gapper with news runs up, dips below session VWAP
    (sellers test), then a 1-minute candle closes back above VWAP on elevated
    volume (buyers reclaim). Enter on the reclaim, stop just below VWAP.

    Parameter groups:
        Screening (3 tuned + news lock): which stocks qualify
        Setup (3):   what counts as a valid VWAP test + reclaim
        Entry (1):   how to enter off the reclaim bar
        Exit (4):    how/when to exit
        Sizing (2):  position size
    """

    # ── Screening ──────────────────────────────────────────────────────────
    min_gap_pct: float = 10.0           # Minimum gap % vs prior close
    min_relative_volume: float = 3.0    # Minimum relative volume at 9:25
    max_price: float = 20.0             # Maximum stock price
    require_news: bool = True           # LOCKED True — no-news reclaims are tier-3

    # ── Setup (the VWAP test + reclaim definition) ─────────────────────────
    lookback_bars: int = 5              # Bars to look back for the VWAP test
    min_bars_below: int = 1             # Min closes below VWAP in lookback (confirms test)
    reclaim_vol_mult: float = 1.2       # Reclaim bar volume vs lookback avg (corpus prior 1.2x)

    # ── Entry ──────────────────────────────────────────────────────────────
    entry_mode: str = 'reclaim_close'   # 'reclaim_close' | 'reclaim_high_break'

    # ── Exit ───────────────────────────────────────────────────────────────
    stop_vwap_offset: float = 0.02      # Stop = entry-time VWAP minus this ($)
    profit_target_pct: float = 5.0      # Take profit at X% gain
    max_hold_bars: int = 30             # Force exit after N bars (reclaims hold 5-30 min)
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

    def to_dict(self) -> dict:
        """Serialize to dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> 'VwapReclaimConfig':
        """Construct from dict, ignoring unknown keys."""
        valid = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in valid})
