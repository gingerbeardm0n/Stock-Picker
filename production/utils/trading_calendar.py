"""
NYSE Trading Calendar
=====================
Authoritative list of NYSE market holidays and early-close days.
Used to determine which dates SHOULD have minute bar data in the DB,
without relying on what data is actually present (which is circular).

Sources:
  - NYSE Group official holiday calendars (ICE press releases)
  - https://www.nyse.com/trade/hours-calendars

Usage:
    from trading_calendar import get_trading_days, is_trading_day, EARLY_CLOSE_DATES

    days = get_trading_days(date(2026, 2, 1), date(2026, 2, 28))
    if is_trading_day(date(2026, 4, 3)):   # Good Friday — False
        ...

Update annually: add next year's holidays each December.
"""

from datetime import date, timedelta

# ── NYSE Full Market Closures ──────────────────────────────────────────────────
# Market is completely closed on these dates.

NYSE_HOLIDAYS = {
    # 2025
    date(2025,  1,  1),  # New Year's Day
    date(2025,  1, 20),  # Martin Luther King Jr. Day
    date(2025,  2, 17),  # Presidents' Day (Washington's Birthday)
    date(2025,  4, 18),  # Good Friday
    date(2025,  5, 26),  # Memorial Day
    date(2025,  6, 19),  # Juneteenth National Independence Day
    date(2025,  7,  4),  # Independence Day
    date(2025,  9,  1),  # Labor Day
    date(2025, 11, 27),  # Thanksgiving Day
    date(2025, 12, 25),  # Christmas Day

    # 2026
    date(2026,  1,  1),  # New Year's Day
    date(2026,  1, 19),  # Martin Luther King Jr. Day
    date(2026,  2, 16),  # Presidents' Day (Washington's Birthday)
    date(2026,  4,  3),  # Good Friday
    date(2026,  5, 25),  # Memorial Day
    date(2026,  6, 19),  # Juneteenth National Independence Day
    date(2026,  7,  3),  # Independence Day (observed — July 4 falls on Saturday)
    date(2026,  9,  7),  # Labor Day
    date(2026, 11, 26),  # Thanksgiving Day
    date(2026, 12, 25),  # Christmas Day
}

# ── NYSE Early Close Days (1:00 PM ET) ────────────────────────────────────────
# Market is OPEN but closes at 1pm ET instead of 4pm.
# We still collect data on these days — just less of it.

EARLY_CLOSE_DATES = {
    # 2025
    date(2025,  7,  3),  # Day before Independence Day
    date(2025, 11, 28),  # Day after Thanksgiving (Black Friday)
    date(2025, 12, 24),  # Christmas Eve

    # 2026
    date(2026, 11, 27),  # Day after Thanksgiving (Black Friday)
    date(2026, 12, 24),  # Christmas Eve
}


# ── Public API ─────────────────────────────────────────────────────────────────

def is_trading_day(d: date) -> bool:
    """Return True if the market is open (full or early close) on date d."""
    return d.weekday() < 5 and d not in NYSE_HOLIDAYS  # weekday() 0=Mon, 4=Fri


def is_early_close(d: date) -> bool:
    """Return True if the market closes early (1pm ET) on date d."""
    return d in EARLY_CLOSE_DATES


def get_trading_days(start: date, end: date) -> list[date]:
    """
    Return all NYSE trading days in [start, end] inclusive.
    Excludes weekends and full holidays. Includes early-close days.
    """
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
    Used for documentation/logging — actual timestamps built in callers.
    Early-close days end at 13:00, normal days end at 20:00 (post-market).
    """
    open_time = "04:00"
    close_time = "13:00" if is_early_close(d) else "20:00"
    return open_time, close_time


if __name__ == '__main__':
    # Quick sanity check
    from datetime import date
    import sys

    year = int(sys.argv[1]) if len(sys.argv) > 1 else 2026
    start = date(year, 1, 1)
    end = date(year, 12, 31)
    days = get_trading_days(start, end)
    print(f"\nNYSE trading days in {year}: {len(days)}")
    print(f"Holidays: {sorted(d for d in NYSE_HOLIDAYS if d.year == year)}")
    print(f"Early closes: {sorted(d for d in EARLY_CLOSE_DATES if d.year == year)}")
    print(f"\nFirst 5 days: {days[:5]}")
    print(f"Last 5 days:  {days[-5:]}")
