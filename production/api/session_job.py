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

_FLAG_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS session_flags (
    run_date   DATE PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""


def _neon_conn():
    conn_str = os.getenv("NEON_CONNECTION_STRING", "")
    if not conn_str:
        return None
    import psycopg2
    return psycopg2.connect(conn_str, connect_timeout=5)


def is_session_started_today() -> bool:
    """True if run_daily_sessions() already kicked off today.

    Neon is the source of truth — the old local-file flag lives on Render's
    ephemeral disk, so every deploy wiped it and the server's startup
    auto-trigger happily launched a SECOND full session (confirmed live
    2026-07-02: a ~11:55 ET deploy spawned a duplicate session that traded 7
    midday positions 11:59-12:07 ET). File is kept as a fallback for when
    Neon is unreachable.
    """
    try:
        conn = _neon_conn()
        if conn is not None:
            with conn, conn.cursor() as cur:
                cur.execute(_FLAG_TABLE_SQL)
                cur.execute("SELECT 1 FROM session_flags WHERE run_date = %s",
                            (datetime.now().date(),))
                row = cur.fetchone()
            conn.close()
            return row is not None
    except Exception as e:
        logger.warning(f"Neon session flag check failed ({e}) — file fallback")
    try:
        return _SESSION_STARTED_FILE.read_text().strip() == str(datetime.now().date())
    except OSError:
        return False


def _claim_session_today() -> bool:
    """Atomically claim today's session. Returns False if already claimed.

    INSERT ... ON CONFLICT DO NOTHING makes the claim race-safe: if the 7:00
    cron, a watchdog /trigger, and a startup auto-trigger all fire together,
    exactly one caller gets rowcount 1.
    """
    claimed = None
    try:
        conn = _neon_conn()
        if conn is not None:
            with conn, conn.cursor() as cur:
                cur.execute(_FLAG_TABLE_SQL)
                cur.execute(
                    "INSERT INTO session_flags (run_date) VALUES (%s) "
                    "ON CONFLICT (run_date) DO NOTHING",
                    (datetime.now().date(),))
                claimed = cur.rowcount == 1
            conn.close()
    except Exception as e:
        logger.warning(f"Neon session flag claim failed ({e}) — file fallback")

    # Local file kept in sync (fast reads + fallback when Neon is down)
    already_in_file = False
    try:
        already_in_file = (_SESSION_STARTED_FILE.read_text().strip()
                           == str(datetime.now().date()))
    except OSError:
        pass
    _SESSION_STARTED_FILE.write_text(str(datetime.now().date()))

    if claimed is None:  # Neon unreachable — best-effort file semantics
        return not already_in_file
    return claimed


def run_daily_sessions():
    """Run scalp, micro-pullback, and VWAP reclaim in coordinated parallel; persist state."""
    from trading.live_scalp_runner import run_scalp_session
    from trading.live_vwap_runner import run_vwap_session
    from trading.live_micro_pullback_runner import run_micro_pullback_session
    import threading

    # Atomically claim today's session (Neon flag). This is the hard guard —
    # deploy-wiped local files can no longer cause a duplicate session.
    if not _claim_session_today():
        logger.warning(
            "run_daily_sessions: today's session already claimed "
            "(Neon session_flags) — refusing duplicate run.")
        return

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
        persist_session(scalp_state_data, vwap_state_data, micro_pullback_state_data)
    except Exception as e:
        logger.error(f"Session persistence import/call failed: {e}", exc_info=True)
