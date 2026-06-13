"""
Unit tests for the Micro-Pullback engine (strategy #3).
Pure-function tests — no DB, no network. Mirrors test_vwap_engine.py.
"""
import os
import sys
from datetime import datetime

import pytz

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from trading.micro_pullback_models import MicroPullbackConfig
from trading.micro_pullback_engine import (
    ema, in_entry_window, evaluate_entry, evaluate_exit,
)

ET = pytz.timezone('US/Eastern')


def _bar(minute_offset, o, h, l, c, v, day=(2025, 3, 17)):
    """Build a bar dict with an ET time at 9:40 + minute_offset."""
    t = ET.localize(datetime(day[0], day[1], day[2], 9, 40) ).replace(second=0)
    t = t.replace(minute=40 + minute_offset) if 40 + minute_offset < 60 else \
        t.replace(hour=10, minute=(40 + minute_offset) - 60)
    return {'open': o, 'high': h, 'low': l, 'close': c, 'volume': v, '_et': t, 'time': t}


def _valid_pullback_bars():
    """A textbook micro-pullback: ramp -> peak -> 3 light-vol pullback bars ->
    green resumption that breaks the pullback high on expanding volume."""
    return [
        _bar(0, 10.00, 10.05, 9.98, 10.03, 1000),
        _bar(1, 10.03, 10.10, 10.00, 10.08, 1000),
        _bar(2, 10.08, 10.15, 10.05, 10.13, 1000),
        _bar(3, 10.13, 10.20, 10.10, 10.18, 1000),
        _bar(4, 10.18, 10.28, 10.15, 10.25, 1500),
        _bar(5, 10.25, 10.40, 10.22, 10.38, 2500),
        _bar(6, 10.38, 10.50, 10.35, 10.48, 3000),   # PEAK
        _bar(7, 10.46, 10.45, 10.40, 10.42, 1000),   # pullback 1 (light)
        _bar(8, 10.42, 10.46, 10.38, 10.41, 900),    # pullback 2 (light)
        _bar(9, 10.41, 10.44, 10.37, 10.40, 800),    # pullback 3 (light)
        _bar(10, 10.41, 10.55, 10.40, 10.52, 2000),  # resumption: green, breaks 10.46
    ]


CFG = MicroPullbackConfig()


# ── ema() ────────────────────────────────────────────────────────────────────

def test_ema_none_below_period():
    assert ema([1, 2, 3], period=9) is None


def test_ema_constant_series():
    assert ema([5.0] * 12, period=9) == 5.0


def test_ema_standard_formula():
    # period=3, k=0.5: seed SMA(10,11,12)=11; 13->12; 14->13
    assert ema([10, 11, 12, 13, 14], period=3) == 13.0


# ── window gate ──────────────────────────────────────────────────────────────

def test_in_window_true():
    assert in_entry_window(_bar(20, 10, 10, 10, 10, 1)) is True   # 10:00


def test_before_window_false():
    b = _bar(0, 10, 10, 10, 10, 1)
    b['_et'] = b['_et'].replace(hour=9, minute=35)
    assert in_entry_window(b) is False


def test_after_window_false():
    b = _bar(0, 10, 10, 10, 10, 1)
    b['_et'] = b['_et'].replace(hour=10, minute=45)
    assert in_entry_window(b) is False


# ── evaluate_entry ───────────────────────────────────────────────────────────

def test_valid_entry_fires():
    sig = evaluate_entry({'symbol': 'TST'}, _valid_pullback_bars(), CFG)
    assert sig is not None
    assert round(sig['entry_price'], 2) == 10.47   # pullback high 10.46 + 0.01
    assert round(sig['stop_price'], 2) == 10.36     # pullback low 10.37 - 0.01
    assert sig['entry_price'] > sig['stop_price']


def test_no_entry_when_too_few_bars():
    bars = _valid_pullback_bars()[:5]
    assert evaluate_entry({'symbol': 'TST'}, bars, CFG) is None


def test_no_entry_outside_window():
    bars = _valid_pullback_bars()
    for b in bars:
        b['_et'] = b['_et'].replace(hour=11, minute=0)
    assert evaluate_entry({'symbol': 'TST'}, bars, CFG) is None


def test_no_entry_red_resumption():
    bars = _valid_pullback_bars()
    bars[-1]['close'] = bars[-1]['open'] - 0.05  # red bar
    assert evaluate_entry({'symbol': 'TST'}, bars, CFG) is None


def test_no_entry_no_break_of_pullback_high():
    bars = _valid_pullback_bars()
    bars[-1]['high'] = 10.42  # below pullback high 10.46
    bars[-1]['close'] = 10.41
    assert evaluate_entry({'symbol': 'TST'}, bars, CFG) is None


def test_no_entry_deep_pullback():
    bars = _valid_pullback_bars()
    bars[8]['low'] = 9.30   # >5% below peak 10.50 -> not shallow
    assert evaluate_entry({'symbol': 'TST'}, bars, CFG) is None


def test_no_entry_heavy_pullback_volume():
    bars = _valid_pullback_bars()
    for i in (7, 8, 9):
        bars[i]['volume'] = 3000  # >= peak_vol * 0.8 -> not a rest
    assert evaluate_entry({'symbol': 'TST'}, bars, CFG) is None


def test_no_entry_no_volume_expansion():
    bars = _valid_pullback_bars()
    bars[-1]['volume'] = 100  # < avg pullback vol * resume_vol_mult
    assert evaluate_entry({'symbol': 'TST'}, bars, CFG) is None


def test_no_entry_below_ema9():
    bars = _valid_pullback_bars()
    bars[-1]['close'] = 9.00   # well below the EMA-9
    bars[-1]['open'] = 8.90
    assert evaluate_entry({'symbol': 'TST'}, bars, CFG) is None


# ── evaluate_exit ────────────────────────────────────────────────────────────

def test_exit_stop_loss():
    sig = evaluate_exit(10.0, 9.8, 10.0, _bar(0, 10, 10, 9.7, 9.75, 100), 1, CFG)
    assert sig['exit_type'] == 'stop_loss'
    assert sig['exit_price'] == 9.8


def test_exit_profit_target():
    cfg = MicroPullbackConfig(profit_target_pct=5.0)
    # stop 9.5 well below the bar low so only the target can fire
    sig = evaluate_exit(10.0, 9.5, 10.5, _bar(0, 10.4, 10.6, 10.3, 10.5, 100), 2, cfg)
    assert sig['exit_type'] == 'profit_target'
    assert round(sig['exit_price'], 2) == 10.5  # 10.0 * 1.05


def test_exit_time_stop():
    cfg = MicroPullbackConfig(max_hold_bars=3, profit_target_pct=99.0)
    sig = evaluate_exit(10.0, 9.5, 10.1, _bar(0, 10.05, 10.12, 10.0, 10.08, 100), 3, cfg)
    assert sig['exit_type'] == 'time_stop'


def test_exit_none_when_holding():
    cfg = MicroPullbackConfig(max_hold_bars=20, profit_target_pct=99.0, trailing_stop_pct=0.0)
    sig = evaluate_exit(10.0, 9.5, 10.2, _bar(0, 10.1, 10.2, 10.05, 10.15, 100), 2, cfg)
    assert sig is None
