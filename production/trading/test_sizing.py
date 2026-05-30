"""
test_sizing.py — prove sizing.compute_shares is byte-identical to the ORIGINAL
inline PositionManager.enter_position math, so rewiring PositionManager to call it
is provably behavior-preserving (no golden-day run needed for the sizing step).

    python production/trading/test_sizing.py
"""

from __future__ import annotations
import sys, os, random
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from trading.sizing import compute_shares

# Frozen reference: the EXACT logic that lived in PositionManager.enter_position
# (trading_engine.py, pre-refactor). Do not "clean up" — it is the spec to match.
_REF_CAPS = [
    (1_000_000,  5_000.0),
    (3_000_000, 15_000.0),
    (10_000_000, 8_000.0),
    (20_000_000, 5_000.0),
]


def _reference_old(entry_price, stop_loss_price, current_balance, risk_pct,
                   max_position_pct, float_shares, size_multiplier, had_loss_today):
    stop_distance = entry_price - stop_loss_price
    if stop_distance <= 0:
        return 0
    gap16_mult = 0.5 if had_loss_today else 1.0
    total_mult = gap16_mult * size_multiplier
    risk_per_trade = current_balance * (risk_pct / 100.0)
    risk_based_shares = int(risk_per_trade / stop_distance)
    max_position_value = current_balance * (max_position_pct / 100.0)
    if float_shares is not None:
        for bucket_float, cap_dollars in _REF_CAPS:
            if float_shares < bucket_float:
                max_position_value = min(max_position_value, cap_dollars)
                break
    max_position_shares = int(max_position_value / entry_price)
    shares = int(min(risk_based_shares, max_position_shares) * total_mult)
    if shares <= 0:
        return 0
    if shares * entry_price > current_balance:
        shares = int(current_balance / entry_price * total_mult)
        if shares <= 0:
            return 0
    return shares


def main() -> int:
    random.seed(7)
    floats = [None, 500_000, 2_000_000, 6_000_000, 15_000_000, 40_000_000]
    mults = [0.25, 0.5, 0.75, 1.0, 1.5]
    mismatches = 0
    n = 0
    for _ in range(20000):
        entry = round(random.uniform(1.0, 20.0), 2)
        stop = round(entry - random.uniform(-0.1, 1.5), 2)   # sometimes >= entry (invalid)
        bal = random.choice([1000, 5000, 25000, 100000]) * random.uniform(0.5, 1.5)
        risk = random.choice([0.5, 1.0, 2.0, 3.0])
        maxpos = random.choice([5.0, 10.0, 15.0, 20.0])
        flt = random.choice(floats)
        mult = random.choice(mults)
        loss = random.choice([True, False])
        kw = dict(entry_price=entry, stop_loss_price=stop, current_balance=bal,
                  risk_pct=risk, max_position_pct=maxpos, float_shares=flt,
                  size_multiplier=mult, had_loss_today=loss)
        a = compute_shares(**kw)
        b = _reference_old(**kw)
        n += 1
        if a != b:
            mismatches += 1
            if mismatches <= 5:
                print(f"  MISMATCH new={a} old={b} :: {kw}")
    print(f"compared {n} randomized cases — {mismatches} mismatches")
    if mismatches == 0:
        print("PASS — compute_shares is identical to the original PositionManager math")
        return 0
    print("FAIL")
    return 1


if __name__ == '__main__':
    sys.exit(main())
