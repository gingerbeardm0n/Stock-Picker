#!/usr/bin/env python3
"""
Open-of-Day Strategy Analysis — March 6, 2026 Watchlist
=========================================================
Simulates two entry strategies against the 14 premarket watchlist symbols:

  Strategy A — Open Buy:
    Buy at the 9:30 candle's OPEN price. Stop below the 9:30 candle low.

  Strategy B — First Green After Dip:
    If 9:30 candle is red (close < open): wait for the first green 1-min candle
    in the 9:30–9:40 window, buy at that candle's CLOSE.
    If 9:30 candle is already green (or flat): same as Strategy A.

Stop/Target:
  risk   = entry - (bar_low - $0.05 buffer)
  stop   = entry - risk
  target = entry + 2.2 * risk   (matches Trial 193 target1_ratio ≈ 2.19)
  If neither hit by 11:00 ET → time-decay exit at the 11:00 bar close.

Run from repo root:
  python research/maintenance/diagnostics/open_of_day_analysis.py
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../production')))

from utils.query_helpers import StockDataDB
from datetime import datetime, date
import pytz

ET = pytz.timezone('US/Eastern')
TARGET_DATE = date(2026, 3, 6)
STOP_BUFFER  = 0.05      # cents below signal-bar low
TARGET_RATIO = 2.19      # risk multiplier for target
TIME_EXIT_HOUR = 11      # exit at 11:00 if not stopped/targetted

# 14 premarket watchlist symbols from the March 6 session log
WATCHLIST = [
    {'symbol': 'INDO',  'pm_gain': 35.4, 'rvol': 10.7,   'price': 6.20,  'float_m': 15.0},
    {'symbol': 'MXC',   'pm_gain': 33.4, 'rvol': 10.4,   'price': 15.75, 'float_m': 2.0},
    {'symbol': 'CRE',   'pm_gain': 30.8, 'rvol': 1080.3, 'price': 3.48,  'float_m': 1.6},
    {'symbol': 'SYNX',  'pm_gain': 26.9, 'rvol': 1092.7, 'price': 1.32,  'float_m': 6.6},
    {'symbol': 'IBG',   'pm_gain': 19.7, 'rvol': 2191.5, 'price': 4.80,  'float_m': 0.7},
    {'symbol': 'JZXN',  'pm_gain': 17.1, 'rvol': 10.7,   'price': 1.48,  'float_m': 1.4},
    {'symbol': 'ANY',   'pm_gain': 16.8, 'rvol': 552.8,  'price': 1.64,  'float_m': 3.4},
    {'symbol': 'STTK',  'pm_gain': 16.5, 'rvol': 8.1,    'price': 5.30,  'float_m': 63.3},
    {'symbol': 'LXU',   'pm_gain': 16.1, 'rvol': 18.9,   'price': 14.50, 'float_m': 71.8},
    {'symbol': 'FTW',   'pm_gain': 16.0, 'rvol': 38.6,   'price': 14.44, 'float_m': 44.6},
    {'symbol': 'EVC',   'pm_gain': 14.8, 'rvol': 56.1,   'price': 3.57,  'float_m': 91.0},
    {'symbol': 'MSGM',  'pm_gain': 12.9, 'rvol': 11.8,   'price': 4.61,  'float_m': 5.8},
    {'symbol': 'VWAV',  'pm_gain': 11.4, 'rvol': 6.9,    'price': 7.65,  'float_m': 19.6},
    {'symbol': 'SWBI',  'pm_gain': 11.2, 'rvol': 37.8,   'price': 13.42, 'float_m': 44.5},
]


def bar_time_et(bar: dict):
    """Return the bar's timestamp as an ET-aware datetime."""
    t = bar['time']
    if t.tzinfo is None:
        import pytz as _tz
        t = _tz.utc.localize(t)
    return t.astimezone(ET)


