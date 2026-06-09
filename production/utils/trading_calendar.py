"""
NYSE Trading Calendar
=====================
Primary: Alpaca /v2/calendar API (free, always up-to-date, handles holidays + early closes).
Fallback: Hardcoded NYSE holidays (weekday + holiday check, no API needed).

Usage:
    from trading_calendar import get_trading_days, is_trading_day

    days = get_trading_days(date(2026, 2, 1), date(2026, 2, 28))
    if is_trading_day(date(2026, 4, 3)):   # Good Friday — False
        ...
"""

from __future__ import annotations
import os
import logging
from datetime import date, timedelta

logger = logging.getLogger(__name__)

# ── Alpaca Calendar API (primary source) ─────────────────────────────────────

_alpaca_cache: dict[str, set[date]] = {}  # keyed by "YYYY" -> set of trading dates


def _fetch_alpaca_calendar(start: date, end: date) -> list[dict] | None:
    """Fetch trading calendar from Alpaca. Returns list of {date, open, close} or None on failure."""
    try:
        import requests
        key = os.getenv('APCA_API_KEY_ID', '')
        secret = os.getenv('APCA_API_SECRET_KEY', '')
        if not key or not secret:
            return None

        base = os.getenv('APCA_API_BASE_URL', 'https://api.alpaca.markets')
        # Calendar endpoint is always on the trading API, not data API
        if 'data.' in base:
            base = 'https://api.alpaca.markets'

        r = requests.get(
            f'{base}/v2/calendar',
            params={'start': start.isoformat(), 'end': end.isoformat()},
            headers={
                'APCA-API-KEY-ID': key,
                'APCA-API-SECRET-KEY': secret,
            },
            timeout=10,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.debug(f"Alpaca calendar fetch failed: {e}")
        return None


def _get_alpaca_trading_dates(start: date, end: date) -> set[date] | None:
    """Get trading dates from Alpaca API, with per-year caching."""
    cal = _fetch_alpaca_calendar(start, end)
    if cal is None:
        return None

    dates = set()
    for day in cal:
        try:
            d = date.fromisoformat(day['date'])
            dates.add(d)
        except (KeyError, ValueError):
            continue

    # Cache by year for future lookups
    for d in dates:
        yr = str(d.year)
        if yr not in _alpaca_cache:
            _alpaca_cache[yr] = set()
        _alpaca_cache[yr].add(d)

    return dates


# ── Static Fallback ──────────────────────────────────────────────────────────
# Used when Alpaca API is unavailable (no keys, network down, etc.)

NYSE_HOLIDAYS = {
    # 2021
    date(2021,  1,  1), date(2021,  1, 18), date(2021,  2, 15),
    date(2021,  4,  2), date(2021,  5, 31), date(2021,  6, 18),
    date(2021,  7,  5), date(2021,  9,  6), date(2021, 11, 25),
    date(2021, 12, 24),
    # 2022
    date(2022,  1, 17), date(2022,  2, 21), date(2022,  4, 15),
    date(2022,  5, 30), date(2022,  6, 20), date(2022,  7,  4),
    date(2022,  9,  5), date(2022, 11, 24), date(2022, 12, 26),
    # 2023
    date(2023,  1,  2), date(2023,  1, 16), date(2023,  2, 20),
    date(2023,  4,  7), date(2023,  5, 29), date(2023,  6, 19),
    date(2023,  7,  4), date(2023,  9,  4), date(2023, 11, 23),
    date(2023, 12, 25),
    # 2024
    date(2024,  1,  1), date(2024,  1, 15), date(2024,  2, 19),
    date(2024,  3, 29), date(2024,  5, 27), date(2024,  6, 19),
    date(2024,  7,  4), date(2024,  9,  2), date(2024, 11, 28),
    date(2024, 12, 25),
    # 2025
    date(2025,  1,  1), date(2025,  1, 20), date(2025,  2, 17),
    date(2025,  4, 18), date(2025,  5, 26), date(2025,  6, 19),
    date(2025,  7,  4), date(2025,  9,  1), date(2025, 11, 27),
    date(2025, 12, 25),
    # 2026
    date(2026,  1,  1), date(2026,  1, 19), date(2026,  2, 16),
    date(2026,  4,  3), date(2026,  5, 25), date(2026,  6, 19),
    date(2026,  7,  3), date(2026,  9,  7), date(2026, 11, 26),
    date(2026, 12, 25),
}

EARLY_CLOSE_DATES = {
    date(2025,  7,  3), date(2025, 11, 28), date(2025, 12, 24),
    date(2026, 11, 27), date(2026, 12, 24),
}


# ── Public API ───────────────────────────────────────────────────────────────

def is_trading_day(d: date) -> bool:
    """Return True if market is open on date d. Uses Alpaca cache if available, else static."""
    yr = str(d.year)
    if yr in _alpaca_cache:
        return d in _alpaca_cache[yr]
    # Static fallback
    return d.weekday() < 5 and d not in NYSE_HOLIDAYS


def is_early_close(d: date) -> bool:
    """Return True if market closes early (1pm ET) on date d."""
    return d in EARLY_CLOSE_DATES


def get_trading_days(start: date, end: date) -> list[date]:
    """
    Return all NYSE trading days in [start, end] inclusive.
    Tries Alpaca API first (authoritative), falls back to static holidays.
    """
    # Try Alpaca API
    alpaca_dates = _get_alpaca_trading_dates(start, end)
    if alpaca_dates is not None:
        result = sorted(d for d in alpaca_dates if start <= d <= end)
        logger.debug(f"Trading days {start}->{end}: {len(result)} (via Alpaca API)")
        return result

    # Static fallback
    logger.debug(f"Trading days {start}->{end}: using static calendar (Alpaca unavailable)")
    days = []
    d = start
    while d <= end:
        if is_trading_day(d):
            days.append(d)
        d += timedelta(days=1)
    return days


def get_expected_bar_window(d: date) -> tuple[str, str]:
    """
    Return (open_time, close_time) strings in ET for a trading day.
    Early-close days end at 13:00, normal days end at 20:00 (post-market).
    """
    open_time = "04:00"
    close_time = "13:00" if is_early_close(d) else "20:00"
    return open_time, close_time


if __name__ == '__main__':
    import sys
    from dotenv import load_dotenv
    load_dotenv()

    year = int(sys.argv[1]) if len(sys.argv) > 1 else 2026
    start = date(year, 1, 1)
    end = date(year, 12, 31)
    days = get_trading_days(start, end)
    print(f"\nNYSE trading days in {year}: {len(days)}")
    print(f"First 5 days: {days[:5]}")
    print(f"Last 5 days:  {days[-5:]}")

    # Show holidays from static list for this year
    holidays = sorted(d for d in NYSE_HOLIDAYS if d.year == year)
    print(f"Static holidays: {holidays}")
