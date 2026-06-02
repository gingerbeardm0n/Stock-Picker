"""
simulate_one.py — Run a full date-range simulation with a given RunConfig.

Returns a metrics dict and list of per-trade dicts suitable for writing to
the results DB. This is the core function called by sweep.py and optuna_run.py.

Usage (direct):
    from optimizer.run_config import RunConfig
    from optimizer.simulate_one import run_date_range

    result = run_date_range(RunConfig.defaults(), '2026-02-03', '2026-02-18')
    print(f"Profit Factor: {result['profit_factor']:.2f}")
"""

from __future__ import annotations
import sys
import os
# Add both research/ and production/ to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))  # research/
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../production')))  # production/

import time
from datetime import datetime

from optimizer.run_config import RunConfig
from optimizer.objective_functions import compute_objective
from simulator.simulation_engine import SimulationRunner
from utils.trading_calendar import get_trading_days


def run_date_range(
    config: RunConfig,
    start_date: str,
    end_date: str,
    verbose: bool = False,
    debug: bool = False,
    cache_data: bool = False,
    cache_dir: str | None = None,
    on_day_complete=None,
    symbol_universe: list | dict | None = None,
    print_dates: bool = False,
    early_abort_days: int = 0,
    dates: list | None = None,
) -> dict:
    """
    Run a simulation over a date range using the given RunConfig.

    dates: optional explicit list of trading days (str 'YYYY-MM-DD' or date objects).
           When provided, it OVERRIDES the contiguous get_trading_days(start, end)
           range — the simulation runs ONLY these days, in the given order.
           start_date/end_date are then used only as metadata labels (results DB).
           This powers the oracle test, which runs a config over a scattered
           subset of days that share one market-temperature label.

    symbol_universe accepts two formats:
      - list[str]        : flat symbol list, same for every day (legacy)
      - dict[str, list]  : date-specific {date_str: [symbols]} mapping;
                           each day only sees its own qualifying stocks
      - None             : scanner mode (dynamic discovery from DB)

    Returns a metrics dict:
        total_trades    int
        winners         int
        losers          int
        win_rate        float (%)
        profit_factor   float
        total_pnl       float ($)
        avg_daily_pnl   float ($)
        max_drawdown    float ($, peak-to-trough on cumulative P&L)
        days_traded     int
        objective       float (profit_factor − 0.25 × drawdown_pct)
        trades          list[dict] — per-trade detail rows for results_db

    On failure (no data for any day), returns a metrics dict with all zeros
    and objective = -999.0 so Optuna treats it as a bad trial.
    """
    if dates is not None:
        # Explicit day-subset mode (oracle test). Accept str or date objects.
        trading_days = [
            d if not isinstance(d, str) else datetime.strptime(d, '%Y-%m-%d').date()
            for d in dates
        ]
    else:
        start = datetime.strptime(start_date, '%Y-%m-%d').date()
        end   = datetime.strptime(end_date,   '%Y-%m-%d').date()
        trading_days = get_trading_days(start, end)

    all_trades: list[dict] = []
    all_daily_pnls: list[float] = []
    total_winners = 0
    total_losers  = 0
    n_days = len(trading_days)
    _days_with_data = 0   # successful SimulationRunner days (for early-abort denominator)

    for day_idx, day in enumerate(trading_days, 1):
        # Resolve per-day symbol list when universe is date-specific dict
        if isinstance(symbol_universe, dict):
            day_symbols = symbol_universe.get(str(day), [])
        else:
            day_symbols = symbol_universe  # flat list or None

        if verbose or print_dates:
            print(f"  [{day_idx}/{n_days}] {day} starting...", flush=True)
        _day_t0 = time.perf_counter()

        runner = SimulationRunner(
            date=day,
            account_size=config.account_size,
            risk_pct=config.risk_pct,
            max_position_pct=config.max_position_pct,
            verbose=verbose,
            exit_config=config.exit_,
            scanner_config=config.scanner,
            entry_config=config.entry,
            add_on_config=getattr(config, 'add_on', None),
            scoring_config=getattr(config, 'scoring', None),
            momentum_config=getattr(config, 'momentum', None),
            temp_config=getattr(config, 'temperature', None),
            debug=debug,
            cache_data=cache_data,
            cache_dir=cache_dir,
            symbol_universe=day_symbols,
            # News cache disabled in optimizer runs: adds ~30s/day of API latency.
            # Re-enable with enable_news_cache=True once news tiers are pre-cached
            # to disk (future work: daily news cache files per hot_symbol).
            enable_news_cache=False,
        )

        success = runner.run()
        _day_elapsed = time.perf_counter() - _day_t0
        if on_day_complete is not None:
            on_day_complete(str(day))
        if verbose or print_dates:
            print(f"  [{day_idx}/{n_days}] {day} done ({_day_elapsed:.1f}s)", flush=True)
        if not success:
            continue

        _days_with_data += 1

        # Early-abort: dead config check.
        # If early_abort_days > 0 and we've run at least that many data-days
        # without a single trade, this config is almost certainly too restrictive.
        # Return empty metrics now instead of burning the remaining days.
        if early_abort_days > 0 and _days_with_data >= early_abort_days and len(all_trades) == 0:
            return _empty_metrics()

        stats = runner.position_manager.get_stats()
        daily_pnl = runner.position_manager.current_balance - config.account_size
        all_daily_pnls.append(daily_pnl)
        total_winners += stats['winners']
        total_losers  += stats['losers']

        for t in runner.position_manager.trades_completed:
            all_trades.append({
                'date':        str(day),
                'symbol':      t.symbol,
                'pattern':     t.pattern_type,
                'entry_price': round(t.entry_price, 4),
                'exit_price':  round(t.exit_price or t.entry_price, 4),
                'shares':      t.shares,
                'pnl':         round(t.get_pnl(), 2),
                'exit_reason': t.exit_reason or 'OPEN',
                'hold_minutes': t.get_exit_time_minutes(),
            })

    # ── Aggregate ──────────────────────────────────────────────────────────────
    total_trades = total_winners + total_losers
    if total_trades == 0:
        return _empty_metrics()

    total_pnl    = sum(t['pnl'] for t in all_trades)
    total_wins   = sum(t['pnl'] for t in all_trades if t['pnl'] > 0)
    total_losses = abs(sum(t['pnl'] for t in all_trades if t['pnl'] < 0))

    win_rate      = total_winners / total_trades * 100
    profit_factor = total_wins / total_losses if total_losses > 0 else 0.0
    avg_daily_pnl = sum(all_daily_pnls) / len(all_daily_pnls) if all_daily_pnls else 0.0
    max_drawdown  = _compute_max_drawdown([t['pnl'] for t in all_trades])

    # Objective: robustness-adjusted ('consistency'). Rewards green-day frequency
    # and payoff ratio, penalizes drawdown, shrinks on thin trade/day samples — and
    # does NOT amputate the right tail (downside-only risk via the green-rate factor).
    # Replaces raw total_pnl, which rewarded the tiny-win / one-lucky-day regime.
    # Raw total_pnl is still reported below for comparison.
    # See research/optimizer/objective_functions.py + memory/optimizer_objective_fix.md.
    objective = compute_objective(
        formula='consistency',
        total_pnl=total_pnl,
        max_drawdown=max_drawdown,
        trade_pnls=[t['pnl'] for t in all_trades],
        daily_pnls=all_daily_pnls,
    )

    return {
        'total_trades':  total_trades,
        'winners':       total_winners,
        'losers':        total_losers,
        'win_rate':      win_rate,
        'profit_factor': profit_factor,
        'total_pnl':     total_pnl,
        'avg_daily_pnl': avg_daily_pnl,
        'max_drawdown':  max_drawdown,
        'days_traded':   len(all_daily_pnls),
        'objective':     objective,
        'trades':        all_trades,
    }


# ── Helpers ────────────────────────────────────────────────────────────────────

def _compute_max_drawdown(pnls: list[float]) -> float:
    """Peak-to-trough drawdown on the cumulative P&L series."""
    if not pnls:
        return 0.0
    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        cum += p
        if cum > peak:
            peak = cum
        dd = peak - cum
        if dd > max_dd:
            max_dd = dd
    return max_dd


def _empty_metrics() -> dict:
    return {
        'total_trades':  0,
        'winners':       0,
        'losers':        0,
        'win_rate':      0.0,
        'profit_factor': 0.0,
        'total_pnl':     0.0,
        'avg_daily_pnl': 0.0,
        'max_drawdown':  0.0,
        'days_traded':   0,
        'objective':     -999.0,
        'trades':        [],
    }
