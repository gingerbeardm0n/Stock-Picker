"""
Live Opening Bell Scalp Runner
===============================
Paper/live trading for the Opening Bell Scalp strategy (Trial 173).

Flow:
    9:00 AM  - Start up, connect to Tradier, log account balance
    9:00-9:25 - Scan for premarket gappers via Tradier quotes
               Fetch news for top gappers via Alpaca
               Rank candidates, display watchlist
    9:25     - Lock in #1 pick, start bar polling for that symbol
    9:30     - First bar arrives, run evaluate_entry()
    9:30-9:40 - Bar-by-bar entry/exit via scalp_engine
               Place orders via AlpacaBroker (paper)
    9:40     - Time stop if still in, done for the day

Usage:
    python live_scalp_runner.py                  # paper trading (default)
    python live_scalp_runner.py --live            # REAL MONEY
    python live_scalp_runner.py --dry-run         # log only, no orders
    python live_scalp_runner.py --start-time 9:15 # start scanning earlier
"""

from __future__ import annotations

import os
import sys
import argparse
import logging
import time
import queue
import threading
from datetime import datetime, timedelta
from dataclasses import dataclass
from pathlib import Path

import pytz

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config import Config
from trading.scalp_models import ScalpConfig
from trading.scalp_engine import evaluate_entry, evaluate_exit, get_premarket_high
from trading.scalp_ranker import rank_candidates, get_top_candidate, ENRICH_TOP_N, MAX_GAP_PCT
from trading.bar_capture import record_news
from trading.broker.base import OrderResult
from trading.rel_vol_live import fetch_rel_vol_baseline, compute_rel_vol
from backend.news_fetcher import has_news_catalyst

ET = pytz.timezone('America/New_York')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-5s | %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger(__name__)


# ── Trial 173 config (trained 2021-2022, validated 2023-2025) ────────────────

# ── Multi-candidate config ───────────────────────────────────────────────────
MAX_ARMED = 10      # candidates to watch simultaneously at open
MAX_CONCURRENT = 3  # max open positions at one time (skip signal if at limit)


TRIAL_173_CONFIG = ScalpConfig(
    min_gap_pct=5.0,
    min_relative_volume=3.61,
    max_float=50_000_000,
    max_price=24.69,
    require_news=True,
    entry_mode='first_green',
    # PAPER-TESTING OVERRIDE: validated value is 4 (entry by 9:34). Set to 30 to
    # "keep hunting" — but a 2025 sim sweep proved this is INERT: with
    # entry_mode='first_green' the first green bar fires in the opening minutes,
    # so 10/20/30/60/90 all produce the identical trade set (entry effectively
    # caps by ~9:50, 0 trades after 10:00). It does NOT harvest more paper data.
    # Restore to the validated 4 before live money. To actually trade 9:40-11:00
    # needs a different entry mechanism (continuation pattern), not a bigger window.
    max_entry_bars=30,
    min_pm_high_break_pct=0.09,
    profit_target_pct=9.88,
    stop_loss_pct=4.70,
    max_hold_bars=6,
    trailing_stop_pct=0.07,
    risk_pct=2.63,
    max_position_pct=48.63,
)


# ── Live state tracking ─────────────────────────────────────────────────────

@dataclass
class LiveScalpState:
    """Mutable state for one trading day."""
    # Pre-market
    candidates: list[dict] = None
    top_pick: dict | None = None

    # Multi-position tracking
    positions: dict = None         # {symbol: position_dict} — currently open
    completed_trades: list = None  # list of closed trade dicts

    # Session summary
    in_position: bool = False      # True if any position open
    trade_done: bool = False
    pnl: float = 0.0              # total session P&L
    trade_count: int = 0

    def __post_init__(self):
        if self.candidates is None:
            self.candidates = []
        if self.positions is None:
            self.positions = {}
        if self.completed_trades is None:
            self.completed_trades = []


# ── Main runner ──────────────────────────────────────────────────────────────

