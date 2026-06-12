#!/usr/bin/env python3
"""
session_report.py — Daily post-session report: paper P&L vs live-counterfactual P&L.

The Tradier sandbox fills paper orders against a 15-min-delayed quote engine,
so paper fill prices are noisy. This report measures that distortion daily:

  1. Pull the session's decision events from the dashboard /logs endpoint
     (entry decisions with price/shares, fills, exit summaries).
  2. Fetch the real 1-min tape for each traded symbol from Tradier production
     timesales (independent of the bar-capture file, which dies on redeploy).
  3. Replay each trade counterfactually: assume the entry filled instantly at
     the DECISION price (live behavior), then walk the real bars through the
     same exit logic (vwap_engine / scalp_engine evaluate_exit) used live.
  4. Print paper vs counterfactual side by side.

Also (if DB_DSN is set) pulls /bars_dump into stock_candles_live_1m first, so
running this IS the end-of-session routine. Run BEFORE any evening deploy —
a Render redeploy wipes the day's capture file.

Usage:
    JTRADER_API_KEY=... DB_DSN=... python production/data/live_capture/session_report.py
    python session_report.py --date 2026-06-12   (tape replay only, no pull)
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

import argparse
import re
from datetime import datetime, date

import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env.paper'))

DASHBOARD = os.getenv('JTRADER_DASHBOARD_URL', 'https://jtrader-api.onrender.com')
API_KEY = os.getenv('JTRADER_API_KEY', '')
PROD_TOKEN = os.getenv('TRADIER_PRODUCTION_TOKEN', '')


# ── Log parsing ─────────────────────────────────────────────────────────────

ENTRY_RE = re.compile(r'>>> ENTRY: (\d+) shares of (\w+) @ \$([\d.]+)')
REASON_RE = re.compile(r'Reason: (\S+)')
FILLED_RE = re.compile(r'FILLED: (\d+) @ \$([\d.]+)')
EXIT_SUMMARY_KEYS = ('Exit:', 'P&L:', 'Bars held:', 'Reason:')


def fetch_logs(count: int = 400) -> list[dict]:
    r = requests.get(f'{DASHBOARD}/logs', params={'count': count},
                     headers={'X-API-Key': API_KEY}, timeout=30)
    r.raise_for_status()
    return r.json()['logs']


def parse_trades(logs: list[dict]) -> list[dict]:
    """
    Walk the session log and extract trade lifecycles:
    decision (ENTRY line price = decision price), paper fill, paper exit.
    Strategy attribution: ENTRY lines before 'VWAP RECLAIM SESSION STARTING'
    belong to the scalp, after it to the vwap runner.
    """
    trades = []
    current = None
    strategy = 'scalp'
    for entry in logs:
        msg = entry['msg']
        if 'VWAP RECLAIM SESSION STARTING' in msg:
            strategy = 'vwap'
        m = ENTRY_RE.search(msg)
        if m:
            current = {
                'strategy': strategy,
                'symbol': m.group(2),
                'shares': int(m.group(1)),
                'decision_price': float(m.group(3)),
                'decision_time': entry['t'],
                'paper_fill': None,
                'paper_exit': None,
                'paper_pnl': None,
                'exit_reason': None,
            }
            trades.append(current)
            continue
        if current is None:
            continue
        m = FILLED_RE.search(msg)
        if m and current['paper_fill'] is None:
            current['paper_fill'] = float(m.group(2))
            current['shares'] = int(m.group(1))
            continue
        if 'Exit:' in msg:
            pm = re.search(r'\$([\d.]+)', msg)
            if pm:
                current['paper_exit'] = float(pm.group(1))
        elif 'P&L:' in msg:
            pm = re.search(r'\$([+-][\d,.]+)', msg)
            if pm:
                current['paper_pnl'] = float(pm.group(1).replace(',', ''))
        elif 'Reason:' in msg and current['paper_exit'] is not None:
            current['exit_reason'] = msg.split('Reason:')[1].strip()
            current = None  # trade closed
    return trades


# ── Real tape ───────────────────────────────────────────────────────────────

def fetch_tape(symbol: str, day: str) -> list[dict]:
    r = requests.get(
        'https://api.tradier.com/v1/markets/timesales',
        params={'symbol': symbol, 'interval': '1min',
                'start': f'{day}T09:30', 'end': f'{day}T16:00',
                'session_filter': 'all'},
        headers={'Authorization': f'Bearer {PROD_TOKEN}', 'Accept': 'application/json'},
        timeout=30,
    )
    r.raise_for_status()
    series = r.json().get('series')
    if not series or not series.get('data'):
        return []
    return series['data']


# ── Counterfactual replay ───────────────────────────────────────────────────

def replay_counterfactual(trade: dict, tape: list[dict]) -> dict | None:
    """
    Assume entry filled instantly at the decision price on the decision bar,
    then run the strategy's own evaluate_exit over the real subsequent bars.
    """
    if trade['strategy'] == 'vwap':
        from trading.vwap_engine import evaluate_exit
        from trading.live_vwap_runner import TRIAL_173_CONFIG as cfg
        # VWAP-anchored stop: reconstruct from decision price the same way the
        # runner did (it logged stop = VWAP - offset; approximate VWAP from the
        # decision log is overkill — use decision_price-relative replay with
        # the stop the runner actually used if parsable, else VWAP unavailable)
    else:
        from trading.scalp_engine import evaluate_exit
        from trading.live_scalp_runner import TRIAL_173_CONFIG as cfg

    entry_price = trade['decision_price']
    # Find the decision bar in the tape: first bar at/after decision minute
    # is approximated by price match window; simpler: first bar whose minute
    # close equals/brackets the decision price is fragile — instead start the
    # replay at the first bar AFTER the decision wall-time minus engine delay.
    # The decision log time is wall UTC; engine bars run 15 min behind.
    dt = datetime.strptime(trade['decision_time'], '%Y-%m-%d %H:%M:%S')
    engine_minute = dt.strftime('%H:%M')  # wall UTC; tape times are ET naive
    # Convert: wall UTC - 4h (ET DST) - 15min engine delay = engine bar time
    from datetime import timedelta
    engine_bar_et = (dt - timedelta(hours=4, minutes=15)).strftime('%H:%M')

    start_idx = None
    for i, b in enumerate(tape):
        if b['time'][11:16] >= engine_bar_et:
            start_idx = i
            break
    if start_idx is None:
        return None

    highest = entry_price
    bars_held = 0
    stop_price = None
    if trade['strategy'] == 'vwap':
        # runner stop was VWAP-0.07 at entry; approximate with decision-bar
        # close relative stop parsed from logs if present, else skip
        stop_price = trade.get('stop_price')

    for b in tape[start_idx + 1:]:
        bars_held += 1
        bar = {'open': b['open'], 'high': b['high'], 'low': b['low'],
               'close': b['close'], 'volume': b.get('volume', 0)}
        highest = max(highest, b['high'])
        if trade['strategy'] == 'vwap':
            sig = evaluate_exit(entry_price, stop_price or entry_price * 0.97,
                                highest, bar, bars_held, cfg)
        else:
            sig = evaluate_exit(entry_price, highest, bar, bars_held, cfg)
        if sig:
            exit_price = float(sig['exit_price'])
            return {
                'cf_entry': entry_price,
                'cf_exit': exit_price,
                'cf_pnl': (exit_price - entry_price) * trade['shares'],
                'cf_reason': sig.get('exit_type', sig.get('reason', '?')),
                'cf_bars_held': bars_held,
            }
    # No exit by end of tape — mark to last close
    last = tape[-1]['close']
    return {
        'cf_entry': entry_price,
        'cf_exit': last,
        'cf_pnl': (last - entry_price) * trade['shares'],
        'cf_reason': 'eod_mark',
        'cf_bars_held': bars_held,
    }


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', default=date.today().isoformat())
    parser.add_argument('--skip-pull', action='store_true')
    args = parser.parse_args()

    # 1. Pull captured bars into the DB (end-of-session routine)
    if not args.skip_pull and os.getenv('DB_DSN'):
        try:
            from data.live_capture.pull_live_bars import main as pull_main
            pull_main()
        except Exception as e:
            print(f'[warn] bar pull failed: {e}')

    # 2. Parse trades from logs
    logs = fetch_logs()
    trades = parse_trades(logs)
    if not trades:
        print('No trades found in session logs.')
        return

    # Parse stop prices for vwap trades from the log (line: Stop: $5.78 ...)
    for entry in logs:
        m = re.search(r'Stop: \$([\d.]+) \(VWAP', entry['msg'])
        if m:
            for t in trades:
                if t['strategy'] == 'vwap' and t.get('stop_price') is None:
                    t['stop_price'] = float(m.group(1))

    # 3. Replay each against the real tape
    print(f"\n{'=' * 78}")
    print(f"  SESSION REPORT {args.date} — paper vs live-counterfactual")
    print(f"{'=' * 78}")
    print(f"{'strategy':>8} {'sym':>6} {'decision':>9} {'paper fill':>10} "
          f"{'paper exit':>10} {'paper P&L':>10} | {'cf exit':>8} {'cf P&L':>10} {'cf reason':>14}")
    print('-' * 105)

    total_paper, total_cf = 0.0, 0.0
    for t in trades:
        tape = fetch_tape(t['symbol'], args.date)
        cf = replay_counterfactual(t, tape) if tape else None
        paper_pnl = t['paper_pnl'] if t['paper_pnl'] is not None else 0.0
        total_paper += paper_pnl
        cf_pnl = cf['cf_pnl'] if cf else 0.0
        total_cf += cf_pnl
        print(f"{t['strategy']:>8} {t['symbol']:>6} {t['decision_price']:>9.2f} "
              f"{t['paper_fill'] or 0:>10.2f} {t['paper_exit'] or 0:>10.2f} "
              f"{paper_pnl:>+10.2f} | "
              f"{(cf['cf_exit'] if cf else 0):>8.2f} {cf_pnl:>+10.2f} "
              f"{(cf['cf_reason'] if cf else 'no tape'):>14}")

    print('-' * 105)
    print(f"{'TOTAL':>26} {'':>21} {total_paper:>+10.2f} | {'':>8} {total_cf:>+10.2f}")
    print(f"\n  Sandbox distortion (paper - counterfactual): {total_paper - total_cf:+.2f}")


if __name__ == '__main__':
    main()
