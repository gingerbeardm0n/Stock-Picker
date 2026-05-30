"""
Position sizing — the single source of truth for "how many shares".

Extracted verbatim from PositionManager.enter_position so that BOTH the simulated
broker and the live broker size positions identically (closing live-sim gap #5 in
docs/LIVE_SIM_PARITY_SPEC.md). No behavior change vs the old inline logic — proven by
test_sizing.py, which compares this against a frozen copy of the original math.

Pure function: no I/O, no state. Inputs in, share count out.
"""

from __future__ import annotations

# GAP-11: float-bucket hard caps on position dollar value.
# Source: concept_position_sizing.md §3 + concept_float_analysis.md.
# Ascending by float — loop breaks on first match. Scanner blocks float > 20M.
FLOAT_BUCKET_CAPS: list[tuple[int, float]] = [
    (1_000_000,  5_000.0),   # sub-1M float  → $5K cap
    (3_000_000, 15_000.0),   # 1M–3M float   → $15K cap
    (10_000_000, 8_000.0),   # 3M–10M float  → $8K cap
    (20_000_000, 5_000.0),   # 10M–20M float → $5K cap
]


def compute_shares(
    *,
    entry_price: float,
    stop_loss_price: float,
    current_balance: float,
    risk_pct: float,
    max_position_pct: float,
    float_shares: int | None = None,
    size_multiplier: float = 1.0,
    had_loss_today: bool = False,
) -> int:
    """Return the share count to buy (0 = do not enter).

    Rules (identical to the original PositionManager.enter_position):
      1. Risk-based: risk `risk_pct`% of balance over the stop distance.
      2. Cap at `max_position_pct`% of balance, further capped by the float bucket.
      3. Multiply by GAP-16 (0.5x if a loss already happened today) × size_multiplier
         (carries GAP-14 cooldown / score / cushion scaling).
      4. Never exceed cash on hand.
    """
    stop_distance = entry_price - stop_loss_price
    if stop_distance <= 0:
        return 0

    gap16_mult = 0.5 if had_loss_today else 1.0
    total_mult = gap16_mult * size_multiplier

    risk_per_trade = current_balance * (risk_pct / 100.0)
    risk_based_shares = int(risk_per_trade / stop_distance)

    max_position_value = current_balance * (max_position_pct / 100.0)
    if float_shares is not None:
        for bucket_float, cap_dollars in FLOAT_BUCKET_CAPS:
            if float_shares < bucket_float:
                max_position_value = min(max_position_value, cap_dollars)
                break

    max_position_shares = int(max_position_value / entry_price)

    shares = int(min(risk_based_shares, max_position_shares) * total_mult)
    if shares <= 0:
        return 0

    if shares * entry_price > current_balance:
        shares = int(current_balance / entry_price * total_mult)
        if shares <= 0:
            return 0

    return shares


def cushion_size_multiplier(daily_pnl: float, daily_goal: float) -> float:
    """
    Cushion-anchored position size modifier (moved from simulation_engine in the
    de-logic refactor — pure sizing logic the orchestrator needs).
    Source: concept_position_sizing.md — Ross scales size by earned daily-P&L cushion.

    in-drawdown  (daily_pnl < 0):              0.50x — protect from further losses
    no-cushion   (daily_pnl < 50% of goal):    0.75x — cautious, building cushion
    cushion-ok   (daily_pnl >= 50% of goal):   1.00x — cushion established, full size

    Capped at 1.0 (temperature + score already scale up); daily_goal <= 0 returns 1.0.
    """
    if daily_pnl < 0:
        return 0.50
    if daily_goal <= 0:
        return 1.00
    cushion_pct = daily_pnl / daily_goal
    if cushion_pct < 0.50:
        return 0.75
    return 1.00
