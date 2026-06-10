"""
Unit tests for the VWAP Reclaim engine (vwap_engine.py + vwap_models.py).

Covers:
  - VwapAccumulator / calculate_vwap (market-hours-only, premarket exclusion)
  - in_entry_window (10:00-11:30 ET fixed window)
  - evaluate_entry (all reclaim conditions, both entry modes)
  - evaluate_exit (stop / target / trailing / time priorities)
"""

import sys
import os
from datetime import datetime, timedelta

import pytest
import pytz

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from trading.vwap_models import VwapReclaimConfig
from trading.vwap_engine import (
    VwapAccumulator, calculate_vwap, in_entry_window,
    evaluate_entry, evaluate_exit,
)

ET = pytz.timezone('US/Eastern')


def et_bar(hour, minute, open_, high, low, close, volume):
    """Bar with an explicit ET timestamp (2025-01-06, a Monday)."""
    t = ET.localize(datetime(2025, 1, 6, hour, minute))
    return {
        'time': t, 'open': open_, 'high': high, 'low': low,
        'close': close, 'volume': volume,
    }


CANDIDATE = {'symbol': 'TEST', 'gap_pct': 25.0, 'news_tier': 'tier1'}


def reclaim_setup_bars(vwap_anchor=10.0):
    """
    Build a textbook reclaim at 10:05: stock holds ~10.00 (defines VWAP),
    dips below, then a high-volume green bar closes back above.

    Returns (bars, config). Last bar is the reclaim candle.
    """
    bars = [
        # 9:30-9:59 — establish VWAP around 10.00 (high volume anchors it)
        et_bar(9, 30, 10.00, 10.10, 9.90, 10.00, 500_000),
        et_bar(9, 45, 10.00, 10.05, 9.95, 10.00, 500_000),
        # 10:00-10:04 — the test: closes below VWAP, light volume
        et_bar(10, 0, 10.00, 10.00, 9.80, 9.85, 80_000),
        et_bar(10, 1, 9.85, 9.95, 9.80, 9.90, 80_000),
        et_bar(10, 2, 9.90, 9.95, 9.85, 9.88, 80_000),
        et_bar(10, 3, 9.88, 9.96, 9.85, 9.92, 80_000),
        et_bar(10, 4, 9.92, 9.99, 9.88, 9.95, 80_000),
        # 10:05 — the reclaim: green, closes above VWAP, 3x lookback volume
        et_bar(10, 5, 9.95, 10.15, 9.94, 10.12, 300_000),
    ]
    cfg = VwapReclaimConfig(lookback_bars=5, min_bars_below=1, reclaim_vol_mult=1.2)
    return bars, cfg


# ── VWAP calculation ─────────────────────────────────────────────────────────

class TestVwapCalculation:
    def test_single_bar(self):
        bar = et_bar(9, 30, 10.0, 10.2, 9.8, 10.0, 1000)
        assert calculate_vwap([bar]) == pytest.approx((10.2 + 9.8 + 10.0) / 3)

    def test_premarket_excluded(self):
        pm = et_bar(8, 0, 50.0, 50.0, 50.0, 50.0, 1_000_000)  # would skew massively
        mkt = et_bar(9, 30, 10.0, 10.2, 9.8, 10.0, 1000)
        assert calculate_vwap([pm, mkt]) == pytest.approx(calculate_vwap([mkt]))

    def test_no_market_bars_returns_none(self):
        pm = et_bar(8, 0, 10.0, 10.0, 10.0, 10.0, 1000)
        assert calculate_vwap([pm]) is None

    def test_zero_volume_skipped(self):
        b1 = et_bar(9, 30, 10.0, 10.0, 10.0, 10.0, 1000)
        b2 = et_bar(9, 31, 99.0, 99.0, 99.0, 99.0, 0)
        assert calculate_vwap([b1, b2]) == pytest.approx(10.0)

    def test_volume_weighting(self):
        b1 = et_bar(9, 30, 10.0, 10.0, 10.0, 10.0, 900)  # typical 10
        b2 = et_bar(9, 31, 20.0, 20.0, 20.0, 20.0, 100)  # typical 20
        assert calculate_vwap([b1, b2]) == pytest.approx(11.0)  # (10*900+20*100)/1000

    def test_accumulator_matches_oneshot(self):
        bars, _ = reclaim_setup_bars()
        acc = VwapAccumulator()
        for b in bars:
            acc.update(b)
        assert acc.value == pytest.approx(calculate_vwap(bars))


