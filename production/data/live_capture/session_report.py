#!/usr/bin/env python3
"""
session_report.py — Daily post-session report: paper P&L vs live-counterfactual P&L.

The Tradier sandbox fills paper orders against a 15-min-delayed quote engine,
so paper fill prices are noisy. This report measures that distortion daily:

  1. Pull the session's decision events from the dashboard /logs endpoint
     (entry decisions with price/shares, fills, exit summaries).
  2. Fetch the real 1-min tape for each traded symbol from Tradier production
     timesales (independent of the bar-capture file, which dies on redeploy).
  3. Replay each trade counterfactually: assume the entry filled instantly at
     the DECISION price (live behavior), then walk the real bars through the
     same exit logic (vwap_engine / scalp_engine evaluate_exit) used live.
  4. Print paper vs counterfactual side by side.

Also (if DB_DSN is set) pulls /bars_dump into stock_candles_live_1m first, so
running this IS the end-of-session routine. Run BEFORE any evening deploy —
a Render redeploy wipes the day's capture file.

Usage:
    JTRADER_API_KEY=... DB_DSN=... python production/data/live_capture/session_report.py
    python session_report.py --date 2026-06-12   (tape replay only, no pull)
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

import argparse
import re
from datetime import datetime, date

import requests
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env.paper'))
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env.render.dec'))

DASHBOARD = os.getenv('JTRADER_DASHBOARD_URL', 'https://jtrader-api.onrender.com')
API_KEY = os.getenv('JTRADER_API_KEY', '')
PROD_TOKEN = os.getenv('TRADIER_PRODUCTION_TOKEN', '')
DB_DSN = os.getenv('DB_DSN') or os.getenv('OPTUNA_STORAGE') or os.getenv('NEON_CONNECTION_STRING')


# ── live_trades table ──────────────────────────────────────────────────────

CREATE_LIVE_TRADES = """
CREATE TABLE IF NOT EXISTS live_trades (
    id              BIGSERIAL PRIMARY KEY,
    trade_date      DATE NOT NULL,
    strategy        TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    shares          INT NOT NULL,
    decision_time   TIMESTAMPTZ,
    decision_price  NUMERIC(10,4),
    paper_fill      NUMERIC(10,4),
    paper_exit      NUMERIC(10,4),
    paper_pnl       NUMERIC(12,4),
    exit_reason     TEXT,
    cf_entry        NUMERIC(10,4),
    cf_exit         NUMERIC(10,4),
    cf_pnl          NUMERIC(12,4),
    cf_reason       TEXT,
    cf_bars_held    INT,
    inserted_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(trade_date, strategy, symbol, decision_time)
);
CREATE INDEX IF NOT EXISTS idx_live_trades_date
    ON live_trades (trade_date DESC);
"""

INSERT_LIVE_TRADE = """
INSERT INTO live_trades (
    trade_date, strategy, symbol, shares,
    decision_time, decision_price,
    paper_fill, paper_exit, paper_pnl, exit_reason,
    cf_entry, cf_exit, cf_pnl, cf_reason, cf_bars_held
) VALUES %s
ON CONFLICT (trade_date, strategy, symbol, decision_time) DO UPDATE SET
    paper_fill = EXCLUDED.paper_fill,
    paper_exit = EXCLUDED.paper_exit,
    paper_pnl = EXCLUDED.paper_pnl,
    exit_reason = EXCLUDED.exit_reason,
    cf_entry = EXCLUDED.cf_entry,
    cf_exit = EXCLUDED.cf_exit,
    cf_pnl = EXCLUDED.cf_pnl,
    cf_reason = EXCLUDED.cf_reason,
    cf_bars_held = EXCLUDED.cf_bars_held,
    inserted_at = NOW();