class LiveScalpRunner:
    """
    Runs the Opening Bell Scalp strategy.
    Data: Tradier production (real-time). Orders: Alpaca paper (real-time fills).
    Live mode: uses BROKER= from .env.live.
    """

    def __init__(
        self,
        config: ScalpConfig = None,
        dry_run: bool = False,
        live: bool = False,
    ):
        self.config = config or TRIAL_173_CONFIG
        self.dry_run = dry_run
        self.live = live
        self.state = LiveScalpState()

        # Load env
        env_file = '.env.live' if live else '.env.paper'
        env_path = os.path.join(os.path.dirname(__file__), '..', env_file)
        if os.path.exists(env_path):
            self._load_env(env_path)

        # Connect broker + data feed
        # Hybrid architecture: Tradier production for real-time data feed,
        # Alpaca paper for order execution (real-time fills, no 15-min delay).
        # Live mode: uses whatever BROKER= is set to in .env.live.
        if not live:
            from trading.broker.alpaca import AlpacaBroker
            if not dry_run:
                self.broker = AlpacaBroker(
                    api_key=Config.ALPACA_PAPER_KEY,
                    secret_key=Config.ALPACA_PAPER_SECRET,
                )
            else:
                self.broker = None
            # Data feed stays on Tradier production (real-time, free)
            self.data_feed = Config.get_data_feed()
            logger.info("Broker: Alpaca paper (real-time fills)")
            logger.info("Data feed: Tradier production (real-time)")
        else:
            self.broker = None if dry_run else Config.get_broker()
            self.data_feed = Config.get_data_feed()

        # News fetcher (Alpaca -- free tier)
        from backend.news_fetcher import NewsFetcher, classify_news_tier
        self.news_fetcher = NewsFetcher()
        self.classify_news_tier = classify_news_tier

        # Live rel-vol parity (Gap #1): fetch the 30-day-avg denominator baseline
        # from the data branch. None → rel_vol=10.0 fallback (filter no-op).
        baseline = fetch_rel_vol_baseline()
        self._rel_vol_baselines = baseline.get('baselines') if baseline else None
        # Float baseline (Gap #2): floats are not yet populated in the baseline
        # (build_baseline_cloud.py ships floats={} always). self._floats will be
        # an empty dict → falsy → float filter is INACTIVE this session. This is
        # a known parity gap: live allows any float, sim enforces max_float.
        self._floats = baseline.get('floats') if baseline else None
        if not self._floats:
            logger.warning("Float baseline empty — max_float filter INACTIVE this session (parity gap)")

        # Symbol list for scanning
        self._symbols = self._load_symbols()

        # Bar queue for live bar polling
        self._bar_queue = queue.Queue(maxsize=1000)

        logger.info("=" * 60)
        logger.info("OPENING BELL SCALP RUNNER")
        logger.info("=" * 60)
        mode = "DRY RUN" if dry_run else ("LIVE" if live else "PAPER")
        logger.info(f"Mode: {mode}")
        logger.info(f"Config: gap>={self.config.min_gap_pct:.1f}% "
                     f"entry={self.config.entry_mode} "
                     f"stop={self.config.stop_loss_pct:.1f}% "
                     f"target={self.config.profit_target_pct:.1f}%")

        if not dry_run:
            balance = self.broker.get_account_balance()
            logger.info(f"Account balance: ${balance:,.2f}")

    # ── Phase 1: Premarket scan (9:00 - 9:25) ───────────────────────────────

    def scan_premarket(self):
        """
        Scan all symbols for gap-ups, fetch news, rank candidates.
        Call this at ~9:00-9:15 AM to build the watchlist.
        """
        logger.info("-" * 40)
        logger.info("PHASE 1: Premarket Gapper Scan")
        logger.info("-" * 40)

        # Step 1: Prior closes (Alpaca quote snapshots don't include prev_close)
        prior_closes: dict[str, float] = {}
        try:
            prior_closes = self.data_feed.get_prior_closes(self._symbols)
            logger.info(f"Fetched prior closes for {len(prior_closes):,} symbols")
        except Exception as e:
            logger.warning(f"Prior close fetch failed: {e} — gap scan may find 0 gappers")

        # Step 2: Get quotes for all symbols (batched)
        logger.info(f"Fetching quotes for {len(self._symbols):,} symbols...")
        quotes = self.data_feed.get_quotes(self._symbols)
        logger.info(f"Got {len(quotes):,} quotes")

        # Patch prev_close from prior-close fetch (Alpaca returns 0.0 in quote snapshot)
        for sym, q in quotes.items():
            if q.prev_close <= 0 and sym in prior_closes:
                q.prev_close = prior_closes[sym]

        # Spot-check: dump raw fields for a few symbols to diagnose stale-quote issues
        spot_check = ['SUGP', 'CRVO', 'PURR', 'HITI', 'ALBT']
        for sym in spot_check:
            if sym in quotes:
                q = quotes[sym]
                logger.info(f"  SPOT {sym}: last={q.last:.4f} prev={q.prev_close:.4f} "
                            f"bid={q.bid:.4f} ask={q.ask:.4f} vol={q.volume:,.0f} "
                            f"gap={(q.last-q.prev_close)/q.prev_close*100:.1f}%" if q.prev_close > 0
                            else f"  SPOT {sym}: last={q.last} prev={q.prev_close} (no prev)")
            else:
                logger.info(f"  SPOT {sym}: NOT IN UNIVERSE")

        # Step 2: Compute gaps
        # Tradier's `last` field = previous session close during premarket (stale).
        # Use bid/ask midpoint as the live price signal when last==prevclose.
        gappers = []
        zero_prev = 0
        zero_last = 0
        last_eq_prev = 0
        used_bidask = 0
        over_max_price = 0
        over_max_gap = 0
        all_gaps = []
        positive_gaps = 0
        for sym, q in quotes.items():
            if q.prev_close <= 0:
                zero_prev += 1
                continue

            # Choose best available price: live bid/ask midpoint if last is stale
            price = q.last
            if q.last <= 0:
                zero_last += 1
                continue
            if q.last == q.prev_close and q.bid > 0 and q.ask > 0:
                spread_ratio = q.ask / q.bid if q.bid > 0 else 999
                if spread_ratio > 3.0:
                    continue
                midpoint = (q.bid + q.ask) / 2
                if abs(midpoint - q.prev_close) / q.prev_close > 0.005:
                    price = midpoint
                    used_bidask += 1
            elif q.last == q.prev_close:
                last_eq_prev += 1

            gap_pct = (price - q.prev_close) / q.prev_close * 100

            if gap_pct > 0:
                positive_gaps += 1
            if gap_pct >= 1.0:
                all_gaps.append((gap_pct, sym, price, q.prev_close, q.bid, q.ask, q.volume))

            if gap_pct < self.config.min_gap_pct:
                continue
            if gap_pct > MAX_GAP_PCT:
                over_max_gap += 1
                continue
            if price > self.config.max_price:
                over_max_price += 1
                continue

            gappers.append({
                'symbol': sym,
                'gap_pct': gap_pct,
                'open_price': price,
                'prior_close': q.prev_close,
                'bid': q.bid,
                'ask': q.ask,
                'quote_volume': q.volume,
            })

        gappers.sort(key=lambda g: g['gap_pct'], reverse=True)
        logger.info(f"Found {len(gappers)} gappers >= {self.config.min_gap_pct:.1f}%")

        # Diagnostic: quote staleness check
        total_valid = len(quotes) - zero_prev - zero_last
        stale_count = last_eq_prev + used_bidask
        logger.info(f"  Quote health: {len(quotes)} returned, {total_valid} valid, "
                     f"stale_last={stale_count} (used_bidask_midpoint={used_bidask}, "
                     f"no_bidask={last_eq_prev}), "
                     f"positive_gap={positive_gaps}, gaps>=1%={len(all_gaps)}")
        if zero_prev or zero_last or over_max_price or over_max_gap:
            logger.info(f"  Filter stats: zero_prev_close={zero_prev}, zero_last={zero_last}, "
                        f"over_max_price={over_max_price}, over_max_gap_1000={over_max_gap}")

        # Show top gaps (lowered threshold to 1% for diagnostic visibility)
        all_gaps.sort(reverse=True)
        if all_gaps:
            logger.info(f"  Top 15 gaps in market (>=1%%):")
            for gap, sym, last, prev, bid, ask, vol in all_gaps[:15]:
                logger.info(f"    {sym}: gap={gap:.1f}% last={last:.4f} prev={prev:.4f} "
                            f"bid={bid:.4f} ask={ask:.4f} vol={vol:,.0f}")
        else:
            logger.warning("  NO stocks with gap >= 1% — quotes likely stale (last==prevclose)")

        if not gappers:
            logger.warning("No gappers found this scan.")
            return

        # Step 3: Enrich top 20 with news + fundamentals
        top_gappers = gappers[:ENRICH_TOP_N]
        logger.info(f"Enriching top {len(top_gappers)} gappers with news...")
        self._enrich_with_news(top_gappers)

        # Step 4: Apply filters
        filtered = []
        for g in top_gappers:
            if self.config.require_news and not g.get('has_news', False):
                logger.info(f"  SKIP {g['symbol']} gap={g['gap_pct']:.1f}% -- no news")
                continue
            filtered.append(g)

        if not filtered:
            logger.warning("No gappers passed news filter this scan.")
            return

        # Step 5: Rank and pick #1
        # Compute real rel-vol now using current quote volume vs 30-day baseline.
        # Volume is low premarket but ratio is still meaningful — a stock at 5x
        # its normal 9:25 cumulative volume at 8 AM is a genuine mover.
        # Filter (min_relative_volume) is NOT applied here; that happens at 9:25
        # refresh so thin candidates are dropped only when volume data is mature.
        for g in filtered:
            g['rel_vol'] = compute_rel_vol(
                g['symbol'], g.get('quote_volume'), self._rel_vol_baselines)
            g['float_shares'] = None  # TODO: fetch from fundamentals

        ranked = rank_candidates(filtered)
        self.state.candidates = ranked

        logger.info(f"\n{'='*60}")
        logger.info("WATCHLIST (ranked)")
        logger.info(f"{'='*60}")
        for i, c in enumerate(ranked[:10]):
            news_str = c.get('news_tier', 'none')
            logger.info(
                f"  #{i+1} {c['symbol']:6s} "
                f"gap={c['gap_pct']:.1f}% "
                f"news={news_str} "
                f"score={c.get('scalp_score', 0):.3f}"
            )

        top = get_top_candidate(filtered)
        self.state.top_pick = top
        logger.info(f"\n>>> TOP PICK: {top['symbol']} "
                     f"gap={top['gap_pct']:.1f}% "
                     f"news={top.get('news_tier', '?')}")

    def refresh_top_pick(self):
        """
        Re-scan at 9:25 with updated prices/volume. Locks in final pick.
        """
        logger.info("-" * 40)
        logger.info("PHASE 1b: Refresh pick (9:25)")
        logger.info("-" * 40)

        if not self.state.candidates:
            logger.warning("No candidates to refresh.")
            return

        # Re-fetch quotes for candidates only
        symbols = [c['symbol'] for c in self.state.candidates]
        quotes = self.data_feed.get_quotes(symbols)

        for c in self.state.candidates:
            q = quotes.get(c['symbol'])
            if q:
                c['open_price'] = q.last
                c['quote_volume'] = q.volume
                # Recalculate gap with latest price
                if q.prev_close > 0:
                    c['gap_pct'] = (q.last - q.prev_close) / q.prev_close * 100

        # Live rel-vol (Gap #1): now that 9:25 quote volume is fresh, compute the
        # real rel-vol (quote_volume / 30-day baseline, 10.0 fallback) and apply
        # the SAME min_relative_volume filter the sim applies. Thin-volume
        # candidates the optimizer's config would reject are dropped here.
        survivors = []
        for c in self.state.candidates:
            c['rel_vol'] = compute_rel_vol(
                c['symbol'], c.get('quote_volume'), self._rel_vol_baselines)
            if c['rel_vol'] < self.config.min_relative_volume:
                logger.info(f"  SKIP {c['symbol']} gap={c['gap_pct']:.1f}% "
                            f"rel_vol={c['rel_vol']:.2f} < {self.config.min_relative_volume:.2f}")
                continue
            # Float filter (Gap #2): match the sim's max_float gate using the
            # shipped float baseline. None (symbol absent / no baseline) → keep,
            # exactly like the sim (`if float_shares and float_shares > max`).
            float_shares = self._floats.get(c['symbol']) if self._floats else None
            c['float_shares'] = float_shares
            if float_shares and float_shares > self.config.max_float:
                logger.info(f"  SKIP {c['symbol']} gap={c['gap_pct']:.1f}% "
                            f"float={float_shares:,.0f} > {self.config.max_float:,.0f}")
                continue
            survivors.append(c)
        self.state.candidates = survivors

        if not survivors:
            logger.warning("No candidates passed rel-vol filter. No trade today.")
            self.state.top_pick = None
            self.state.trade_done = True
            return

        # Re-rank
        ranked = rank_candidates(self.state.candidates)
        self.state.candidates = ranked
        top = get_top_candidate(ranked)

        if top:
            self.state.top_pick = top
            logger.info(f">>> LOCKED IN: {top['symbol']} "
                         f"gap={top['gap_pct']:.1f}% "
                         f"price=${top['open_price']:.2f}")
        else:
            logger.warning("No candidates after refresh. No trade today.")
            self.state.trade_done = True

    # ── Phase 2: Execute trade (9:30 - 9:40) ────────────────────────────────

    def execute_trade(self):
        """
        Monitor minute bars for up to MAX_ARMED candidates simultaneously.
        Enters up to MAX_CONCURRENT positions at once; skips signal if at limit.
        Blocks until all candidates have traded or missed entry window.
        """
        if self.state.trade_done:
            logger.info("No trade to execute today.")
            return

        armed = self.state.candidates[:MAX_ARMED]
        if not armed:
            logger.info("No candidates to trade.")
            self.state.trade_done = True
            return

        symbols = [c['symbol'] for c in armed]
        logger.info("-" * 40)
        logger.info(f"PHASE 2: Execute trade -- {len(symbols)} candidates armed")
        logger.info(f"  Watching: {', '.join(symbols)}")
        logger.info(f"  Max concurrent: {MAX_CONCURRENT}")
        logger.info("-" * 40)

        # Fetch premarket bars for all armed symbols upfront
        logger.info(f"Fetching premarket bars for {len(symbols)} symbols...")
        pm_bars_all = self.data_feed.get_bars_since_4am(symbols)
        pm_highs = {}
        for sym in symbols:
            bars = pm_bars_all.get(sym, [])
            pm_bar_dicts = []
            for b in bars:
                bar_et = b.time.astimezone(ET)
                if bar_et.hour < 9 or (bar_et.hour == 9 and bar_et.minute < 30):
                    pm_bar_dicts.append({
                        'open': b.open, 'high': b.high,
                        'low': b.low, 'close': b.close,
                        'volume': b.volume,
                    })
            pm_highs[sym] = get_premarket_high(pm_bar_dicts) if pm_bar_dicts else None
            h = pm_highs[sym]
            logger.info(f"  {sym}: PM high = ${h:.2f}" if h else f"  {sym}: PM high = N/A")

        # Per-symbol tracking
        sym_meta = {
            c['symbol']: {
                'candidate': c,
                'pm_high': pm_highs.get(c['symbol']),
                'bars_since_open': 0,
                'done': False,
            }
            for c in armed
        }

        open_positions = {}   # {sym: position_dict}
        completed_trades = []

        # Start bar poller for all symbols
        from trading.broker.tradier import TradierBarPoller
        poller = TradierBarPoller(
            token=Config.TRADIER_PRODUCTION_TOKEN or Config.TRADIER_PAPER_TOKEN,
            sandbox=False,
            delay_minutes=0,
            bar_queue=self._bar_queue,
        )
        poller.set_watchlist(symbols)
        poller_thread = threading.Thread(target=poller.start, daemon=True)
        poller_thread.start()

        self._wait_for_market_open()
        logger.info(f"Listening for bars on {len(symbols)} symbols...")

        while True:
            if all(m['done'] for m in sym_meta.values()) and not open_positions:
                break

            try:
                bar = self._bar_queue.get(timeout=180)
            except queue.Empty:
                logger.warning("No bar received in 180s -- timeout")
                if open_positions:
                    logger.warning(f"Timeout with {len(open_positions)} open position(s) — emergency exit all")
                    for sym, pos in list(open_positions.items()):
                        trade = self._place_exit_multi(
                            sym, {'close': pos['entry_price']},
                            {'reason': 'BAR_TIMEOUT_SAFETY_EXIT'}, pos)
                        completed_trades.append(trade)
                        self.state.pnl += trade['pnl']
                        self.state.trade_count += 1
                    open_positions.clear()
                break

            sym = bar.get('symbol')
            if sym not in sym_meta or sym_meta[sym]['done']:
                continue

            # Skip premarket bars
            bar_time = bar.get('time', datetime.now(ET))
            if isinstance(bar_time, str):
                bar_time = datetime.fromisoformat(bar_time)
            bar_et = bar_time.astimezone(ET) if hasattr(bar_time, 'astimezone') else None
            if bar_et is not None and (bar_et.hour < 9 or (bar_et.hour == 9 and bar_et.minute < 30)):
                logger.info(f"  [{sym}] Premarket {bar_et.strftime('%H:%M')} C={bar['close']:.2f} — skipping")
                continue

            meta = sym_meta[sym]
            meta['bars_since_open'] += 1
            n = meta['bars_since_open']

            logger.info(
                f"  [{sym}] Bar {n}: "
                f"O={bar['open']:.2f} H={bar['high']:.2f} "
                f"L={bar['low']:.2f} C={bar['close']:.2f} "
                f"V={bar.get('volume', 0):,}"
            )

            if sym in open_positions:
                pos = open_positions[sym]
                pos['bars_held'] += 1
                if bar['high'] > pos['highest_since_entry']:
                    pos['highest_since_entry'] = bar['high']

                exit_signal = evaluate_exit(
                    entry_price=pos['entry_price'],
                    highest_since_entry=pos['highest_since_entry'],
                    current_bar=bar,
                    bars_held=pos['bars_held'],
                    config=self.config,
                )
                if exit_signal:
                    trade = self._place_exit_multi(sym, bar, exit_signal, pos)
                    completed_trades.append(trade)
                    del open_positions[sym]
                    meta['done'] = True
                    self.state.pnl += trade['pnl']
                    self.state.trade_count += 1
                    self.state.in_position = bool(open_positions)
            else:
                if len(open_positions) < MAX_CONCURRENT:
                    entry = evaluate_entry(
                        candidate=meta['candidate'],
                        current_bar=bar,
                        premarket_high=meta['pm_high'],
                        bars_since_open=n,
                        config=self.config,
                    )
                    if entry:
                        pos = self._place_entry_multi(sym, bar, entry)
                        if pos:
                            open_positions[sym] = pos
                            self.state.in_position = True
                elif n == 1:
                    logger.info(f"  [{sym}] Concurrent limit ({MAX_CONCURRENT}) reached — watching only")

                if n >= self.config.max_entry_bars and sym not in open_positions:
                    logger.info(f"  [{sym}] Max entry bars ({self.config.max_entry_bars}) reached, no entry")
                    meta['done'] = True

        # Cleanup
        poller.stop()

        self.state.completed_trades = completed_trades
        self.state.positions = {}
        self.state.in_position = False
        self.state.trade_done = True

        self._print_summary()

    # ── Order placement ──────────────────────────────────────────────────────

    def _place_entry_multi(self, symbol: str, bar: dict, entry: dict) -> dict | None:
        """Place entry order. Returns position dict on success, None on failure."""
        entry_price = bar['close']
        account_balance = 5000.0

        if not self.dry_run:
            if Config.PAPER_STARTING_BALANCE > 0:
                account_balance = Config.PAPER_STARTING_BALANCE
            else:
                try:
                    account_balance = self.broker.get_account_balance()
                except Exception:
                    pass

        # Divide max_position_pct by MAX_CONCURRENT so 3 simultaneous positions
        # don't exceed available capital (e.g. 48% / 3 = 16% per slot).
        risk_amount = account_balance * (self.config.risk_pct / 100)
        stop_distance = entry_price * (self.config.stop_loss_pct / 100)
        shares_by_risk = int(risk_amount / stop_distance) if stop_distance > 0 else 0
        max_position_value = account_balance * (self.config.max_position_pct / 100) / MAX_CONCURRENT
        shares_by_position = int(max_position_value / entry_price) if entry_price > 0 else 0
        shares = min(shares_by_risk, shares_by_position)

        if shares <= 0:
            logger.warning(f"  [{symbol}] Position size = 0 shares. Skipping entry.")
            return None

        logger.info(f">>> ENTRY [{symbol}]: {shares} shares @ ${entry_price:.2f}")
        logger.info(f"    Reason: {entry.get('reason', '?')}")
        logger.info(f"    Risk: ${risk_amount:.2f} | Position: ${shares * entry_price:.2f}")

        entry_order_id = ''
        stop_order_id = ''
        entry_price = round(entry_price, 2)
        if not self.dry_run:
            result = self.broker.place_limit_buy(symbol, shares, entry_price)
            entry_order_id = result.order_id
            logger.info(f"    Order ID: {result.order_id} Status: {result.status}")

            time.sleep(2)
            fill = self.broker.get_order(result.order_id)
            if fill.status == 'filled':
                entry_price = fill.filled_price
                shares = fill.filled_qty
                logger.info(f"    FILLED: {shares} @ ${entry_price:.2f}")
            else:
                logger.info(f"    Order status: {fill.status} -- waiting...")
                for _ in range(5):
                    time.sleep(2)
                    fill = self.broker.get_order(result.order_id)
                    if fill.status == 'filled':
                        entry_price = fill.filled_price
                        shares = fill.filled_qty
                        logger.info(f"    FILLED: {shares} @ ${entry_price:.2f}")
                        break
                else:
                    logger.warning(f"    [{symbol}] Entry not filled after 10s. Cancelling.")
                    cancelled = self.broker.cancel_order(result.order_id)
                    # Cancel can race a fill — verify final state before abandoning.
                    time.sleep(2)
                    fill = self.broker.get_order(result.order_id)
                    if fill.status in ('filled', 'partially_filled') and fill.filled_qty > 0:
                        entry_price = fill.filled_price or entry_price
                        shares = fill.filled_qty
                        logger.warning(
                            f"    Cancel raced fill ({fill.status}, cancel ok={cancelled}): "
                            f"{shares} @ ${entry_price:.2f} — adopting position."
                        )
                    else:
                        return None

            stop_price = round(entry_price * (1 - self.config.stop_loss_pct / 100), 2)
            stop_result = self.broker.place_stop_sell(symbol, shares, stop_price)
            stop_order_id = stop_result.order_id
            logger.info(f"    Stop order: {stop_result.order_id} @ ${stop_price:.2f}")

        return {
            'symbol': symbol,
            'entry_price': entry_price,
            'shares': shares,
            'entry_order_id': entry_order_id,
            'stop_order_id': stop_order_id,
            'stop_price': round(entry_price * (1 - self.config.stop_loss_pct / 100), 2),
            'highest_since_entry': bar['high'],
            'bars_held': 0,
            'entry_time': datetime.now(ET).isoformat(),
        }

    def _place_exit_multi(self, symbol: str, bar: dict, exit_signal: dict, pos: dict) -> dict:
        """Place exit order. Returns completed trade dict."""
        exit_price = exit_signal.get('exit_price', bar['close'])

        logger.info(f">>> EXIT [{symbol}]: {pos['shares']} shares @ ${exit_price:.2f}")
        logger.info(f"    Reason: {exit_signal.get('reason', '?')}")

        if not self.dry_run:
            # Cancel stop — if cancel fails, stop may have already filled server-side.
            # Verify before placing market sell to avoid double-selling (opening a short).
            if pos.get('stop_order_id'):
                cancelled = self.broker.cancel_order(pos['stop_order_id'])
                if not cancelled:
                    time.sleep(1)
                    stop_status = self.broker.get_order(pos['stop_order_id'])
                    if stop_status.status == 'filled':
                        logger.warning(
                            f"    Stop {pos['stop_order_id']} already filled "
                            f"@ ${stop_status.filled_price:.2f} — adopting stop fill"
                        )
                        exit_price = stop_status.filled_price
                        pnl = (exit_price - pos['entry_price']) * pos['shares']
                        logger.info(f"    P&L: ${pnl:+.2f}")
                        return {
                            'symbol': symbol,
                            'entry_price': pos['entry_price'],
                            'exit_price': exit_price,
                            'shares': pos['shares'],
                            'pnl': pnl,
                            'exit_reason': 'STOP_FILLED_SERVER',
                            'bars_held': pos['bars_held'],
                        }

            result = self.broker.place_market_sell(symbol, pos['shares'])
            logger.info(f"    Sell order: {result.order_id} Status: {result.status}")

            time.sleep(2)
            fill = self.broker.get_order(result.order_id)
            if fill.status == 'filled':
                exit_price = fill.filled_price
                logger.info(f"    FILLED: {fill.filled_qty} @ ${exit_price:.2f}")

        pnl = (exit_price - pos['entry_price']) * pos['shares']
        logger.info(f"    P&L: ${pnl:+.2f}")
        return {
            'symbol': symbol,
            'entry_price': pos['entry_price'],
            'exit_price': exit_price,
            'shares': pos['shares'],
            'pnl': pnl,
            'exit_reason': exit_signal.get('reason', '?'),
            'bars_held': pos['bars_held'],
        }

    # ── News enrichment ──────────────────────────────────────────────────────

    def _enrich_with_news(self, candidates: list[dict]):
        """Fetch news for each candidate via Alpaca API."""
        today = datetime.now(ET).date()
        for c in candidates:
            try:
                articles = self.news_fetcher.get_news_for_symbol(
                    c['symbol'],
                    as_of_date=today,
                    hours_back=48,
                )
                if articles:
                    tier = self.classify_news_tier(articles)
                    c['has_news'] = has_news_catalyst(tier)  # shared sim/live gate
                    c['news_tier'] = tier
                    record_news(c['symbol'], articles, tier)
                else:
                    c['has_news'] = False
                    c['news_tier'] = 'none'
            except Exception as e:
                logger.warning(f"News fetch failed for {c['symbol']}: {e}")
                c['has_news'] = False
                c['news_tier'] = 'none'

            # Rate limit
            time.sleep(0.35)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _wait_for_market_open(self):
        """Sleep until 9:30 AM ET when market open bars are available."""
        now = datetime.now(ET)
        target = now.replace(hour=9, minute=30, second=0, microsecond=0)

        if now >= target:
            logger.info("Market open — bars available.")
            return

        wait = (target - now).total_seconds()
        logger.info(f"Waiting {wait:.0f}s for 9:30 AM ET...")
        time.sleep(wait)
        logger.info("Market open — bars available!")

    def _load_symbols(self) -> list[str]:
        """Fetch fresh US stock universe from NASDAQ, then filter by live price."""
        symbols = self._fetch_nasdaq_symbols()
        if not symbols:
            # Fallback to static file
            paths = [
                os.path.join(os.path.dirname(__file__), '..', 'services', 'stocks_in_price_range.txt'),
                os.path.join(os.path.dirname(__file__), '..', '..', 'database', 'stocks_1_to_20.txt'),
            ]
            for p in paths:
                if os.path.exists(p):
                    with open(p) as f:
                        symbols = [line.strip() for line in f if line.strip()]
                    logger.warning(f"Using static fallback: {len(symbols):,} symbols from {os.path.basename(p)}")
                    break

        if not symbols:
            logger.warning("No symbols available.")
            return []

        # Live-filter: keep only symbols with price $0.50-$30
        if self.data_feed:
            logger.info(f"Fetching live quotes for {len(symbols):,} symbols to filter by price...")
            quotes = self.data_feed.get_quotes(symbols)
            no_quote = len(symbols) - len(quotes)
            zero_last = sum(1 for q in quotes.values() if q.last <= 0)
            alive = [s for s, q in quotes.items() if 0.50 <= q.last <= 30.0]
            logger.info(f"Live universe: {len(alive):,} stocks in $0.50-$30 range "
                        f"(no_quote={no_quote}, zero_last={zero_last}, "
                        f"total_fetched={len(quotes)})")
            return alive

        return symbols

    @staticmethod
    def _fetch_nasdaq_symbols() -> list[str]:
        """Fetch full US stock list from NASDAQ trader (updated daily, free)."""
        import requests as req
        url = 'https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt'
        try:
            r = req.get(url, timeout=15)
            r.raise_for_status()
            lines = r.text.strip().split('\n')
            symbols = []
            for line in lines[1:-1]:  # skip header + footer
                parts = line.split('|')
                if len(parts) < 8:
                    continue
                sym = parts[1]
                is_etf = parts[5] == 'Y'
                is_test = parts[7] == 'Y'
                # Keep non-ETF, non-test, normal ticker symbols
                if (not is_etf and not is_test and sym and ' ' not in sym
                        and '$' not in sym and '.' not in sym and len(sym) <= 5):
                    symbols.append(sym)
            logger.info(f"Fetched {len(symbols):,} symbols from NASDAQ trader")
            return symbols
        except Exception as e:
            logger.warning(f"Failed to fetch NASDAQ symbol list: {e}")
            return []

    def _load_env(self, path: str):
        """Load .env file into os.environ."""
        try:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, val = line.split('=', 1)
                        os.environ.setdefault(key.strip(), val.strip())
            logger.info(f"Loaded env from {os.path.basename(path)}")
        except Exception as e:
            logger.warning(f"Could not load {path}: {e}")

    def _print_summary(self):
        """Print end-of-day summary."""
        s = self.state
        logger.info("\n" + "=" * 60)
        logger.info("DAILY SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Candidates watched: {len(s.candidates)}")

        if not s.completed_trades:
            logger.info("Result: NO TRADE")
        else:
            logger.info(f"Trades: {len(s.completed_trades)}")
            for t in s.completed_trades:
                logger.info(
                    f"  {t['symbol']:6s}  entry=${t['entry_price']:.2f}  "
                    f"exit=${t['exit_price']:.2f}  "
                    f"shares={t['shares']}  P&L=${t['pnl']:+.2f}  "
                    f"bars={t['bars_held']}  ({t['exit_reason']})"
                )
            logger.info(f"Total P&L: ${s.pnl:+.2f}")

        logger.info("=" * 60)


