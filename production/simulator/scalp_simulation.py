"""
Scalp Simulation Runner — Backtest Harness for Opening Bell Scalp
=================================================================
Runs the Opening Bell Scalp strategy on historical data.

Key differences from SimulationRunner:
  - Only loads first 10 minutes of data per day (9:25-9:40 ET)
  - Pre-selects ONE symbol before 9:30 (ranking phase)
  - Executes exactly 0 or 1 trade per day
  - ~50-100x faster than the existing simulator

Usage:
    runner = ScalpSimulationRunner('2025-03-15', ScalpConfig())
    result = runner.run()
"""

from __future__ import annotations
import sys
import os
import logging
from datetime import datetime, date as dateclass, timedelta
from dataclasses import dataclass, field

import pytz

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from trading.scalp_models import ScalpConfig
from trading.scalp_ranker import rank_candidates, get_top_candidate
from trading.scalp_engine import get_premarket_high, evaluate_entry, evaluate_exit
from utils.query_helpers import StockDataDB

logger = logging.getLogger(__name__)

ET = pytz.timezone('US/Eastern')


@dataclass
class ScalpTrade:
    """One completed scalp trade."""
    symbol: str
    date: dateclass
    entry_price: float
    exit_price: float
    shares: int
    entry_time: datetime
    exit_time: datetime
    entry_reason: str
    exit_reason: str
    exit_type: str
    pnl: float
    pnl_pct: float
    bars_held: int
    gap_pct: float = 0.0
    rel_vol: float = 0.0
    news_tier: str = 'none'
    scalp_score: float = 0.0


