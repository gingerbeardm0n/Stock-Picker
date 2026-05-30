"""
SimBroker — the simulator's Broker adapter (broker replacement, ZERO trading logic).

Implements trading.broker.Broker by delegating to PositionManager (instant fills at
signal price, balance + P&L tracking). This is one of the two things the simulator is
allowed to be (the other is the data-feed adapter). All decision logic lives in the
orchestrator; this object only fills orders and keeps the books.

Live trading swaps this for a LiveBroker that wraps LiveTradeManager — same interface,
so the orchestrator is unchanged.
"""

from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from datetime import datetime

from trading.trading_engine import Trade, PositionManager
from trading.models import EntrySignal, ExitSignal
from trading.add_on_engine import AddOnSignal


class SimBroker:
    """Broker adapter over PositionManager. Conforms to trading.broker.Broker."""

    def __init__(self, account_size: float, risk_pct: float = 2.0,
                 max_position_pct: float = 20.0, daily_max_loss_pct: float = 3.0):
        self._pm = PositionManager(
            account_size=account_size,
            risk_per_trade_pct=risk_pct,
            daily_max_loss_pct=daily_max_loss_pct,
            max_position_pct=max_position_pct,
        )

    # ── Broker interface ───────────────────────────────────────────────────────
    def has_position(self) -> bool:
        return self._pm.position is not None

    @property
    def position(self) -> Trade | None:
        return self._pm.position

    def can_enter(self) -> bool:
        """Sim-side convenience mirroring PositionManager.can_enter_trade()."""
        return self._pm.can_enter_trade()

    def enter(self, signal: EntrySignal, *, when: datetime, ref_price: float,
              float_shares: int | None = None, size_multiplier: float = 1.0) -> Trade | None:
        # `when` = the decision timestamp (sim: the bar's minute; live: fill time).
        # Required for correct entry_time → hold_minutes. ref_price is the live ask;
        # the sim fills at pat.entry_price, so ref_price is unused here (kept for the
        # Broker interface / LiveBroker).
        pat = signal.pattern
        return self._pm.enter_position(
            symbol=signal.symbol,
            entry_price=pat.entry_price,
            entry_time=when,
            stop_loss_price=pat.stop_price,
            target1=pat.target1,
            target2=pat.target2,
            pattern_type=pat.pattern_type,
            float_shares=float_shares,
            size_multiplier=size_multiplier,
        )

    def exit(self, exit_signal: ExitSignal, when: datetime) -> float:
        return self._pm.apply_exit_signal(exit_signal, when)

    def add_on(self, add_on_signal: AddOnSignal, when: datetime) -> int:
        return self._pm.apply_add_on(add_on_signal, when)

    def balance(self) -> float:
        return self._pm.current_balance

    def set_max_position_pct(self, pct: float) -> None:
        """Update the position-size cap (orchestrator calls this on temperature change)."""
        self._pm.max_position_pct = pct

    def completed_trade_count(self) -> int:
        """Number of trades closed so far today (for the portfolio max-trades rule)."""
        return len(self._pm.trades_completed)

    # ── Sim-only accessors (reporting; not part of the Broker Protocol) ─────────
    @property
    def position_manager(self) -> PositionManager:
        """Escape hatch for the sim's existing reporting/stats code during migration."""
        return self._pm

    def stats(self) -> dict:
        return self._pm.get_stats()


def _now() -> datetime:
    from datetime import timezone
    return datetime.now(timezone.utc)
