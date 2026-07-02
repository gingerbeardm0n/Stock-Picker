"""
Daily session job — runs both strategies in sequence and persists state.

Shared by:
  - api/server.py     (APScheduler daily 7:00 AM ET job, --run-now flag)
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


_SESSION_STARTED_FILE = STATE_DIR / "session_started_date.txt"


def is_session_started_today() -> bool:
    """True if run_daily_sessions() already kicked off today."""
    try:
        return _SESSION_STARTED_FILE.read_text().strip() == str(datetime.now().date())
    except OSError:
        return False


def run_daily_sessions():
    """Run scalp, micro-pullback, and VWAP reclaim in coordinated parallel; persist state."""
    from trading.live_scalp_runner import run_scalp_session
    from trading.live_vwap_runner import run_vwap_session
    from trading.live_micro_pullback_runner import run_micro_pullback_session
    import threading

    # Write start flag immediately — lets /trigger guard against double-fire.
    _SESSION_STARTED_FILE.write_text(str(datetime.now().date()))

    scalp_state_data = {}
    vwap_state_data = {}
    micro_pullback_state_data = {}

    # ── Strategy #1: Opening Bell Scalp (9:30-9:40) ─────────────────────────
    logger.info("=== SCALP SESSION STARTING ===")
    try:
        state = run_scalp_session(dry_run=False, live=False, start_time='8:00')

        scalp_completed = getattr(state, 'completed_trades', [])
        first = scalp_completed[0] if scalp_completed else {}
        scalp_state_data = {
            "last_run": datetime.utcnow().isoformat(),
            "strategy": "opening_bell_scalp",
            "last_result": "trade" if scalp_completed else "no_trade",
            "date": str(datetime.now().date()),
            "candidates": _serialize_candidates(getattr(state, 'candidates', None)),
            # top_pick on the runner state is the full candidate dict; store
            # just the symbol (JSON state + Neon session_runs both expect text)
            "top_pick": (getattr(state, 'top_pick', None) or {}).get('symbol')
                        if isinstance(getattr(state, 'top_pick', None), dict)
                        else getattr(state, 'top_pick', None),
            "completed_trades": scalp_completed,
            "trade_count": len(scalp_completed),
            "pnl": getattr(state, 'pnl', 0),
            "trade_done": getattr(state, 'trade_done', False),
            # Legacy compat fields so dashboard _infer_stage still works
            "entry_price": first.get('entry_price'),
            "exit_price": first.get('exit_price'),
            "shares": first.get('shares'),
            "bars_held": first.get('bars_held'),
            "exit_reason": first.get('exit_reason', ''),
        }
        (STATE_DIR / "state.json").write_text(json.dumps(scalp_state_data, default=str))
        for trade in scalp_completed:
            _append_trade({**scalp_state_data, **trade, "completed_trades": None})
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

    # ── Strategy #2 & #3: Micro-Pullback (9:30-11:30) + VWAP (10:00-11:30) ────
    # Run in parallel threads with active_positions blocking for coordination
    logger.info("=== MICRO-PULLBACK & VWAP SESSIONS STARTING (parallel) ===")

    vstate = None
    mpstate = None

    def run_vwap_thread():
        nonlocal vwap_state_data
        logger.info("=== VWAP RECLAIM SESSION STARTING ===")
        try:
            nonlocal vstate
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
                "bars_held": getattr(vstate, 'bars_held', None),
                "exit_reason": getattr(vstate, 'exit_reason', ''),
                "positions": getattr(vstate, 'positions', {}),
                "watchlist": _serialize_candidates(getattr(vstate, 'watchlist', [])),
                "completed_trades": completed,
                "trade_count": len(completed),
            }
            (STATE_DIR / "vwap_state.json").write_text(json.dumps(vwap_state_data, default=str))
            for trade in completed:
                _append_trade({**vwap_state_data, **trade, "completed_trades": None})
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

    def run_micro_pullback_thread():
        nonlocal micro_pullback_state_data
        logger.info("=== MICRO-PULLBACK SESSION STARTING ===")
        try:
            nonlocal mpstate
            mpstate = run_micro_pullback_session(dry_run=False, live=False)
            completed = getattr(mpstate, 'completed_trades', [])
            first = completed[0] if completed else {}
            micro_pullback_state_data = {
                "last_run": datetime.utcnow().isoformat(),
                "strategy": "micro_pullback",
                "date": str(datetime.now().date()),
                "last_result": "trade" if completed else "no_trade",
                "watchlist": _serialize_candidates(getattr(mpstate, 'watchlist', [])),
                "completed_trades": completed,
                "trade_count": len(completed),
                "pnl": sum(t.get('pnl', 0) for t in completed) if completed else 0,
                "trade_done": getattr(mpstate, 'trade_done', False),
                # Legacy single-position compat fields so dashboard _infer_stage
                # and stage-tagging work the same way scalp/VWAP's do.
                "top_pick": getattr(mpstate, 'symbol', '') or None,
                "symbol": getattr(mpstate, 'symbol', ''),
                "entry_price": first.get('entry_price') or getattr(mpstate, 'entry_price', None),
                "exit_price": first.get('exit_price') or getattr(mpstate, 'exit_price', None),
                "stop_price": getattr(mpstate, 'stop_price', None),
                "shares": first.get('shares') or getattr(mpstate, 'shares', None),
                "bars_held": first.get('bars_held') or getattr(mpstate, 'bars_held', None),
                "exit_reason": first.get('exit_reason', '') or getattr(mpstate, 'exit_reason', ''),
            }
            (STATE_DIR / "micro_pullback_state.json").write_text(json.dumps(micro_pullback_state_data, default=str))
            for trade in completed:
                _append_trade({**micro_pullback_state_data, **trade, "completed_trades": None})
            logger.info(f"=== MICRO-PULLBACK COMPLETE: {micro_pullback_state_data['last_result']} ===")
        except Exception as e:
            logger.error(f"Micro-Pullback session failed: {e}", exc_info=True)
            micro_pullback_state_data = {
                "last_run": datetime.utcnow().isoformat(),
                "strategy": "micro_pullback",
                "last_result": "error",
                "error": str(e),
            }
            (STATE_DIR / "micro_pullback_state.json").write_text(json.dumps(micro_pullback_state_data))

    vwap_thread = threading.Thread(target=run_vwap_thread, daemon=False)
    mp_thread = threading.Thread(target=run_micro_pullback_thread, daemon=False)
    vwap_thread.start()
    mp_thread.start()
    vwap_thread.join()
    mp_thread.join()
    logger.info("=== MICRO-PULLBACK & VWAP SESSIONS COMPLETE ===")

    # ── Persist everything to TimescaleDB ──────────────────────────────────
    logger.info("=== PERSISTING SESSION TO DB ===")
    try:
        from api.session_persistence import persist_session
        # persist_session currently takes scalp + vwap; micro-pullback trades
        # are appended via _append_trade above, so no additional call needed
        persist_session(scalp_state_data, vwap_state_data)
    except Exception as e:
        logger.error(f"Session persistence import/call failed: {e}", exc_info=True)
