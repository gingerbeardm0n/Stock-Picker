"""
objective_functions.py — selectable Optuna objective formulas (NOT yet wired).

Background: `simulate_one.py` currently hardcodes `objective = total_pnl`, which
rewards the tiny-win / amputated-tail / outlier-dependent regime (see
`memory/optimizer_objective_fix.md`). Two replacement formulas were proposed by two
parallel agents and the choice is NOT settled. This module implements BOTH (plus the
status-quo and a hybrid) behind one selector so the decision can be made with data,
then wired into `run_date_range` with a single call — without rewriting anything now.

NOTHING in this module changes the live optimizer default. `simulate_one.py` is
untouched. To adopt later, replace `objective = total_pnl` with:

    from optimizer.objective_functions import compute_objective
    objective = compute_objective(
        formula='payoff_ratio',          # or 'drop_best_day' / 'hybrid' / 'total_pnl'
        total_pnl=total_pnl,
        max_drawdown=max_drawdown,
        trade_pnls=[t['pnl'] for t in all_trades],
        daily_pnls=all_daily_pnls,
    )

All formulas keep raw `total_pnl` available separately for reporting.
"""

from __future__ import annotations
import math
from dataclasses import dataclass

FORMULAS = ('total_pnl', 'drop_best_day', 'payoff_ratio', 'hybrid', 'consistency')


@dataclass
class ObjectiveParams:
    """Tunable constants for the non-trivial formulas."""
    dd_penalty: float = 0.5        # objective $ removed per $ of peak-to-trough drawdown
    min_trades: int = 30           # below this, shrink objective linearly (small-sample guard)
    target_payoff: float = 1.2     # payoff_ratio at/above which payoff_factor saturates at 1.0
    concentration_cap: float = 0.5 # hybrid: penalize when best_day/total_pnl exceeds this
    min_days: int = 5              # 'consistency': below this many days, shrink (thin sample)
    green_floor: float = 0.0       # 'consistency': green_rate below this zeroes the bonus
    variance_penalty_k: float = 1.0  # 'consistency': subtract k * stdev(daily_pnls) from final
                                     # score. Penalises wild day-to-day swings even when total P&L
                                     # looks good (e.g. one $500 day + many -$5 days).  Set to 0
                                     # to disable.


# ── Helpers ─────────────────────────────────────────────────────────────────────

def payoff_ratio(trade_pnls: list[float]) -> float:
    """avg_win / avg_loss. Returns a high sentinel (10.0) when there are no losers
    (can't divide), 0.0 when there are no winners."""
    wins = [p for p in trade_pnls if p > 0]
    losses = [abs(p) for p in trade_pnls if p < 0]
    if not wins:
        return 0.0
    if not losses:
        return 10.0  # all winners — cap rather than divide by zero
    avg_win = sum(wins) / len(wins)
    avg_loss = sum(losses) / len(losses)
    if avg_loss <= 0:
        return 10.0
    return avg_win / avg_loss


def _sample_factor(n_trades: int, min_trades: int) -> float:
    if min_trades <= 0:
        return 1.0
    return min(1.0, n_trades / min_trades)


def green_day_rate(daily_pnls: list[float]) -> float:
    """Fraction of days that were net positive. 0..1. Direct consistency signal."""
    if not daily_pnls:
        return 0.0
    return sum(1 for d in daily_pnls if d > 0) / len(daily_pnls)


def daily_std_dev(daily_pnls: list[float]) -> float:
    """Sample standard deviation of daily P&Ls (ddof=1). Returns 0 if < 2 data points."""
    n = len(daily_pnls)
    if n < 2:
        return 0.0
    mean = sum(daily_pnls) / n
    return math.sqrt(sum((d - mean) ** 2 for d in daily_pnls) / (n - 1))


def downside_deviation(daily_pnls: list[float]) -> float:
    """Root-mean-square of the negative daily P&Ls (Sortino denominator). Only
    penalizes downside volatility — big up days are NOT punished (keeps the tail)."""
    if not daily_pnls:
        return 0.0
    sq = [min(0.0, d) ** 2 for d in daily_pnls]
    return math.sqrt(sum(sq) / len(daily_pnls))


def sortino(daily_pnls: list[float]) -> float:
    """mean(daily) / downside_deviation. High sentinel when no down days."""
    if not daily_pnls:
        return 0.0
    dd = downside_deviation(daily_pnls)
    mean = sum(daily_pnls) / len(daily_pnls)
    if dd <= 0:
        return 10.0 if mean > 0 else 0.0
    return mean / dd


# ── The selector ─────────────────────────────────────────────────────────────────

