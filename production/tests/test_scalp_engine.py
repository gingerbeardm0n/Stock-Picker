"""
Unit tests for Opening Bell Scalp strategy components.
Tests: ScalpConfig, ScalpEngine (entry/exit), GapperRanker.

Run: python -m pytest production/tests/test_scalp_engine.py -v
"""

import sys
import os
import pytest
from datetime import datetime
import pytz

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from trading.scalp_models import ScalpConfig
from trading.scalp_engine import evaluate_entry, evaluate_exit, get_premarket_high
from trading.scalp_ranker import rank_candidates, get_top_candidate, _float_score, _news_score

ET = pytz.timezone('US/Eastern')


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_bar(hour, minute, open_, high, low, close, volume=10000):
    """Create a bar dict with ET-aware timestamp."""
    t = ET.localize(datetime(2025, 3, 15, hour, minute))
    return {
        'time': t,
        'open': open_,
        'high': high,
        'low': low,
        'close': close,
        'volume': volume,
    }


def _make_candidate(symbol='TEST', gap_pct=15.0, rel_vol=8.0,
                    float_shares=10_000_000, has_news=True, news_tier='tier1'):
    return {
        'symbol': symbol,
        'gap_pct': gap_pct,
        'rel_vol': rel_vol,
        'float_shares': float_shares,
        'has_news': has_news,
        'news_tier': news_tier,
    }


# ═══════════════════════════════════════════════════════════════════════════
# ScalpConfig tests
# ═══════════════════════════════════════════════════════════════════════════

class TestScalpConfig:
    def test_defaults(self):
        cfg = ScalpConfig()
        assert cfg.min_gap_pct == 10.0
        assert cfg.require_news is True
        assert cfg.entry_mode == 'pm_high_break'
        assert cfg.max_hold_bars == 5

    def test_to_dict_roundtrip(self):
        cfg = ScalpConfig(min_gap_pct=15.0, stop_loss_pct=3.0)
        d = cfg.to_dict()
        cfg2 = ScalpConfig.from_dict(d)
        assert cfg2.min_gap_pct == 15.0
        assert cfg2.stop_loss_pct == 3.0

    def test_from_dict_ignores_unknown(self):
        d = {'min_gap_pct': 12.0, 'bogus_key': 999}
        cfg = ScalpConfig.from_dict(d)
        assert cfg.min_gap_pct == 12.0
        assert not hasattr(cfg, 'bogus_key')

    def test_param_count(self):
        """The scalp config should have exactly 14 tunable parameters."""
        cfg = ScalpConfig()
        d = cfg.to_dict()
        assert len(d) == 14, f"Expected 14 params, got {len(d)}: {list(d.keys())}"


# ═══════════════════════════════════════════════════════════════════════════
# Premarket high tests
# ═══════════════════════════════════════════════════════════════════════════

class TestPremarketHigh:
    def test_finds_highest(self):
        bars = [
            _make_bar(8, 0, 5.0, 5.5, 4.9, 5.3),
            _make_bar(8, 30, 5.3, 6.0, 5.2, 5.8),
            _make_bar(9, 0, 5.8, 5.9, 5.7, 5.85),
            _make_bar(9, 30, 5.9, 6.5, 5.8, 6.3),  # at 9:30 — NOT premarket
        ]
        pm_high = get_premarket_high(bars)
        assert pm_high == 6.0  # 8:30 bar had high of 6.0

    def test_no_premarket_bars(self):
        bars = [_make_bar(9, 30, 5.0, 5.5, 4.9, 5.3)]
        assert get_premarket_high(bars) is None

    def test_empty_bars(self):
        assert get_premarket_high([]) is None


# ═══════════════════════════════════════════════════════════════════════════
# Entry engine tests
# ═══════════════════════════════════════════════════════════════════════════

