"""
Technical Indicators
====================
Pure functions — no DB access, no side effects.
All functions operate on lists of bar dicts (OHLCV) or price lists.

Bar dict format (from query_helpers.get_minute_bars):
    {time, symbol, open, high, low, close, volume, vwap, hour, minute}
"""

from __future__ import annotations


# ── EMA ───────────────────────────────────────────────────────────────────────

def calculate_ema(prices: list[float], period: int = 9) -> list[float | None]:
    """
    Exponential Moving Average.

    Returns a list the same length as prices.
    The first (period - 1) values are None (not enough history).
    Uses the standard multiplier: k = 2 / (period + 1)
    """
    if not prices or period <= 0:
        return []

    result: list[float | None] = [None] * len(prices)
    k = 2.0 / (period + 1)

    # Seed: first valid EMA = simple average of first `period` values
    if len(prices) < period:
        return result

    seed = sum(prices[:period]) / period
    result[period - 1] = seed

    for i in range(period, len(prices)):
        result[i] = prices[i] * k + result[i - 1] * (1 - k)

    return result


def get_current_ema(prices: list[float], period: int = 9) -> float | None:
    """Returns only the most recent EMA value, or None if not enough history."""
    ema = calculate_ema(prices, period)
    for v in reversed(ema):
        if v is not None:
            return v
    return None


# ── MACD ──────────────────────────────────────────────────────────────────────

def calculate_macd(
    prices: list[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> dict | None:
    """
    MACD (Moving Average Convergence Divergence).

    Returns dict with:
        'macd'      - MACD line (fast EMA - slow EMA)
        'signal'    - Signal line (EMA of MACD line)
        'histogram' - Histogram (MACD - signal)

    Returns None if not enough price history (need at least slow + signal bars).
    """
    min_bars = slow + signal
    if len(prices) < min_bars:
        return None

    fast_ema = calculate_ema(prices, fast)
    slow_ema = calculate_ema(prices, slow)

    # Build MACD line (only where both EMAs are valid)
    macd_line: list[float] = []
    for f, s in zip(fast_ema, slow_ema):
        if f is not None and s is not None:
            macd_line.append(f - s)

    if len(macd_line) < signal:
        return None

    signal_ema = calculate_ema(macd_line, signal)
    sig_val = next((v for v in reversed(signal_ema) if v is not None), None)
    if sig_val is None:
        return None

    macd_val = macd_line[-1]
    histogram = macd_val - sig_val

    return {
        'macd': macd_val,
        'signal': sig_val,
        'histogram': histogram,
    }


# ── Volume ────────────────────────────────────────────────────────────────────

def estimate_buy_sell_volume(
    open_: float,
    high: float,
    low: float,
    close: float,
    volume: float,
) -> tuple[float, float]:
    """
    Estimate buying vs selling volume from a single OHLCV bar.

    Formula:
        bar_position = (close - low) / (high - low)
        buying_volume  = total_volume × bar_position
        selling_volume = total_volume × (1 - bar_position)

    bar_position near 1.0 = close near top = buying pressure (bullish)
    bar_position near 0.0 = close near bottom = selling pressure (bearish)

    Returns (buying_vol, selling_vol). If high == low (doji), splits 50/50.
    """
    open_ = float(open_)
    high = float(high)
    low = float(low)
    close = float(close)
    volume = float(volume)

    if high <= low or volume == 0:
        return volume * 0.5, volume * 0.5

    position = (close - low) / (high - low)
    position = max(0.0, min(1.0, position))

    return volume * position, volume * (1.0 - position)


def get_volume_direction(bar: dict) -> tuple[str, float, float]:
    """
    Convenience wrapper: classify a bar as BULLISH, BEARISH, or NEUTRAL.

    Returns: (direction, buying_vol, selling_vol)
    """
    buying_vol, selling_vol = estimate_buy_sell_volume(
        bar['open'], bar['high'], bar['low'], bar['close'], bar['volume']
    )
    if buying_vol > selling_vol:
        return 'BULLISH', buying_vol, selling_vol
    elif selling_vol > buying_vol:
        return 'BEARISH', buying_vol, selling_vol
    else:
        return 'NEUTRAL', buying_vol, selling_vol


def average_volume(bars: list[dict], lookback: int = 5) -> float:
    """Mean volume of the last `lookback` bars."""
    recent = bars[-lookback:] if len(bars) >= lookback else bars
    if not recent:
        return 0.0
    return sum(float(b['volume']) for b in recent) / len(recent)


def is_light_volume(bar: dict, reference_bars: list[dict], threshold: float = 0.5) -> bool:
    """
    True if bar's volume is below `threshold` fraction of the reference bar average.
    Used to identify "light volume" pullbacks in pattern detection.

    Default: bar volume < 50% of prior 5-bar average = light volume.
    """
    avg = average_volume(reference_bars, lookback=5)
    if avg == 0:
        return False
    return float(bar['volume']) < avg * threshold


# ── Trend ─────────────────────────────────────────────────────────────────────

def is_trending_up(bars: list[dict], lookback: int = 5) -> bool:
    """
    True if the stock is in an uptrend over the last `lookback` bars.

    Conditions (both must be true):
        1. >= 3 of the last 5 bars are green (close > open)
        2. Most recent close > close from `lookback` bars ago (higher highs)
    """
    if len(bars) < lookback:
        return False

    recent = bars[-lookback:]
    green_count = sum(1 for b in recent if float(b['close']) > float(b['open']))

    close_now = float(recent[-1]['close'])
    close_then = float(recent[0]['close'])

    return green_count >= 3 and close_now > close_then


def volume_on_up_bars_dominates(bars: list[dict], lookback: int = 5) -> bool:
    """
    True if total volume on green candles > total volume on red candles
    in the last `lookback` bars.

    Ross Cameron: "Volume on UP candles > volume on DOWN candles" = healthy trend.
    """
    if not bars:
        return False

    recent = bars[-lookback:]
    up_vol = sum(float(b['volume']) for b in recent if float(b['close']) >= float(b['open']))
    down_vol = sum(float(b['volume']) for b in recent if float(b['close']) < float(b['open']))

    return up_vol > down_vol