def compute_objective(
    *,
    formula: str = 'total_pnl',
    total_pnl: float,
    max_drawdown: float = 0.0,
    trade_pnls: list[float] | None = None,
    daily_pnls: list[float] | None = None,
    params: ObjectiveParams | None = None,
    min_trades_override: int | None = None,
) -> float:
    """Compute an Optuna objective from run metrics.

    formula:
      'total_pnl'     — status quo: raw dollar sum (the mis-specified baseline).
      'drop_best_day' — defb69cc proposal: (total_pnl - max(daily)) - dd_penalty*dd,
                        then small-sample shrink. Strongest anti-outlier lever, but
                        suppresses the right tail the corpus says is the real edge.
      'payoff_ratio'  — elated-euclid proposal: (total_pnl - dd_penalty*dd) scaled by
                        payoff_factor (avg_win/avg_loss vs target) and sample_factor.
                        Kills the tiny-win regime WITHOUT amputating the tail.
      'hybrid'        — payoff_ratio PLUS a concentration guard: only subtract the
                        best day when it dominates (best_day/total_pnl > cap). Catches
                        "profitable only on one lucky day" while passing a fat
                        DISTRIBUTED tail.

    min_trades_override: per-regime floor for the oracle test (thin regimes would be
                         unfairly crushed by the global default). None = use params.min_trades.
    """
    if formula not in FORMULAS:
        raise ValueError(f"formula must be one of {FORMULAS}, got {formula!r}")

    p = params or ObjectiveParams()
    trade_pnls = trade_pnls or []
    daily_pnls = daily_pnls or []
    n_trades = len(trade_pnls)
    min_trades = min_trades_override if min_trades_override is not None else p.min_trades

    if formula == 'total_pnl':
        return total_pnl

    if formula == 'drop_best_day':
        best_day = max(daily_pnls) if daily_pnls else 0.0
        robust = total_pnl - best_day
        obj = robust - p.dd_penalty * max_drawdown
        return obj * _sample_factor(n_trades, min_trades)

    if formula == 'payoff_ratio':
        pf = payoff_ratio(trade_pnls)
        payoff_factor = min(1.0, pf / p.target_payoff) if p.target_payoff > 0 else 1.0
        base = total_pnl - p.dd_penalty * max_drawdown
        # Only scale DOWN a positive base; scaling a negative base by <1 would
        # perversely make a bad config look better, so clamp factor=1 when base<0.
        factor = payoff_factor if base > 0 else 1.0
        return base * factor * _sample_factor(n_trades, min_trades)

    if formula == 'hybrid':
        pf = payoff_ratio(trade_pnls)
        payoff_factor = min(1.0, pf / p.target_payoff) if p.target_payoff > 0 else 1.0
        best_day = max(daily_pnls) if daily_pnls else 0.0
        concentration = (best_day / total_pnl) if total_pnl > 0 else 0.0
        concentrated = concentration > p.concentration_cap
        base = total_pnl - (best_day if concentrated else 0.0) - p.dd_penalty * max_drawdown
        factor = payoff_factor if base > 0 else 1.0
        return base * factor * _sample_factor(n_trades, min_trades)

    # consistency: reward low-variance, broadly-profitable configs.
    # base (dd-penalized $) scaled by green-day rate, payoff floor, and sample size.
    # Keeps the right tail (uses downside-only risk via the green-rate multiplier,
    # never subtracts up days). green_rate is the primary consistency lever.
    # variance_penalty_k * stdev(daily_pnls) is subtracted from the final score:
    # penalises configs that win big on a few days and chop/lose the rest, even if
    # total P&L is positive (e.g. +$500 on day 1, -$5 every other day).
    pf = payoff_ratio(trade_pnls)
    payoff_factor = min(1.0, pf / p.target_payoff) if p.target_payoff > 0 else 1.0
    gr = green_day_rate(daily_pnls)
    green_factor = gr if gr >= p.green_floor else 0.0
    base = total_pnl - p.dd_penalty * max_drawdown
    factor = (green_factor * payoff_factor) if base > 0 else 1.0
    days_factor = _sample_factor(len(daily_pnls), p.min_days)
    score = base * factor * _sample_factor(n_trades, min_trades) * days_factor
    if p.variance_penalty_k > 0:
        score -= p.variance_penalty_k * daily_std_dev(daily_pnls)
    return score


# ── Evaluation scheme: worst-fold / walk-forward ─────────────────────────────────

def worst_fold_objective(
    fold_metrics: list[dict],
    *,
    formula: str = 'consistency',
    params: ObjectiveParams | None = None,
    min_trades_override: int | None = None,
) -> float:
    """Score the WORST of k folds rather than the aggregate.

    The single strongest anti-overfit / pro-consistency lever: a config cannot win
    by being great in one regime and terrible in another — it is judged by its
    weakest fold. Each item in `fold_metrics` is a metrics dict with keys
    total_pnl, max_drawdown, trade_pnls, daily_pnls (a fold = a date sub-range or
    a regime). Returns min over folds of compute_objective(fold). Empty → -999.
    """
    if not fold_metrics:
        return -999.0
    scores = [
        compute_objective(
            formula=formula,
            total_pnl=m.get('total_pnl', 0.0),
            max_drawdown=m.get('max_drawdown', 0.0),
            trade_pnls=m.get('trade_pnls', []),
            daily_pnls=m.get('daily_pnls', []),
            params=params,
            min_trades_override=min_trades_override,
        )
        for m in fold_metrics
    ]
    return min(scores)
