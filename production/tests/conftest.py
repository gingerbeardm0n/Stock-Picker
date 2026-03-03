"""
Shared test fixtures and helpers for all unit tests.
"""

from datetime import datetime, timezone
from decimal import Decimal
import pytest


def make_bar(open_: float, high: float, low: float, close: float, volume: int,
             time: datetime = None, symbol: str = 'TEST') -> dict:
    """
    Create a synthetic bar dict for testing.

    Args:
        open_, high, low, close: OHLC prices
        volume: bar volume
        time: bar timestamp (UTC). Defaults to 2025-01-06 09:30:00 UTC
        symbol: stock ticker

    Returns:
        A bar dict matching the format from StockDataDB.get_minute_bars()
    """
    if time is None:
        time = datetime(2025, 1, 6, 14, 30, tzinfo=timezone.utc)  # 9:30 AM ET

    # Calculate hour/minute for ET
    et_time = time.astimezone()  # local timezone
    hour = et_time.hour
    minute = et_time.minute

    return {
        'time': time,
        'symbol': symbol,
        'open': Decimal(str(open_)),
        'high': Decimal(str(high)),
        'low': Decimal(str(low)),
        'close': Decimal(str(close)),
        'volume': volume,
        'vwap': Decimal(str((open_ + high + low + close) / 4)),
        'hour': hour,
        'minute': minute,
    }


def make_bars(specs: list[tuple]) -> list[dict]:
    """
    Create multiple bars from (open, high, low, close, volume) tuples.

    Each bar is spaced 1 minute apart, starting at 2025-01-06 09:30 UTC.

    Example:
        bars = make_bars([
            (4.00, 4.10, 3.95, 4.05, 100000),
            (4.05, 4.15, 4.00, 4.10, 120000),
            (4.10, 4.20, 4.05, 4.15, 150000),
        ])
    """
    bars = []
    base_time = datetime(2025, 1, 6, 14, 30, tzinfo=timezone.utc)  # 9:30 AM ET

    for i, (o, h, l, c, v) in enumerate(specs):
        from datetime import timedelta
        time = base_time + timedelta(minutes=i)
        bars.append(make_bar(o, h, l, c, v, time=time))

    return bars


@pytest.fixture
def simple_uptrend():
    """Green bar trend: consistently rising closes and higher highs."""
    return make_bars([
        (10.00, 10.10, 9.90, 10.05, 100000),   # green
        (10.05, 10.15, 10.00, 10.10, 105000),  # green, higher close
        (10.10, 10.20, 10.05, 10.15, 110000),  # green, higher close
        (10.15, 10.25, 10.10, 10.20, 115000),  # green, higher close
    ])


@pytest.fixture
def simple_downtrend():
    """Red bar trend: consistently falling closes and lower lows."""
    return make_bars([
        (10.00, 10.05, 9.95, 10.00, 100000),   # red (close=open)
        (10.00, 10.05, 9.90, 9.95, 105000),    # red, lower close
        (9.95, 10.00, 9.85, 9.90, 110000),     # red, lower close
        (9.90, 9.95, 9.80, 9.85, 115000),      # red, lower close
    ])


@pytest.fixture
def mixed_bars():
    """Alternating green and red bars."""
    return make_bars([
        (10.00, 10.10, 9.95, 10.05, 100000),   # green
        (10.05, 10.10, 9.95, 10.00, 110000),   # red
        (10.00, 10.15, 9.98, 10.10, 120000),   # green
        (10.10, 10.12, 9.90, 9.95, 130000),    # red
        (9.95, 10.05, 9.90, 10.00, 140000),    # green
    ])