"""


def persist_trades(trade_date: str, rows: list[dict]):
    if not DB_DSN:
        print('[warn] DB_DSN not set — skipping trade persistence')
        return
    for r in rows:
        if not r.get('strategy'):
            print(f"[warn] {r.get('symbol')}: strategy never resolved (missing Reason: tag "
                  f"line?) — defaulting to 'unknown' so persistence doesn't fail")
            r['strategy'] = 'unknown'
    conn = psycopg2.connect(DB_DSN)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(CREATE_LIVE_TRADES)
                if not rows:
                    return
                values = []
                for r in rows:
                    dt = None
                    if r.get('decision_time'):
                        try:
                            dt = datetime.strptime(r['decision_time'], '%Y-%m-%d %H:%M:%S')
                        except (ValueError, TypeError):
                            dt = None
                    values.append((
                        trade_date, r.get('strategy'), r.get('symbol'), r.get('shares'),
                        dt, r.get('decision_price'),
                        r.get('paper_fill'), r.get('paper_exit'),
                        r.get('paper_pnl'), r.get('exit_reason'),
                        r.get('cf_entry'), r.get('cf_exit'),
                        r.get('cf_pnl'), r.get('cf_reason'), r.get('cf_bars_held'),
                    ))
                psycopg2.extras.execute_values(cur, INSERT_LIVE_TRADE, values, page_size=100)
                print(f'[db] persisted {len(values)} trade(s) to live_trades')
    finally:
        conn.close()


# ── Log parsing ─────────────────────────────────────────────────────────────
#
# Three runners, two log shapes:
#   scalp:            >>> ENTRY [SYMBOL]: N shares @ $price   (symbol in brackets)
#   vwap / mp:         >>> ENTRY: N shares of SYMBOL @ $price  (identical for both —
#                       disambiguated by the Reason: tag on the very next line:
#                       "Reason: VWAP_RECLAIM ..." vs "Reason: MICRO_PULLBACK ...")
#
# Trades are tracked in a dict keyed by symbol (not a single "current" var) so
# scalp's concurrent multi-candidate positions, and VWAP/micro-pullback running
# on separate threads at the same time, don't clobber each other. All 3 runners'
# FILLED lines were patched (this session) to include the symbol, so a bare
# "FILLED: SYMBOL N @ $price" line can always be routed to the right open trade.

ENTRY_BRACKET_RE = re.compile(r'>>> ENTRY \[(\w+)\]: (\d+) shares @ \$([\d.]+)')      # scalp
ENTRY_OF_RE       = re.compile(r'>>> ENTRY: (\d+) shares of (\w+) @ \$([\d.]+)')      # vwap / mp
EXIT_BRACKET_RE   = re.compile(r'>>> EXIT \[(\w+)\]: (\d+) shares @ \$([\d.]+)')      # scalp
EXIT_OF_RE        = re.compile(r'>>> EXIT: (\d+) shares of (\w+) @ \$([\d.]+)')       # vwap / mp
FILLED_RE         = re.compile(r'FILLED: (\w+) (\d+) @ \$([\d.]+)')                   # any strategy (symbol-tagged)
SCALP_PNL_RE      = re.compile(r'^\s*P&L: \$([+-][\d,.]+)')                           # scalp's bare per-trade P&L line
TRADE_SUMMARY_RE  = re.compile(r'Trade #\d+: (\w+) P&L \$([+-][\d,.]+) \((.+)\)')     # vwap/mp's close event (symbol+pnl+reason together)
REASON_TAG_RE     = re.compile(r'Reason: (VWAP_RECLAIM|MICRO_PULLBACK)')
STOP_RE           = re.compile(r'Stop: \$([\d.]+)')


def fetch_logs_from_neon(run_date: str) -> list[dict]:
    """Read the full session log from Neon's durable session_logs table.

    /logs is an in-memory ring buffer (max 500 lines) that resets to empty
    on every Render restart/redeploy — by the time this script runs, hours
    after the actual trades, it usually only has a handful of lines from the
    most recent restart. session_logs is written in real time and survives
    deploys, so it's the only reliable source for a full day's log once any
    redeploy has happened since the trades occurred.
    """
    if not DB_DSN:
        return []
    conn = psycopg2.connect(DB_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT logged_at, message FROM session_logs "
                "WHERE run_date = %s ORDER BY logged_at",
                (run_date,),
            )
            return [{'t': str(t), 'msg': msg} for t, msg in cur.fetchall()]
    finally:
        conn.close()


def fetch_logs(count: int = 400) -> list[dict]:
    r = requests.get(f'{DASHBOARD}/logs', params={'n': count},
                     headers={'X-API-Key': API_KEY}, timeout=30)
    r.raise_for_status()
    return r.json()['logs']


def parse_trades(logs: list[dict]) -> list[dict]:
    """
    Walk the session log and extract trade lifecycles for all 3 live strategies
    (scalp, vwap, micro_pullback), correctly attributed even when trades from
    different strategies (or multiple scalp candidates) are open concurrently.

    Design:
      - Open trades are tracked in `open_trades`, keyed by SYMBOL (not a single
        "current" variable) — scalp can hold several concurrent candidate
        positions, and VWAP + micro-pullback run on separate threads that can
        each have a fill in flight at the same time. A dict keyed by symbol
        handles both without one trade's data clobbering another's.
      - scalp's ENTRY/EXIT lines self-identify their symbol in brackets
        (">>> ENTRY [SYM]: ..."), so there's no ambiguity for scalp at all.
      - VWAP and micro-pullback share the exact same ENTRY/EXIT wording
        (">>> ENTRY: N shares of SYM @ $price", no strategy tag) — the very
        next "Reason: VWAP_RECLAIM ..." or "Reason: MICRO_PULLBACK ..." line
        is what tells them apart. `pending_of_symbol` holds the symbol from
        the most recent "of SYM"-style entry until that Reason line arrives.
      - All 3 runners' FILLED lines were patched to include the symbol
        (this session), so every "FILLED: SYM N @ $price" line can be routed
        to the correct open trade even with several in flight at once.
      - VWAP/micro-pullback additionally print a single unambiguous close
        event when a trade finishes: "Trade #N: SYM P&L $+X.XX (reason)" —
        used directly instead of trying to track every possible exit-fill
        wording (limit fill, market fallback, stop-filled-during-cancel all
        route through this one line via _record_trade()).
      - scalp has no equivalent combined close line; its EXIT[SYM] line and
        the plain "P&L: $+X.XX" line that follows it are paired via
        `last_scalp_exit_symbol`, safe because scalp processes one bar-driven
        action at a time within a single thread (no other EXIT can interleave
        before its own P&L line is printed).
    """
    trades: list[dict] = []
    open_trades: dict[str, dict] = {}
    pending_of_symbol: str | None = None
    last_scalp_exit_symbol: str | None = None

    def _new_trade(strategy, symbol, shares, price, t):
        tr = {
            'strategy': strategy, 'symbol': symbol, 'shares': shares,
            'decision_price': price, 'decision_time': t,
            'paper_fill': None, 'paper_exit': None, 'paper_pnl': None,
            'exit_reason': None, 'stop_price': None,
        }
        open_trades[symbol] = tr
        trades.append(tr)
        return tr

    for entry in logs:
        msg = entry['msg']
        t = entry['t']

        m = ENTRY_BRACKET_RE.search(msg)
        if m:
            sym = m.group(1)
            _new_trade('scalp', sym, int(m.group(2)), float(m.group(3)), t)
            continue

        m = ENTRY_OF_RE.search(msg)
        if m:
            sym = m.group(2)
            # strategy filled in once the Reason: tag line arrives, below
            _new_trade(None, sym, int(m.group(1)), float(m.group(3)), t)
            pending_of_symbol = sym
            continue

        m = REASON_TAG_RE.search(msg)
        if m and pending_of_symbol and pending_of_symbol in open_trades:
            tag = m.group(1)
            open_trades[pending_of_symbol]['strategy'] = (
                'vwap' if tag == 'VWAP_RECLAIM' else 'micro_pullback'
            )
            continue

        if pending_of_symbol:
            m = STOP_RE.search(msg)
            if m:
                open_trades[pending_of_symbol]['stop_price'] = float(m.group(1))
                pending_of_symbol = None  # stop line always closes out the ENTRY/Reason/Stop triplet
                continue

        m = FILLED_RE.search(msg)
        if m:
            sym = m.group(1)
            tr = open_trades.get(sym)
            if tr:
                if tr['paper_fill'] is None:
                    tr['paper_fill'] = float(m.group(3))
                    tr['shares'] = int(m.group(2))
                elif tr['paper_exit'] is None:
                    tr['paper_exit'] = float(m.group(3))
            continue

        m = TRADE_SUMMARY_RE.search(msg)
        if m:
            sym, pnl_str, reason = m.group(1), m.group(2), m.group(3)
            tr = open_trades.pop(sym, None)
            if tr:
                pnl = float(pnl_str.replace(',', ''))
                tr['paper_pnl'] = pnl
                tr['exit_reason'] = reason
                if tr['paper_exit'] is None and tr['paper_fill'] is not None and tr['shares']:
                    tr['paper_exit'] = tr['paper_fill'] + pnl / tr['shares']
            continue

        m = EXIT_BRACKET_RE.search(msg)
        if m:
            last_scalp_exit_symbol = m.group(1)
            continue

        m = SCALP_PNL_RE.search(msg)
        if m and last_scalp_exit_symbol:
            tr = open_trades.pop(last_scalp_exit_symbol, None)
            if tr:
                pnl = float(m.group(1).replace(',', ''))
                tr['paper_pnl'] = pnl
                if tr['paper_exit'] is None and tr['paper_fill'] is not None and tr['shares']:
                    tr['paper_exit'] = tr['paper_fill'] + pnl / tr['shares']
            last_scalp_exit_symbol = None
            continue

        if 'Reason:' in msg and last_scalp_exit_symbol:
            # scalp's exit reason line (comes before the P&L line)
            sym = last_scalp_exit_symbol
            if sym in open_trades:
                open_trades[sym]['exit_reason'] = msg.split('Reason:')[1].strip()

    return trades


# ── Real tape ───────────────────────────────────────────────────────────────

def fetch_tape(symbol: str, day: str) -> list[dict]:
    r = requests.get(
        'https://api.tradier.com/v1/markets/timesales',
        params={'symbol': symbol, 'interval': '1min',
                'start': f'{day}T09:30', 'end': f'{day}T16:00',
                'session_filter': 'all'},
        headers={'Authorization': f'Bearer {PROD_TOKEN}', 'Accept': 'application/json'},
        timeout=30,
    )
    r.raise_for_status()
    series = r.json().get('series')
    if not series or not series.get('data'):
        return []
    return series['data']


# ── Counterfactual replay ───────────────────────────────────────────────────

def replay_counterfactual(trade: dict, tape: list[dict]) -> dict | None:
    """
    Assume entry filled instantly at the decision price on the decision bar,
    then run the strategy's own evaluate_exit over the real subsequent bars.
    """
    if trade['strategy'] == 'vwap':
        from trading.vwap_engine import evaluate_exit
        from trading.live_vwap_runner import TRIAL_184_CONFIG as cfg
        # VWAP-anchored stop: reconstruct from decision price the same way the
        # runner did (it logged stop = VWAP - offset; approximate VWAP from the
        # decision log is overkill — use decision_price-relative replay with
        # the stop the runner actually used if parsable, else VWAP unavailable)
    else:
        from trading.scalp_engine import evaluate_exit
        from trading.live_scalp_runner import TRIAL_173_CONFIG as cfg

    entry_price = trade['decision_price']
    # Find the decision bar in the tape: first bar at/after decision minute
    # is approximated by price match window; simpler: first bar whose minute
    # close equals/brackets the decision price is fragile — instead start the
    # replay at the first bar AFTER the decision wall-time minus engine delay.
    # The decision log time is wall UTC; engine bars run 15 min behind.
    dt = datetime.strptime(trade['decision_time'], '%Y-%m-%d %H:%M:%S')
    engine_minute = dt.strftime('%H:%M')  # wall UTC; tape times are ET naive
    # Convert: wall UTC - 4h (ET DST) - 15min engine delay = engine bar time
    from datetime import timedelta
    engine_bar_et = (dt - timedelta(hours=4, minutes=15)).strftime('%H:%M')

    start_idx = None
    for i, b in enumerate(tape):
        if b['time'][11:16] >= engine_bar_et:
            start_idx = i
            break
    if start_idx is None:
        return None

    highest = entry_price
    bars_held = 0
    stop_price = None
    if trade['strategy'] == 'vwap':
        # runner stop was VWAP-0.07 at entry; approximate with decision-bar
        # close relative stop parsed from logs if present, else skip
        stop_price = trade.get('stop_price')

    for b in tape[start_idx + 1:]:
        bars_held += 1
        bar = {'open': b['open'], 'high': b['high'], 'low': b['low'],
               'close': b['close'], 'volume': b.get('volume', 0)}
        highest = max(highest, b['high'])
        if trade['strategy'] == 'vwap':
            sig = evaluate_exit(entry_price, stop_price or entry_price * 0.97,
                                highest, bar, bars_held, cfg)
        else:
            sig = evaluate_exit(entry_price, highest, bar, bars_held, cfg)
        if sig:
            exit_price = float(sig['exit_price'])
            return {
                'cf_entry': entry_price,
                'cf_exit': exit_price,
                'cf_pnl': (exit_price - entry_price) * trade['shares'],
                'cf_reason': sig.get('exit_type', sig.get('reason', '?')),
                'cf_bars_held': bars_held,
            }
    # No exit by end of tape — mark to last close
    last = tape[-1]['close']
    return {
        'cf_entry': entry_price,
        'cf_exit': last,
        'cf_pnl': (last - entry_price) * trade['shares'],
        'cf_reason': 'eod_mark',
        'cf_bars_held': bars_held,
    }


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', default=date.today().isoformat())
    parser.add_argument('--skip-pull', action='store_true')
    args = parser.parse_args()

    # 1. Pull captured bars into the DB (end-of-session routine)
    if not args.skip_pull and os.getenv('DB_DSN'):
        try:
            from data.live_capture.pull_live_bars import main as pull_main
            pull_main()
        except Exception as e:
            print(f'[warn] bar pull failed: {e}')

    # 2. Parse trades from logs — prefer Neon's durable session_logs (survives
    # deploys) over the /logs ring buffer, which resets to empty on every
    # Render restart and is usually already wiped by the time this runs.
    logs = fetch_logs_from_neon(args.date)
    if not logs:
        print('[info] no Neon session_logs for this date — falling back to /logs ring buffer')
        logs = fetch_logs()
    trades = parse_trades(logs)
    # An ENTRY line gets logged for every attempt, including ones that never
    # filled (missed limit, cancelled, ran away) — those never get a
    # paper_pnl (no exit ever happens for a position that was never opened),
    # so this filter keeps only trades that actually completed.
    total_attempts = len(trades)
    trades = [t for t in trades if t['paper_pnl'] is not None]
    skipped = total_attempts - len(trades)
    if skipped:
        print(f'[info] {skipped} entry attempt(s) never filled/closed — excluded from report')
    if not trades:
        print('No completed trades found in session logs.')
        return


    # 3. Replay each against the real tape
    print(f"\n{'=' * 78}")
    print(f"  SESSION REPORT {args.date} — paper vs live-counterfactual")
    print(f"{'=' * 78}")
    print(f"{'strategy':>14} {'sym':>6} {'decision':>9} {'paper fill':>10} "
          f"{'paper exit':>10} {'paper P&L':>10} | {'cf exit':>8} {'cf P&L':>10} {'cf reason':>14}")
    print('-' * 111)

    total_paper, total_cf = 0.0, 0.0
    for t in trades:
        tape = fetch_tape(t['symbol'], args.date)
        cf = replay_counterfactual(t, tape) if tape else None
        if cf:
            t.update(cf)
        paper_pnl = t['paper_pnl'] if t['paper_pnl'] is not None else 0.0
        total_paper += paper_pnl
        cf_pnl = cf['cf_pnl'] if cf else 0.0
        total_cf += cf_pnl
        print(f"{(t['strategy'] or '?'):>14} {t['symbol']:>6} {t['decision_price']:>9.2f} "
              f"{t['paper_fill'] or 0:>10.2f} {t['paper_exit'] or 0:>10.2f} "
              f"{paper_pnl:>+10.2f} | "
              f"{(cf['cf_exit'] if cf else 0):>8.2f} {cf_pnl:>+10.2f} "
              f"{(cf['cf_reason'] if cf else 'no tape'):>14}")

    print('-' * 111)
    print(f"{'TOTAL':>32} {'':>21} {total_paper:>+10.2f} | {'':>8} {total_cf:>+10.2f}")
    print(f"\n  Sandbox distortion (paper - counterfactual): {total_paper - total_cf:+.2f}")

    # 4. Persist to DB
    persist_trades(args.date, trades)


if __name__ == '__main__':
    main()
