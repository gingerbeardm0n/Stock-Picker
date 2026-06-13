"""
Live / Paper Trading Entry Point
=================================
Wires together: data feed (quotes) + bar poller → LiveScanner → LiveTradeManager.

Broker is selected via BROKER= in .env.paper / .env.live (default: tradier).
Switch to Alpaca by setting BROKER=alpaca (requires pip install alpaca-py).

Usage:
    export TRADING_MODE=PAPER
    python production/run_trading.py

    # Custom stop time:
    python production/run_trading.py --stop-hour 11

Safety:
    - TRADING_MODE must be PAPER or LIVE (enforced by config.py)
    - PAPER is the default; LIVE requires explicit env var + confirmation phrase
    - emergency_flatten() called if process is stopped while position is open
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

import argparse
import csv
import json
import logging
import logging.handlers
import queue
import signal
import threading
import time
from datetime import datetime
from pathlib import Path

STATUS_FILE = Path(__file__).parent / 'logs' / 'session_status.json'

import pytz

from config import Config
from trading.order_manager import OrderExecutor, LiveTradeManager
from trading.live_scanner import LiveScanner

ET = pytz.timezone('America/New_York')

# Symbols file — checked in both canonical locations
_services_file = os.path.join(os.path.dirname(__file__), 'services/stocks_in_price_range.txt')
_database_file = os.path.join(os.path.dirname(__file__), '../database/stocks_1_to_20.txt')
SYMBOLS_FILE   = _services_file if os.path.exists(_services_file) else _database_file
LOGS_DIR       = Path(__file__).parent / 'logs'

logger = logging.getLogger(__name__)


def setup_logging(today_str: str):
    """Configure logging to console + rotating daily session log."""
    LOGS_DIR.mkdir(exist_ok=True)
    log_path = LOGS_DIR / f'session_{today_str}.log'

    fmt = logging.Formatter(
        '%(asctime)s [%(levelname)-8s] %(name)s — %(message)s',
        datefmt='%H:%M:%S',
    )

    file_handler    = logging.FileHandler(log_path, encoding='utf-8')
    console_handler = logging.StreamHandler(sys.stdout)
    file_handler.setFormatter(fmt)
    console_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(console_handler)

    # Suppress noisy third-party loggers
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('requests').setLevel(logging.WARNING)
    logging.getLogger('alpaca').setLevel(logging.WARNING)
    logging.getLogger('websockets').setLevel(logging.WARNING)

    logger.info(f"Session log: {log_path}")


TRADE_CSV_COLUMNS = [
    'date', 'symbol', 'pattern_type',
    'entry_time', 'entry_price', 'shares',
    'stop_loss', 'target1', 'target2',
    'exit_time', 'exit_price', 'exit_reason',
    'hold_minutes', 'pnl', 'pnl_pct',
    'fills',
]


def open_trade_csv(today_str: str) -> tuple[csv.DictWriter, object]:
    """Open (or append to) today's trade CSV. Returns (writer, file_handle)."""
    LOGS_DIR.mkdir(exist_ok=True)
    csv_path = LOGS_DIR / f'trades_{today_str}.csv'
    is_new   = not csv_path.exists()
    fh       = open(csv_path, 'a', newline='', encoding='utf-8')
    writer   = csv.DictWriter(fh, fieldnames=TRADE_CSV_COLUMNS)
    if is_new:
        writer.writeheader()
    logger.info(f"Trade log: {csv_path}")
    return writer, fh


def log_trade(writer: csv.DictWriter, trade, today_str: str):
    """Write a completed Trade object as one CSV row."""
    pnl     = trade.get_pnl()
    pnl_pct = (pnl / (trade.entry_price * trade.shares) * 100) if trade.shares else 0

    fills_json = json.dumps([
        {
            'qty':    f['qty'],
            'price':  round(f['price'], 4),
            'reason': f['reason'],
            'time':   f['time'].isoformat() if hasattr(f['time'], 'isoformat') else str(f['time']),
        }
        for f in (trade.fills or [])
    ])

    writer.writerow({
        'date':         today_str,
        'symbol':       trade.symbol,
        'pattern_type': trade.pattern_type,
        'entry_time':   trade.entry_time.astimezone(ET).strftime('%H:%M:%S') if trade.entry_time else '',
        'entry_price':  round(trade.entry_price, 4),
        'shares':       trade.shares,
        'stop_loss':    round(trade.stop_loss, 4),
        'target1':      round(trade.target1, 4),
        'target2':      round(trade.target2, 4),
        'exit_time':    trade.exit_time.astimezone(ET).strftime('%H:%M:%S') if trade.exit_time else '',
        'exit_price':   round(trade.exit_price, 4) if trade.exit_price else '',
        'exit_reason':  trade.exit_reason or '',
        'hold_minutes': trade.get_exit_time_minutes(),
        'pnl':          round(pnl, 2),
        'pnl_pct':      round(pnl_pct, 2),
        'fills':        fills_json,
    })


