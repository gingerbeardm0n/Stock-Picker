"""
Daily session job — runs both strategies in sequence and persists state.

Shared by:
  - api/server.py     (APScheduler daily 8:55 AM ET job, --run-now flag)
  - api/dashboard.py  (POST /trigger manual kick)

Order: Opening Bell Scalp (9:30-9:40) then VWAP Reclaim (10:00-11:30).
The VWAP entry window is enforced on BAR TIME by the engine, so chaining
it right after the scalp just means it watches and waits for 10:00 bars.
"""

from __future__ import annotations
import os
import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

STATE_DIR = Path(os.getenv("JTRADER_STATE_DIR", "/tmp/jtrader"))
STATE_DIR.mkdir(parents=True, exist_ok=True)

_CANDIDATE_FIELDS = (
    'symbol', 'gap_pct', 'open_price', 'prior_close', 'rel_vol',
    'float_shares', 'has_news', 'news_tier', 'scalp_score', 'quote_volume',
)


def _serialize_candidates(candidates: list[dict] | None) -> list[dict]:
    if not candidates:
        return []
    return [
        {k: c.get(k) for k in _CANDIDATE_FIELDS}
        for c in candidates
    ]


def _append_trade(trade_data: dict):
    trades_file = STATE_DIR / "trades.json"
    trades = []
    if trades_file.exists():
        try:
            trades = json.loads(trades_file.read_text())
        except (json.JSONDecodeError, OSError):
            trades = []
    trades.append(trade_data)
    trades_file.write_text(json.dumps(trades, default=str))


def run_daily_sessions():
    """Run scalp then VWAP reclaim; persist state for the dashboard."""
    from trading.live_scalp_runner import run_scalp_session
    from trading.live_vwap_runner import run_vwap_session

    scalp_state_data = {}
    vwap_state_data = {}

    # ── Strategy #1: Opening Bell Scalp ────────────────────────────────────
    logger.info("=== SCALP SESSION STARTING ===")
    try:
        state = run_scalp_session(dry_run=False, live=False, start_time='8:00')

        scalp_state_data = {
            "last_run": datetime.utcnow().isoformat(),
            "strategy": "opening_bell_scalp",
            "last_result": "trade" if getattr(state, 'entry_price', 0) > 0 else "no_trade",
            "date": str(datetime.now().date()),
            "candidates": _serialize_candidates(getattr(state, 'candidates', None)),
            "top_pick": getattr(state, 'top_pick', None),
            "entry_price": getattr(state, 'entry_price', None),
            "exit_price": getattr(state, 'exit_price', None),
            "pnl": getattr(state, 'pnl', None),
            "shares": getattr(state, 'shares', None),
            "stop_price": getattr(state, 'stop_price', None),
            "bars_held": getattr(state, 'bars_held', None),
            "exit_reason": getattr(state, 'exit_reason', ''),
            "trade_done": getattr(state, 'trade_done', False),
        }
        (STATE_DIR / "state.json").write_text(json.dumps(scalp_state_data, default=str))
        if scalp_state_data["last_result"] == "trade":
            _append_trade(scalp_state_data)
        logger.info(f"=== SCALP SESSION COMPLETE: {scalp_state_data['last_result']} ===")
    except Exception as e:
        logger.error(f"Scalp session failed: {e}", exc_info=True)
        scalp_state_data = {
            "last_run": datetime.utcnow().isoformat(),
            "strategy": "opening_bell_scalp",
            "last_result": "error",
            "error": str(e),
        }
        (STATE_DIR / "state.json").write_text(json.dumps(scalp_state_data))

    # ── Strategy #2: VWAP Reclaim ──────────────────────────────────────────
    logger.info("=== VWAP RECLAIM SESSION STARTING ===")
    try:
        vstate = run_vwap_session(dry_run=False, live=False)
        completed = getattr(vstate, 'completed_trades', [])
        total_pnl = sum(t.get('pnl', 0) for t in completed) if completed else getattr(vstate, 'pnl', None)
        vwap_state_data = {
            "last_run": datetime.utcnow().isoformat(),
            "strategy": "vwap_reclaim",
            "date": str(datetime.now().date()),
            "last_result": "trade" if completed or getattr(vstate, 'entry_price', 0) > 0 else "no_trade",
            "symbol": getattr(vstate, 'symbol', ''),
            "top_pick": getattr(vstate, 'symbol', '') or None,
            "entry_price": getattr(vstate, 'entry_price', None),
            "exit_price": getattr(vstate, 'exit_price', None),
            "pnl": total_pnl,
            "shares": getattr(vstate, 'shares', None),
            "stop_price": getattr(vstate, 'stop_price', None),
            "bars_held": getattr(vstate, 'bars_held', None),
            "exit_reason": getattr(vstate, 'exit_reason', ''),
            "watchlist": _serialize_candidates(getattr(vstate, 'watchlist', [])),
            "completed_trades": completed,
            "trade_count": len(completed),
        }
        (STATE_DIR / "vwap_state.json").write_text(json.dumps(vwap_state_data, default=str))
        if vwap_state_data["last_result"] == "trade":
            _append_trade(vwap_state_data)
        logger.info(f"=== VWAP RECLAIM COMPLETE: {vwap_state_data['last_result']} ===")
    except Exception as e:
        logger.error(f"VWAP session failed: {e}", exc_info=True)
        vwap_state_data = {
            "last_run": datetime.utcnow().isoformat(),
            "strategy": "vwap_reclaim",
            "last_result": "error",
            "error": str(e),
        }
        (STATE_DIR / "vwap_state.json").write_text(json.dumps(vwap_state_data))

    # ── Persist everything to TimescaleDB ──────────────────────────────────
    logger.info("=== PERSISTING SESSION TO DB ===")
    try:
        from api.session_persistence import persist_session
        persist_session(scalp_state_data, vwap_state_data)
    except Exception as e:
        logger.error(f"Session persistence import/call failed: {e}", exc_info=True)
