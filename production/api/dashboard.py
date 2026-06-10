"""
jTrader Dashboard API
=====================
Lightweight FastAPI service powering the jtrader.jbirdsall.dev dashboard.
Runs on Render alongside the scalp runner.

Endpoints:
  GET /health          — API + broker + news connectivity check
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

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config import Config
from trading.scalp_models import ScalpConfig

logger = logging.getLogger(__name__)

# In-memory log ring buffer (last 500 lines) — survives Render's ephemeral log window
_LOG_BUFFER: deque[dict] = deque(maxlen=500)


class _BufferHandler(logging.Handler):
    def emit(self, record):
        _LOG_BUFFER.append({
            "t": self.format(record)[:19],
            "level": record.levelname,
            "msg": record.getMessage(),
        })


_handler = _BufferHandler()
_handler.setFormatter(logging.Formatter('%(asctime)s', datefmt='%Y-%m-%d %H:%M:%S'))
logging.getLogger().addHandler(_handler)

app = FastAPI(title="jTrader API", version="1.0")

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


@app.get("/health")
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


@app.get("/trades")
def get_trades():
    """Return trade history."""
    trades_file = Path(os.getenv("JTRADER_STATE_DIR", "/tmp/jtrader")) / "trades.json"
    if trades_file.exists():
        try:
            trades = json.loads(trades_file.read_text())
            return {"trades": trades}
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
            "min_gap_pct": state.get("min_gap_pct", 11.65),
            "entry_mode": state.get("entry_mode", "first_green"),
            "require_news": True,
        },
        "mode": "paper",
        "server_time": datetime.utcnow().isoformat(),
    }


@app.get("/logs")
def get_logs(n: int = Query(default=100, le=500)):
    """Return last N log lines from in-memory buffer."""
    entries = list(_LOG_BUFFER)[-n:]
    return {"count": len(entries), "logs": entries}
