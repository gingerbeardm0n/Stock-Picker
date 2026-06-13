"""
VWAP Reclaim Simulation Runner — Backtest Harness
==================================================
Runs the VWAP Reclaim strategy on historical data.

Daily flow (mirrors how the live runner will work):
  1. Find gappers from daily bars (the 9:25 premarket scan)
  2. Enrich with news / relative volume / float, apply config filters
  3. Rank (shared fixed-weight ranker) and watch the top-N candidates
  4. Walk 9:30-12:30 minute bars per candidate with a running VWAP;
     inside the fixed 10:00-11:30 window, look for a reclaim signal
  5. Take the EARLIEST signal across watched candidates (tie -> rank order)
  6. Simulate exit bar-by-bar; exactly 0 or 1 trade per day

Usage:
    runner = VwapSimulationRunner('2025-03-15', VwapReclaimConfig())
    result = runner.run()
"""

from __future__ import annotations
import sys
import os
import logging
from datetime import datetime, date as dateclass
from dataclasses import dataclass

import pytz

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from trading.vwap_models import VwapReclaimConfig, WATCH_TOP_N
from trading.vwap_engine import VwapAccumulator, evaluate_entry, evaluate_exit
from trading.scalp_ranker import rank_candidates, screen_candidates
from utils.query_helpers import StockDataDB

logger = logging.getLogger(__name__)

ET = pytz.timezone('US/Eastern')


@dataclass
class VwapTrade:
    """One completed VWAP reclaim trade."""
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
    vwap_at_entry: float = 0.0
    gap_pct: float = 0.0
    rel_vol: float = 0.0
    news_tier: str = 'none'


