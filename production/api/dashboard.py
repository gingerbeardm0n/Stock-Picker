"""
jTrader Dashboard API
=====================
Lightweight FastAPI service powering the jtrader.jbirdsall.dev dashboard.
Runs on Render alongside the scalp runner.

Endpoints:
  GET /health          — API + broker + news connectivity check
  GET /dashboard       — unified endpoint (candidates + position + config + stage)
  GET /watchlist       — today's gapper candidates + rankings
  GET /position        — current open position (if any)
  GET /trades          — trade history log
  GET /status          — system status (last run, next scheduled, config)
"""

from __future__ import annotations
import os
import sys
import json
import logging
from collections import deque
from datetime import datetime, date
from pathlib import Path

from fastapi import FastAPI, Query, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config import Config
from trading.scalp_models import ScalpConfig
from trading.vwap_models import VwapReclaimConfig

logger = logging.getLogger(__name__)

# In-memory log ring buffer — survives Render's ephemeral log window
_LOG_BUFFER: deque[dict] = deque(maxlen=20000)

# ── Real-time log persistence to Neon ─────────────────────────────────────
# Background thread flushes new log entries to Neon every 30s so logs
# survive Render redeploys without waiting for end-of-session batch.

import threading
import queue as _queue_mod

_LOG_PERSIST_QUEUE: _queue_mod.Queue = _queue_mod.Queue(maxsize=50000)
_NEON_DSN = os.getenv('NEON_CONNECTION_STRING', '')

_SESSION_LOGS_DDL = """
CREATE TABLE IF NOT EXISTS session_logs (
    id          SERIAL PRIMARY KEY,
    run_date    DATE NOT NULL,
    logged_at   TEXT,
    level       TEXT,
    message     TEXT
);
CREATE INDEX IF NOT EXISTS idx_session_logs_date
    ON session_logs (run_date DESC);
"""


def _log_flusher():
    """Background daemon: batch-insert queued log entries to Neon every 30s."""
    import psycopg2
    from psycopg2.extras import execute_values

    if not _NEON_DSN:
        return

    tables_created = False
    while True:
        threading.Event().wait(30)
        batch = []
        while not _LOG_PERSIST_QUEUE.empty() and len(batch) < 5000:
            try:
                batch.append(_LOG_PERSIST_QUEUE.get_nowait())
            except _queue_mod.Empty:
                break
        if not batch:
            continue
        try:
            conn = psycopg2.connect(_NEON_DSN, connect_timeout=10)
            try:
                with conn.cursor() as cur:
                    if not tables_created:
                        cur.execute(_SESSION_LOGS_DDL)
                        tables_created = True
                    execute_values(cur, """
                        INSERT INTO session_logs (run_date, logged_at, level, message)
                        VALUES %s
                    """, batch)
                conn.commit()
            finally:
                conn.close()
        except Exception:
            for row in batch:
                try:
                    _LOG_PERSIST_QUEUE.put_nowait(row)
                except _queue_mod.Full:
                    break


_flusher_thread = threading.Thread(target=_log_flusher, daemon=True)
_flusher_thread.start()


class _BufferHandler(logging.Handler):
    def emit(self, record):
        entry = {
            "t": self.format(record)[:19],
            "level": record.levelname,
            "msg": record.getMessage(),
        }
        _LOG_BUFFER.append(entry)
        run_date = str(date.today())
        try:
            _LOG_PERSIST_QUEUE.put_nowait(
                (run_date, entry["t"], entry["level"], entry["msg"])
            )
        except _queue_mod.Full:
            pass


_handler = _BufferHandler()
_handler.setFormatter(logging.Formatter('%(asctime)s', datefmt='%Y-%m-%d %H:%M:%S'))
_root = logging.getLogger()
_root.addHandler(_handler)
if _root.level > logging.INFO:
    _root.setLevel(logging.INFO)

app = FastAPI(title="jTrader API", version="1.0")

# API key auth — all endpoints except /health require X-API-Key header
_API_KEY = os.getenv("JTRADER_API_KEY", "")
_PUBLIC_PATHS = {"/health", "/docs", "/openapi.json"}


@app.middleware("http")
async def check_api_key(request: Request, call_next):
    if not _API_KEY:
        return await call_next(request)
    if request.url.path in _PUBLIC_PATHS:
        return await call_next(request)
    key = request.headers.get("X-API-Key", "")
    if key != _API_KEY:
        return JSONResponse(status_code=401, content={"detail": "Invalid or missing API key"})
    return await call_next(request)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://jtrader.jbirdsall.dev",
        "http://localhost:3000",
    ],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# Shared state file — written by live_scalp_runner, read by dashboard
