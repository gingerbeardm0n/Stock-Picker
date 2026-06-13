#!/usr/bin/env python3
"""
Simulate Multiple Trading Days
================================

Runs simulations across a date range and aggregates results.

Usage:
    python simulator/simulate_date_range.py --start 2026-02-03 --end 2026-02-18
    python simulator/simulate_date_range.py --last-n 10  # Last 10 trading days
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from simulator.simulation_engine import SimulationRunner
from utils.trading_calendar import get_trading_days
from datetime import datetime, timedelta
import argparse
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


def get_trading_dates(start_date, end_date):
    """Get all NYSE trading dates in range using the authoritative market calendar."""
    return get_trading_days(start_date, end_date)


def run_simulation_range(start_date, end_date, account_size=5000, risk_pct=2.0):
    """Run simulations across date range and aggregate results"""
    trading_dates = get_trading_dates(start_date, end_date)

    if not trading_dates:
        logger.error("No trading dates found in range")
        return None

    logger.info(f"\n{'='*80}")
    logger.info(f"  MULTI-DAY SIMULATION: {start_date} to {end_date}")
    logger.info(f"  Account: ${account_size:,.0f} | Risk/trade: {risk_pct}%")
    logger.info(f"  Trading days: {len(trading_dates)}")
    logger.info(f"{'='*80}\n")

    # Run simulations
    all_results = []
    for date in trading_dates:
        runner = SimulationRunner(
            date=date,
            account_size=account_size,
            risk_pct=risk_pct,
            verbose=False
        )

        if runner.run():
            stats = runner.position_manager.get_stats()
            pnl = runner.position_manager.current_balance - runner.account_size
            ps = runner.portfolio_summary or {}
            all_results.append({
                'date': date,
                'pnl': pnl,
                'balance': runner.position_manager.current_balance,
                'trades': stats['total_trades'],
                'win_rate': stats['win_rate'],
                'best_trade': stats['best_trade'],
                'worst_trade': stats['worst_trade'],
                'portfolio_summary': ps,
                'runner': runner
            })
            # Show portfolio rule flags inline (F=fired on this day)
            ps_flags = ''
            if ps.get('rules'):
                flags = []
                for abbrev, rule in [('ML', 'DAILY_MAX_LOSS'), ('GR', 'GREEN_TO_RED'), ('GH', 'GIVE_BACK_HALF')]:
                    if ps['rules'].get(rule, {}).get('fired'):
                        flags.append(abbrev)
                if flags:
                    ps_flags = f" [{','.join(flags)}]"
            logger.info(f"  {date} | P&L: ${pnl:>8,.0f} | "
                       f"Trades: {stats['total_trades']:2} | "
                       f"Win: {stats['win_rate']:5.1f}%{ps_flags}")
        else:
            logger.warning(f"  {date} | No data")

    if not all_results:
        logger.error("No simulations completed")
        return None

    # Aggregate statistics
    logger.info(f"\n{'='*80}\n")

    total_pnl = sum(r['pnl'] for r in all_results)
    total_trades = sum(r['trades'] for r in all_results)
    avg_win_rate = sum(r['win_rate'] for r in all_results) / len(all_results) if all_results else 0
    winning_days = sum(1 for r in all_results if r['pnl'] > 0)
    losing_days = sum(1 for r in all_results if r['pnl'] < 0)
    flat_days = sum(1 for r in all_results if r['pnl'] == 0)
    best_day_pnl = max(r['pnl'] for r in all_results)
    worst_day_pnl = min(r['pnl'] for r in all_results)

    logger.info(f"AGGREGATE RESULTS")
    logger.info(f"{'='*80}\n")

    logger.info(f"Days Simulated:    {len(all_results)}")
    logger.info(f"  Winning days:    {winning_days}")
    logger.info(f"  Losing days:     {losing_days}")
    logger.info(f"  Flat days:       {flat_days}\n")

    logger.info(f"Total P&L:         ${total_pnl:>12,.0f}")
    pct = (total_pnl / (account_size * len(all_results)) * 100) if account_size else 0
    logger.info(f"Avg P&L/day:       ${total_pnl / len(all_results):>12,.0f}")
    logger.info(f"Best day:          ${best_day_pnl:>12,.0f}")
    logger.info(f"Worst day:         ${worst_day_pnl:>12,.0f}\n")

    logger.info(f"Total Trades:      {total_trades:>12}")
    logger.info(f"Avg trades/day:    {total_trades / len(all_results):>12.1f}")
    logger.info(f"Avg Win Rate:      {avg_win_rate:>12.1f}%\n")

    logger.info(f"Win Rate Above 50%: {sum(1 for r in all_results if r['win_rate'] >= 50)}/{len(all_results)} days")

    # ── Portfolio Rule Analysis (counterfactual aggregate) ─────────────────
    rule_configs = [
        ('DAILY_MAX_LOSS', 'Daily Max Loss  '),
        ('GREEN_TO_RED',   'Green-to-Red    '),
        ('GIVE_BACK_HALF', 'Give-Back-Half  '),
    ]
    logger.info(f"\n{'─'*60}")
    logger.info(f"Portfolio Rule Analysis (would-have-fired, NOT enforced):")
    logger.info(f"  Legend: days_fired / total | +$saved means rule would have helped\n")

    for rule, label in rule_configs:
        days_fired = 0
        total_saved = 0.0
        saved_days = 0
        cost_days = 0

        for r in all_results:
            ps = r.get('portfolio_summary', {})
            rule_info = ps.get('rules', {}).get(rule, {})
            if rule_info.get('fired'):
                days_fired += 1
                sc = rule_info.get('saved_or_cost', 0.0)
                total_saved += sc
                if sc > 1.0:
                    saved_days += 1
                elif sc < -1.0:
                    cost_days += 1

        if days_fired == 0:
            logger.info(f"  {label}  Never fired")
        else:
            verdict = 'NET SAVE' if total_saved > 0 else 'NET COST'
            logger.info(
                f"  {label}  {days_fired}/{len(all_results)} days | "
                f"Saved {saved_days}d / Cost {cost_days}d | "
                f"{verdict} ${abs(total_saved):.2f} total"
            )

    logger.info(f"\n{'='*80}\n")

    return all_results


def main():
    parser = argparse.ArgumentParser(
        description='Simulate multiple trading days'
    )
    parser.add_argument('--start', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', type=str, help='End date (YYYY-MM-DD)')
    parser.add_argument('--last-n', type=int, help='Last N trading days')
    parser.add_argument('--account', type=float, default=5000, help='Starting account')
    parser.add_argument('--risk', type=float, default=2.0, help='Risk per trade (%)')

    args = parser.parse_args()

    # Determine date range
    if args.last_n:
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=args.last_n * 7 // 5)  # Rough estimate
    elif args.start and args.end:
        start_date = datetime.strptime(args.start, '%Y-%m-%d').date()
        end_date = datetime.strptime(args.end, '%Y-%m-%d').date()
    else:
        # Default: last 2 weeks
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=14)

    # Run simulations
    results = run_simulation_range(
        start_date=start_date,
        end_date=end_date,
        account_size=args.account,
        risk_pct=args.risk
    )


if __name__ == '__main__':
    main()