class TestEvaluateEntry:
    def test_market_open_first_bar(self):
        cfg = ScalpConfig(entry_mode='market_open', stop_loss_pct=2.0)
        bar = _make_bar(9, 30, 10.0, 10.5, 9.8, 10.3)
        candidate = _make_candidate()

        signal = evaluate_entry(candidate, bar, premarket_high=9.5,
                                bars_since_open=0, config=cfg)
        assert signal is not None
        assert signal['entry_price'] == 10.0  # open price
        assert signal['stop_price'] == pytest.approx(9.80, abs=0.01)

    def test_market_open_not_first_bar(self):
        cfg = ScalpConfig(entry_mode='market_open')
        bar = _make_bar(9, 31, 10.0, 10.5, 9.8, 10.3)

        signal = evaluate_entry(_make_candidate(), bar, premarket_high=9.5,
                                bars_since_open=1, config=cfg)
        assert signal is None  # only enters on bar 0

    def test_pm_high_break_triggers(self):
        cfg = ScalpConfig(entry_mode='pm_high_break', min_pm_high_break_pct=0.0)
        bar = _make_bar(9, 30, 9.4, 9.8, 9.3, 9.6)  # high=9.8 > PM high 9.5

        signal = evaluate_entry(_make_candidate(), bar, premarket_high=9.5,
                                bars_since_open=0, config=cfg)
        assert signal is not None

    def test_pm_high_break_no_break(self):
        cfg = ScalpConfig(entry_mode='pm_high_break', min_pm_high_break_pct=0.0)
        bar = _make_bar(9, 30, 9.0, 9.4, 8.9, 9.2)  # high=9.4 < PM high 9.5

        signal = evaluate_entry(_make_candidate(), bar, premarket_high=9.5,
                                bars_since_open=0, config=cfg)
        assert signal is None

    def test_pm_high_break_with_threshold(self):
        cfg = ScalpConfig(entry_mode='pm_high_break', min_pm_high_break_pct=1.0)
        # PM high = 10.0, threshold = 10.10 (1% above)
        bar = _make_bar(9, 30, 10.0, 10.05, 9.9, 10.02)  # high=10.05 < 10.10

        signal = evaluate_entry(_make_candidate(), bar, premarket_high=10.0,
                                bars_since_open=0, config=cfg)
        assert signal is None  # didn't break 1% above PM high

    def test_first_green_triggers(self):
        cfg = ScalpConfig(entry_mode='first_green')
        bar = _make_bar(9, 30, 10.0, 10.5, 9.8, 10.3)  # close > open = green

        signal = evaluate_entry(_make_candidate(), bar, premarket_high=9.5,
                                bars_since_open=0, config=cfg)
        assert signal is not None
        assert signal['entry_price'] == 10.3  # close price

    def test_first_green_red_bar(self):
        cfg = ScalpConfig(entry_mode='first_green')
        bar = _make_bar(9, 30, 10.0, 10.2, 9.5, 9.8)  # close < open = red

        signal = evaluate_entry(_make_candidate(), bar, premarket_high=9.5,
                                bars_since_open=0, config=cfg)
        assert signal is None

    def test_max_entry_bars_exceeded(self):
        cfg = ScalpConfig(entry_mode='pm_high_break', max_entry_bars=2)
        bar = _make_bar(9, 33, 9.0, 10.0, 9.0, 9.8)

        signal = evaluate_entry(_make_candidate(), bar, premarket_high=9.5,
                                bars_since_open=3, config=cfg)
        assert signal is None  # bars_since_open=3 > max_entry_bars=2


# ═══════════════════════════════════════════════════════════════════════════
# Exit engine tests
# ═══════════════════════════════════════════════════════════════════════════

