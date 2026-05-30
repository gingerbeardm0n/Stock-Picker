"""
Truth-table regression for entry_gate.entry_blocked_reason.

Proves the extracted pure function is BEHAVIOR-IDENTICAL to the inline boolean chain
that used to live in simulation_engine._process_minute Step 3, across all 16 input
combinations. If this passes, the sim rewire is a pure relocation (no behavior change).

Run: python production/trading/test_entry_gate.py   (no DB, no network)
"""

from __future__ import annotations
import sys, os, itertools

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from trading.entry_gate import (
    entry_blocked_reason, NO_CAPACITY, SESSION_STOP, PORTFOLIO_RULE,
)


def _old_inline_decision(can_enter_trade, premarket_classified, session_over, any_rule_fired):
    """Frozen replica of the ORIGINAL sim chain (simulation_engine.py ~763-778).

    Returns (should_scan: bool, reason: str | None) — reason mirrors what the
    original code did at each branch (SESSION_STOP was silent; PORTFOLIO_RULE logged;
    NO_CAPACITY just fell through). 'should_scan' is the only externally-observable
    behavior; reason is asserted too for completeness.
    """
    if can_enter_trade:
        if premarket_classified and session_over:
            return False, SESSION_STOP        # silent block
        elif any_rule_fired:
            return False, PORTFOLIO_RULE       # HALTED log + block
        else:
            return True, None                  # run _scan_for_entry
    else:
        return False, NO_CAPACITY              # fall through, no scan


def test_truth_table_identical():
    mismatches = []
    for can_enter, classified, over, fired in itertools.product([False, True], repeat=4):
        old_scan, old_reason = _old_inline_decision(can_enter, classified, over, fired)
        new_reason = entry_blocked_reason(
            can_enter_trade=can_enter,
            premarket_classified=classified,
            session_over=over,
            any_rule_fired=fired,
        )
        new_scan = new_reason is None
        if new_scan != old_scan or new_reason != old_reason:
            mismatches.append(
                (can_enter, classified, over, fired, old_scan, old_reason, new_scan, new_reason)
            )
    assert not mismatches, f"{len(mismatches)} mismatches vs old inline logic: {mismatches}"


def test_priority_order():
    # capacity beats everything
    assert entry_blocked_reason(
        can_enter_trade=False, premarket_classified=True, session_over=True, any_rule_fired=True
    ) == NO_CAPACITY
    # session-stop beats portfolio rule (when capacity ok)
    assert entry_blocked_reason(
        can_enter_trade=True, premarket_classified=True, session_over=True, any_rule_fired=True
    ) == SESSION_STOP
    # portfolio rule fires when capacity ok and not session-stopped
    assert entry_blocked_reason(
        can_enter_trade=True, premarket_classified=True, session_over=False, any_rule_fired=True
    ) == PORTFOLIO_RULE
    # session_over ignored until premarket classified (matches original `and` guard)
    assert entry_blocked_reason(
        can_enter_trade=True, premarket_classified=False, session_over=True, any_rule_fired=False
    ) is None
    # all clear → proceed
    assert entry_blocked_reason(
        can_enter_trade=True, premarket_classified=True, session_over=False, any_rule_fired=False
    ) is None


if __name__ == "__main__":
    test_truth_table_identical()
    test_priority_order()
    print("OK: entry_gate matches old inline logic across all 16 combos + priority cases")
