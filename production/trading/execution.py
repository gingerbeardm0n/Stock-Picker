"""
Broker interface — the ONLY way the engine places/manages orders.

Part of the sim de-logic refactor (docs/LIVE_SIM_PARITY_SPEC.md). The orchestrator
enters / exits / adds / reads position exclusively through this Protocol. Two
implementations:

    simulator/sim_broker.py    — instant fills at signal price; wraps PositionManager;
                                 tracks balance + realized P&L (the "broker simulator")
    trading/order_manager.py   — LiveTradeManager (real broker round-trips) adapts to this

The orchestrator must NEVER import PositionManager, LiveTradeManager, or a broker SDK
directly — only this Protocol. That is what keeps trading logic out of both the sim
and the live wiring.

P&L convention: enter()/add_on() return the resulting Trade / shares added; exit()
returns realized P&L for that fill (not cumulative). balance() is authoritative
account value. All accounting (including add-on cost basis) lives in the broker impl,
NOT in the orchestrator.
"""

from __future__ import annotations
from datetime import datetime
from typing import Protocol, runtime_checkable

from trading.trading_engine import Trade
from trading.models import EntrySignal, ExitSignal
from trading.add_on_engine import AddOnSignal


@runtime_checkable
class Broker(Protocol):
    """Single-position broker abstraction (matches the one-stock-at-a-time strategy)."""

    def has_position(self) -> bool: ...

    @property
    def position(self) -> Trade | None: ...

    def enter(
        self,
        signal: EntrySignal,
        *,
        when: datetime,
        ref_price: float,
        float_shares: int | None = None,
        size_multiplier: float = 1.0,
    ) -> Trade | None:
        """Open a position from an entry signal. `when` = decision timestamp (sim: the
        bar's minute; live: fill time) → sets entry_time. Returns the Trade, or None if
        the order could not be sized/placed. The broker owns share sizing (sim: via
        sizing.compute_shares; live: same formula) so sim and live size identically."""
        ...

    def exit(self, exit_signal: ExitSignal, when: datetime) -> float:
        """Apply an exit (partial or full). Returns realized P&L for this fill."""
        ...

    def add_on(self, add_on_signal: AddOnSignal, when: datetime) -> int:
        """Apply an add-on. Returns shares actually added (0 if rejected/capped)."""
        ...

    def balance(self) -> float:
        """Authoritative current account value."""
        ...

    def can_enter(self) -> bool:
        """True if a new position may be opened (no open position + under own loss cap)."""
        ...

    def set_max_position_pct(self, pct: float) -> None:
        """Update the position-size cap (orchestrator calls on temperature change)."""
        ...

    def completed_trade_count(self) -> int:
        """Trades closed so far today (for the portfolio max-trades-per-day rule)."""
        ...