class TestEvaluateExit:
    def test_stop_loss(self):
        cfg = ScalpConfig(stop_loss_pct=2.0, profit_target_pct=5.0, max_hold_bars=10)
        bar = _make_bar(9, 31, 9.8, 9.85, 9.7, 9.75)
        # Entry at 10.0, stop at 9.80. Bar low 9.7 hits stop.

        signal = evaluate_exit(10.0, 10.0, bar, bars_held=1, config=cfg)
        assert signal is not None
        assert signal['exit_type'] == 'stop_loss'
        assert signal['exit_price'] == pytest.approx(9.80, abs=0.01)

    def test_profit_target(self):
        cfg = ScalpConfig(stop_loss_pct=2.0, profit_target_pct=3.0, max_hold_bars=10)
        bar = _make_bar(9, 31, 10.1, 10.35, 10.0, 10.3)
        # Entry at 10.0, target at 10.30. Bar high 10.35 hits target.

        signal = evaluate_exit(10.0, 10.1, bar, bars_held=1, config=cfg)
        assert signal is not None
        assert signal['exit_type'] == 'profit_target'
        assert signal['exit_price'] == pytest.approx(10.30, abs=0.01)

    def test_time_stop(self):
        cfg = ScalpConfig(stop_loss_pct=5.0, profit_target_pct=10.0, max_hold_bars=3)
        bar = _make_bar(9, 33, 10.1, 10.2, 10.0, 10.15)
        # Neither stop nor target hit, but bars_held=3 = max_hold_bars.

        signal = evaluate_exit(10.0, 10.2, bar, bars_held=3, config=cfg)
        assert signal is not None
        assert signal['exit_type'] == 'time_stop'

    def test_trailing_stop(self):
        cfg = ScalpConfig(stop_loss_pct=5.0, profit_target_pct=10.0,
                          max_hold_bars=10, trailing_stop_pct=1.5)
        # Entry at 10.0, highest was 10.50.
        # Trail stop = 10.50 * (1 - 1.5%) = 10.3425
        bar = _make_bar(9, 33, 10.4, 10.45, 10.30, 10.35)
        # Bar low 10.30 < trail stop 10.3425

        signal = evaluate_exit(10.0, 10.50, bar, bars_held=3, config=cfg)
        assert signal is not None
        assert signal['exit_type'] == 'trailing_stop'

    def test_trailing_stop_disabled(self):
        cfg = ScalpConfig(stop_loss_pct=5.0, profit_target_pct=10.0,
                          max_hold_bars=10, trailing_stop_pct=0.0)
        bar = _make_bar(9, 33, 10.4, 10.45, 10.30, 10.35)

        signal = evaluate_exit(10.0, 10.50, bar, bars_held=3, config=cfg)
        assert signal is None  # no exit triggers

    def test_no_exit_normal_bar(self):
        cfg = ScalpConfig(stop_loss_pct=2.0, profit_target_pct=5.0, max_hold_bars=5)
        bar = _make_bar(9, 31, 10.0, 10.2, 9.9, 10.1)
        # No stop, no target, not time-expired.

        signal = evaluate_exit(10.0, 10.2, bar, bars_held=1, config=cfg)
        assert signal is None

    def test_stop_takes_priority_over_trailing(self):
        """If both stop and trailing would trigger, stop wins (checked first)."""
        cfg = ScalpConfig(stop_loss_pct=2.0, profit_target_pct=10.0,
                          max_hold_bars=10, trailing_stop_pct=1.0)
        bar = _make_bar(9, 33, 9.7, 9.75, 9.5, 9.6)
        # Entry 10.0, stop at 9.80, bar low 9.5 hits stop.

        signal = evaluate_exit(10.0, 10.2, bar, bars_held=3, config=cfg)
        assert signal['exit_type'] == 'stop_loss'


# ═══════════════════════════════════════════════════════════════════════════
# Ranker tests
# ═══════════════════════════════════════════════════════════════════════════

class TestRanker:
    def test_rank_order(self):
        candidates = [
            _make_candidate('A', gap_pct=10, rel_vol=5, has_news=False, news_tier='none'),
            _make_candidate('B', gap_pct=20, rel_vol=10, has_news=True, news_tier='tier1'),
            _make_candidate('C', gap_pct=15, rel_vol=8, has_news=True, news_tier='tier2'),
        ]
        ranked = rank_candidates(candidates)
        assert ranked[0]['symbol'] == 'B'  # best overall

    def test_news_is_decisive(self):
        """Two identical gappers except news — news one should win."""
        candidates = [
            _make_candidate('NO_NEWS', gap_pct=15, rel_vol=8, has_news=False, news_tier='none'),
            _make_candidate('HAS_NEWS', gap_pct=15, rel_vol=8, has_news=True, news_tier='tier1'),
        ]
        ranked = rank_candidates(candidates)
        assert ranked[0]['symbol'] == 'HAS_NEWS'

    def test_empty_candidates(self):
        assert rank_candidates([]) == []

    def test_single_candidate(self):
        ranked = rank_candidates([_make_candidate('ONLY')])
        assert len(ranked) == 1
        assert ranked[0]['symbol'] == 'ONLY'
        assert 'scalp_score' in ranked[0]

    def test_get_top_candidate(self):
        candidates = [
            _make_candidate('A', gap_pct=10, rel_vol=5),
            _make_candidate('B', gap_pct=20, rel_vol=10),
        ]
        top = get_top_candidate(candidates)
        assert top['symbol'] == 'B'

    def test_get_top_none(self):
        assert get_top_candidate([]) is None

    def test_float_score(self):
        assert _float_score(3_000_000) == 1.0
        assert _float_score(8_000_000) == 0.7
        assert _float_score(15_000_000) == 0.5
        assert _float_score(30_000_000) == 0.2
        assert _float_score(None) == 0.3

    def test_news_score(self):
        assert _news_score(True, 'tier1') == 1.0
        assert _news_score(True, 'tier2') == 0.7
        assert _news_score(True, 'tier3') == 0.4
        assert _news_score(True, 'presence') == 0.0  # presence no longer a catalyst
        assert _news_score(False, 'tier1') == 0.0
        assert _news_score(False, None) == 0.0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
