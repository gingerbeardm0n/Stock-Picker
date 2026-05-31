"""
Verify live_scanner's Orchestrator-path BATCHING plumbing (the de-logic flip rewire).

The engine itself is parity-proven (research/optimizer/parity_check.py: sim==live via on_minute).
This isolates the OTHER half: does process_bar, with _use_orchestrator=True, accumulate each
minute's streaming bars and flush them to orch.on_minute exactly once at the minute boundary,
with the right timestamp and bar set? Uses a recording stub orchestrator — no DB query, no real
engine, no orders.

Run: python production/trading/test_live_orch_batching.py
"""

from __future__ import annotations
import sys, os
from datetime import datetime, timezone, timedelta, date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from trading.live_scanner import LiveScanner, ET


class _RecorderOrch:
    """Stub: records each on_minute(ts, bars) call."""
    def __init__(self):
        self.calls = []  # list of (minute_tuple_ET, [symbols])

    def on_minute(self, ts, bars):
        et = ts.astimezone(ET)
        self.calls.append(((et.hour, et.minute), sorted(b['symbol'] for b in bars)))


def _bar(symbol, t):
    return {'symbol': symbol, 'time': t, 'open': 5.0, 'high': 5.1, 'low': 4.9,
            'close': 5.05, 'volume': 1000}


def test_minute_batching():
    # Construct a scanner; force the orchestrator path with a recording stub.
    ls = LiveScanner.__new__(LiveScanner)   # bypass __init__ (avoids opening a DB connection)
    # Minimal state the orchestrator-path branch + preamble touch:
    from collections import defaultdict, deque
    ls._bar_history = defaultdict(lambda: deque(maxlen=40))
    ls._today_volume = defaultdict(int)
    ls._gap_trackers = defaultdict(lambda: _NoGap())
    ls._gaprun_qualified = set()
    ls._premarket_scans_done = set()
    ls._current_trade_date = date(2025, 6, 2)  # ET date of the test bars — skip _on_new_day
    ls._scan_minute = None
    ls._minute_bars = []
    ls._minute_bars_ts = None
    ls._use_orchestrator = True
    rec = _RecorderOrch()
    ls._orch = rec

    base = datetime(2025, 6, 2, 13, 31, tzinfo=timezone.utc)  # 9:31 ET
    seq = [
        _bar('AAA', base),                       # 9:31
        _bar('BBB', base),                       # 9:31
        _bar('AAA', base + timedelta(minutes=1)),  # 9:32 -> boundary, flush 9:31
        _bar('BBB', base + timedelta(minutes=1)),  # 9:32
        _bar('CCC', base + timedelta(minutes=1)),  # 9:32
        _bar('AAA', base + timedelta(minutes=2)),  # 9:33 -> boundary, flush 9:32
    ]
    for b in seq:
        ls.process_bar(b)

    # 9:31 and 9:32 should have flushed; 9:33 still buffered (no boundary after it).
    assert rec.calls == [
        ((9, 31), ['AAA', 'BBB']),
        ((9, 32), ['AAA', 'BBB', 'CCC']),
    ], rec.calls
    # The current buffer holds the un-flushed 9:33 bar.
    assert [b['symbol'] for b in ls._minute_bars] == ['AAA'], ls._minute_bars
    assert ls._minute_bars_ts.astimezone(ET).minute == 33


class _NoGap:
    """gap tracker stub: never qualifies, never errors."""
    def update(self, bar):
        return None
    def reset(self):
        pass


if __name__ == '__main__':
    test_minute_batching()
    print("OK: live_scanner Orchestrator-path batching — per-minute bars flushed to on_minute "
          "at the correct boundary (1 call per completed minute, correct bar sets + timestamp).")
