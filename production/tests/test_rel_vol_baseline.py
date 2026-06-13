"""
Unit tests for the live rel-vol parity helper (Gap #1).

Covers compute_rel_vol() — the pure function shared by both live runners —
including every fallback path that must collapse to the sim's 10.0 default.

Run: python -m pytest production/tests/test_rel_vol_baseline.py -v
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from trading.rel_vol_live import compute_rel_vol, DEFAULT_REL_VOL


BASELINES = {'AAA': 100_000.0, 'BBB': 50_000.0, 'ZERO': 0.0}


def test_real_computation():
    # 250k today / 100k baseline = 2.5x
    assert compute_rel_vol('AAA', 250_000.0, BASELINES) == 2.5
    assert compute_rel_vol('BBB', 200_000.0, BASELINES) == 4.0


def test_symbol_missing_from_baseline_falls_back():
    # Recent IPO / ticker change — sim defaults to 10.0, live must match.
    assert compute_rel_vol('MISSING', 999_999.0, BASELINES) == DEFAULT_REL_VOL


def test_no_baseline_file_falls_back():
    # Fetch failed → baselines is None → 10.0 for every symbol.
    assert compute_rel_vol('AAA', 250_000.0, None) == DEFAULT_REL_VOL
    assert compute_rel_vol('AAA', 250_000.0, {}) == DEFAULT_REL_VOL


def test_zero_or_negative_baseline_falls_back():
    assert compute_rel_vol('ZERO', 250_000.0, BASELINES) == DEFAULT_REL_VOL


def test_unknown_or_zero_quote_volume_falls_back():
    assert compute_rel_vol('AAA', None, BASELINES) == DEFAULT_REL_VOL
    assert compute_rel_vol('AAA', 0.0, BASELINES) == DEFAULT_REL_VOL
    assert compute_rel_vol('AAA', -5.0, BASELINES) == DEFAULT_REL_VOL


def test_filter_semantics_threshold():
    # With min_relative_volume=2.79 (trial 173), a 2.5x candidate is rejected,
    # a 3.0x candidate passes.
    min_rv = 2.79
    rv_low = compute_rel_vol('AAA', 250_000.0, BASELINES)   # 2.5
    rv_high = compute_rel_vol('AAA', 300_000.0, BASELINES)  # 3.0
    assert rv_low < min_rv
    assert rv_high >= min_rv


def test_missing_symbol_passes_filter_like_sim():
    # No-history symbols default to 10.0 and therefore pass any sane filter,
    # exactly as the simulator treats them.
    assert compute_rel_vol('MISSING', 1.0, BASELINES) >= 2.79
