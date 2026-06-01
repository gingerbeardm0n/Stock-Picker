"""
Unit tests for momentum_scanner.qualifies_momentum().

Truth-table over all 6 gates. No DB, no network.
Run: python production/trading/test_momentum_scanner.py
"""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytz
from datetime import datetime

from trading.momentum_scanner import qualifies_momentum
from trading.models import MomentumScanConfig

ET = pytz.timezone('US/Eastern')


def _time(hour: int, minute: int = 0) -> datetime:
    """ET datetime on a fixed date."""
    return ET.localize(datetime(2025, 1, 6, hour, minute, 0))


def _cfg(**kwargs) -> MomentumScanConfig:
    return MomentumScanConfig(**kwargs)


# ── Baseline: a stock that passes every gate ──────────────────────────────────
_BASE = dict(
    price=5.0,
    prior_close=4.0,       # 25% gain -> passes G6 (5% threshold)
    high_of_day=5.0,       # price == hod -> passes G2
    rel_vol=10.0,          # 10x -> passes G1 (5x threshold)
    float_shares=5_000_000,# 5M -> passes G4 (20M cap)
    et_time=_time(9, 45),  # 9:45 AM -> passes G3 (9:30-11:00 window)
    cfg=_cfg(),
)


def _make(**overrides):
    kw = dict(_BASE)
    kw.update(overrides)
    return kw


def _test(name: str, expected: bool, **overrides) -> bool:
    result = qualifies_momentum(**_make(**overrides))
    ok = result == expected
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] {name}: got {result}, expected {expected}")
    return ok


def run_tests() -> bool:
    passed = failed = 0

    def T(name, expected, **kw):
        nonlocal passed, failed
        if _test(name, expected, **kw):
            passed += 1
        else:
            failed += 1

    print("-- Baseline " + "-"*51)
    T("baseline all gates pass", True)

    print("\n-- G5: price range " + "-"*44)
    T("G5 price below min_price", False, price=0.5, high_of_day=0.5, prior_close=0.4)
    T("G5 price above max_price", False, price=25.0, high_of_day=25.0, prior_close=20.0)
    T("G5 price exactly at min_price", True,
      price=1.0, prior_close=0.8, high_of_day=1.0)   # 25% gain, valid
    T("G5 price exactly at max_price", True,
      price=20.0, prior_close=16.0, high_of_day=20.0)

    print("\n-- G6: intraday gain " + "-"*42)
    # 5% gain exactly: price = 4.0 * 1.05 = 4.20
    T("G6 gain exactly at 5% threshold", True,
      price=4.20, prior_close=4.0, high_of_day=4.20)
    # Just below 5%: 4.19 / 4.0 = 4.75% gain
    T("G6 gain just below 5% threshold", False,
      price=4.19, prior_close=4.0, high_of_day=4.19)
    T("G6 prior_close zero -> reject", False, prior_close=0.0)
    T("G6 prior_close negative -> reject", False, prior_close=-1.0)
    T("G6 custom min_intraday_gain=10%", False,
      price=4.20, prior_close=4.0, high_of_day=4.20,
      cfg=_cfg(min_intraday_gain=10.0))

    print("\n-- G2: high-of-day " + "-"*44)
    T("G2 price == hod (strict hod_tol=0)", True)
    T("G2 price 1 cent below hod (strict)", False, price=4.99, high_of_day=5.0)
    T("G2 price 2% below hod with hod_tol=0.02", True,
      price=4.91, high_of_day=5.01, cfg=_cfg(hod_tol=0.02))
    T("G2 price 2.1% below hod with hod_tol=0.02", False,
      price=4.90, high_of_day=5.01, cfg=_cfg(hod_tol=0.02))
    # hod_tol=0.05 -> threshold=4.75; price=4.76 passes
    T("G2 price within 5% tol", True,
      price=4.76, high_of_day=5.01, cfg=_cfg(hod_tol=0.05))

    print("\n-- G1: relative volume " + "-"*41)
    T("G1 rel_vol exactly at 5x threshold", True, rel_vol=5.0)
    T("G1 rel_vol just below threshold", False, rel_vol=4.99)
    T("G1 rel_vol zero", False, rel_vol=0.0)
    T("G1 custom min_rel_vol=10", False, rel_vol=9.9,
      cfg=_cfg(min_relative_volume=10.0))
    T("G1 custom min_rel_vol=10 passes", True, rel_vol=10.0,
      cfg=_cfg(min_relative_volume=10.0))

    print("\n-- G3: time window " + "-"*44)
    T("G3 before 9:30 AM", False, et_time=_time(9, 29))
    T("G3 exactly 9:30 AM (inclusive)", True, et_time=_time(9, 30))
    T("G3 9:31 AM", True, et_time=_time(9, 31))
    T("G3 10:59 AM (last minute before 11)", True, et_time=_time(10, 59))
    T("G3 exactly 11:00 AM (exclusive boundary)", False, et_time=_time(11, 0))
    T("G3 11:30 AM", False, et_time=_time(11, 30))
    T("G3 14:00 (afternoon)", False, et_time=_time(14, 0))
    T("G3 custom scan_end_hour=10 at 10:00", False,
      et_time=_time(10, 0), cfg=_cfg(scan_end_hour=10))
    T("G3 custom scan_end_hour=10 at 9:59", True,
      et_time=_time(9, 59), cfg=_cfg(scan_end_hour=10))

    print("\n-- G4: float filter " + "-"*43)
    T("G4 float exactly at 20M limit passes (<=)", True, float_shares=20_000_000)
    T("G4 float one share over 20M", False, float_shares=20_000_001)
    T("G4 float=None (unknown) -> skipped gracefully", True, float_shares=None)
    T("G4 float=1M -> passes", True, float_shares=1_000_000)
    T("G4 custom max_float=5M, float=5.1M -> fail", False,
      float_shares=5_100_000, cfg=_cfg(max_float=5_000_000))

    print("\n-- Combined edge cases " + "-"*41)
    T("combined: good gain but wrong time (afternoon)", False,
      price=8.0, prior_close=4.0, high_of_day=8.0, et_time=_time(14, 0))
    T("combined: good time but low rel_vol", False, rel_vol=2.0)
    T("combined: all pass with max_float=None via float=None", True,
      float_shares=None, cfg=_cfg(max_float=1))   # G4 skipped when float_shares=None
    T("combined: minimum viable momentum stock", True,
      price=1.10, prior_close=1.0, high_of_day=1.10,
      rel_vol=5.0, float_shares=None, et_time=_time(9, 30),
      cfg=_cfg(min_intraday_gain=5.0, hod_tol=0.0, scan_end_hour=11))

    print(f"\n{'='*60}")
    print(f"RESULT: {passed}/{passed+failed} passed", end="")
    if failed:
        print(f"  ({failed} FAILED)")
    else:
        print("  OK")
    return failed == 0


if __name__ == '__main__':
    ok = run_tests()
    sys.exit(0 if ok else 1)
