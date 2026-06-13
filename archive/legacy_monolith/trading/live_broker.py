"""
LiveBroker — live trading's Broker adapter (wraps LiveTradeManager).

The mirror image of simulator/sim_broker.py: conforms to the same trading.execution.Broker
Protocol so the Orchestrator drives live trading with the IDENTICAL decision code it uses
in the sim. Only the order mechanics (real broker round-trips, fills, stop placement) live
behind here in LiveTradeManager — never in the orchestrator.

Sizing parity (audit H2): enter() computes shares via sizing.compute_shares() — the same
formula + float caps + size_multiplier the sim uses — and injects it into
LiveTradeManager.execute_entry(shares=...), instead of live's basic _calculate_shares.
This is what makes a backtested config size the same way live.
"""

from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from datetime import datetime

from trading.trading_engine import Trade
from trading.models import EntrySignal, ExitSignal
from trading.add_on_engine import AddOnSignal
from trading.sizing import compute_shares


class LiveBroker:
    """Broker adapter over LiveTradeManager. Conforms to trading.execution.Broker."""

    def __init__(self, trade_manager):
        self._ltm = trade_manager
        self._had_loss_today = False   # GAP-16: half-size next entry after a loss (parity with sim PM)

    # ── Broker interface ───────────────────────────────────────────────────────
    def has_position(self) -> bool:
        return self._ltm.has_open_position()

    @property
    def position(self) -> Trade | None:
        return self._ltm.active_trade

    def can_enter(self) -> bool:
        # No open position. (Portfolio daily-loss/green-to-red halts are enforced
        # separately by the orchestrator's entry_gate via portfolio_manager.)
        return not self._ltm.has_open_position()

    def enter(self, signal: EntrySignal, *, when: datetime, ref_price: float,
              float_shares: int | None = None, size_multiplier: float = 1.0) -> Trade | None:
        pat = signal.pattern
        # H2 FIX: size with the SAME formula as the sim (compute_shares), not live's
        # basic _calculate_shares. ref_price is the live ask (entry reference).
        shares = compute_shares(
            entry_price=ref_price,
            stop_loss_price=pat.stop_price,
            current_balance=self._ltm.account_balance,
            risk_pct=self._ltm.risk_pct,
            max_position_pct=self._ltm.max_position_pct,
            float_shares=float_shares,
            size_multiplier=size_multiplier,
            had_loss_today=self._had_loss_today,
        )
        if shares <= 0:
            return None
        ok = self._ltm.execute_entry(signal, ask_price=ref_price, shares=shares)
        return self._ltm.active_trade if ok else None

    def exit(self, exit_signal: ExitSignal, when: datetime) -> float:
        pnl = self._ltm.execute_exit(exit_signal, when)
        # GAP-16: flag a loss once the position fully closes red (mirrors sim PM).
        if self._ltm.active_trade is None and pnl is not None and pnl < 0:
            self._had_loss_today = True
        return pnl if pnl is not None else 0.0

    def add_on(self, add_on_signal: AddOnSignal, when: datetime) -> int:
        return self._ltm.execute_add_on(add_on_signal, when)

    def balance(self) -> float:
        return self._ltm.account_balance

    def set_max_position_pct(self, pct: float) -> None:
        self._ltm.max_position_pct = pct

    def completed_trade_count(self) -> int:
        return len(self._ltm.completed_trades)