def simulate_trade(entry_price: float, signal_bar_low: float, bars_after: list[dict]) -> dict:
    """
    Given an entry and subsequent minute bars, simulate the trade to completion.
    Returns dict with exit_price, exit_reason, pnl_per_share, bars_held.
    """
    stop   = signal_bar_low - STOP_BUFFER
    risk   = entry_price - stop
    if risk <= 0:
        return {'exit_price': entry_price, 'exit_reason': 'FLAT_RISK', 'pnl': 0.0, 'bars': 0}
    target = entry_price + TARGET_RATIO * risk

    for i, bar in enumerate(bars_after):
        t_et = bar_time_et(bar)
        # Time-decay exit at or after 11:00 ET
        if t_et.hour >= TIME_EXIT_HOUR:
            return {
                'exit_price':  float(bar['open']),
                'exit_reason': 'TIME_DECAY',
                'pnl':         float(bar['open']) - entry_price,
                'stop':        round(stop, 4),
                'target':      round(target, 4),
                'bars':        i + 1,
                'exit_time':   t_et.strftime('%H:%M'),
            }
        # Check low vs stop
        if float(bar['low']) <= stop:
            return {
                'exit_price':  stop,
                'exit_reason': 'STOP',
                'pnl':         stop - entry_price,
                'stop':        round(stop, 4),
                'target':      round(target, 4),
                'bars':        i + 1,
                'exit_time':   t_et.strftime('%H:%M'),
            }
        # Check high vs target
        if float(bar['high']) >= target:
            return {
                'exit_price':  target,
                'exit_reason': 'TARGET',
                'pnl':         target - entry_price,
                'stop':        round(stop, 4),
                'target':      round(target, 4),
                'bars':        i + 1,
                'exit_time':   t_et.strftime('%H:%M'),
            }

    # End of data without exit
    last = bars_after[-1] if bars_after else None
    exit_p = float(last['close']) if last else entry_price
    return {
        'exit_price':  exit_p,
        'exit_reason': 'END_OF_DATA',
        'pnl':         exit_p - entry_price,
        'stop':        round(stop, 4),
        'target':      round(target, 4),
        'bars':        len(bars_after),
        'exit_time':   bar_time_et(last).strftime('%H:%M') if last else '?',
    }


