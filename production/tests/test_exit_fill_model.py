"""
Tests for the Gate 0 honest exit fill model (docs/DEEP_REVIEW_2026_09.md §1/§4).

These test the SIMULATOR-layer fill resolution in `simulator.fill_model`
(resolve_honest_exit_fill, apply_exit_slippage) plus the trail-peak-lag
contract that scalp_simulation.py / vwap_simulation.py /
micro_pullback_simulation.py implement around each engine's evaluate_exit().
No DB required — synthetic 3-5 bar tapes only. The engines' evaluate_exit()
itself is untouched by Gate 0 (still returns the exact trigger level, which
is what the live runners consume), so these tests exercise the simulator
layer that turns that trigger into a booked fill.
"""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from dataclasses import dataclass

import pytest

from simulator.fill_model import (
    resolve_honest_exit_fill, apply_exit_slippage, uses_honest_exit_fill,
)
from trading.scalp_engine import evaluate_exit as scalp_evaluate_exit
from trading.scalp_models import ScalpConfig


def bar(o, h, l, c):
    return {'open': o, 'high': h, 'low': l, 'close': c}


@dataclass
class _Cfg:
    exit_slippage_pct: float = 0.3
    exit_fill_mode: str = 'honest'


# ── resolve_honest_exit_fill ────────────────────────────────────────────────

class TestResolveHonestExitFill:
    def test_stop_gap_through_at_open(self):
        """Trigger bar's own OPEN is already through the stop -> fill at that open."""
        cfg = _Cfg(exit_slippage_pct=0.0)
        trigger_bar = bar(o=9.00, h=9.10, l=8.80, c=8.90)  # opened below stop
        signal = {'exit_price': 9.50, 'exit_type': 'stop_loss'}
        trig, fill = resolve_honest_exit_fill(signal, trigger_bar, next_bar=None, config=cfg)
        assert trig == 9.50
        assert fill == 9.00  # trigger bar's open, not the stop level

    def test_stop_next_open_above_stop_fills_at_stop(self):
        """Stop touched intrabar, but next bar opens back above the stop level
        -> resting-stop fill caps at the stop price (not the higher open)."""
        cfg = _Cfg(exit_slippage_pct=0.0)
        trigger_bar = bar(o=10.00, h=10.05, l=9.40, c=9.90)  # low pierced stop=9.50
        next_bar = bar(o=9.80, h=10.00, l=9.70, c=9.95)      # opens above stop
        signal = {'exit_price': 9.50, 'exit_type': 'stop_loss'}
        trig, fill = resolve_honest_exit_fill(signal, trigger_bar, next_bar, cfg)
        assert trig == 9.50
        assert fill == 9.50  # min(stop, next_open) = min(9.50, 9.80) = 9.50

    def test_stop_next_open_below_stop_fills_at_open(self):
        """Next bar gaps down below the stop -> fill at that lower open (gap-through)."""
        cfg = _Cfg(exit_slippage_pct=0.0)
        trigger_bar = bar(o=10.00, h=10.05, l=9.40, c=9.90)
        next_bar = bar(o=9.20, h=9.30, l=9.00, c=9.10)  # gapped below stop=9.50
        signal = {'exit_price': 9.50, 'exit_type': 'stop_loss'}
        trig, fill = resolve_honest_exit_fill(signal, trigger_bar, next_bar, cfg)
        assert trig == 9.50
        assert fill == 9.20  # min(9.50, 9.20) = 9.20

    def test_target_fills_at_next_open(self):
        cfg = _Cfg(exit_slippage_pct=0.0)
        trigger_bar = bar(o=10.00, h=10.60, l=9.95, c=10.30)  # touched target=10.50
        next_bar = bar(o=10.55, h=10.70, l=10.40, c=10.60)
        signal = {'exit_price': 10.50, 'exit_type': 'profit_target'}
        trig, fill = resolve_honest_exit_fill(signal, trigger_bar, next_bar, cfg)
        assert trig == 10.50
        assert fill == 10.55  # next bar's open, not the target level

    def test_trailing_stop_fills_at_next_open(self):
        cfg = _Cfg(exit_slippage_pct=0.0)
        trigger_bar = bar(o=10.30, h=10.40, l=10.00, c=10.10)
        next_bar = bar(o=10.05, h=10.15, l=9.95, c=10.00)
        signal = {'exit_price': 10.10, 'exit_type': 'trailing_stop'}
        trig, fill = resolve_honest_exit_fill(signal, trigger_bar, next_bar, cfg)
        assert trig == 10.10
        assert fill == 10.05

    def test_end_of_tape_fallback_to_trigger_close(self):
        """No next bar (end of available data) -> fill at trigger bar's close."""
        cfg = _Cfg(exit_slippage_pct=0.0)
        trigger_bar = bar(o=10.30, h=10.40, l=10.00, c=10.12)
        signal = {'exit_price': 10.10, 'exit_type': 'trailing_stop'}
        trig, fill = resolve_honest_exit_fill(signal, trigger_bar, next_bar=None, config=cfg)
        assert trig == 10.10
        assert fill == 10.12  # trigger bar close

    def test_time_stop_fills_at_next_open_else_close(self):
        cfg = _Cfg(exit_slippage_pct=0.0)
        trigger_bar = bar(o=10.00, h=10.10, l=9.95, c=10.05)
        next_bar = bar(o=10.02, h=10.20, l=10.00, c=10.15)
        signal = {'exit_price': 10.05, 'exit_type': 'time_stop'}
        trig, fill = resolve_honest_exit_fill(signal, trigger_bar, next_bar, cfg)
        assert fill == 10.02
        trig2, fill2 = resolve_honest_exit_fill(signal, trigger_bar, None, cfg)
        assert fill2 == 10.05  # trigger bar close, no next bar

    def test_slippage_applied_on_honest_fill(self):
        cfg = _Cfg(exit_slippage_pct=0.3)
        trigger_bar = bar(o=10.00, h=10.10, l=9.95, c=10.05)
        next_bar = bar(o=10.00, h=10.20, l=9.98, c=10.15)
        signal = {'exit_price': 9.90, 'exit_type': 'profit_target'}  # not actually hit at open but tests slippage math
        trig, fill = resolve_honest_exit_fill(signal, trigger_bar, next_bar, cfg)
        expected = 10.00 * (1 - 0.3 / 100)
        assert fill == pytest.approx(expected)

    def test_apply_exit_slippage_helper(self):
        cfg = _Cfg(exit_slippage_pct=1.0)
        assert apply_exit_slippage(100.0, cfg) == pytest.approx(99.0)

    def test_uses_honest_exit_fill_flag(self):
        assert uses_honest_exit_fill(_Cfg(exit_fill_mode='honest')) is True
        assert uses_honest_exit_fill(_Cfg(exit_fill_mode='par')) is False
        # default (attribute absent) is 'honest'
        class _Bare:
            pass
        assert uses_honest_exit_fill(_Bare()) is True