# ── Entry window ─────────────────────────────────────────────────────────────

class TestEntryWindow:
    def test_before_window(self):
        assert not in_entry_window(et_bar(9, 59, 10, 10, 10, 10, 1))

    def test_window_start(self):
        assert in_entry_window(et_bar(10, 0, 10, 10, 10, 10, 1))

    def test_mid_window(self):
        assert in_entry_window(et_bar(10, 45, 10, 10, 10, 10, 1))

    def test_window_end(self):
        assert in_entry_window(et_bar(11, 30, 10, 10, 10, 10, 1))

    def test_after_window(self):
        assert not in_entry_window(et_bar(11, 31, 10, 10, 10, 10, 1))


# ── Entry evaluation ─────────────────────────────────────────────────────────

class TestEvaluateEntry:
    def test_textbook_reclaim_fires(self):
        bars, cfg = reclaim_setup_bars()
        vwap = calculate_vwap(bars)
        sig = evaluate_entry(CANDIDATE, bars, vwap, cfg)
        assert sig is not None
        assert sig['entry_price'] == pytest.approx(10.12)  # reclaim_close mode
        assert sig['stop_price'] == pytest.approx(vwap - cfg.stop_vwap_offset)

    def test_reclaim_high_break_mode(self):
        bars, cfg = reclaim_setup_bars()
        cfg.entry_mode = 'reclaim_high_break'
        vwap = calculate_vwap(bars)
        sig = evaluate_entry(CANDIDATE, bars, vwap, cfg)
        assert sig is not None
        assert sig['entry_price'] == pytest.approx(10.15 + 0.01)

    def test_no_vwap_no_signal(self):
        bars, cfg = reclaim_setup_bars()
        assert evaluate_entry(CANDIDATE, bars, None, cfg) is None

    def test_outside_window_no_signal(self):
        bars, cfg = reclaim_setup_bars()
        # Move the reclaim bar to 11:45 (past window end)
        bars[-1]['time'] = ET.localize(datetime(2025, 1, 6, 11, 45))
        vwap = calculate_vwap(bars)
        assert evaluate_entry(CANDIDATE, bars, vwap, cfg) is None

    def test_close_below_vwap_no_signal(self):
        bars, cfg = reclaim_setup_bars()
        vwap = calculate_vwap(bars)
        bars[-1]['close'] = vwap - 0.05  # didn't actually reclaim
        assert evaluate_entry(CANDIDATE, bars, vwap, cfg) is None

    def test_red_bar_no_signal(self):
        bars, cfg = reclaim_setup_bars()
        vwap = calculate_vwap(bars)
        # Close above VWAP but below open — red candle, no buyer conviction
        bars[-1]['open'] = vwap + 0.50
        bars[-1]['close'] = vwap + 0.10
        assert evaluate_entry(CANDIDATE, bars, vwap, cfg) is None

    def test_no_vwap_test_no_signal(self):
        """No bars closed below VWAP in the lookback — there was no dip to reclaim."""
        bars = [
            et_bar(9, 30, 10.00, 10.10, 9.90, 10.00, 500_000),
            # all lookback bars stay well above VWAP
            et_bar(10, 0, 10.20, 10.30, 10.18, 10.25, 80_000),
            et_bar(10, 1, 10.25, 10.35, 10.22, 10.30, 80_000),
            et_bar(10, 2, 10.30, 10.40, 10.28, 10.35, 80_000),
            et_bar(10, 3, 10.35, 10.45, 10.32, 10.40, 80_000),
            et_bar(10, 4, 10.40, 10.50, 10.38, 10.45, 80_000),
            et_bar(10, 5, 10.45, 10.60, 10.42, 10.55, 300_000),
        ]
        cfg = VwapReclaimConfig(lookback_bars=5, min_bars_below=1)
        vwap = calculate_vwap(bars)
        assert evaluate_entry(CANDIDATE, bars, vwap, cfg) is None

    def test_weak_volume_no_signal(self):
        bars, cfg = reclaim_setup_bars()
        vwap = calculate_vwap(bars)
        bars[-1]['volume'] = 50_000  # below 1.2x the 80k lookback average
        assert evaluate_entry(CANDIDATE, bars, vwap, cfg) is None

    def test_too_few_bars_no_signal(self):
        bars, cfg = reclaim_setup_bars()
        vwap = calculate_vwap(bars)
        assert evaluate_entry(CANDIDATE, bars[-3:], vwap, cfg) is None