class VwapSimulationRunner:
    """Backtest harness for the VWAP Reclaim strategy — one day, 0 or 1 trade."""

    def __init__(
        self,
        trade_date,
        config: VwapReclaimConfig | None = None,
        account_size: float = 5000.0,
        verbose: bool = True,
    ):
        if isinstance(trade_date, str):
            self.trade_date = datetime.strptime(trade_date, '%Y-%m-%d').date()
        elif isinstance(trade_date, datetime):
            self.trade_date = trade_date.date()
        else:
            self.trade_date = trade_date

        self.config = config or VwapReclaimConfig()
        self.account_size = account_size
        self.verbose = verbose
        self.trade: VwapTrade | None = None

    def run(self) -> dict:
        with StockDataDB() as db:
            return self._run_with_db(db)

    def _run_with_db(self, db: StockDataDB) -> dict:
        # ── Phase 1: gappers ───────────────────────────────────────────────
        candidates = db.find_gappers(
            self.trade_date,
            min_gap_pct=self.config.min_gap_pct,
            max_price=self.config.max_price,
        )
        if not candidates:
            return self._no_trade_result(0)

        # Live-parity screen: same top-20 / >1000% cuts the live runner makes
        candidates = screen_candidates(candidates)

        # ── Phase 2: enrich + filter ───────────────────────────────────────
        candidates = self._enrich_candidates(db, candidates)
        filtered = self._apply_filters(candidates)
        if not filtered:
            return self._no_trade_result(len(candidates))

        # ── Phase 3: rank, watch top N ─────────────────────────────────────
        watchlist = rank_candidates(filtered)[:WATCH_TOP_N]

        # ── Phase 4: load bars + find earliest reclaim across watchlist ───
        symbols = [c['symbol'] for c in watchlist]
        bars_data = db.get_minute_bars(symbols, self.trade_date, start_hour=9, end_hour=13)

        best = None  # (entry_et, rank_idx, candidate, market_bars, entry_idx, signal)
        for rank_idx, cand in enumerate(watchlist):
            found = self._find_first_signal(cand, bars_data.get(cand['symbol'], []))
            if found is None:
                continue
            entry_et, market_bars, entry_idx, signal = found
            key = (entry_et, rank_idx)
            if best is None or key < (best[0], best[1]):
                best = (entry_et, rank_idx, cand, market_bars, entry_idx, signal)

        if best is None:
            if self.verbose:
                logger.debug(f"{self.trade_date} | {len(watchlist)} watched, no reclaim signal")
            return self._no_trade_result(len(filtered))

        _, _, cand, market_bars, entry_idx, signal = best
        return self._simulate_exit(cand, market_bars, entry_idx, signal, len(filtered))

    # ── Signal search ──────────────────────────────────────────────────────

    def _find_first_signal(self, candidate: dict, all_bars: list[dict]):
        """
        Walk one symbol's bars with a running VWAP; return the first entry
        signal as (entry_et, market_bars, entry_idx, signal), or None.
        """
        market_bars = []
        for bar in all_bars:
            t = bar.get('time')
            if t is None:
                continue
            et = t.astimezone(ET) if hasattr(t, 'astimezone') else \
                datetime.fromisoformat(str(t)).astimezone(ET)
            if et.hour > 9 or (et.hour == 9 and et.minute >= 30):
                bar['_et'] = et
                market_bars.append(bar)

        if len(market_bars) < self.config.lookback_bars + 1:
            return None

        acc = VwapAccumulator()
        bars_so_far: list[dict] = []
        for i, bar in enumerate(market_bars):
            acc.update(bar)
            bars_so_far.append(bar)
            # evaluate_entry handles the 10:00-11:30 window gate itself
            signal = evaluate_entry(candidate, bars_so_far, acc.value, self.config)
            if signal:
                return (bar['_et'], market_bars, i, signal)
            # past window end + lookahead margin -> stop scanning this symbol
            if bar['_et'].hour >= 12:
                break
        return None

    # ── Exit simulation ────────────────────────────────────────────────────

    def _simulate_exit(self, candidate, market_bars, entry_idx, signal, n_filtered) -> dict:
        symbol = candidate['symbol']
        entry_price = signal['entry_price']
        stop_price = signal['stop_price']

        # Position sizing (same approach as scalp sim)
        risk_per_share = max(entry_price - stop_price, entry_price * 0.005)
        risk_amount = self.account_size * (self.config.risk_pct / 100)
        max_position_value = self.account_size * (self.config.max_position_pct / 100)
        shares = max(1, min(int(risk_amount / risk_per_share),
                            int(max_position_value / entry_price)))

        highest = entry_price
        exit_signal = None
        exit_idx = entry_idx
        for j in range(entry_idx + 1, len(market_bars)):
            bar = market_bars[j]
            highest = max(highest, float(bar['high']))
            exit_signal = evaluate_exit(
                entry_price, stop_price, highest, bar,
                bars_held=j - entry_idx, config=self.config,
            )
            if exit_signal:
                exit_idx = j
                break

        if not exit_signal:
            exit_idx = len(market_bars) - 1
            exit_signal = {
                'exit_price': float(market_bars[exit_idx]['close']),
                'reason': 'END_OF_DATA forced exit',
                'exit_type': 'end_of_data',
            }

        exit_price = exit_signal['exit_price']
        pnl = (exit_price - entry_price) * shares
        pnl_pct = (exit_price - entry_price) / entry_price * 100

        self.trade = VwapTrade(
            symbol=symbol,
            date=self.trade_date,
            entry_price=entry_price,
            exit_price=exit_price,
            shares=shares,
            entry_time=market_bars[entry_idx]['_et'],
            exit_time=market_bars[exit_idx].get('_et', market_bars[exit_idx].get('time')),
            entry_reason=signal['reason'],
            exit_reason=exit_signal['reason'],
            exit_type=exit_signal['exit_type'],
            pnl=round(pnl, 2),
            pnl_pct=round(pnl_pct, 2),
            bars_held=exit_idx - entry_idx,
            vwap_at_entry=signal.get('vwap', 0.0),
            gap_pct=candidate.get('gap_pct', 0),
            rel_vol=candidate.get('rel_vol', 0),
            news_tier=candidate.get('news_tier', 'none'),
        )

        if self.verbose:
            win_loss = "WIN" if pnl > 0 else "LOSS"
            logger.info(
                f"{self.trade_date} | {symbol} {win_loss} ${pnl:+.2f} ({pnl_pct:+.1f}%) "
                f"| entry={entry_price:.2f}@{self.trade.entry_time.strftime('%H:%M')} "
                f"exit={exit_price:.2f} shares={shares} bars={self.trade.bars_held} "
                f"| {exit_signal['exit_type']}"
            )

        return {
            'traded': True,
            'trade': self.trade,
            'pnl': pnl,
            'candidate_count': n_filtered,
            'top_candidate': candidate,
        }

    # ── Enrichment (same data sources as scalp sim) ────────────────────────

    def _enrich_candidates(self, db: StockDataDB, candidates: list[dict]) -> list[dict]:
        """Add float / news / relative volume. Same queries as scalp sim."""
        symbols = [c['symbol'] for c in candidates]
        fundamentals = db.get_fundamentals_batch(symbols)

        MINUTE_925 = 9 * 60 + 25
        cursor = db.conn.cursor()

        today_vols = {}
        if symbols:
            cursor.execute("""
                SELECT symbol, cum_total FROM rel_vol_cum_cache
                WHERE trade_date = %s AND minute_of_day = %s
                  AND symbol = ANY(%s)
            """, [self.trade_date, MINUTE_925, symbols])
            for row in cursor.fetchall():
                today_vols[row[0]] = float(row[1])

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

        market_open_930 = ET.localize(
            datetime.combine(self.trade_date, datetime.min.time()).replace(hour=9, minute=30)
        )

        for c in candidates:
            sym = c['symbol']
            c['float_shares'] = fundamentals.get(sym, {}).get('float_shares')

            today_vol = today_vols.get(sym, 0)
            avg_vol = avg_vols.get(sym, 0)
            c['rel_vol'] = today_vol / avg_vol if avg_vol > 0 else 10.0

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
        filtered = []
        for c in candidates:
            if c.get('rel_vol', 0) < self.config.min_relative_volume:
                continue
            if self.config.require_news and not c.get('has_news', False):
                continue
            filtered.append(c)
        return filtered

    def _no_trade_result(self, candidate_count: int) -> dict:
        return {
            'traded': False,
            'trade': None,
            'pnl': 0.0,
            'candidate_count': candidate_count,
            'top_candidate': None,
        }


