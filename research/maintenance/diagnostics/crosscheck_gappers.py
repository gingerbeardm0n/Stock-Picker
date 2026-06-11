"""Cross-check real gappers (Alpaca daily bars) vs what Tradier sandbox quotes report.

Purpose: the live scalp/vwap runners found 0 gappers all morning (Jun 11, 2026).
Did the market really have no gappers, or are Tradier sandbox quotes reporting
stale/zero gap data in premarket?

Method:
  1. Fetch NASDAQ-traded universe (same source as live runner).
  2. Pull Alpaca daily bars for prev day + target day, compute
     gap_open = open_today / close_prev - 1 (and gap_high using day high).
  3. List symbols with gap_open >= --min-gap and open <= --max-price.
  4. (--tradier) Fetch current Tradier sandbox quotes for those symbols and
     show what gap% the runner's formula (last vs prevclose) would have seen.

Usage:
  python crosscheck_gappers.py --date 2026-06-11
  python crosscheck_gappers.py --date 2026-06-11 --min-gap 9 --tradier
"""
import argparse
import io
import os
import sys
from datetime import datetime, timedelta

import requests
from dotenv import load_dotenv

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
load_dotenv(os.path.join(REPO_ROOT, '.env'))

ALPACA_KEY = os.getenv('APCA_API_KEY_ID')
ALPACA_SECRET = os.getenv('APCA_API_SECRET_KEY')
ALPACA_DATA = 'https://data.alpaca.markets/v2/stocks/bars'
NASDAQ_URL = 'https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt'
BATCH = 200


def fetch_universe() -> list[str]:
    r = requests.get(NASDAQ_URL, timeout=30)
    r.raise_for_status()
    symbols = []
    for line in io.StringIO(r.text):
        parts = line.split('|')
        if len(parts) < 8 or parts[0] not in ('Y', 'N'):
            continue
        sym, etf, test = parts[1], parts[5], parts[3]
        if etf == 'Y' or test == 'Y':
            continue
        if not sym.isalpha():  # skip units/warrants/weird suffixes
            continue
        symbols.append(sym)
    return symbols


def fetch_daily_bars(symbols: list[str], start: str, end: str) -> dict[str, list[dict]]:
    headers = {'APCA-API-KEY-ID': ALPACA_KEY, 'APCA-API-SECRET-KEY': ALPACA_SECRET}
    out: dict[str, list[dict]] = {}
    for i in range(0, len(symbols), BATCH):
        chunk = symbols[i:i + BATCH]
        page = None
        while True:
            params = {
                'symbols': ','.join(chunk), 'timeframe': '1Day',
                'start': start, 'end': end, 'feed': 'iex', 'limit': 10000,
            }
            if page:
                params['page_token'] = page
            for attempt in range(4):
                try:
                    r = requests.get(ALPACA_DATA, params=params, headers=headers, timeout=60)
                    r.raise_for_status()
                    break
                except requests.exceptions.RequestException:
                    if attempt == 3:
                        raise
            data = r.json()
            for sym, bars in (data.get('bars') or {}).items():
                out.setdefault(sym, []).extend(bars)
            page = data.get('next_page_token')
            if not page:
                break
        done = min(i + BATCH, len(symbols))
        print(f"  bars fetched for {done}/{len(symbols)} symbols", end='\r', flush=True)
    print()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--date', required=True, help='Target trading day (YYYY-MM-DD)')
    ap.add_argument('--min-gap', type=float, default=9.0)
    ap.add_argument('--max-price', type=float, default=30.0)
    ap.add_argument('--tradier', action='store_true',
                    help='Also fetch Tradier sandbox quotes for the found gappers')
    args = ap.parse_args()

    target = datetime.strptime(args.date, '%Y-%m-%d').date()
    start = (target - timedelta(days=7)).isoformat()  # window catches prev trading day

    print(f"Universe fetch from NASDAQ trader...")
    universe = fetch_universe()
    print(f"  {len(universe)} symbols")

    print(f"Alpaca daily bars {start} -> {target} (iex feed)...")
    bars = fetch_daily_bars(universe, start, target.isoformat())

    gappers = []
    for sym, blist in bars.items():
        blist.sort(key=lambda b: b['t'])
        # last bar must be the target day
        if not blist or blist[-1]['t'][:10] != target.isoformat():
            continue
        if len(blist) < 2:
            continue
        today, prev = blist[-1], blist[-2]
        pc = prev['c']
        if pc <= 0:
            continue
        gap_open = (today['o'] - pc) / pc * 100
        gap_high = (today['h'] - pc) / pc * 100
        if gap_open >= args.min_gap and today['o'] <= args.max_price:
            gappers.append({
                'symbol': sym, 'prev_close': pc, 'open': today['o'],
                'high': today['h'], 'close': today['c'], 'volume': today['v'],
                'gap_open': gap_open, 'gap_high': gap_high,
            })

    gappers.sort(key=lambda g: g['gap_open'], reverse=True)
    print(f"\n{len(gappers)} symbols opened >= {args.min_gap:.1f}% above prior close "
          f"(open <= ${args.max_price:.0f}) on {target}:\n")
    print(f"{'symbol':>8} {'prevC':>8} {'open':>8} {'high':>8} {'close':>8} "
          f"{'gapOpen%':>9} {'gapHigh%':>9} {'vol':>11}")
    for g in gappers[:40]:
        print(f"{g['symbol']:>8} {g['prev_close']:>8.2f} {g['open']:>8.2f} "
              f"{g['high']:>8.2f} {g['close']:>8.2f} "
              f"{g['gap_open']:>9.1f} {g['gap_high']:>9.1f} {g['volume']:>11,}")

    if args.tradier and gappers:
        sys.path.insert(0, os.path.join(REPO_ROOT, 'production'))
        from config import Config
        broker = Config.make_broker(live=False)
        syms = [g['symbol'] for g in gappers[:40]]
        print(f"\nTradier sandbox quotes for the same symbols (runner formula: "
              f"(last - prevclose) / prevclose):\n")
        quotes = broker.get_quotes(syms)
        print(f"{'symbol':>8} {'alpaca_gap%':>12} {'tradier_last':>13} "
              f"{'tradier_prevC':>14} {'tradier_gap%':>13}")
        for g in gappers[:40]:
            q = quotes.get(g['symbol'])
            if q is None or q.prev_close <= 0:
                print(f"{g['symbol']:>8} {g['gap_open']:>12.1f} {'--- no quote ---':>42}")
                continue
            t_gap = (q.last - q.prev_close) / q.prev_close * 100
            print(f"{g['symbol']:>8} {g['gap_open']:>12.1f} {q.last:>13.2f} "
                  f"{q.prev_close:>14.2f} {t_gap:>13.1f}")


if __name__ == '__main__':
    main()
