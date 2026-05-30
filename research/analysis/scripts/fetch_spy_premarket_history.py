"""
Fetch SPY premarket summary data from Alpaca SIP feed.

For each trading day in the date range, fetches SPY bars and writes one row:
    date, prior_close, pm_open, pm_close, pm_volume, market_open

  pm_open      — SPY price at first premarket bar (4:00am ET)
  pm_close     — SPY price at last premarket bar before 9:30am ET
  pm_volume    — total SPY volume 4:00am–9:29am ET
  prior_close  — SPY close on the prior trading day
  market_open  — SPY open at 9:30am ET (first regular-hours bar)

Derived features (computed at validation time, not stored):
  spy_gap_pct       = (market_open - prior_close) / prior_close * 100
  spy_pm_trend_pct  = (pm_close - pm_open) / pm_open * 100
  spy_pm_vol_ratio  = pm_volume / prior_pm_volume  (rolling, computed in validation)

Output: research/analysis/outputs/spy_premarket_history.csv

Usage:
    python research/analysis/scripts/fetch_spy_premarket_history.py
    python research/analysis/scripts/fetch_spy_premarket_history.py --start 2021-01-01 --end 2024-12-31
    python research/analysis/scripts/fetch_spy_premarket_history.py --year 2023
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from datetime import date, datetime, timedelta

import pytz
import requests

# ── Config ────────────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../production')))

ET = pytz.timezone('US/Eastern')

ALPACA_DATA_URL = "https://data.alpaca.markets/v2/stocks"
OUTPUT_PATH = os.path.join(
    os.path.dirname(__file__), '../outputs/spy_premarket_history.csv'
)

# Alpaca credentials — read from env or .env.paper
def _load_credentials() -> tuple[str, str]:
    key = os.environ.get('APCA_API_KEY_ID', '')
    secret = os.environ.get('APCA_API_SECRET_KEY', '')
    if not key:
        # Try .env.paper
        env_path = os.path.join(os.path.dirname(__file__), '../../../.env.paper')
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('APCA_API_KEY_ID='):
                        key = line.split('=', 1)[1]
                    elif line.startswith('APCA_API_SECRET_KEY='):
                        secret = line.split('=', 1)[1]
    if not key or not secret:
        raise RuntimeError("Alpaca credentials not found. Set APCA_API_KEY_ID / APCA_API_SECRET_KEY.")
    return key, secret


def _alpaca_get(url: str, params: dict, headers: dict) -> dict:
    """GET with simple retry on 429 / 5xx."""
    for attempt in range(4):
        resp = requests.get(url, params=params, headers=headers, timeout=30)
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 429:
            wait = 2 ** attempt
            print(f"  Rate limit — sleeping {wait}s")
            time.sleep(wait)
            continue
        if resp.status_code >= 500:
            time.sleep(2)
            continue
        resp.raise_for_status()
    raise RuntimeError(f"Alpaca request failed after retries: {url}")


def fetch_spy_day(trade_date: date, headers: dict) -> dict | None:
    """
    Fetch SPY premarket summary for one trading day.
    Returns dict with keys: date, prior_close, pm_open, pm_close, pm_volume, market_open
    Returns None if data unavailable.
    """
    # Premarket window: 4:00am–9:30am ET in UTC
    pm_start = ET.localize(datetime(trade_date.year, trade_date.month, trade_date.day, 4, 0))
    pm_end   = ET.localize(datetime(trade_date.year, trade_date.month, trade_date.day, 9, 30))
    pm_start_utc = pm_start.astimezone(pytz.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    pm_end_utc   = pm_end.astimezone(pytz.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    # Fetch premarket minute bars
    data = _alpaca_get(
        f"{ALPACA_DATA_URL}/SPY/bars",
        params={
            'timeframe': '1Min',
            'start': pm_start_utc,
            'end': pm_end_utc,
            'feed': 'sip',
            'limit': 400,
        },
        headers=headers,
    )
    bars = data.get('bars', [])
    if not bars:
        return None

    pm_open   = bars[0]['o']
    pm_close  = bars[-1]['c']
    pm_volume = sum(b['v'] for b in bars)

    # Fetch prior trading day close + today's 9:30am open via daily bar
    prior_date = trade_date - timedelta(days=5)   # go back far enough to find prior trading day
    daily_data = _alpaca_get(
        f"{ALPACA_DATA_URL}/SPY/bars",
        params={
            'timeframe': '1Day',
            'start': prior_date.strftime('%Y-%m-%d'),
            'end': trade_date.strftime('%Y-%m-%d'),
            'feed': 'sip',
            'limit': 10,
        },
        headers=headers,
    )
    daily_bars = daily_data.get('bars', [])
    if len(daily_bars) < 1:
        return None

    # Most recent daily bar before trade_date = prior close
    prior_close = daily_bars[-1]['c']

    # Fetch first minute bar at 9:30am for market_open price
    mkt_start = ET.localize(datetime(trade_date.year, trade_date.month, trade_date.day, 9, 30))
    mkt_end   = ET.localize(datetime(trade_date.year, trade_date.month, trade_date.day, 9, 32))
    mkt_start_utc = mkt_start.astimezone(pytz.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    mkt_end_utc   = mkt_end.astimezone(pytz.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    mkt_data = _alpaca_get(
        f"{ALPACA_DATA_URL}/SPY/bars",
        params={
            'timeframe': '1Min',
            'start': mkt_start_utc,
            'end': mkt_end_utc,
            'feed': 'sip',
            'limit': 5,
        },
        headers=headers,
    )
    mkt_bars = mkt_data.get('bars', [])
    market_open = mkt_bars[0]['o'] if mkt_bars else None

    return {
        'date':         trade_date.isoformat(),
        'prior_close':  round(prior_close, 4),
        'pm_open':      round(pm_open, 4),
        'pm_close':     round(pm_close, 4),
        'pm_volume':    pm_volume,
        'market_open':  round(market_open, 4) if market_open else '',
    }


def get_trading_days(start: date, end: date) -> list[date]:
    """Return weekdays in range. Alpaca will return empty bars for holidays — handled by None check."""
    days = []
    d = start
    while d <= end:
        if d.weekday() < 5:  # Mon–Fri
            days.append(d)
        d += timedelta(days=1)
    return days


def main():
    parser = argparse.ArgumentParser(description='Fetch SPY premarket history from Alpaca')
    parser.add_argument('--start', default='2021-01-01')
    parser.add_argument('--end',   default='2024-12-31')
    parser.add_argument('--year',  type=int, help='Shortcut: set start/end to full year')
    args = parser.parse_args()

    if args.year:
        args.start = f'{args.year}-01-01'
        args.end   = f'{args.year}-12-31'

    start = date.fromisoformat(args.start)
    end   = date.fromisoformat(args.end)

    key, secret = _load_credentials()
    headers = {
        'APCA-API-KEY-ID':     key,
        'APCA-API-SECRET-KEY': secret,
    }

    trading_days = get_trading_days(start, end)
    print(f"Fetching SPY premarket data: {start} to {end} ({len(trading_days)} weekdays)")

    # Load already-fetched dates if output file exists (resume support)
    out_path = os.path.abspath(OUTPUT_PATH)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    existing_dates: set[str] = set()
    if os.path.exists(out_path):
        with open(out_path, newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing_dates.add(row['date'])
        print(f"  {len(existing_dates)} dates already in file — skipping")

    fieldnames = ['date', 'prior_close', 'pm_open', 'pm_close', 'pm_volume', 'market_open']
    mode = 'a' if existing_dates else 'w'

    skipped = 0
    fetched = 0
    errors  = 0

    with open(out_path, mode, newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if mode == 'w':
            writer.writeheader()

        for i, d in enumerate(trading_days):
            iso = d.isoformat()
            if iso in existing_dates:
                skipped += 1
                continue

            try:
                row = fetch_spy_day(d, headers)
            except Exception as e:
                print(f"  ERROR {iso}: {e}")
                errors += 1
                continue

            if row is None:
                # Holiday or no data — skip silently
                skipped += 1
                continue

            writer.writerow(row)
            f.flush()
            fetched += 1

            if fetched % 20 == 0 or i == len(trading_days) - 1:
                print(f"  {iso}  [{fetched} fetched, {skipped} skipped, {errors} errors]")

            # Polite pacing — ~3 requests per day = ~3 calls here, keep under rate limit
            time.sleep(0.1)

    print(f"\nDone. {fetched} new rows -> {out_path}")
    if errors:
        print(f"  {errors} errors — re-run to retry missing dates")


if __name__ == '__main__':
    main()
