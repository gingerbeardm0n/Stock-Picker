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
from trading.rel_vol_live import fetch_rel_vol_baseline, fetch_missing_floats, DEFAULT_REL_VOL
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
    # 2025 sim sweep: 4/10/20/30 all produce identical trade sets with first_green
    # mode — first green bar fires in bars 1-4 every time. 10 gives a small buffer
    # for slow starters without changing behavior. Permanent setting.
    max_entry_bars=10,
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
        # Float baseline (Gap #2): weekly bulk refresh (build_baseline_cloud.py,
        # GitHub Actions daily 4:30pm ET) covers symbols already seen before. Always
        # a dict (never None) so fetch_missing_floats() can enrich it per-scan for
        # brand-new gappers not yet in the baseline — see rel_vol_live.py.
        self._floats = (baseline.get('floats') if baseline else None) or {}
        if not self._floats:
            logger.warning("Float baseline empty — live per-scan fetch will populate as needed")

        # Live rel-vol: hybrid feed — today's cumulative volume from Tradier
        # (real-time premarket data, Alpaca can't serve same-day bars), 30-day
        # average at the same minute-of-day from Alpaca historical minute bars
        # (matches the simulator's rel_vol_cum_cache denominator exactly — see
        # rel-vol-lookback-research memory). Replaces the 5-day Tradier-only
        # denominator, which was a vendor-constraint stopgap, not a match for
        # the 30-day window the sim was tuned against.
        from trading.rel_vol_live import HybridRelVol
        self._relvol = None
        try:
            self._relvol = HybridRelVol(
                Config._make_tradier_data_feed(),
                Config._make_alpaca_data_feed(),
                lookback_days=30)
            logger.info("Rel-vol: hybrid (Tradier numerator, Alpaca 30-day denominator)")
        except Exception as e:
            logger.warning(
                f"HybridRelVol unavailable: {e} — rel_vol falls back to 10.0")

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
            try:
                balance = self.broker.get_account_balance()
                logger.info(f"Account balance: ${balance:,.2f}")
            except Exception as e:
                logger.warning(f"Could not fetch account balance: {e}")

    # ── Phase 1: Premarket scan (9:00 - 9:25) ───────────────────────────────

    def _assign_rel_vol(self, candidates: list[dict]) -> None:
        """Set c['rel_vol'] for each candidate via Tradier single-feed rel-vol.

        Tradier (numerator = today cumulative premarket vol, denominator = 5-day avg at
        same minute). None → DEFAULT_REL_VOL=10.0 fallback. Mutates in place.
        """
        now = datetime.now(ET)
        for c in candidates:
            rv = None
            if self._relvol is not None:
                try:
                    self._relvol.invalidate(c['symbol'])  # numerator grows intraday
                    rv = self._relvol.compute(c['symbol'], now)
                except Exception as e:
                    logger.debug(f"  rel-vol compute failed for {c['symbol']}: {e}")
            c['rel_vol'] = rv if rv is not None else DEFAULT_REL_VOL

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
        try:
            quotes = self.data_feed.get_quotes(self._symbols)
        except Exception as e:
            logger.error(f"Quote fetch failed: {e} — no candidates this scan")
            return
        logger.info(f"Got {len(quotes):,} quotes")

        # Always overwrite prev_close with get_prior_closes() result when available.
        # Alpaca's quote snapshot prev_close is unreliable — can be 0.0 early premarket,
        # then flip to a wrong non-zero value (e.g. today's open) mid-session, causing
        # gap to oscillate between correct and 0 across successive full rescans.
        for sym, q in quotes.items():
            if sym in prior_closes:
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
            if price < 1.00:
                continue  # sub-$1 warrants/shells — too illiquid, wide spreads
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
        self._assign_rel_vol(filtered)
        # Float (Gap #2): weekly Neon baseline covers known symbols; live-fetch
        # (yfinance) fills in any brand-new gapper not yet in that baseline. Cheap
        # here — `filtered` is only the small news+gap-qualified short-list.
        fetch_missing_floats([g['symbol'] for g in filtered], self._floats)
        for g in filtered:
            g['float_shares'] = self._floats.get(g['symbol'])

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
        try:
            quotes = self.data_feed.get_quotes(symbols)
        except Exception as e:
            logger.warning(f"Quote refresh failed: {e} — using stale data")
            return

        for c in self.state.candidates:
            q = quotes.get(c['symbol'])
            if q:
                c['quote_volume'] = q.volume

                # Fix 1: re-evaluate gap from current bid/ask midpoint.
                # Initial scan may lock in a stale/erroneous early premarket print;
                # refresh with latest price so collapsed gaps get dropped.
                if q.bid > 0 and q.ask > 0:
                    spread_ratio = q.ask / q.bid
                    if spread_ratio <= 3.0:
                        mid = (q.bid + q.ask) / 2
                        prev = c.get('prior_close', 0)
                        if prev > 0:
                            new_gap = (mid - prev) / prev * 100
                            # Fix 2: sanity-check stored open_price — if current
                            # midpoint is >3x away AND open was the outlier (open >
                            # 2x midpoint or < 0.5x midpoint), replace open_price.
                            old_open = c.get('open_price', mid)
                            if old_open > 0 and (old_open > mid * 2 or old_open < mid * 0.5):
                                logger.info(
                                    f"  {c['symbol']}: open_price ${old_open:.2f} looks "
                                    f"erroneous vs current mid ${mid:.2f} — replacing")
                                c['open_price'] = mid
                            c['gap_pct'] = new_gap

        # Live rel-vol (Gap #1): recompute now that we're at 9:25 (numerator captures more
        # of the premarket session), then apply the SAME min_relative_volume filter the sim
        # applies. Tradier single-feed — see _assign_rel_vol.
        self._assign_rel_vol(self.state.candidates)

        survivors = []
        for c in self.state.candidates:
            if c['gap_pct'] < self.config.min_gap_pct:
                logger.info(f"  DROP {c['symbol']} gap collapsed to {c['gap_pct']:.1f}% "
                            f"< {self.config.min_gap_pct:.1f}% — erroneous early print")
                continue
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

    def _write_live_state(self):
        """Write state.json as trades happen, not just once the whole session
        function returns. Without this, /dashboard shows stale premarket-scan
        data for the entire ~10-20min trading window even on a normal day —
        found 2026-07-01 when Alpaca showed 6 closed round-trips while the
        dashboard still read stage=ARMED, position=null."""
        import json as _json
        state_file = Path(os.getenv("JTRADER_STATE_DIR", "/tmp/jtrader")) / "state.json"
        candidates = []
        for c in (self.state.candidates or []):
            candidates.append({k: c.get(k) for k in (
                'symbol', 'gap_pct', 'open_price', 'prior_close', 'rel_vol',
                'float_shares', 'has_news', 'news_tier', 'scalp_score', 'quote_volume',
            )})
        top = self.state.top_pick
        top_sym = (top.get('symbol') if isinstance(top, dict) else top) if top else None
        first = self.state.completed_trades[0] if self.state.completed_trades else {}
        try:
            state_file.write_text(_json.dumps({
                "last_run": datetime.utcnow().isoformat(),
                "strategy": "opening_bell_scalp",
                "last_result": "trade" if self.state.completed_trades else "scanning",
                "date": str(datetime.now(ET).date()),
                "candidates": candidates,
                "top_pick": top_sym,
                "positions": self.state.positions,
                "completed_trades": self.state.completed_trades,
                "trade_count": len(self.state.completed_trades),
                "pnl": self.state.pnl,
                "entry_price": first.get('entry_price'),
                "exit_price": first.get('exit_price'),
                "shares": first.get('shares'),
                "bars_held": first.get('bars_held'),
                "exit_reason": first.get('exit_reason', ''),
            }, default=str))
        except Exception as e:
            logger.warning(f"_write_live_state failed (non-fatal): {e}")

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
        try:
            pm_bars_all = self.data_feed.get_bars_since_4am(symbols)
        except Exception as e:
            logger.warning(f"Premarket bar fetch failed: {e} — PM highs unavailable")
            pm_bars_all = {}
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

        monitor_start = datetime.now(ET)
        max_entry_wait = timedelta(minutes=self.config.max_entry_bars)

        while True:
            if all(m['done'] for m in sym_meta.values()) and not open_positions:
                break

            # Wall-clock fallback: a symbol whose bar-count timeout never
            # fires because it never receives ANY bars (illiquid/no-quote
            # ticker) would otherwise block this loop — and therefore VWAP +
            # micro-pullback, which run after this returns — forever. The
            # per-bar max_entry_bars check below can't help since it only
            # runs when a bar for THAT symbol arrives.
            if datetime.now(ET) - monitor_start >= max_entry_wait:
                for sym, meta in sym_meta.items():
                    if not meta['done'] and sym not in open_positions:
                        logger.warning(
                            f"  [{sym}] No entry after {max_entry_wait.total_seconds()/60:.0f}min "
                            f"wall-clock ({meta['bars_since_open']} bars received) — "
                            f"marking done (bar starvation)")
                        meta['done'] = True

            try:
                bar = self._bar_queue.get(timeout=180)
            except queue.Empty:
                logger.warning("No bar received in 180s -- timeout")
                if open_positions:
                    logger.warning(f"Timeout with {len(open_positions)} open position(s) — emergency exit all")
                    for sym, pos in list(open_positions.items()):
                        try:
                            trade = self._place_exit_multi(
                                sym, {'close': pos['entry_price']},
                                {'reason': 'BAR_TIMEOUT_SAFETY_EXIT'}, pos)
                            completed_trades.append(trade)
                            self.state.pnl += trade['pnl']
                            self.state.trade_count += 1
                            del open_positions[sym]
                            self.state.positions.pop(sym, None)
                            self.state.completed_trades = completed_trades
                            self._write_live_state()
                        except Exception as e:
                            # Don't let one symbol's failure skip the rest.
                            logger.error(f"  [{sym}] Emergency exit failed: {e}", exc_info=True)
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
                    try:
                        trade = self._place_exit_multi(sym, bar, exit_signal, pos)
                        completed_trades.append(trade)
                        del open_positions[sym]
                        meta['done'] = True
                        self.state.pnl += trade['pnl']
                        self.state.trade_count += 1
                        self.state.in_position = bool(open_positions)
                        self.state.positions.pop(sym, None)
                        self.state.completed_trades = completed_trades
                        self._write_live_state()
                    except Exception as e:
                        # A single symbol's exit failure must NOT crash the monitor
                        # loop and orphan the other open positions (root cause of the
                        # 2026-06-25 multi-orphan). Keep the position and retry the
                        # exit on the next bar.
                        logger.error(
                            f"  [{sym}] EXIT FAILED: {e} — keeping position, "
                            f"retry next bar", exc_info=True)
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
                        try:
                            pos = self._place_entry_multi(sym, bar, entry)
                        except Exception as e:
                            logger.error(
                                f"  [{sym}] ENTRY FAILED: {e} — skipping symbol",
                                exc_info=True)
                            meta['done'] = True
                            pos = None
                        if pos and pos.get('_already_exited'):
                            trade = pos['trade']
                            completed_trades.append(trade)
                            self.state.pnl += trade['pnl']
                            self.state.trade_count += 1
                            meta['done'] = True
                            self.state.completed_trades = completed_trades
                            self._write_live_state()
                        elif pos:
                            open_positions[sym] = pos
                            self.state.in_position = True
                            self.state.positions[sym] = pos
                            self._write_live_state()
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
        # Marketable limit: 0.25% above signal close. Exact-close limits suffer
        # adverse selection on fast gappers — 2026-07-02: 12/15 attempts missed
        # (price ran = the winners), the 2 fills came on falling bars and both
        # stopped out. 0.25% keeps ~70% of the backtested edge if paid
        # (slippage sensitivity: edge dies at ~1%; see
        # research/analysis/outputs/slippage_sensitivity.txt). Sub-$4 names
        # round back to the close (a penny would exceed the 0.25% budget).
        limit_price = round(entry_price * 1.0025, 2)
        if not self.dry_run:
            result = self.broker.place_limit_buy(symbol, shares, limit_price)
            entry_order_id = result.order_id
            logger.info(f"    Limit: ${limit_price:.2f} (signal close ${entry_price:.2f} +0.25%)")
            logger.info(f"    Order ID: {result.order_id} Status: {result.status}")

            time.sleep(2)
            fill = self.broker.get_order(result.order_id)
            if fill.status == 'filled':
                entry_price = fill.filled_price
                shares = fill.filled_qty
                logger.info(f"    FILLED: {symbol} {shares} @ ${entry_price:.2f}")
            else:
                logger.info(f"    Order status: {fill.status} -- waiting...")
                for _ in range(5):
                    time.sleep(2)
                    fill = self.broker.get_order(result.order_id)
                    if fill.status == 'filled':
                        entry_price = fill.filled_price
                        shares = fill.filled_qty
                        logger.info(f"    FILLED: {symbol} {shares} @ ${entry_price:.2f}")
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
            try:
                stop_result = self.broker.place_stop_sell(symbol, shares, stop_price)
                stop_order_id = stop_result.order_id
                logger.info(f"    Stop order: {stop_result.order_id} @ ${stop_price:.2f}")
            except Exception as e:
                # Broker rejects a stop whose trigger price is already past current
                # market (price crashed between fill and stop placement) — that means
                # the position should already be exiting. Flatten immediately at market
                # instead of leaving it open with no protection at all.
                logger.error(
                    f"    [{symbol}] STOP ORDER FAILED: {e} — attempting emergency market exit")
                try:
                    mkt_result = self.broker.place_market_sell(symbol, shares)
                    time.sleep(2)
                    mkt_fill = self.broker.get_order(mkt_result.order_id)
                    if mkt_fill.status == 'filled':
                        exit_price = mkt_fill.filled_price
                        pnl = (exit_price - entry_price) * shares
                        logger.warning(
                            f"    [{symbol}] Emergency market exit FILLED: "
                            f"{mkt_fill.filled_qty} @ ${exit_price:.2f} (P&L ${pnl:+.2f})")
                        return {
                            '_already_exited': True,
                            'trade': {
                                'symbol': symbol,
                                'entry_price': entry_price,
                                'exit_price': exit_price,
                                'shares': shares,
                                'pnl': pnl,
                                'bars_held': 0,
                                'reason': 'STOP_REJECTED_MARKET_EXIT',
                            },
                        }
                    logger.error(
                        f"    [{symbol}] Emergency market exit NOT FILLED "
                        f"(status={mkt_fill.status}) — position UNHEDGED")
                except Exception as e2:
                    logger.error(
                        f"    [{symbol}] Emergency market exit ALSO FAILED: {e2} — position UNHEDGED")

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
            # Cancel the protective stop and WAIT until the cancel settles — the
            # broker only releases the held shares once the stop is terminal. Selling
            # before that races 'insufficient qty available' (the order error that
            # crashed the 2026-06-25 session and orphaned the other open positions).
            if pos.get('stop_order_id'):
                final = self.broker.cancel_order_and_wait(pos['stop_order_id'])
                if final.status == 'filled':
                    # Price fell through the stop during the exit — adopt that fill
                    # instead of double-selling (which would open a short).
                    exit_price = final.filled_price
                    logger.warning(
                        f"    Stop {pos['stop_order_id']} filled @ ${exit_price:.2f} "
                        f"during cancel — adopting stop fill"
                    )
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
                logger.info(f"    FILLED: {symbol} {fill.filled_qty} @ ${exit_price:.2f}")

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
            try:
                quotes = self.data_feed.get_quotes(symbols)
            except Exception as e:
                logger.warning(f"Universe quote fetch failed: {e} — using unfiltered list")
                return symbols
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

        if not runner.state.candidates:
            # No candidates yet — full rescan in 60s
            next_scan = min(60, (scan_cutoff - now).total_seconds())
            logger.info(f"Rescanning in {next_scan:.0f}s...")
            time.sleep(next_scan)
        else:
            # Hybrid: fast 60s re-quote of watchlist candidates between 5-min full scans
            full_scan_interval = 300
            fast_interval = 60
            elapsed = 0
            while elapsed < full_scan_interval:
                remaining_to_cutoff = (scan_cutoff - datetime.now(ET)).total_seconds()
                if remaining_to_cutoff <= 0:
                    break
                sleep_secs = min(fast_interval, remaining_to_cutoff, full_scan_interval - elapsed)
                time.sleep(sleep_secs)
                elapsed += sleep_secs
                if elapsed >= full_scan_interval or (scan_cutoff - datetime.now(ET)).total_seconds() <= 0:
                    break
                # Fast re-quote: update price/volume on known candidates only
                logger.info("Fast watchlist refresh (price/volume update)...")
                runner.refresh_top_pick()
                # Re-write state file with updated metrics
                _candidates = []
                for c in (runner.state.candidates or []):
                    _candidates.append({k: c.get(k) for k in (
                        'symbol', 'gap_pct', 'open_price', 'prior_close', 'rel_vol',
                        'float_shares', 'has_news', 'news_tier', 'scalp_score', 'quote_volume',
                    )})
                _top = runner.state.top_pick
                _top_sym = (_top.get('symbol') if isinstance(_top, dict) else _top) if _top else None
                import json as _json2
                _state_file.write_text(_json2.dumps({
                    "last_run": datetime.utcnow().isoformat(),
                    "strategy": "opening_bell_scalp",
                    "last_result": "scanning",
                    "date": str(datetime.now(ET).date()),
                    "candidates": _candidates,
                    "top_pick": _top_sym,
                }, default=str))

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