# ── Exit evaluation ──────────────────────────────────────────────────────────

class TestEvaluateExit:
    ENTRY = 10.12
    STOP = 9.96  # VWAP-anchored

    def _cfg(self, **kw):
        defaults = dict(profit_target_pct=5.0, max_hold_bars=30, trailing_stop_pct=0.0)
        defaults.update(kw)
        return VwapReclaimConfig(**defaults)

    def test_stop_loss(self):
        bar = et_bar(10, 10, 10.05, 10.06, 9.90, 9.92, 50_000)  # low pierces stop
        sig = evaluate_exit(self.ENTRY, self.STOP, 10.20, bar, 5, self._cfg())
        assert sig['exit_type'] == 'stop_loss'
        assert sig['exit_price'] == pytest.approx(self.STOP)

    def test_profit_target(self):
        target = self.ENTRY * 1.05
        bar = et_bar(10, 10, 10.50, target + 0.10, 10.45, target + 0.05, 50_000)
        sig = evaluate_exit(self.ENTRY, self.STOP, 10.20, bar, 5, self._cfg())
        assert sig['exit_type'] == 'profit_target'
        assert sig['exit_price'] == pytest.approx(target)

    def test_stop_beats_target_same_bar(self):
        """Wide bar hits both — stop wins (conservative assumption)."""
        target = self.ENTRY * 1.05
        bar = et_bar(10, 10, 10.05, target + 0.50, self.STOP - 0.10, 10.30, 50_000)
        sig = evaluate_exit(self.ENTRY, self.STOP, 10.20, bar, 5, self._cfg())
        assert sig['exit_type'] == 'stop_loss'

    def test_trailing_stop(self):
        cfg = self._cfg(trailing_stop_pct=2.0, profit_target_pct=50.0)
        highest = 11.00
        trail = highest * 0.98
        bar = et_bar(10, 10, 10.85, 10.86, trail - 0.05, trail - 0.02, 50_000)
        sig = evaluate_exit(self.ENTRY, self.STOP, highest, bar, 5, cfg)
        assert sig['exit_type'] == 'trailing_stop'
        assert sig['exit_price'] == pytest.approx(trail)

    def test_time_stop(self):
        cfg = self._cfg(max_hold_bars=10)
        bar = et_bar(10, 30, 10.20, 10.25, 10.18, 10.22, 50_000)
        sig = evaluate_exit(self.ENTRY, self.STOP, 10.30, bar, 10, cfg)
        assert sig['exit_type'] == 'time_stop'
        assert sig['exit_price'] == pytest.approx(10.22)

    def test_hold_no_exit(self):
        bar = et_bar(10, 10, 10.20, 10.25, 10.15, 10.22, 50_000)
        assert evaluate_exit(self.ENTRY, self.STOP, 10.25, bar, 5, self._cfg()) is None


# ── Config serialization ─────────────────────────────────────────────────────

class TestConfig:
    def test_roundtrip(self):
        cfg = VwapReclaimConfig(min_gap_pct=15.0, max_hold_bars=20)
        assert VwapReclaimConfig.from_dict(cfg.to_dict()) == cfg

    def test_from_dict_ignores_unknown(self):
        cfg = VwapReclaimConfig.from_dict({'min_gap_pct': 12.0, 'bogus_key': 99})
        assert cfg.min_gap_pct == 12.0