def analyse_symbol(symbol: str, bars: list[dict]) -> dict:
    """
    Returns Strategy A and B results for a single symbol.
    bars = all minute bars for the symbol from 9:00 to 12:00 ET.
    """
    # Find the 9:30 ET bar (first regular-session bar)
    market_bars = []
    for b in bars:
        t = bar_time_et(b)
        if t.hour > 9 or (t.hour == 9 and t.minute >= 30):
            market_bars.append(b)

    if len(market_bars) < 2:
        return {'error': f'insufficient bars ({len(market_bars)})'}

    bar_930 = market_bars[0]
    future_bars = market_bars[1:]   # bars AFTER the signal bar

    t_930     = bar_time_et(bar_930)
    open_930  = float(bar_930['open'])
    close_930 = float(bar_930['close'])
    low_930   = float(bar_930['low'])
    high_930  = float(bar_930['high'])
    is_green  = close_930 >= open_930

    result = {
        'bar_930': {
            'time':  t_930.strftime('%H:%M'),
            'open':  open_930,
            'high':  high_930,
            'low':   low_930,
            'close': close_930,
            'green': is_green,
        }
    }

    # ── Strategy A: Buy at 9:30 open ──────────────────────────────────────────
    result['A'] = simulate_trade(
        entry_price=open_930,
        signal_bar_low=low_930,
        bars_after=future_bars,
    )
    result['A']['entry_price'] = open_930
    result['A']['entry_time']  = '9:30'

    # ── Strategy B: First green candle after dip ───────────────────────────────
    if is_green:
        # 9:30 already green — same as A
        result['B'] = dict(result['A'])
        result['B']['entry_note'] = '9:30 green → same as A'
    else:
        # Look for first green candle within 9:31–9:40
        found = False
        for idx, bar in enumerate(future_bars):
            t_et = bar_time_et(bar)
            if t_et.hour > 9 or t_et.minute > 40:
                break
            if float(bar['close']) >= float(bar['open']):   # green candle
                entry_b = float(bar['close'])
                remaining = future_bars[idx + 1:]
                result['B'] = simulate_trade(
                    entry_price=entry_b,
                    signal_bar_low=float(bar['low']),
                    bars_after=remaining,
                )
                result['B']['entry_price'] = entry_b
                result['B']['entry_time']  = t_et.strftime('%H:%M')
                result['B']['entry_note']  = 'first green after red 9:30'
                found = True
                break
        if not found:
            result['B'] = {'exit_reason': 'NO_GREEN_CANDLE', 'pnl': 0.0, 'entry_note': 'no green by 9:40'}

    return result


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main():
    db = StockDataDB()
    symbols = [w['symbol'] for w in WATCHLIST]

    print(f"\n{'='*90}")
    print(f"OPEN-OF-DAY STRATEGY ANALYSIS — March 6, 2026 ({len(symbols)} watchlist stocks)")
    print(f"Strategy A: Buy at 9:30 open  |  Strategy B: First green candle after open dip")
    print(f"Stop: signal-bar low - $0.05  |  Target: entry + {TARGET_RATIO}x risk  |  Time exit: 11:00 ET")
    print(f"{'='*90}\n")

    # Fetch minute bars 9:29–11:30 for all symbols
    bars_dict = db.get_minute_bars(symbols, TARGET_DATE, start_hour=9, end_hour=12)

    results = []
    for w in WATCHLIST:
        sym = w['symbol']
        bars = bars_dict.get(sym, [])
        r    = analyse_symbol(sym, bars)
        r['meta'] = w
        results.append((sym, r))

    # ── Per-symbol detail ─────────────────────────────────────────────────────
    print(f"{'Symbol':<6} {'PM%':>6} {'RVol':>7} {'Float':>6}  "
          f"{'9:30 Bar':^22}  "
          f"{'--- Strategy A (buy open) ---':^35}  "
          f"{'--- Strategy B (first green) ---':^37}")
    print(f"{'':6} {'':6} {'':7} {'':6}  "
          f"{'O':>6} {'H':>6} {'L':>6} {'C':>6} {'Dir':>3}  "
          f"{'Entry':>6} {'Stop':>6} {'Tgt':>7} {'Exit':>7} {'P&L':>7} {'Reason':<11}  "
          f"{'Entry':>6} {'Time':>5} {'Exit':>7} {'P&L':>7} {'Reason':<12}")
    print('-' * 175)

    a_wins = a_losses = a_skipped = 0
    b_wins = b_losses = b_skipped = 0
    a_total_pnl = b_total_pnl = 0.0

    for sym, r in results:
        if 'error' in r:
            print(f"{sym:<6}  (no data)")
            continue

        meta = r['meta']
        b930 = r['bar_930']
        A    = r['A']
        B    = r['B']

        dir_str = 'GRN' if b930['green'] else 'RED'

        # Strategy A
        a_entry = A.get('entry_price', 0)
        a_stop  = A.get('stop', 0)
        a_tgt   = A.get('target', 0)
        a_exit  = A.get('exit_price', 0)
        a_pnl   = A.get('pnl', 0.0)
        a_rsn   = A.get('exit_reason', '?')
        if a_rsn == 'TARGET': a_wins += 1
        elif a_rsn in ('STOP',): a_losses += 1
        else: a_skipped += 1
        a_total_pnl += a_pnl

        # Strategy B
        b_rsn   = B.get('exit_reason', '?')
        b_entry = B.get('entry_price', 0)
        b_exit  = B.get('exit_price', 0)
        b_pnl   = B.get('pnl', 0.0)
        b_time  = B.get('entry_time', '—')
        if b_rsn == 'TARGET': b_wins += 1
        elif b_rsn == 'STOP': b_losses += 1
        else: b_skipped += 1
        b_total_pnl += b_pnl

        a_pnl_str  = f"${a_pnl:+.3f}"
        b_pnl_str  = f"${b_pnl:+.3f}" if b_rsn not in ('NO_GREEN_CANDLE',) else '  —'
        b_rsn_disp = b_rsn if b_rsn != 'NO_GREEN_CANDLE' else 'NO_GREEN'

        print(
            f"{sym:<6} {meta['pm_gain']:>5.1f}% {meta['rvol']:>6.0f}x {meta['float_m']:>5.1f}M  "
            f"{b930['open']:>6.2f} {b930['high']:>6.2f} {b930['low']:>6.2f} {b930['close']:>6.2f} {dir_str:>3}  "
            f"{a_entry:>6.2f} {a_stop:>6.2f} {a_tgt:>7.2f} {a_exit:>7.2f} {a_pnl_str:>8} {a_rsn:<11}  "
            f"{b_entry:>6.2f} {b_time:>5} {b_exit:>7.2f} {b_pnl_str:>8} {b_rsn_disp:<12}"
        )

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'='*90}")
    print(f"SUMMARY (per-share P&L, 1 share each for comparability)")
    print(f"{'':25} {'Strategy A':^30}  {'Strategy B':^30}")
    print(f"{'':25} {'(buy at 9:30 open)':^30}  {'(first green candle)':^30}")
    print(f"  Winners (TARGET hit):   {a_wins:>4}  ({a_wins/len(results)*100:.0f}%)             {b_wins:>4}  ({b_wins/len(results)*100:.0f}%)")
    print(f"  Losers  (STOP hit):     {a_losses:>4}  ({a_losses/len(results)*100:.0f}%)             {b_losses:>4}  ({b_losses/len(results)*100:.0f}%)")
    print(f"  Time/No-signal exit:    {a_skipped:>4}  ({a_skipped/len(results)*100:.0f}%)             {b_skipped:>4}  ({b_skipped/len(results)*100:.0f}%)")
    print(f"  Total per-share P&L:  ${a_total_pnl:>+7.3f}                    ${b_total_pnl:>+7.3f}")
    print(f"{'='*90}")

    print(f"\nNOTE: P&L shown is per-share (ignores position sizing).")
    print(f"For rough $ impact, multiply by position size (e.g. $1000 / entry_price shares).")

    db.close()


if __name__ == '__main__':
    main()
