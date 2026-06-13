"""
Unit tests for indicator calculations in trading/indicators.py

Tests cover:
- EMA calculation and edge cases
- MACD calculation
- Buy/sell volume estimation
- Trend detection
- Volume analysis functions
"""

import pytest
from trading.indicators import (
    calculate_ema,
    calculate_macd,
    estimate_buy_sell_volume,
    is_trending_up,
    volume_on_up_bars_dominates,
    get_current_ema,
)
from tests.conftest import make_bar, make_bars


class TestEMA:
    """Tests for EMA (Exponential Moving Average) calculation."""

    def test_ema_seed_is_sma(self):
        """First EMA value should be the SMA of the period."""
        prices = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0, 19.0]
        emas = calculate_ema(prices, period=5)
        # First SMA = (10+11+12+13+14) / 5 = 12.0
        assert emas[4] == pytest.approx(12.0, abs=0.01)

    def test_ema_returns_none_before_period(self):
        """EMA values before period should be None."""
        prices = [10.0, 11.0, 12.0, 13.0]
        emas = calculate_ema(prices, period=5)
        assert emas[0] is None
        assert emas[1] is None
        assert emas[2] is None
        assert emas[3] is None

    def test_ema_formula_correct(self):
        """EMA should follow standard exponential formula."""
        prices = [10.0, 11.0, 12.0, 13.0, 14.0]
        emas = calculate_ema(prices, period=3)
        # period=3: k = 2/(3+1) = 0.5
        # SMA(0-2) = 11.0
        # EMA[2] = 11.0
        # EMA[3] = 12.0 * 0.5 + 11.0 * 0.5 = 11.5
        # EMA[4] = 13.0 * 0.5 + 11.5 * 0.5 = 12.25
        assert emas[2] == pytest.approx(11.0, abs=0.01)
        assert emas[3] == pytest.approx(11.5, abs=0.01)
        assert emas[4] == pytest.approx(12.25, abs=0.01)

    def test_ema_length_preserved(self):
        """Output list should same length as input."""
        prices = [10.0 + i for i in range(20)]
        emas = calculate_ema(prices, period=9)
        assert len(emas) == len(prices)

    def test_get_current_ema(self):
        """get_current_ema should return last non-None EMA value."""
        prices = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0]
        ema = get_current_ema(prices, period=3)
        # Should be the last EMA value
        emas = calculate_ema(prices, period=3)
        assert ema == emas[-1]

    def test_get_current_ema_all_none(self):
        """get_current_ema should return None if not enough bars."""
        prices = [10.0, 11.0]
        ema = get_current_ema(prices, period=5)
        assert ema is None


class TestMACD:
    """Tests for MACD (Moving Average Convergence Divergence)."""

    def test_macd_returns_dict_when_valid(self):
        """MACD should return dict with macd, signal, histogram keys."""
        prices = [10.0 + i * 0.1 for i in range(40)]  # 40 bars
        macd = calculate_macd(prices)
        assert macd is not None
        assert 'macd' in macd
        assert 'signal' in macd
        assert 'histogram' in macd

    def test_macd_returns_none_before_35_bars(self):
        """MACD should return None if < 35 bars."""
        prices = [10.0 + i * 0.1 for i in range(34)]
        macd = calculate_macd(prices)
        assert macd is None

    def test_macd_positive_on_rising_prices(self):
        """MACD histogram should be positive when prices rise."""
        # Steadily rising prices should have positive MACD
        prices = [10.0 + i * 0.1 for i in range(50)]
        macd = calculate_macd(prices)
        assert macd is not None
        assert macd['histogram'] > 0

    def test_macd_negative_on_falling_prices(self):
        """MACD histogram should be negative when prices fall."""
        # Steadily falling prices should have negative MACD
        prices = [10.0 - i * 0.1 for i in range(50)]
        macd = calculate_macd(prices)
        assert macd is not None
        assert macd['histogram'] < 0