STATE_FILE = Path(os.getenv("JTRADER_STATE_DIR", "/tmp/jtrader")) / "state.json"


def _read_state() -> dict:
    """Read the latest state from the runner's state file."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


VWAP_STATE_FILE = Path(os.getenv("JTRADER_STATE_DIR", "/tmp/jtrader")) / "vwap_state.json"


def _read_vwap_state() -> dict:
    if VWAP_STATE_FILE.exists():
        try:
            return json.loads(VWAP_STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


MICRO_PULLBACK_STATE_FILE = Path(os.getenv("JTRADER_STATE_DIR", "/tmp/jtrader")) / "micro_pullback_state.json"


def _read_micro_pullback_state() -> dict:
    if MICRO_PULLBACK_STATE_FILE.exists():
        try:
            return json.loads(MICRO_PULLBACK_STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _infer_stage(state_data: dict) -> str:
    if state_data.get("last_result") == "error":
        return "ERROR"
    if state_data.get("trade_done"):
        if state_data.get("completed_trades") or state_data.get("exit_price"):
            return "EXITED"
    # Multi-position: any open positions → ENTERED
    if state_data.get("positions"):
        return "ENTERED"
    # Legacy single-position compat
    if state_data.get("entry_price") and state_data["entry_price"] > 0:
        if state_data.get("exit_price"):
            return "EXITED"
        return "ENTERED"
    candidates = state_data.get("candidates") or state_data.get("watchlist") or []
    if not candidates:
        return "IDLE"
    if state_data.get("top_pick"):
        return "ARMED"
    return "SCANNING"


def _candidate_stage(candidate: dict, top_pick, strategy_stage: str) -> str:
    sym = candidate.get("symbol", "")
    if isinstance(top_pick, dict):
        is_top = top_pick.get("symbol") == sym
    else:
        is_top = top_pick == sym
    if strategy_stage == "ENTERED" and is_top:
        return "ENTERED"
    if strategy_stage == "EXITED" and is_top:
        return "EXITED"
    if is_top:
        return "ARMED"
    return "WATCHING"


def _config_to_dict(config) -> dict:
    from dataclasses import asdict
    return asdict(config)


@app.api_route("/health", methods=["GET", "HEAD"])
def health_check():
    """Check connectivity to Tradier and Alpaca APIs."""
    checks = {}

    # Tradier
    try:
        import requests as req
        token = os.getenv("TRADIER_PAPER_TOKEN", "")
        if token:
            r = req.get(
                "https://sandbox.tradier.com/v1/markets/clock",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                timeout=5,
            )
            checks["tradier"] = {"status": "ok" if r.status_code == 200 else "error", "code": r.status_code}
        else:
            checks["tradier"] = {"status": "no_key"}
    except Exception as e:
        checks["tradier"] = {"status": "error", "detail": str(e)}

    # Alpaca (news)
    try:
        key = os.getenv("APCA_API_KEY_ID", "")
        secret = os.getenv("APCA_API_SECRET_KEY", "")
        if key and secret:
            import requests as req
            r = req.get(
                "https://data.alpaca.markets/v1beta1/news?limit=1",
                headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret},
                timeout=5,
            )
            checks["alpaca_news"] = {"status": "ok" if r.status_code == 200 else "error", "code": r.status_code}
        else:
            checks["alpaca_news"] = {"status": "no_key"}
    except Exception as e:
        checks["alpaca_news"] = {"status": "error", "detail": str(e)}

    all_ok = all(c.get("status") == "ok" for c in checks.values())
    return {"healthy": all_ok, "checks": checks, "timestamp": datetime.utcnow().isoformat()}


@app.get("/watchlist")
def get_watchlist():
    """Return today's gapper watchlist with rankings."""
    state = _read_state()
    return {
        "date": state.get("date", str(date.today())),
        "candidates": state.get("candidates", []),
        "top_pick": state.get("top_pick"),
        "scanned_at": state.get("scanned_at"),
    }


@app.get("/position")
def get_position():
    """Return current open position details."""
    state = _read_state()
    return {
        "has_position": state.get("has_position", False),
        "symbol": state.get("position_symbol"),
        "entry_price": state.get("entry_price"),
        "current_price": state.get("current_price"),
        "pnl": state.get("pnl"),
        "stop_price": state.get("stop_price"),
        "target_price": state.get("target_price"),
        "bars_held": state.get("bars_held"),
    }