class ScalpSimulationRunner:
    """
    Backtest harness for the Opening Bell Scalp strategy.

    For each trading day:
    1. Find gappers from daily bars (premarket scan at ~9:25)
    2. Enrich with news + fundamentals
    3. Rank and pick #1 candidate
    4. Simulate entry/exit on 9:30-9:40 minute bars
    """

    def __init__(
        self,
        trade_date,
        config: ScalpConfig | None = None,
        account_size: float = 5000.0,
        verbose: bool = True,
    ):
        if isinstance(trade_date, str):
            self.trade_date = datetime.strptime(trade_date, '%Y-%m-%d').date()
        elif isinstance(trade_date, datetime):
            self.trade_date = trade_date.date()
        else:
            self.trade_date = trade_date

        self.config = config or ScalpConfig()
        self.account_size = account_size
        self.verbose = verbose
        self.trade: ScalpTrade | None = None

    def run(self) -> dict:
        """
        Run the scalp simulation for one day.

        Returns dict with:
            traded: bool
            trade: ScalpTrade | None
            pnl: float
            candidate_count: int
            top_candidate: dict | None
        """
        with StockDataDB() as db:
            return self._run_with_db(db)

    def _run_with_db(self, db: StockDataDB) -> dict:
        """Core logic, separated for testability and connection reuse."""

        # ── Phase 1: Find gappers ──────────────────────────────────────────
        candidates = self._find_candidates(db)

        if not candidates:
            if self.verbose:
                logger.debug(f"{self.trade_date} | No candidates")
            return self._no_trade_result(0, None)

        # ── Phase 2: Enrich with news + fundamentals ───────────────────────
        candidates = self._enrich_candidates(db, candidates)

        # ── Phase 3: Apply filters ─────────────────────────────────────────
        filtered = self._apply_filters(candidates)

        if not filtered:
            if self.verbose:
                logger.debug(f"{self.trade_date} | {len(candidates)} gappers, 0 pass filters")
            return self._no_trade_result(len(candidates), None)

        # ── Phase 4: Rank and pick #1 ─────────────────────────────────────
        top = get_top_candidate(filtered)

        if not top:
            return self._no_trade_result(len(candidates), None)

        if self.verbose:
            logger.info(
                f"{self.trade_date} | #{1} {top['symbol']} "
                f"gap={top['gap_pct']:.1f}% rv={top['rel_vol']:.1f}x "
                f"news={top.get('news_tier', '?')} score={top.get('scalp_score', 0):.3f} "
                f"| {len(filtered)} candidates"
            )

        # ── Phase 5: Simulate entry/exit on minute bars ───────────────────
        result = self._simulate_trade(db, top)
        return result

    def _find_candidates(self, db: StockDataDB) -> list[dict]:
        """
        Find stocks gapping up on trade_date using daily bars.
        This mimics the 9:25 AM premarket scan.

        Uses the shared db.find_gappers() — single source of truth for
        gapper discovery, also used by backfill_news.py.
        """
        return db.find_gappers(
            self.trade_date,
            min_gap_pct=self.config.min_gap_pct,
            max_price=self.config.max_price,
        )

    def _enrich_candidates(self, db: StockDataDB, candidates: list[dict]) -> list[dict]:
        """Add fundamentals (float) + news + relative volume to candidates."""
        symbols = [c['symbol'] for c in candidates]

        # Batch fetch fundamentals
        fundamentals = db.get_fundamentals_batch(symbols)

        # Relative volume from rel_vol_cum_cache (precomputed cumulative
        # volume per symbol per minute). Compare today's 9:25 AM volume
        # to 20-day average at same time — same logic as live trading.
        MINUTE_925 = 9 * 60 + 25  # minute_of_day for 9:25 AM ET
        cursor = db.conn.cursor()

        # Today's cumulative volume at 9:25 for each candidate
        today_vols = {}
        if symbols:
            cursor.execute("""
                SELECT symbol, cum_total FROM rel_vol_cum_cache
                WHERE trade_date = %s AND minute_of_day = %s
                  AND symbol = ANY(%s)
            """, [self.trade_date, MINUTE_925, symbols])
            for row in cursor.fetchall():
                today_vols[row[0]] = float(row[1])

        # 20-day average cumulative volume at 9:25 for each candidate
        avg_vols = {}
        if symbols:
            cursor.execute("""
                SELECT symbol, AVG(cum_total) FROM rel_vol_cum_cache
                WHERE trade_date < %s
                  AND trade_date >= %s::date - interval '30 days'
                  AND minute_of_day = %s
                  AND symbol = ANY(%s)
                GROUP BY symbol
            """, [self.trade_date, self.trade_date, MINUTE_925, symbols])
            for row in cursor.fetchall():
                avg_vols[row[0]] = float(row[1])
        cursor.close()

        # News: query per symbol (from stock_news table)
        market_open_930 = ET.localize(
            datetime.combine(self.trade_date, datetime.min.time()).replace(hour=9, minute=30)
        )

        for c in candidates:
            sym = c['symbol']

            # Float
            fund = fundamentals.get(sym, {})
            c['float_shares'] = fund.get('float_shares')

            # Relative volume (from rel_vol_cum_cache)
            today_vol = today_vols.get(sym, 0)
            avg_vol = avg_vols.get(sym, 0)
            c['rel_vol'] = today_vol / avg_vol if avg_vol > 0 else 10.0

            # News
            try:
                articles = db.get_news_for_symbol(sym, market_open_930, hours_back=48)
                if articles:
                    c['has_news'] = any(a.get('is_specific', True) for a in articles)
                    c['news_tier'] = db.get_news_tier(sym, market_open_930, hours_back=48)
                else:
                    c['has_news'] = False
                    c['news_tier'] = 'none'
            except Exception:
                c['has_news'] = False
                c['news_tier'] = 'none'

        return candidates

    def _apply_filters(self, candidates: list[dict]) -> list[dict]:
        """Apply ScalpConfig filters to candidates."""
        filtered = []
        for c in candidates:
            # Relative volume gate
            if c.get('rel_vol', 0) < self.config.min_relative_volume:
                continue

            # Float gate
            if c.get('float_shares') and c['float_shares'] > self.config.max_float:
                continue

            # News gate
            if self.config.require_news and not c.get('has_news', False):
                continue

            filtered.append(c)

        return filtered

    def _simulate_trade(self, db: StockDataDB, candidate: dict) -> dict:
        """
        Simulate the scalp trade on minute bars for the chosen symbol.
        Load only 9:30-9:40 bars (10 minutes).
        """
        symbol = candidate['symbol']

        # Load minute bars: 9:30 to 9:30 + max_entry_bars + max_hold_bars + 2
        end_minute = 30 + self.config.max_entry_bars + self.config.max_hold_bars + 2
        end_hour = 9 + (end_minute // 60)
        end_min = end_minute % 60

        bars_data = db.get_minute_bars(
            [symbol], self.trade_date,
            start_hour=9, end_hour=end_hour + 1,  # +1 because end_hour is exclusive
        )
        all_bars = bars_data.get(symbol, [])

        if not all_bars:
            if self.verbose:
                logger.debug(f"{self.trade_date} | {symbol} — no minute bars")
            return self._no_trade_result(1, candidate)

        # Also load premarket bars for PM high calculation
        pm_bars_data = db.get_minute_bars([symbol], self.trade_date, start_hour=4, end_hour=9)
        pm_bars = pm_bars_data.get(symbol, [])

        # Also check hourly premarket bars
        pm_hour_data = db.get_hour_bars([symbol], self.trade_date, start_hour=4, end_hour=9)
        pm_hour_bars = pm_hour_data.get(symbol, [])

        # Combine premarket bars for PM high
        combined_pm = pm_hour_bars + pm_bars
        premarket_high = get_premarket_high(combined_pm)

        # Filter to only bars at/after 9:30
        market_bars = []
        for bar in all_bars:
            t = bar.get('time')
            if t is None:
                continue
            if hasattr(t, 'astimezone'):
                et = t.astimezone(ET)
            else:
                et = datetime.fromisoformat(str(t)).astimezone(ET)

            if et.hour > 9 or (et.hour == 9 and et.minute >= 30):
                bar['_et'] = et
                market_bars.append(bar)

        if not market_bars:
            if self.verbose:
                logger.debug(f"{self.trade_date} | {symbol} — no market-hours bars")
            return self._no_trade_result(1, candidate)

        # ── Try to enter ──────────────────────────────────────────────────
        entry_signal = None
        entry_bar_idx = None

        for i, bar in enumerate(market_bars):
            signal = evaluate_entry(
                candidate, bar, premarket_high,
                bars_since_open=i,
                config=self.config,
            )
            if signal:
                entry_signal = signal
                entry_bar_idx = i
                break

        if not entry_signal:
            if self.verbose:
                logger.debug(f"{self.trade_date} | {symbol} — no entry signal within {self.config.max_entry_bars} bars")
            return self._no_trade_result(1, candidate)

        # ── Calculate position size ───────────────────────────────────────
        entry_price = entry_signal['entry_price']
        stop_price = entry_signal['stop_price']
        risk_per_share = abs(entry_price - stop_price)

        if risk_per_share <= 0:
            risk_per_share = entry_price * 0.02  # fallback 2%

        risk_amount = self.account_size * (self.config.risk_pct / 100)
        max_position_value = self.account_size * (self.config.max_position_pct / 100)

        shares_by_risk = int(risk_amount / risk_per_share)
        shares_by_cap = int(max_position_value / entry_price)
        shares = max(1, min(shares_by_risk, shares_by_cap))

        # ── Simulate exit bar by bar ──────────────────────────────────────
        highest_since_entry = entry_price
        exit_signal = None
        exit_bar_idx = entry_bar_idx

        for j in range(entry_bar_idx + 1, len(market_bars)):
            bar = market_bars[j]
            bar_high = float(bar['high'])
            highest_since_entry = max(highest_since_entry, bar_high)
            bars_held = j - entry_bar_idx

            exit_signal = evaluate_exit(
                entry_price, highest_since_entry,
                bar, bars_held, self.config,
            )
            if exit_signal:
                exit_bar_idx = j
                break

        # If no exit triggered, force exit on last bar
        if not exit_signal:
            exit_bar_idx = len(market_bars) - 1
            last_bar = market_bars[exit_bar_idx]
            exit_signal = {
                'exit_price': float(last_bar['close']),
                'reason': 'END_OF_DATA forced exit',
                'exit_type': 'end_of_data',
            }

        # ── Build trade result ────────────────────────────────────────────
        exit_price = exit_signal['exit_price']
        pnl = (exit_price - entry_price) * shares
        pnl_pct = ((exit_price - entry_price) / entry_price) * 100

        self.trade = ScalpTrade(
            symbol=symbol,
            date=self.trade_date,
            entry_price=entry_price,
            exit_price=exit_price,
            shares=shares,
            entry_time=market_bars[entry_bar_idx].get('_et', market_bars[entry_bar_idx].get('time')),
            exit_time=market_bars[exit_bar_idx].get('_et', market_bars[exit_bar_idx].get('time')),
            entry_reason=entry_signal['reason'],
            exit_reason=exit_signal['reason'],
            exit_type=exit_signal['exit_type'],
            pnl=round(pnl, 2),
            pnl_pct=round(pnl_pct, 2),
            bars_held=exit_bar_idx - entry_bar_idx,
            gap_pct=candidate.get('gap_pct', 0),
            rel_vol=candidate.get('rel_vol', 0),
            news_tier=candidate.get('news_tier', 'none'),
            scalp_score=candidate.get('scalp_score', 0),
        )

        if self.verbose:
            win_loss = "WIN" if pnl > 0 else "LOSS"
            logger.info(
                f"{self.trade_date} | {symbol} {win_loss} "
                f"${pnl:+.2f} ({pnl_pct:+.1f}%) | "
                f"entry={entry_price:.2f} exit={exit_price:.2f} "
                f"shares={shares} bars={self.trade.bars_held} "
                f"| {exit_signal['exit_type']}"
            )

        return {
            'traded': True,
            'trade': self.trade,
            'pnl': pnl,
            'candidate_count': 1,
            'top_candidate': candidate,
        }

    def _no_trade_result(self, candidate_count: int, top_candidate: dict | None) -> dict:
        return {
            'traded': False,
            'trade': None,
            'pnl': 0.0,
            'candidate_count': candidate_count,
            'top_candidate': top_candidate,
        }


def run_scalp_date_range(
    config: ScalpConfig,
    start_date: str,
    end_date: str,
    account_size: float = 5000.0,
    verbose: bool = True,
    print_dates: bool = False,
) -> dict:
    """
    Run the scalp strategy across a date range.

    Returns aggregated metrics dict compatible with the existing optimizer format:
        days_traded, total_trades, winners, losers, win_rate,
        total_pnl, avg_daily_pnl, max_drawdown, profit_factor, trades (list)
    """
    with StockDataDB() as db:
        trading_days = db.get_trading_days(start_date, end_date)

    if not trading_days:
        logger.warning(f"No trading days found between {start_date} and {end_date}")
        return _empty_result()

    trades: list[ScalpTrade] = []
    daily_pnls: list[float] = []

    for trade_date in trading_days:
        runner = ScalpSimulationRunner(
            trade_date, config, account_size, verbose=verbose
        )
        result = runner.run()

        if result['traded'] and result['trade']:
            trades.append(result['trade'])
            daily_pnls.append(result['pnl'])
        else:
            daily_pnls.append(0.0)

        if print_dates:
            status = f"${result['pnl']:+.2f}" if result['traded'] else "no trade"
            print(f"  {trade_date} | {status}")

    # ── Aggregate metrics ─────────────────────────────────────────────────
    total_pnl = sum(t.pnl for t in trades)
    winners = [t for t in trades if t.pnl > 0]
    losers = [t for t in trades if t.pnl <= 0]
    win_rate = (len(winners) / len(trades) * 100) if trades else 0.0

    gross_profit = sum(t.pnl for t in winners)
    gross_loss = abs(sum(t.pnl for t in losers))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

    # Max drawdown from cumulative P&L
    cum_pnl = 0.0
    peak = 0.0
    max_dd = 0.0
    for pnl in daily_pnls:
        cum_pnl += pnl
        peak = max(peak, cum_pnl)
        dd = peak - cum_pnl
        max_dd = max(max_dd, dd)

    days_traded = len([p for p in daily_pnls if p != 0.0])
    avg_daily_pnl = total_pnl / days_traded if days_traded > 0 else 0.0

    return {
        'days_traded': days_traded,
        'total_trades': len(trades),
        'winners': len(winners),
        'losers': len(losers),
        'win_rate': win_rate,
        'total_pnl': round(total_pnl, 2),
        'avg_daily_pnl': round(avg_daily_pnl, 2),
        'max_drawdown': round(max_dd, 2),
        'profit_factor': round(profit_factor, 2),
        'trades': trades,
        'daily_pnls': daily_pnls,
    }


def _empty_result() -> dict:
    return {
        'days_traded': 0,
        'total_trades': 0,
        'winners': 0,
        'losers': 0,
        'win_rate': 0.0,
        'total_pnl': 0.0,
        'avg_daily_pnl': 0.0,
        'max_drawdown': 0.0,
        'profit_factor': 0.0,
        'trades': [],
        'daily_pnls': [],
    }