def write_status_json(scanner, trade_manager, bars_processed: int, session_pnl: float):
    """Write scanner state to production/logs/session_status.json (read by Flask UI)."""
    now_et = datetime.now(ET)
    try:
        snapshot = scanner.get_status_snapshot(now_et)
        snapshot['bars_processed']   = bars_processed
        snapshot['session_pnl']      = round(session_pnl, 2)
        snapshot['completed_trades'] = len(trade_manager.completed_trades)
        LOGS_DIR.mkdir(exist_ok=True)
        STATUS_FILE.write_text(json.dumps(snapshot, indent=2), encoding='utf-8')
    except Exception as e:
        logger.warning(f"Failed to write session_status.json: {e}")


def clear_status_json():
    """Write 'session not running' marker when session ends."""
    try:
        STATUS_FILE.write_text(
            json.dumps({'session_running': False,
                        'as_of': datetime.now(ET).strftime('%H:%M:%S')}),
            encoding='utf-8',
        )
    except Exception:
        pass


def load_symbols(path: str) -> list[str]:
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Symbol file not found: {path}\n"
            "Run: python database/fetch_stocks_1_to_20.py"
        )
    with open(path) as f:
        symbols = [line.strip() for line in f if line.strip()]
    logger.info(f"Loaded {len(symbols):,} symbols from {os.path.basename(path)}")
    return symbols


