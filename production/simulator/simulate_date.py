#!/usr/bin/env python3
"""
Simulate Historical Trading Day
================================

Runs minute-by-minute simulation of trading logic against historical data
for a specific date.

Usage:
    python simulator/simulate_date.py                    # Interactive
    python simulator/simulate_date.py --date 2026-02-13  # Specific date
    python simulator/simulate_date.py --account 10000 --risk 1.5  # Custom settings
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from simulator.simulation_engine import SimulationRunner
from datetime import datetime, timedelta
import argparse


def interactive_mode():
    """Prompt user for simulation parameters"""
    print("\n" + "="*80)
    print("  STOCK SCANNER SIMULATION ENGINE")
    print("="*80 + "\n")

    # Get date
    while True:
        date_input = input("Enter date (YYYY-MM-DD) or 'last' for yesterday: ").strip()
        if date_input.lower() == 'last':
            date = (datetime.now() - timedelta(days=1)).date()
            print(f"Using yesterday: {date}\n")
            break
        try:
            date = datetime.strptime(date_input, '%Y-%m-%d').date()
            print(f"Using date: {date}\n")
            break
        except ValueError:
            print("Invalid date format. Try again.\n")

    # Get account size
    while True:
        try:
            account = float(input("Starting account size [$5,000]: ").strip() or "5000")
            if account <= 0:
                print("Account must be > 0. Try again.\n")
                continue
            print(f"Using account: ${account:,.0f}\n")
            break
        except ValueError:
            print("Invalid amount. Try again.\n")

    # Get risk per trade
    while True:
        try:
            risk = float(input("Risk per trade as % of account [2.0]: ").strip() or "2.0")
            if risk <= 0 or risk > 10:
                print("Risk should be 0-10%. Try again.\n")
                continue
            print(f"Using risk: {risk}%\n")
            break
        except ValueError:
            print("Invalid amount. Try again.\n")

    return date, account, risk


def run_simulation(date, account, risk, verbose=True):
    """Run the simulation"""
    runner = SimulationRunner(
        date=date,
        account_size=account,
        risk_pct=risk,
        verbose=verbose
    )

    success = runner.run()
    if success:
        runner.print_report()
    else:
        print(f"\nSimulation failed for {date}")
        print("(No data available or error loading bars)")

    return runner


def main():
    parser = argparse.ArgumentParser(
        description='Simulate historical trading day'
    )
    parser.add_argument('--date', type=str, help='Date (YYYY-MM-DD)')
    parser.add_argument('--account', type=float, default=5000, help='Starting account size')
    parser.add_argument('--risk', type=float, default=2.0, help='Risk per trade (percent)')
    parser.add_argument('--quiet', action='store_true', help='Suppress detailed output')

    args = parser.parse_args()

    # Get parameters
    if args.date:
        try:
            date = datetime.strptime(args.date, '%Y-%m-%d').date()
        except ValueError:
            print(f"Invalid date: {args.date}")
            sys.exit(1)
    else:
        # Interactive mode
        date, account, risk = interactive_mode()
        args.account = account
        args.risk = risk

    # Run simulation
    runner = run_simulation(
        date=date,
        account=args.account,
        risk=args.risk,
        verbose=not args.quiet
    )


if __name__ == '__main__':
    main()