# live_trades.strategy uses short tags; generate_journal.py and the frontend
# expect the same long-form names session state files use.
_STRATEGY_DISPLAY_NAME = {
    "scalp": "opening_bell_scalp",
    "vwap": "vwap_reclaim",
    "micro_pullback": "micro_pullback",
}


@app.get("/trades")
def get_trades(days: int = Query(default=30, le=365)):
    """Return trade history from Neon live_trades — durable, survives deploys.

    /tmp/jtrader/trades.json (the old source) is on Render's ephemeral disk
    and resets to empty on every redeploy regardless of what actually
    happened. live_trades is populated by session_report.py (run after each
    session) and isn't affected by app restarts.
    """
    try:
        from api.session_persistence import _get_conn
        conn = _get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT trade_date, strategy, symbol, shares, decision_time,
                           decision_price, paper_fill, paper_exit, paper_pnl, exit_reason
                    FROM live_trades
                    WHERE trade_date >= CURRENT_DATE - %s
                    ORDER BY trade_date DESC, decision_time DESC
                    LIMIT 500
                """, (days,))
                cols = [d[0] for d in cur.description]
                rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        finally:
            conn.close()

        trades = []
        for r in rows:
            entry_price = r["paper_fill"] if r["paper_fill"] is not None else r["decision_price"]
            trades.append({
                "date": str(r["trade_date"]),
                "strategy": _STRATEGY_DISPLAY_NAME.get(r["strategy"], r["strategy"]),
                "symbol": r["symbol"],
                "shares": r["shares"],
                "entry_price": float(entry_price) if entry_price is not None else None,
                "exit_price": float(r["paper_exit"]) if r["paper_exit"] is not None else None,
                "pnl": float(r["paper_pnl"]) if r["paper_pnl"] is not None else None,
                "exit_reason": r["exit_reason"],
                "decision_time": r["decision_time"].isoformat() if r["decision_time"] else None,
            })
        return {"trades": trades}
    except Exception as e:
        logger.error(f"/trades: Neon query failed ({e}) — falling back to ephemeral file")
        trades_file = Path(os.getenv("JTRADER_STATE_DIR", "/tmp/jtrader")) / "trades.json"
        if trades_file.exists():
            try:
                return {"trades": json.loads(trades_file.read_text())}
            except (json.JSONDecodeError, OSError):
                pass
        return {"trades": []}


@app.get("/status")
def get_status():
    """Return system status."""
    state = _read_state()
    return {
        "last_run": state.get("last_run"),
        "last_result": state.get("last_result"),
        "error": state.get("error"),
        "config": {
            "min_gap_pct": state.get("min_gap_pct", 5.0),
            "entry_mode": state.get("entry_mode", "first_green"),
            "require_news": True,
        },
        "mode": "paper",
        "server_time": datetime.utcnow().isoformat(),
    }


@app.get("/logs")
def get_logs(n: int = Query(default=500, le=20000)):
    """Return last N log lines from in-memory buffer."""
    entries = list(_LOG_BUFFER)[-n:]
    return {"count": len(entries), "logs": entries}


@app.get("/bars_dump")
def get_bars_dump(date: str | None = Query(None, description="YYYY-MM-DD; omit for today")):
    """Return bars captured on a given day (default today) — live/sim parity diagnostic.

    Pass ?date=YYYY-MM-DD to pull a prior day still on Render's ephemeral disk
    (e.g. Friday's capture fetched Saturday before the next redeploy wipes it).
    """
    from trading.bar_capture import read_today, read_bars_for_date, available_dates
    try:
        rows = read_bars_for_date(date) if date else read_today()
    except ValueError:
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD or YYYYMMDD")
    return {"count": len(rows), "date": date or "today",
            "available": available_dates("bars"), "bars": rows}


@app.get("/news_dump")
def get_news_dump(date: str | None = Query(None, description="YYYY-MM-DD; omit for today")):
    """Return news the live runners fetched on a given day (default today) — parity diagnostic."""
    from trading.bar_capture import read_today_news, read_news_for_date, available_dates
    try:
        rows = read_news_for_date(date) if date else read_today_news()
    except ValueError:
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD or YYYYMMDD")
    return {"count": len(rows), "date": date or "today",
            "available": available_dates("news"), "news": rows}


@app.post("/trigger")
def trigger_session():
    """Manually trigger the daily sessions (scalp + VWAP reclaim) in background."""
    import threading
    from api.session_job import run_daily_sessions, is_session_started_today

    if is_session_started_today():
        logger.info("Trigger received but session already started today — skipping")
        return {"triggered": False, "message": "Session already running today"}

    t = threading.Thread(target=run_daily_sessions, daemon=True)
    t.start()
    logger.info("Manual trigger: daily sessions (scalp + vwap) kicked off")
    return {"triggered": True, "message": "Daily sessions started in background"}


@app.get("/dashboard")
def get_dashboard():
    """Unified dashboard endpoint — all data in one call."""
    scalp_state = _read_state()
    vwap_state = _read_vwap_state()
    mp_state = _read_micro_pullback_state()

    scalp_stage = _infer_stage(scalp_state)
    vwap_stage = _infer_stage(vwap_state)
    mp_stage = _infer_stage(mp_state)

    scalp_candidates = scalp_state.get("candidates", [])
    scalp_top = scalp_state.get("top_pick")
    scalp_open_syms = set((scalp_state.get("positions") or {}).keys())
    scalp_done_syms = {t.get("symbol") for t in (scalp_state.get("completed_trades") or [])}
    for c in scalp_candidates:
        if isinstance(c, dict):
            sym = c.get("symbol", "")
            if scalp_stage in ("IDLE", "SCANNING"):
                c["stage"] = "WATCHING"
            elif sym in scalp_open_syms:
                c["stage"] = "ENTERED"
            elif sym in scalp_done_syms:
                c["stage"] = "EXITED"
            else:
                c["stage"] = "ARMED"

    vwap_candidates = vwap_state.get("watchlist", [])
    vwap_top = vwap_state.get("top_pick") or vwap_state.get("symbol")
    vwap_open_syms = set((vwap_state.get("positions") or {}).keys())
    vwap_done_syms = {t.get("symbol") for t in (vwap_state.get("completed_trades") or [])}
    for c in vwap_candidates:
        if isinstance(c, dict):
            sym = c.get("symbol", "")
            if vwap_stage in ("IDLE", "SCANNING"):
                c["stage"] = "WATCHING"
            elif sym in vwap_open_syms:
                c["stage"] = "ENTERED"
            elif sym in vwap_done_syms:
                c["stage"] = "EXITED"
            else:
                c["stage"] = "ARMED"

    # Micro-Pullback is single-position (not multi like scalp/VWAP), so there's
    # no "positions" dict — just the current/last trade's symbol.
    mp_candidates = mp_state.get("watchlist", [])
    mp_top = mp_state.get("top_pick") or mp_state.get("symbol")
    mp_open_sym = mp_state.get("symbol") if mp_stage == "ENTERED" else None
    mp_done_syms = {t.get("symbol") for t in (mp_state.get("completed_trades") or [])}
    for c in mp_candidates:
        if isinstance(c, dict):
            sym = c.get("symbol", "")
            if mp_stage in ("IDLE", "SCANNING"):
                c["stage"] = "WATCHING"
            elif sym == mp_open_sym:
                c["stage"] = "ENTERED"
            elif sym in mp_done_syms:
                c["stage"] = "EXITED"
            else:
                c["stage"] = "ARMED"

    # Multi-position: return completed_trades list + any open positions dict.
    # Fall back to legacy single-position fields for backward compat.
    scalp_position = None
    if scalp_stage in ("ENTERED", "EXITED"):
        scalp_position = {
            "completed_trades": scalp_state.get("completed_trades", []),
            "open_positions": scalp_state.get("positions", {}),
            "trade_count": scalp_state.get("trade_count", 0),
            "pnl": scalp_state.get("pnl"),
            # Legacy compat (first trade) for any older frontend code
            "entry_price": scalp_state.get("entry_price"),
            "exit_price": scalp_state.get("exit_price"),
            "shares": scalp_state.get("shares"),
            "bars_held": scalp_state.get("bars_held"),
        }

    vwap_position = None
    if vwap_stage in ("ENTERED", "EXITED"):
        vwap_position = {
            "open_positions": vwap_state.get("positions", {}),
            "completed_trades": vwap_state.get("completed_trades", []),
            "trade_count": vwap_state.get("trade_count", 0),
            "pnl": vwap_state.get("pnl"),
            # Legacy compat
            "entry_price": vwap_state.get("entry_price"),
            "exit_price": vwap_state.get("exit_price"),
            "exit_reason": vwap_state.get("exit_reason"),
        }

    mp_position = None
    if mp_stage in ("ENTERED", "EXITED"):
        mp_position = {
            "completed_trades": mp_state.get("completed_trades", []),
            "trade_count": mp_state.get("trade_count", 0),
            "pnl": mp_state.get("pnl"),
            "entry_price": mp_state.get("entry_price"),
            "exit_price": mp_state.get("exit_price"),
            "stop_price": mp_state.get("stop_price"),
            "shares": mp_state.get("shares"),
            "bars_held": mp_state.get("bars_held"),
            "exit_reason": mp_state.get("exit_reason"),
        }

    scalp_pnl = scalp_state.get("pnl") or 0
    # VWAP may have multiple trades; use persisted total_pnl if available
    vwap_pnl = vwap_state.get("pnl") or 0
    mp_pnl = mp_state.get("pnl") or 0
    scalp_trades = 1 if (scalp_state.get("entry_price") or 0) > 0 else 0
    vwap_trades = vwap_state.get("trade_count") or (1 if (vwap_state.get("entry_price") or 0) > 0 else 0)
    mp_trades = mp_state.get("trade_count") or (1 if (mp_state.get("entry_price") or 0) > 0 else 0)
    trade_count = scalp_trades + vwap_trades + mp_trades

    from trading.live_scalp_runner import TRIAL_173_CONFIG as SCALP_CONFIG
    from trading.live_vwap_runner import TRIAL_56_CONFIG as VWAP_CONFIG
    from trading.live_micro_pullback_runner import TRIAL_167_CONFIG as MP_CONFIG

    return {
        "server_time": datetime.utcnow().isoformat(),
        "scalp": {
            "stage": scalp_stage,
            "last_run": scalp_state.get("last_run"),
            "last_result": scalp_state.get("last_result"),
            "date": scalp_state.get("date"),
            "candidates": scalp_candidates,
            "top_pick": scalp_top,
            "position": scalp_position,
            "config": _config_to_dict(SCALP_CONFIG),
        },
        "vwap": {
            "stage": vwap_stage,
            "last_run": vwap_state.get("last_run"),
            "last_result": vwap_state.get("last_result"),
            "date": vwap_state.get("date"),
            "candidates": vwap_candidates,
            "top_pick": vwap_top,
            "position": vwap_position,
            "config": _config_to_dict(VWAP_CONFIG),
        },
        "micro_pullback": {
            "stage": mp_stage,
            "last_run": mp_state.get("last_run"),
            "last_result": mp_state.get("last_result"),
            "date": mp_state.get("date"),
            "candidates": mp_candidates,
            "top_pick": mp_top,
            "position": mp_position,
            "config": _config_to_dict(MP_CONFIG),
        },
        "session_pnl": scalp_pnl + vwap_pnl + mp_pnl,
        "trade_count": trade_count,
    }


@app.get("/vwap")
def get_vwap_state():
    """Return latest VWAP Reclaim session state."""
    vwap_file = Path(os.getenv("JTRADER_STATE_DIR", "/tmp/jtrader")) / "vwap_state.json"
    if vwap_file.exists():
        try:
            return json.loads(vwap_file.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"last_run": None, "last_result": None, "strategy": "vwap_reclaim"}


@app.post("/persist")
def force_persist():
    """Force-persist current session data to TimescaleDB (use before manual deploys)."""
    from api.session_persistence import persist_session
    scalp = _read_state()
    vwap = _read_vwap_state()
    if not scalp and not vwap:
        return {"persisted": False, "reason": "no session data on disk"}
    persist_session(scalp, vwap)
    return {"persisted": True, "scalp_result": scalp.get("last_result"), "vwap_result": vwap.get("last_result")}


@app.get("/session_history")
def get_session_history(days: int = Query(default=30, le=365)):
    """Return past session runs from TimescaleDB."""
    try:
        from api.session_persistence import _get_conn
        conn = _get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT run_date, strategy, result, top_pick,
                           entry_price, exit_price, pnl, persisted_at
                    FROM session_runs
                    WHERE run_date >= CURRENT_DATE - %s
                    ORDER BY run_date DESC, strategy
                """, (days,))
                cols = [d[0] for d in cur.description]
                rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            return {"count": len(rows), "sessions": rows}
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"session_history query failed: {e}")
        return {"count": 0, "sessions": [], "error": str(e)}