# ── Main entry point ─────────────────────────────────────────────────────────

def run_scalp_session(dry_run=False, live=False, start_time='9:00'):
    """
    Run a complete scalp trading session.

    Can be called programmatically or from CLI.
    """
    runner = LiveScalpRunner(dry_run=dry_run, live=live)

    # Parse start time
    hour, minute = map(int, start_time.split(':'))
    now = datetime.now(ET)
    start = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    if now < start:
        wait = (start - now).total_seconds()
        logger.info(f"Waiting {wait:.0f}s until {start_time} ET to start scanning...")
        time.sleep(wait)

    # Phase 1: Premarket scan — rescan until 9:25 so late gappers still make
    # the watchlist. Every 60s while empty, every 5 min once we have candidates
    # (full scan = quotes for ~8k symbols + news, too heavy to run each minute).
    scan_cutoff = now.replace(hour=9, minute=25, second=0, microsecond=0)

    _state_file = Path(os.getenv("JTRADER_STATE_DIR", "/tmp/jtrader")) / "state.json"

    while True:
        runner.state.trade_done = False  # reset for rescan
        runner.scan_premarket()

        # Write live state so dashboard shows candidates during premarket scan
        _candidates = []
        for c in (runner.state.candidates or []):
            _candidates.append({k: c.get(k) for k in (
                'symbol', 'gap_pct', 'open_price', 'prior_close', 'rel_vol',
                'float_shares', 'has_news', 'news_tier', 'scalp_score', 'quote_volume',
            )})
        _top = runner.state.top_pick
        _top_sym = (_top.get('symbol') if isinstance(_top, dict) else _top) if _top else None
        import json as _json
        _state_file.write_text(_json.dumps({
            "last_run": datetime.utcnow().isoformat(),
            "strategy": "opening_bell_scalp",
            "last_result": "scanning",
            "date": str(datetime.now(ET).date()),
            "candidates": _candidates,
            "top_pick": _top_sym,
        }, default=str))

        now = datetime.now(ET)
        if now >= scan_cutoff:
            if not runner.state.candidates:
                logger.info("9:25 ET reached, no gappers found. No trade today.")
                runner.state.trade_done = True
            break

        scan_interval = 300 if runner.state.candidates else 60
        next_scan = min(scan_interval, (scan_cutoff - now).total_seconds())
        logger.info(f"Rescanning in {next_scan:.0f}s...")
        time.sleep(next_scan)

    if not runner.state.trade_done:
        # Refresh at 9:25
        now = datetime.now(ET)
        refresh_time = now.replace(hour=9, minute=25, second=0, microsecond=0)
        if now < refresh_time:
            wait = (refresh_time - now).total_seconds()
            logger.info(f"Waiting {wait:.0f}s until 9:25 for final refresh...")
            time.sleep(wait)

        runner.refresh_top_pick()

    if not runner.state.trade_done:
        # Phase 2: Execute trade
        runner.execute_trade()

    return runner.state


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Opening Bell Scalp - Live Trading')
    parser.add_argument('--live', action='store_true',
                        help='Use LIVE credentials (real money)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Log signals only, no orders placed')
    parser.add_argument('--start-time', default='9:00',
                        help='When to start scanning (HH:MM ET, default 9:00)')

    args = parser.parse_args()

    if args.live and not args.dry_run:
        print("\n" + "!" * 60)
        print("WARNING: LIVE TRADING MODE - REAL MONEY")
        print("!" * 60)
        confirm = input("Type 'YES' to confirm: ")
        if confirm != 'YES':
            print("Aborted.")
            sys.exit(0)

    state = run_scalp_session(
        dry_run=args.dry_run,
        live=args.live,
        start_time=args.start_time,
    )
