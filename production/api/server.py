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
from api.session_job import run_daily_sessions

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-5s | %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger(__name__)

STATE_DIR = Path(os.getenv("JTRADER_STATE_DIR", "/tmp/jtrader"))
STATE_DIR.mkdir(parents=True, exist_ok=True)


def main():
    parser = argparse.ArgumentParser(description='jTrader Server')
    parser.add_argument('--run-now', action='store_true',
                        help='Run a scalp session immediately on startup')
    args = parser.parse_args()

    # Set up APScheduler — run both strategies (scalp then VWAP reclaim)
    # starting at 8:00 AM ET Mon-Fri (early start = premarket smoke test:
    # scanning, quotes, and news all warm up well before the bell)
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_daily_sessions,
        CronTrigger(
            day_of_week='mon-fri',
            hour=8, minute=0,  # 8:00 AM ET
            timezone='US/Eastern',
        ),
        id='daily_sessions',
        name='Opening Bell Scalp + VWAP Reclaim',
        misfire_grace_time=300,
    )
    scheduler.start()
    logger.info("Scheduler started — scalp + vwap reclaim run Mon-Fri at 8:00 AM ET")

    if args.run_now:
        logger.info("--run-now flag: launching sessions in background thread")
        t = threading.Thread(target=run_daily_sessions, daemon=True)
        t.start()

    port = int(os.getenv("PORT", 8000))
    logger.info(f"Dashboard API starting on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == '__main__':
    main()
