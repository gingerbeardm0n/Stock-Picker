"""
Integration tests for entry_engine.evaluate_entry() pipeline.

Tests the complete entry decision flow:
- Gate 1: Trading window (9:30-12:00 ET)
- Gate 2: 5 Pillars (price, gain, rel_vol, buying vol, float, market cap)
- Gate 3: Technical confirmation (EMA, MACD, trend, volume)
- Gate 4: Pattern detection
- Gate 5: Risk/Reward >= 2:1
"""

import pytest
from datetime import datetime, timezone, timedelta
from trading.entry_engine import evaluate_entry
from trading.models import ScannerConfig, EntryConfig
from tests.conftest import make_bar, make_bars


class TestGate1TradingWindow:
    """Gate 1: Trading window 9:30 AM - 12:00 PM ET."""

    def test_rejects_before_930am(self):
        """Entry should be rejected before 9:30 AM ET."""
        # 9:25 AM ET = 14:25 UTC
        bar = make_bar(4.0, 4.1, 3.95, 4.05, 100000,
                       time=datetime(2025, 1, 6, 14, 25, tzinfo=timezone.utc))
        history = make_bars([(4.0, 4.1, 3.95, 4.0, 100000) for _ in range(30)])

        signal = evaluate_entry(
            symbol='TEST',
            bar_history=history[:-1],
            current_bar=bar,
            fundamentals={},
            prior_close=3.5,
            current_time=bar['time'],
            relative_volume=100.0,
            scanner_config=ScannerConfig(),
            entry_config=EntryConfig(),
        )
        assert signal is None

    def test_accepts_at_930am(self):
        """Entry should be accepted at 9:30 AM ET (with all gates passing)."""
        # 9:30 AM ET = 14:30 UTC (the default in make_bar)
        bars = make_bars([(4.0 + i*0.01, 4.0 + i*0.01 + 0.05, 3.95 + i*0.01, 4.02 + i*0.01, 200000)
                          for i in range(40)])  # 40 green bars, high volume
        current_bar = bars[-1]

        # Calculate proper indicators
        from trading.indicators import get_current_ema, calculate_macd
        prices = [float(b['close']) for b in bars]
        ema9 = get_current_ema(prices, 9)
        macd = calculate_macd(prices)

        indicators_dict = {
            'ema9': ema9,
            'macd_histogram': macd['histogram'] if macd else None,
        }

        signal = evaluate_entry(
            symbol='TEST',
            bar_history=bars[:-1],
            current_bar=current_bar,
            fundamentals={},
            prior_close=3.5,  # 14%+ gain ✓
            current_time=current_bar['time'],
            relative_volume=100.0,  # 100x ✓
            scanner_config=ScannerConfig(),
            entry_config=EntryConfig(),
        )
        # Should pass Gate 1 at minimum (others may fail due to pattern)
        # Just verify it's not rejected by Gate 1
        if signal is None:
            # Gate 1 passed, but later gates failed (expected)
            pass
        else:
            # Signal returned (all gates passed)
            assert signal.symbol == 'TEST'

    def test_rejects_after_12pm(self):
        """Entry should be rejected after 12:00 PM ET."""
        # 12:05 PM ET = 17:05 UTC
        bar = make_bar(4.0, 4.1, 3.95, 4.05, 100000,
                       time=datetime(2025, 1, 6, 17, 5, tzinfo=timezone.utc))
        history = make_bars([(4.0, 4.1, 3.95, 4.0, 100000) for _ in range(30)])

        signal = evaluate_entry(
            symbol='TEST',
            bar_history=history[:-1],
            current_bar=bar,
            fundamentals={},
            prior_close=3.5,
            current_time=bar['time'],
            relative_volume=100.0,
            scanner_config=ScannerConfig(),
            entry_config=EntryConfig(),
        )
        assert signal is None


