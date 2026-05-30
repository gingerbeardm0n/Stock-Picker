"""
Entry gate — the pure, shared "may a new-entry scan run this minute?" decision.

This is the de-logic'd version of the inline gate that used to live ONLY in
`simulator/simulation_engine.py::_process_minute` (Step 3). Extracting it here means
the simulator AND the live orchestrator make the identical block/allow decision by
calling one function, instead of each maintaining its own copy of the boolean chain.

Pure function: no I/O, no DB, no side effects. The caller passes already-computed
booleans (the sim/live harness owns *how* they are computed; this owns the *order*
and the *reason*).

Decision order (must match the original sim chain exactly):
  1. capacity        — PositionManager.can_enter_trade()  (no open position AND under
                       its own daily-max-loss). False ⇒ block, no scan.
  2. session stop    — temperature-driven hard stop time reached (only once the
                       premarket temperature has been classified).
  3. portfolio rules — any of DAILY_MAX_LOSS / GREEN_TO_RED / GIVE_BACK_HALF fired.

The single highest-leverage discipline rule in the whole system lives in step 3
(clean sessions win 73.1% vs 49.2% when deviating — see
concepts/concept_behavioral_deviation.md). Keeping it in a shared, tested function is
how live trading inherits it instead of it being a simulator-only behavior.
"""

from __future__ import annotations

# Block-reason constants (stable strings — safe to log / assert against in tests).
NO_CAPACITY = "NO_CAPACITY"        # open position already, or PositionManager daily-max-loss
SESSION_STOP = "SESSION_STOP"      # temperature session-stop time reached
PORTFOLIO_RULE = "PORTFOLIO_RULE"  # a portfolio risk rule has fired today


def entry_blocked_reason(
    *,
    can_enter_trade: bool,
    premarket_classified: bool,
    session_over: bool,
    any_rule_fired: bool,
) -> str | None:
    """Return the reason a new-entry scan is blocked this minute, or None to proceed.

    Args:
        can_enter_trade:     PositionManager.can_enter_trade() — capacity + own loss cap.
        premarket_classified: TemperatureState.premarket_classified — has the 9:25 snapshot
                              run yet. Session-stop only applies after classification, matching
                              the original `temp_state.premarket_classified and is_session_over(...)`.
        session_over:        is_session_over(temp_state, now) — temperature hard-stop reached.
        any_rule_fired:      PortfolioManager.any_rule_fired() — risk circuit-breaker tripped.

    Returns:
        None  → all gates pass; the caller should run its entry scan.
        str   → one of NO_CAPACITY / SESSION_STOP / PORTFOLIO_RULE (first that applies).
    """
    if not can_enter_trade:
        return NO_CAPACITY
    if premarket_classified and session_over:
        return SESSION_STOP
    if any_rule_fired:
        return PORTFOLIO_RULE
    return None
