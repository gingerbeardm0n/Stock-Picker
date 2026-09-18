"""
Scalp Models — Opening Bell Scalp Configuration
================================================
14 tunable parameters for the scalp strategy.
Deliberately minimal to avoid overfitting (vs 126 params in the main system).
"""

from dataclasses import dataclass, asdict, field


@dataclass
class ScalpConfig:
    """
    Opening Bell Scalp configuration.

    The scalp strategy: buy the #1 premarket gapper with a news catalyst
    right at 9:30 AM open and sell within 1-10 minutes.

    Parameter groups:
        Screening (4): which stocks qualify
        News (1):      catalyst gate
        Entry (3):     how/when to enter
        Exit (4):      how/when to exit
        Sizing (2):    position size
    """

    # ── Screening ──────────────────────────────────────────────────────────
    min_gap_pct: float = 10.0           # Minimum gap % vs prior close
    min_relative_volume: float = 5.0    # Minimum premarket relative volume
    max_float: int = 20_000_000         # Maximum float shares
    max_price: float = 20.0             # Maximum stock price

    # ── News gate ──────────────────────────────────────────────────────────
    require_news: bool = True           # Must have a specific news catalyst

    # ── Entry ──────────────────────────────────────────────────────────────
    entry_mode: str = 'pm_high_break'   # 'pm_high_break' | 'market_open' | 'first_green'
    max_entry_bars: int = 2             # Max bars after 9:30 to wait for entry
    min_pm_high_break_pct: float = 0.0  # Min % above PM high to confirm break

    # ── Exit ───────────────────────────────────────────────────────────────
    profit_target_pct: float = 3.0      # Take profit at X% gain
    stop_loss_pct: float = 2.0          # Stop loss at X% loss
    max_hold_bars: int = 5              # Force exit after N bars (minutes)
    trailing_stop_pct: float = 0.0      # 0 = disabled; e.g. 1.5 = trail 1.5% from high

    # ── Position sizing ────────────────────────────────────────────────────
    risk_pct: float = 3.0               # % of account to risk
    max_position_pct: float = 30.0      # Max % of account in one position

    # ── Sim entry fill model (docs/SIM_FILL_MODEL_DESIGN.md) ───────────────
    # 'perfect' keeps historical results reproducible; live-parity diagnostic
    # runs use 'marketable_limit'. Ignored by the live runners.
    fill_model: str = 'perfect'         # 'perfect' | 'marketable_limit'
    entry_headroom_pct: float = 0.25    # marketable-limit headroom above signal
    entry_slippage_pct: float = 0.0     # flat extra slippage on any fill

    # ── Sim EXIT fill model (Gate 0, docs/DEEP_REVIEW_2026_09.md §1/§4) ─────
    # 'par' reproduces the legacy exact-level fill (regression anchor only).
    # 'honest' (default) books stops at min(stop, next-bar open) with
    # gap-through, and target/trail/time exits at next-bar open — the
    # most live-favorable realistic model. Ignored by the live runners,
    # which already fill this way via the broker.
    exit_fill_mode: str = 'honest'      # 'par' | 'honest'
    exit_slippage_pct: float = 0.3      # adverse slippage applied to 'honest' exit fills only

    def to_dict(self) -> dict:
        """Serialize to dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> 'ScalpConfig':
        """Construct from dict, ignoring unknown keys."""
        valid = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in valid})
