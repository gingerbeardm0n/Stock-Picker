"""
DataFeed interface — the ONLY way the engine gets market data.

Part of the sim de-logic refactor (docs/LIVE_SIM_PARITY_SPEC.md). The orchestrator
pulls bars exclusively through this Protocol. Two implementations exist:

    simulator/replay_feed.py   — replays DB minute bars in chronological order
    live (Alpaca/Tradier)      — blocks until each live minute bar closes

Neither the orchestrator nor any engine code may import a concrete feed; they depend
only on this Protocol. This is what lets "go live" be a one-line adapter swap.

Bar contract (every bar dict the feed yields MUST carry these keys):
    time   : datetime  (UTC, tz-aware)
    symbol : str
    open   : float
    high   : float
    low    : float
    close  : float
    volume : float
    rel_vol: float | None   # relative volume AT THIS MINUTE (sim: precomputed
                            # rel_vol_30d; live: cumulative/avg). None = unavailable.
    vwap   : float | None   # session VWAP if known, else None
"""

from __future__ import annotations
from datetime import datetime
from typing import Iterator, Protocol, runtime_checkable

# A single OHLCV(+derived) bar. Kept as a plain dict for zero-friction interop with
# the existing engine code, which already consumes dicts everywhere.
BarDict = dict

# Required keys on every bar the feed yields (validated by validate_bar()).
REQUIRED_BAR_KEYS = ('time', 'symbol', 'open', 'high', 'low', 'close', 'volume')
# Optional-but-contracted keys (may be None, but the key should be present).
OPTIONAL_BAR_KEYS = ('rel_vol', 'vwap')


@runtime_checkable
class DataFeed(Protocol):
    """A source of minute bars, grouped by minute, in chronological order."""

    def bars(self) -> Iterator[tuple[datetime, list[BarDict]]]:
        """Yield (minute_ts, bars_for_that_minute) tuples in ascending time order.

        - Sim: iterate the loaded/indexed day, one minute at a time.
        - Live: yield once per minute as the bar for that minute finalizes.

        Each inner list contains every symbol that printed a bar in that minute.
        The orchestrator treats each yield as "one tick of the clock".
        """
        ...

    def reset(self) -> None:
        """Reset to the start of the session (sim) or no-op (live). Optional to call."""
        ...


def validate_bar(bar: BarDict) -> None:
    """Raise ValueError if a bar is missing required keys. Cheap contract guard the
    feed adapters can call in tests; the hot loop should not call this per bar."""
    missing = [k for k in REQUIRED_BAR_KEYS if k not in bar]
    if missing:
        raise ValueError(f"bar missing required keys {missing}: {bar!r}")