def main():
    parser = argparse.ArgumentParser(description='Live/Paper Trading Bot')
    parser.add_argument('--stop-hour', type=int, default=12,
                        help='ET hour to stop the session (default: 12 = noon)')
    parser.add_argument('--entry-hour-end', type=int, default=11,
                        help='ET hour to stop looking for new entries (default: 11)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Log signals but do NOT place any orders (safe for testing)')
    args = parser.parse_args()

    today_str = datetime.now(ET).strftime('%Y-%m-%d')
    setup_logging(today_str)

    # ── Live mode confirmation gate ───────────────────────────────────────────
    if Config.TRADING_MODE == 'LIVE':
        print("\n" + "!" * 70)
        print("  WARNING: LIVE TRADING MODE")
        print("  Real money will be used. Orders will be placed on your live account.")
        print("!" * 70)
        try:
            phrase = input("\n  Type exactly  ->  yes, use real money  <-  to continue: ")
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            sys.exit(0)
        if phrase.strip().lower() != "yes, use real money":
            print("Confirmation phrase did not match. Exiting.")
            sys.exit(1)
        print("Confirmed. Starting LIVE session.\n")

    dry_run_label = " [DRY RUN — no orders will be placed]" if args.dry_run else ""
    print("\n" + "=" * 70)
    print(f"LIVE TRADING ENGINE — {today_str} — {Config.TRADING_MODE}{dry_run_label}")
    print(f"Broker: {Config.BROKER.upper()}")
    print(f"Entry window: 9:30am – {args.entry_hour_end}:00 ET | "
          f"Session ends: {args.stop_hour}:00 ET")
    print("=" * 70)

    # ── Connect to broker + data feed ─────────────────────────────────────────
    broker    = Config.get_broker()
    data_feed = Config.get_data_feed()
    balance   = broker.get_account_balance()
    logger.info(f"Starting balance: ${balance:,.2f}")

    # ── Load symbols ──────────────────────────────────────────────────────────
    symbols = load_symbols(SYMBOLS_FILE)

    # ── Build trading stack ───────────────────────────────────────────────────
    executor      = OrderExecutor(broker)
    trade_manager = LiveTradeManager(executor, account_balance=balance)
    scanner       = LiveScanner(
        trade_manager,
        symbols,
        data_feed=data_feed,
        entry_hour_end=args.entry_hour_end,
        dry_run=args.dry_run,
    )

    # ── Open trade log CSV ────────────────────────────────────────────────────
    trade_writer, trade_csv_fh = open_trade_csv(today_str)
    trades_logged = 0

    # ── Pre-load historical data from DB ──────────────────────────────────────
    logger.info("Pre-loading prior closes and fundamentals from DB...")
    scanner.startup_preload()
    logger.info("Pre-load complete.")

    write_status_json(scanner, trade_manager, 0, 0.0)

    # ── Set up bar stream / poller ────────────────────────────────────────────
    bar_queue = queue.Queue(maxsize=10_000)

    if Config.BROKER == 'tradier':
        from trading.broker.tradier import TradierBarPoller
        bar_poller = TradierBarPoller(
            token=Config.TRADIER_TOKEN,
            sandbox=(Config.TRADING_MODE == 'PAPER'),
            bar_queue=bar_queue,
        )
        # Seed watchlist with premarket-qualified symbols from startup_preload
        bar_poller.set_watchlist(scanner.get_watchlist())
        stream_thread = threading.Thread(target=bar_poller.start, name='poller', daemon=True)
        stream_thread.start()
        logger.info(f"TradierBarPoller started with {len(scanner.get_watchlist())} symbols.")
    else:
        # Alpaca WebSocket stream
        from trading.broker.alpaca import AlpacaBarStream
        bar_stream = AlpacaBarStream(
            api_key=Config.ALPACA_API_KEY,
            secret_key=Config.ALPACA_SECRET_KEY,
            symbols=symbols,
            bar_queue=bar_queue,
        )
        stream_thread = threading.Thread(target=bar_stream.start, name='stream', daemon=True)
        stream_thread.start()
        logger.info(f"AlpacaBarStream started, monitoring {len(symbols):,} symbols.")
        bar_poller = None

    # ── Graceful shutdown handler ─────────────────────────────────────────────
    shutdown_requested = threading.Event()

    def _handle_signal(sig, frame):
        logger.warning(f"Signal {sig} received — shutting down...")
        shutdown_requested.set()

    signal.signal(signal.SIGINT,  _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    # ── Main bar-processing loop ──────────────────────────────────────────────
    bars_processed = 0
    session_start  = time.time()

    if args.dry_run:
        logger.info("DRY RUN MODE: signals logged but NO orders placed.")
    logger.info(f"Entry window: 9:30am – {args.entry_hour_end}:00 ET. "
                f"Session ends: {args.stop_hour}:00 ET.")
    print("=" * 70)

    try:
        while not shutdown_requested.is_set():
            now_et = datetime.now(ET)

            if now_et.hour >= args.stop_hour:
                logger.info(f"{args.stop_hour}:00 ET reached — trading window closed.")
                break

            try:
                bar = bar_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            scanner.process_bar(bar)
            bars_processed += 1

            # After premarket scan fires, sync poller watchlist + write status
            if scanner.status_write_requested:
                scanner.status_write_requested = False
                write_status_json(scanner, trade_manager, bars_processed,
                                  trade_manager.realized_pnl)
                if bar_poller is not None:
                    bar_poller.set_watchlist(scanner.get_watchlist())

            # ── Write newly completed trades to CSV ────────────────────────
            completed = trade_manager.completed_trades
            while trades_logged < len(completed):
                trade = completed[trades_logged]
                log_trade(trade_writer, trade, today_str)
                trade_csv_fh.flush()
                pnl = trade.get_pnl()
                logger.info(
                    f"TRADE LOGGED: {trade.symbol} {trade.pattern_type} "
                    f"entry=${trade.entry_price:.2f} exit=${trade.exit_price:.2f} "
                    f"shares={trade.shares} P&L=${pnl:+.2f} "
                    f"({trade.exit_reason}) held {trade.get_exit_time_minutes()}min"
                )
                trades_logged += 1

            # Periodic heartbeat every 100 bars
            if bars_processed % 100 == 0:
                elapsed = time.time() - session_start
                qsize   = bar_queue.qsize()
                logger.info(f"Heartbeat: {bars_processed:,} bars | queue={qsize} | "
                            f"{elapsed:.0f}s | gaprun={len(scanner.get_watchlist())}")
                write_status_json(scanner, trade_manager, bars_processed,
                                  trade_manager.realized_pnl)

                # Top 5 gap-run symbols by peak gain
                trackers = scanner._gap_trackers
                if trackers:
                    top = sorted(
                        ((sym, t) for sym, t in trackers.items() if t.max_gain_seen > 0),
                        key=lambda x: x[1].max_gain_seen,
                        reverse=True,
                    )[:5]
                    if top:
                        lines = []
                        for sym, t in top:
                            active = (f" [ACTIVE streak from ${t.run_start_open:.2f}]"
                                      if t.run_start_open else "")
                            lines.append(f"  {sym}: peak={t.max_gain_seen:.1f}%{active}")
                        logger.info("Top streak gains:\n" + "\n".join(lines))

    finally:
        # ── Shutdown ──────────────────────────────────────────────────────────
        logger.info("Shutting down...")

        if trade_manager.has_open_position():
            logger.warning("Position still open — emergency flattening...")
            pnl = trade_manager.emergency_flatten()
            logger.info(f"Emergency flatten P&L: ${pnl:+.2f}")

        if bar_poller is not None:
            bar_poller.stop()
        elif 'bar_stream' in locals():
            bar_stream.stop()

        scanner.close()
        trade_csv_fh.close()
        clear_status_json()

        elapsed = time.time() - session_start
        logger.info(f"Session complete: {bars_processed:,} bars in {elapsed:.0f}s")
        logger.info(f"Session P&L: ${trade_manager.realized_pnl:+.2f}")
        logger.info(f"Completed trades: {len(trade_manager.completed_trades)}")
        if trade_manager.completed_trades:
            wins  = sum(1 for t in trade_manager.completed_trades if t.get_pnl() > 0)
            total = len(trade_manager.completed_trades)
            logger.info(f"Win rate: {wins}/{total} ({wins/total*100:.0f}%)")
        logger.info(f"Trade log: {LOGS_DIR / f'trades_{today_str}.csv'}")

    print("=" * 70)
    print("Trading session ended.")
    print("=" * 70)


if __name__ == "__main__":
    main()