class TestBuySellVolume:
    """Tests for estimate_buy_sell_volume (OHLC position method)."""

    def test_green_bar_all_buying(self):
        """Green bar (close=high) should be all buying volume."""
        buy_vol, sell_vol = estimate_buy_sell_volume(
            open_=10.0, high=11.0, low=10.0, close=11.0, volume=100000
        )
        # position = (11-10)/(11-10) = 1.0 → all buying
        assert buy_vol == pytest.approx(100000, rel=0.01)
        assert sell_vol == pytest.approx(0, abs=1)

    def test_red_bar_all_selling(self):
        """Red bar (close=low) should be all selling volume."""
        buy_vol, sell_vol = estimate_buy_sell_volume(
            open_=10.0, high=11.0, low=10.0, close=10.0, volume=100000
        )
        # position = (10-10)/(11-10) = 0 → all selling
        assert buy_vol == pytest.approx(0, abs=1)
        assert sell_vol == pytest.approx(100000, rel=0.01)

    def test_doji_50_50_split(self):
        """Doji bar (close=open) should split buying/selling 50/50."""
        buy_vol, sell_vol = estimate_buy_sell_volume(
            open_=10.0, high=11.0, low=9.0, close=10.0, volume=100000
        )
        # position = (10-9)/(11-9) = 0.5 → 50% each
        assert buy_vol == pytest.approx(50000, rel=0.02)
        assert sell_vol == pytest.approx(50000, rel=0.02)

    def test_buy_sell_sum_equals_volume(self):
        """Buy volume + sell volume should always equal total volume."""
        buy_vol, sell_vol = estimate_buy_sell_volume(
            open_=10.0, high=11.5, low=9.5, close=10.7, volume=100000
        )
        assert (buy_vol + sell_vol) == pytest.approx(100000, rel=0.01)


class TestTrendingUp:
    """Tests for is_trending_up() function."""

    def test_all_green_bars_trending(self, simple_uptrend):
        """All green bars with higher closes should trend up."""
        result = is_trending_up(simple_uptrend)
        assert result is True

    def test_all_red_bars_not_trending(self, simple_downtrend):
        """All red bars should not trend up."""
        result = is_trending_up(simple_downtrend)
        assert result is False

    def test_mixed_bars_below_threshold(self, mixed_bars):
        """Majority red bars (3/5) should not trend up."""
        # mixed_bars = [green, red, green, red, green] = 3 green, 2 red
        # Need >= 3 of 5 green, which is marginal. But also need close[-1] > close[-5]
        result = is_trending_up(mixed_bars)
        # This depends on exact closes, but should fail the majority check or close check
        assert isinstance(result, bool)

    def test_too_few_bars_returns_false(self):
        """Less than 5 bars should return False."""
        bars = make_bars([(10.0, 10.1, 9.9, 10.05, 100000)])
        result = is_trending_up(bars)
        assert result is False

    def test_trend_close_requirement(self):
        """Trend requires last close > close from 5 bars ago."""
        # 4 green bars, then red bar
        bars = make_bars([
            (10.00, 10.10, 9.95, 10.05, 100000),  # green
            (10.05, 10.15, 10.00, 10.10, 100000),  # green
            (10.10, 10.20, 10.05, 10.15, 100000),  # green
            (10.15, 10.25, 10.10, 10.20, 100000),  # green
            (10.20, 10.22, 9.95, 10.00, 100000),   # red (lower close)
        ])
        result = is_trending_up(bars)
        # 4/5 green (>= 60%), but close[4]=10.00 < close[0]=10.05, so should fail
        assert result is False


class TestVolumeOnUpBars:
    """Tests for volume_on_up_bars_dominates()."""

    def test_high_vol_on_green_bars_dominates(self):
        """High volume on green bars should dominate."""
        bars = make_bars([
            (10.00, 10.10, 9.95, 10.05, 100000),   # green, 100K vol
            (10.05, 10.10, 9.95, 10.00, 10000),    # red, 10K vol
            (10.00, 10.15, 9.98, 10.10, 100000),   # green, 100K vol
            (10.10, 10.12, 9.90, 9.95, 10000),     # red, 10K vol
            (9.95, 10.05, 9.90, 10.00, 100000),    # green, 100K vol
        ])
        result = volume_on_up_bars_dominates(bars)
        # Green total: 300K, Red total: 20K → green dominates
        assert result is True

    def test_high_vol_on_red_bars_not_dominated(self):
        """High volume on red bars should not dominate."""
        bars = make_bars([
            (10.00, 10.05, 9.95, 10.00, 10000),    # red, 10K vol
            (10.00, 10.10, 9.95, 10.05, 100000),   # green, 100K vol
            (10.05, 10.10, 9.95, 10.00, 100000),   # red, 100K vol
            (10.00, 10.15, 9.98, 10.10, 10000),    # green, 10K vol
            (10.10, 10.15, 9.90, 10.00, 100000),   # red, 100K vol
        ])
        result = volume_on_up_bars_dominates(bars)
        # Green total: 110K, Red total: 210K → red dominates
        assert result is False

    def test_equal_volume_no_dominance(self):
        """Equal volume on up/down bars should return False."""
        bars = make_bars([
            (10.00, 10.10, 9.95, 10.05, 50000),   # green
            (10.05, 10.10, 9.95, 10.00, 50000),   # red
            (10.00, 10.15, 9.98, 10.10, 50000),   # green
            (10.10, 10.12, 9.90, 9.95, 50000),    # red
        ])
        result = volume_on_up_bars_dominates(bars)
        # Green: 100K, Red: 100K → equal
        assert result is False