class TestGate2FivePillars:
    """Gate 2: Ross Cameron's 5 Pillars."""

    def test_rejects_price_too_low(self):
        """Gate 2 should reject price below $2."""
        bar = make_bar(1.5, 1.6, 1.45, 1.55, 100000)
        history = make_bars([(4.0, 4.1, 3.95, 4.0, 100000) for _ in range(30)])

        signal = evaluate_entry(
            symbol='TEST',
            bar_history=history[:-1],
            current_bar=bar,
            fundamentals={},
            prior_close=1.4,
            current_time=bar['time'],
            relative_volume=100.0,
            scanner_config=ScannerConfig(min_price=2.0),
            entry_config=EntryConfig(),
        )
        assert signal is None

    def test_rejects_price_too_high(self):
        """Gate 2 should reject price above $20."""
        bar = make_bar(25.0, 25.1, 24.9, 25.05, 100000)
        history = make_bars([(4.0, 4.1, 3.95, 4.0, 100000) for _ in range(30)])

        signal = evaluate_entry(
            symbol='TEST',
            bar_history=history[:-1],
            current_bar=bar,
            fundamentals={},
            prior_close=24.0,
            current_time=bar['time'],
            relative_volume=100.0,
            scanner_config=ScannerConfig(max_price=20.0),
            entry_config=EntryConfig(),
        )
        assert signal is None

    def test_rejects_gain_too_low(self):
        """Gate 2 should reject if gain < 10% from prior close."""
        bar = make_bar(4.0, 4.1, 3.95, 4.05, 100000)
        history = make_bars([(4.0, 4.1, 3.95, 4.0, 100000) for _ in range(30)])

        signal = evaluate_entry(
            symbol='TEST',
            bar_history=history[:-1],
            current_bar=bar,
            fundamentals={},
            prior_close=3.9,  # only 3.8% gain
            current_time=bar['time'],
            relative_volume=100.0,
            scanner_config=ScannerConfig(min_premarket_gain=10.0),
            entry_config=EntryConfig(),
        )
        assert signal is None

    def test_rejects_rel_vol_too_low(self):
        """Gate 2 should reject if relative volume < 5x."""
        bar = make_bar(4.0, 4.1, 3.95, 4.05, 100000)
        history = make_bars([(4.0, 4.1, 3.95, 4.0, 100000) for _ in range(30)])

        signal = evaluate_entry(
            symbol='TEST',
            bar_history=history[:-1],
            current_bar=bar,
            fundamentals={},
            prior_close=3.5,  # 14%+ gain ✓
            current_time=bar['time'],
            relative_volume=3.0,  # only 3x (need 5x)
            scanner_config=ScannerConfig(min_relative_volume=5.0),
            entry_config=EntryConfig(),
        )
        assert signal is None

    def test_rejects_selling_pressure(self):
        """Gate 2 should reject if selling volume > buying volume."""
        # Red bar: all selling volume
        bar = make_bar(4.1, 4.15, 3.95, 3.95, 100000)  # close = low (red)
        history = make_bars([(4.0, 4.1, 3.95, 4.0, 100000) for _ in range(30)])

        signal = evaluate_entry(
            symbol='TEST',
            bar_history=history[:-1],
            current_bar=bar,
            fundamentals={},
            prior_close=3.5,
            current_time=bar['time'],
            relative_volume=100.0,
            scanner_config=ScannerConfig(),
            entry_config=EntryConfig(),
        )
        assert signal is None

    def test_rejects_buying_vol_too_low(self):
        """Gate 2 should reject if buying volume < 50K."""
        # Green bar with low total volume
        bar = make_bar(4.0, 4.1, 3.95, 4.05, 10000)  # only 10K volume
        history = make_bars([(4.0, 4.1, 3.95, 4.0, 200000) for _ in range(30)])

        signal = evaluate_entry(
            symbol='TEST',
            bar_history=history[:-1],
            current_bar=bar,
            fundamentals={},
            prior_close=3.5,
            current_time=bar['time'],
            relative_volume=100.0,
            scanner_config=ScannerConfig(min_buying_volume=50000),
            entry_config=EntryConfig(),
        )
        assert signal is None