def run_vwap_date_range(
    config: VwapReclaimConfig,
    start_date: str,
    end_date: str,
    account_size: float = 5000.0,
    verbose: bool = True,
    print_dates: bool = False,
) -> dict:
    """
    Run the VWAP Reclaim strategy across a date range.
    Returns the same aggregated metrics dict format as run_scalp_date_range.
    """
    with StockDataDB() as db:
        trading_days = db.get_trading_days(start_date, end_date)

    if not trading_days:
        logger.warning(f"No trading days found between {start_date} and {end_date}")
        return _empty_result()

    trades: list[VwapTrade] = []
    daily_pnls: list[float] = []

    for trade_date in trading_days:
        runner = VwapSimulationRunner(trade_date, config, account_size, verbose=verbose)
        result = runner.run()

        if result['traded'] and result['trade']:
            trades.append(result['trade'])
            daily_pnls.append(result['pnl'])
        else:
            daily_pnls.append(0.0)

        if print_dates:
            status = f"${result['pnl']:+.2f}" if result['traded'] else "no trade"
            print(f"  {trade_date} | {status}")

    total_pnl = sum(t.pnl for t in trades)
    winners = [t for t in trades if t.pnl > 0]
    losers = [t for t in trades if t.pnl <= 0]
    win_rate = (len(winners) / len(trades) * 100) if trades else 0.0

    gross_profit = sum(t.pnl for t in winners)
    gross_loss = abs(sum(t.pnl for t in losers))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

    cum_pnl = peak = max_dd = 0.0
    for pnl in daily_pnls:
        cum_pnl += pnl
        peak = max(peak, cum_pnl)
        max_dd = max(max_dd, peak - cum_pnl)

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
        'days_traded': 0, 'total_trades': 0, 'winners': 0, 'losers': 0,
        'win_rate': 0.0, 'total_pnl': 0.0, 'avg_daily_pnl': 0.0,
        'max_drawdown': 0.0, 'profit_factor': 0.0, 'trades': [], 'daily_pnls': [],
    }


if __name__ == '__main__':
    import argparse
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    parser = argparse.ArgumentParser(description='VWAP Reclaim backtest')
    parser.add_argument('--start', required=True)
    parser.add_argument('--end', required=True)
    parser.add_argument('--account-size', type=float, default=5000.0)
    args = parser.parse_args()

    result = run_vwap_date_range(
        VwapReclaimConfig(), args.start, args.end,
        account_size=args.account_size, verbose=True, print_dates=True,
    )
    print()
    print("=" * 50)
    print(f"Trades: {result['total_trades']}  WR: {result['win_rate']:.1f}%  "
          f"P&L: ${result['total_pnl']:+,.2f}  PF: {result['profit_factor']:.2f}  "
          f"DD: ${result['max_drawdown']:.2f}")