# ── 'par' mode is untouched ─────────────────────────────────────────────────

class TestParModeUnchanged:
    def test_par_config_default_still_perfect_fill_in_engine(self):
        """The engine itself never changes: it always returns the exact
        trigger level regardless of exit_fill_mode. par vs honest is decided
        entirely by whether the simulator calls resolve_honest_exit_fill."""
        config = ScalpConfig(stop_loss_pct=2.0, profit_target_pct=5.0,
                              trailing_stop_pct=0.0, max_hold_bars=10,
                              exit_fill_mode='par')
        entry = 10.0
        current_bar = bar(o=9.90, h=9.95, l=9.70, c=9.80)  # low <= stop(9.80)
        signal = scalp_evaluate_exit(entry, entry, current_bar, bars_held=1, config=config)
        assert signal is not None
        assert signal['exit_type'] == 'stop_loss'
        assert signal['exit_price'] == pytest.approx(9.80)  # exact stop level, par-style


# ── Trail-peak lag: par (same-bar) vs honest (prior-bars-only) ─────────────

class TestTrailPeakLag:
    """A bar that makes a NEW high and then dips through the trail on the
    SAME bar: par mode uses that bar's own high to compute the trail (can
    exit on the very bar that made the high); honest mode must not — the
    peak used to test bar N is only known through bar N-1."""

    def test_par_same_bar_peak_can_trigger_trail_immediately(self):
        config = ScalpConfig(stop_loss_pct=50.0, profit_target_pct=50.0,
                              trailing_stop_pct=1.0, max_hold_bars=10,
                              exit_fill_mode='par')
        entry = 10.0
        # Same bar makes a new high of 12.0, then dips to 11.80 (< 12.0*0.99=11.88)
        current_bar = bar(o=11.00, h=12.00, l=11.80, c=11.90)
        highest_including_this_bar = max(entry, 12.00)  # par: peak updated BEFORE test
        signal = scalp_evaluate_exit(
            entry, highest_including_this_bar, current_bar, bars_held=1, config=config)
        assert signal is not None
        assert signal['exit_type'] == 'trailing_stop'

    def test_honest_prior_bar_peak_does_not_trigger_on_the_new_high_bar(self):
        config = ScalpConfig(stop_loss_pct=50.0, profit_target_pct=50.0,
                              trailing_stop_pct=1.0, max_hold_bars=10,
                              exit_fill_mode='honest')
        entry = 10.0
        current_bar = bar(o=11.00, h=12.00, l=11.80, c=11.90)
        highest_through_prior_bar = entry  # honest: peak lags by one bar (no prior move yet)
        signal = scalp_evaluate_exit(
            entry, highest_through_prior_bar, current_bar, bars_held=1, config=config)
        # low 11.80 vs trail from OLD peak (10.0 * 0.99 = 9.90) -> not hit
        assert signal is None
