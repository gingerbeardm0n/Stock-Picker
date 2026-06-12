#!/usr/bin/env python3
"""
sim_replay.py — Run the VWAP simulator on the bars the LIVE session saw.

The decision-parity test: live runner and simulator share the same engine
modules (vwap_engine evaluate_entry/evaluate_exit), so given the same bars
and the same watchlist they should produce the SAME trade — same symbol,
same entry bar, same exit. Any difference is a code/orchestration parity bug
(data path, seeding, ordering), which is exactly what this tool surfaces.

Bar source priority:
  1. stock_candles_live_1m — the bars the live poller actually captured
     (true apples-to-apples; requires the post-session pull ran that day)
  2. --source timesales — Tradier production tape (fallback when the capture
     was lost, e.g. wiped by a redeploy; near-identical but not guaranteed
     bar-for-bar equal to what the poller delivered)

Usage:
    python sim_replay.py --date 2026-06-12 --watchlist AERT,ADTX,BYAH
    python sim_replay.py --date 2026-06-12 --watchlist AERT --source timesales
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

import argparse
from datetime import datetime

import pytz
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env.paper'))

ET = pytz.timezone('America/New_York')


def load_live_bars(symbols: list[str], day: str) -> dict[str, list[dict]]:
    """Bars from stock_candles_live_1m (what the live poller captured)."""
    import psycopg2
    dsn = os.getenv('DB_DSN') or os.getenv('OPTUNA_STORAGE')
    if not dsn:
        print('DB_DSN not set'); sys.exit(1)
    out: dict[str, list[dict]] = {s: [] for s in symbols}
    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT symbol, time, open, high, low, close, volume
            FROM stock_candles_live_1m
            WHERE symbol = ANY(%s) AND time::date = %s
            ORDER BY time
            """,
            (symbols, day),
        )
        for sym, t, o, h, l, c, v in cur.fetchall():
            out[sym].append({'time': t, 'open': float(o), 'high': float(h),
                             'low': float(l), 'close': float(c), 'volume': int(v)})
    return out


def load_timesales(symbols: list[str], day: str) -> dict[str, list[dict]]:
    """Fallback: real tape from Tradier production timesales."""
    import requests
    token = os.getenv('TRADIER_PRODUCTION_TOKEN', '')
    out: dict[str, list[dict]] = {}
    for sym in symbols:
        r = requests.get(
            'https://api.tradier.com/v1/markets/timesales',
            params={'symbol': sym, 'interval': '1min',
                    'start': f'{day}T09:30', 'end': f'{day}T13:00',
                    'session_filter': 'all'},
            headers={'Authorization': f'Bearer {token}', 'Accept': 'application/json'},
            timeout=30,
        )
        r.raise_for_status()
        series = r.json().get('series') or {}
        bars = []
        for b in series.get('data') or []:
            t = ET.localize(datetime.fromisoformat(b['time']))
            bars.append({'time': t, 'open': b['open'], 'high': b['high'],
                         'low': b['low'], 'close': b['close'], 'volume': b['volume']})
        out[sym] = bars
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', required=True)
    parser.add_argument('--watchlist', required=True,
                        help='Comma-separated symbols, in the LIVE ranking order')
    parser.add_argument('--source', choices=['capture', 'timesales'], default='capture')
    parser.add_argument('--account', type=float, default=100_000.0,
                        help='Account size for share sizing (match paper account)')
    args = parser.parse_args()

    symbols = [s.strip().upper() for s in args.watchlist.split(',')]

    from simulator.vwap_simulation import VwapSimulationRunner
    from trading.live_vwap_runner import TRIAL_173_CONFIG

    bars_data = (load_live_bars(symbols, args.date) if args.source == 'capture'
                 else load_timesales(symbols, args.date))
    for s in symbols:
        n = len(bars_data.get(s, []))
        print(f'  {s}: {n} bars ({args.source})')
        if n == 0 and args.source == 'capture':
            print('  -> empty capture; retry with --source timesales')

    runner = VwapSimulationRunner(args.date, config=TRIAL_173_CONFIG,
                                  account_size=args.account, verbose=True)

    # Same earliest-signal-across-watchlist selection as the simulator core
    best = None
    for rank_idx, sym in enumerate(symbols):
        cand = {'symbol': sym, 'gap_pct': 0, 'rel_vol': 0, 'news_tier': 'presence'}
        found = runner._find_first_signal(cand, bars_data.get(sym, []))
        if found is None:
            continue
        entry_et, market_bars, entry_idx, signal = found
        if best is None or (entry_et, rank_idx) < (best[0], best[1]):
            best = (entry_et, rank_idx, cand, market_bars, entry_idx, signal)

    print(f"\nSIM REPLAY {args.date} (config=trial 173, source={args.source})")
    print('-' * 60)
    if best is None:
        print('Simulator decision: NO TRADE (no reclaim signal on watchlist)')
        return

    _, _, cand, market_bars, entry_idx, signal = best
    result = runner._simulate_exit(cand, market_bars, entry_idx, signal, len(symbols))
    t = result['trade']
    print(f"Simulator decision:")
    print(f"  {t.symbol}  entry ${t.entry_price:.2f} @ {t.entry_time.strftime('%H:%M')} ET"
          f"  ({t.entry_reason})")
    print(f"  exit  ${t.exit_price:.2f}  {t.exit_type}  after {t.bars_held} bars")
    print(f"  P&L: ${t.pnl:+.2f} ({t.pnl_pct:+.1f}%) on {t.shares} shares")
    print(f"\nCompare against the live session log (entry bar/price/exit must match")
    print(f"when source=capture; small diffs under timesales = poller-vs-tape gaps).")


if __name__ == '__main__':
    main()
