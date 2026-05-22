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

from datetime import datetime

from optimizer.run_config import RunConfig
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
) -> dict:
    """
    Run a simulation over a date range using the given RunConfig.

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
    start = datetime.strptime(start_date, '%Y-%m-%d').date()
    end   = datetime.strptime(end_date,   '%Y-%m-%d').date()
    trading_days = get_trading_days(start, end)

    all_trades: list[dict] = []
    all_daily_pnls: list[float] = []
    total_winners = 0
    total_losers  = 0

    for day in trading_days:
        # Resolve per-day symbol list when universe is date-specific dict
        if isinstance(symbol_universe, dict):
            day_symbols = symbol_universe.get(str(day), [])
        else:
            day_symbols = symbol_universe  # flat list or None

        runner = SimulationRunner(
            date=day,
            account_size=config.account_size,
            risk_pct=config.risk_pct,
            max_position_pct=config.max_position_pct,
            verbose=verbose,
            exit_config=config.exit_,
            scanner_config=config.scanner,
            entry_config=config.entry,
            scoring_config=getattr(config, 'scoring', None),
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
        if on_day_complete is not None:
            on_day_complete()
        if not success:
            continue

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

    # Objective: total P&L in dollars (account-size-agnostic, easy to read)
    objective = total_pnl

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
