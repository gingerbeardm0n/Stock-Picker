"""
Broker/local position reconciliation.

Detects positions the broker actually holds that no runner's local state
file claims — the CLRO incident (Jul 2 2026): a partial fill survived a
runner crash/restart with no exit logic ever attached to it, and sat
unmonitored across a holiday + weekend because nothing checked the broker
against local state on startup.

Read-only. Never places, modifies, or cancels an order — flags only.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

STATE_DIR = Path(os.getenv("JTRADER_STATE_DIR", "/tmp/jtrader"))
_STATE_FILES = ("state.json", "vwap_state.json", "micro_pullback_state.json")


def _known_position_symbols() -> set[str]:
    """Union of symbols any runner's local state currently claims to hold."""
    symbols: set[str] = set()
    for name in _STATE_FILES:
        f = STATE_DIR / name
        if not f.exists():
            continue
        try:
            data = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        positions = data.get("positions") or {}
        symbols.update(positions.keys())
        # Single-position runners may key off a flat symbol field instead.
        sym = data.get("symbol")
        if sym and not data.get("trade_done") and data.get("entry_price"):
            symbols.add(sym)
    return symbols


def find_orphaned_positions(broker) -> list[dict]:
    """Broker positions with no matching entry in any runner's local state.

    Returns a list of dicts (symbol, qty, avg_price) — empty if none found
    or if the broker call fails (fail-open: never blocks session startup).
    """
    try:
        broker_positions = broker.get_all_positions()
    except Exception as e:
        logger.warning(f"Position reconciliation: broker query failed ({e}) — skipping check")
        return []

    known = _known_position_symbols()
    orphans = [
        {"symbol": p.symbol, "qty": p.qty, "avg_price": p.avg_price}
        for p in broker_positions
        if p.symbol not in known
    ]
    if orphans:
        logger.warning(
            "ORPHANED POSITION(S) DETECTED — held by broker, not tracked by any "
            "runner (no exit logic attached): "
            + ", ".join(f"{o['symbol']} x{o['qty']} @ ${o['avg_price']:.2f}" for o in orphans)
        )
    return orphans
