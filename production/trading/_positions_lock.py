"""
Cross-strategy active-position coordination.

VWAP and micro-pullback run in parallel threads. Without a shared lock,
both could pass _can_enter_symbol() for the same symbol and place two
orders before either records the position. This module provides an
atomic try_claim / release pair backed by a single process-level Lock.

Usage:
    from trading._positions_lock import try_claim, release, is_claimed

    # In _place_entry, BEFORE placing the order:
    if not try_claim(symbol, "my_strategy"):
        return  # another strategy beat us
    ...
    # On exit:
    release(symbol)
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path

_LOCK = threading.Lock()


def _pos_file() -> Path:
    return Path(os.getenv("JTRADER_STATE_DIR", "/tmp/jtrader")) / "active_positions.json"


def try_claim(symbol: str, strategy: str) -> bool:
    """Atomically claim symbol for strategy. Returns False if already owned."""
    with _LOCK:
        f = _pos_file()
        active: dict = {}
        if f.exists():
            try:
                active = json.loads(f.read_text())
            except Exception:
                active = {}
        if symbol in active:
            return False
        active[symbol] = {"strategy": strategy, "entry_time": datetime.utcnow().isoformat()}
        f.write_text(json.dumps(active))
        return True


def release(symbol: str) -> None:
    """Remove symbol from active_positions (call on exit or failed entry)."""
    with _LOCK:
        f = _pos_file()
        if not f.exists():
            return
        try:
            active = json.loads(f.read_text())
            active.pop(symbol, None)
            f.write_text(json.dumps(active))
        except Exception as e:
            # A failed release leaves the symbol claimed for the whole
            # session, blocking every other strategy from entering it.
            import logging
            logging.getLogger(__name__).warning(
                "positions_lock release FAILED for %s (%s) — symbol stays "
                "claimed until session end", symbol, e)


def is_claimed(symbol: str) -> bool:
    """Fast pre-check (not locked — hint only, not authoritative)."""
    f = _pos_file()
    if not f.exists():
        return False
    try:
        return symbol in json.loads(f.read_text())
    except Exception:
        return False
