"""
jTrader Server
==============
Combined FastAPI dashboard + APScheduler for daily scalp execution.
Single process — runs the dashboard API and schedules the scalp runner.

Usage:
  python api/server.py              # Start server (port from $PORT or 8000)
  python api/server.py --run-now    # Start server AND immediately run a scalp session
"""

from __future__ import annotations
import os
import sys
import json
import logging
import threading
import argparse
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from dotenv import load_dotenv

# Load env before anything else
env_file = os.path.join(os.path.dirname(__file__), '..', '.env.paper')
if os.path.exists(env_file):
    load_dotenv(env_file)

import uvicorn
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from api.dashboard import app
from trading.live_scalp_runner import run_scalp_session

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-5s | %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger(__name__)

STATE_DIR = Path(os.getenv("JTRADER_STATE_DIR", "/tmp/jtrader"))
STATE_DIR.mkdir(parents=True, exist_ok=True)


def _run_scalp_and_save_state():
    """Run a scalp session and persist state for the dashboard."""
    logger.info("=== SCHEDULED SCALP SESSION STARTING ===")
    try:
        state = run_scalp_session(dry_run=False, live=False)

        state_data = {
            "last_run": datetime.utcnow().isoformat(),
            "last_result": "trade" if getattr(state, 'trade_placed', False) else "no_trade",
            "date": str(datetime.now().date()),
            "candidates": getattr(state, 'candidates', []),
            "top_pick": getattr(state, 'top_pick', None),
            "scanned_at": getattr(state, 'scanned_at', None),
            "has_position": getattr(state, 'has_position', False),
            "position_symbol": getattr(state, 'position_symbol', None),
            "entry_price": getattr(state, 'entry_price', None),
            "pnl": getattr(state, 'pnl', None),
            "trade_done": getattr(state, 'trade_done', False),
        }

        state_file = STATE_DIR / "state.json"
        state_file.write_text(json.dumps(state_data, default=str))

        # Append to trade history if a trade was placed
        if state_data.get("last_result") == "trade":
            trades_file = STATE_DIR / "trades.json"
            trades = []
            if trades_file.exists():
                try:
                    trades = json.loads(trades_file.read_text())
                except (json.JSONDecodeError, OSError):
                    trades = []
            trades.append(state_data)
            trades_file.write_text(json.dumps(trades, default=str))

        logger.info(f"=== SCALP SESSION COMPLETE: {state_data['last_result']} ===")
    except Exception as e:
        logger.error(f"Scalp session failed: {e}", exc_info=True)
        state_file = STATE_DIR / "state.json"
        state_file.write_text(json.dumps({
            "last_run": datetime.utcnow().isoformat(),
            "last_result": "error",
            "error": str(e),
        }))


def main():
    parser = argparse.ArgumentParser(description='jTrader Server')
    parser.add_argument('--run-now', action='store_true',
                        help='Run a scalp session immediately on startup')
    args = parser.parse_args()

    # Set up APScheduler — run scalp at 8:55 AM ET (13:55 UTC) Mon-Fri
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        _run_scalp_and_save_state,
        CronTrigger(
            day_of_week='mon-fri',
            hour=8, minute=55,  # 8:55 AM ET
            timezone='US/Eastern',
        ),
        id='daily_scalp',
        name='Opening Bell Scalp',
        misfire_grace_time=300,
    )
    scheduler.start()
    logger.info("Scheduler started — scalp runs Mon-Fri at 8:55 AM ET")

    if args.run_now:
        logger.info("--run-now flag: launching scalp session in background thread")
        t = threading.Thread(target=_run_scalp_and_save_state, daemon=True)
        t.start()

    port = int(os.getenv("PORT", 8000))
    logger.info(f"Dashboard API starting on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == '__main__':
    main()