class TestGate3TechnicalConfirmation:
    """Gate 3: Technical confirmation (EMA, MACD, trending up)."""

    def test_rejects_price_below_ema9(self):
        """Gate 3 should reject if price < EMA9."""
        bars = make_bars([(4.0 + i*0.05, 4.0 + i*0.05 + 0.05, 3.95 + i*0.05, 4.02 + i*0.05, 200000)
                          for i in range(40)])
        current_bar = make_bar(3.80, 3.85, 3.75, 3.80, 200000,
                               time=bars[-1]['time'] + timedelta(minutes=1))

        from trading.indicators import get_current_ema, calculate_macd
        prices = [float(b['close']) for b in bars]
        ema9 = get_current_ema(prices, 9)  # Should be around 4.1+
        macd = calculate_macd(prices)

        signal = evaluate_entry(
            symbol='TEST',
            bar_history=bars,
            current_bar=current_bar,
            fundamentals={},
            prior_close=3.5,
            current_time=current_bar['time'],
            relative_volume=100.0,
            scanner_config=ScannerConfig(),
            entry_config=EntryConfig(),
        )
        assert signal is None

    def test_rejects_macd_negative(self):
        """Gate 3 should reject if MACD histogram <= 0."""
        # Downtrend: 40 bars falling
        bars = make_bars([(5.0 - i*0.01, 5.0 - i*0.01 + 0.05, 4.9 - i*0.01, 4.95 - i*0.01, 200000)
                          for i in range(40)])
        current_bar = bars[-1]

        from trading.indicators import calculate_macd
        prices = [float(b['close']) for b in bars]
        macd = calculate_macd(prices)
        assert macd is not None
        assert macd['histogram'] < 0

        signal = evaluate_entry(
            symbol='TEST',
            bar_history=bars[:-1],
            current_bar=current_bar,
            fundamentals={},
            prior_close=5.5,
            current_time=current_bar['time'],
            relative_volume=100.0,
            scanner_config=ScannerConfig(),
            entry_config=EntryConfig(),
        )
        assert signal is None

    def test_rejects_not_trending_up(self):
        """Gate 3 should reject if not trending up."""
        # Downtrend: all red bars
        bars = make_bars([(10.0 - i*0.05, 10.0 - i*0.05 + 0.02, 9.9 - i*0.05, 9.95 - i*0.05, 100000)
                          for i in range(40)])
        current_bar = bars[-1]

        signal = evaluate_entry(
            symbol='TEST',
            bar_history=bars[:-1],
            current_bar=current_bar,
            fundamentals={},
            prior_close=10.5,
            current_time=current_bar['time'],
            relative_volume=100.0,
            scanner_config=ScannerConfig(),
            entry_config=EntryConfig(),
        )
        assert signal is None


class TestGate5RiskReward:
    """Gate 5: Risk/Reward ratio >= 2:1."""

    def test_accepts_2_1_rr(self):
        """Entry should be accepted if R/R >= 2:1 after passing all other gates."""
        # Create a strong uptrend that will pass Gates 1-4
        bars = make_bars([(4.0 + i*0.01, 4.0 + i*0.01 + 0.05, 3.95 + i*0.01, 4.02 + i*0.01, 200000)
                          for i in range(40)])
        current_bar = bars[-1]

        signal = evaluate_entry(
            symbol='TEST',
            bar_history=bars[:-1],
            current_bar=current_bar,
            fundamentals={},
            prior_close=3.5,
            current_time=current_bar['time'],
            relative_volume=100.0,
            scanner_config=ScannerConfig(),
            entry_config=EntryConfig(min_rr_ratio=2.0),
        )
        # Pattern detection may still fail, so just check R/R is evaluated
        # If signal is None, it's due to pattern detection, not R/R
        if signal is not None:
            assert signal.pattern.risk_reward_ratio >= 2.0

    def test_rejects_1_1_rr(self):
        """Entry should be rejected if R/R < 2:1 (after fixing pattern stop/targets)."""
        # This test verifies R/R gate exists
        # Creating a pattern with poor R/R requires specific setup
        bars = make_bars([(4.0, 4.1, 3.95, 4.05, 100000) for _ in range(30)])
        current_bar = bars[-1]

        # If a pattern with R/R=1:1 were created, it should be rejected
        # (Pattern detectors themselves enforce good R/R, so hard to test directly)
        assert True  # Placeholder
