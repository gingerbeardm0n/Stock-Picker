"""Issue #23 backtest: does excluding rel_vol=10.0 fallback symbols change results?

The sim assigns rel_vol=10.0 when a symbol has NO 30-day baseline in
rel_vol_cum_cache (scalp_simulation.py _enrich_candidates) — the same fallback
the live runner uses when Tradier returns zero premarket prints. This ablation
re-runs the deployed Trial 211 config with those symbols EXCLUDED (rel_vol=0.0
→ fails the min_relative_volume gate) and compares against the baseline.

Usage:
    python relvol_fallback_ablation.py 2025-01-01 2025-12-31
"""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'production')))

import logging
logging.basicConfig(level=logging.WARNING)

from simulator.scalp_simulation import ScalpSimulationRunner, run_scalp_date_range_multi
from trading.live_scalp_runner import TRIAL_211_CONFIG

MINUTE_925 = 9 * 60 + 25

_original_enrich = ScalpSimulationRunner._enrich_candidates
_ablation_stats = {'fallback_candidates': 0, 'days_with_fallback': set()}


def _enrich_exclude_fallback(self, db, candidates):
    """Baseline enrich, then exclude symbols with no rel-vol baseline.

    A candidate got the 10.0 fallback iff it has no 30-day average in
    rel_vol_cum_cache (avg_vol missing/0). Re-derive that set exactly and
    zero those candidates out so the min_relative_volume gate drops them.
    """
    candidates = _original_enrich(self, db, candidates)
    symbols = [c['symbol'] for c in candidates]
    if not symbols:
        return candidates

    cursor = db.conn.cursor()
    cursor.execute("""
        SELECT symbol FROM rel_vol_cum_cache
        WHERE trade_date < %s
          AND trade_date >= %s::date - interval '30 days'
          AND minute_of_day = %s
          AND symbol = ANY(%s)
        GROUP BY symbol
        HAVING AVG(cum_total) > 0
    """, [self.trade_date, self.trade_date, MINUTE_925, symbols])
    has_baseline = {row[0] for row in cursor.fetchall()}
    cursor.close()

    for c in candidates:
        if c['symbol'] not in has_baseline:
            c['rel_vol'] = 0.0
            _ablation_stats['fallback_candidates'] += 1
            _ablation_stats['days_with_fallback'].add(str(self.trade_date))
    return candidates


def summarize(tag, r):
    print(f"{tag:>22} | trades={r['total_trades']:>4} WR={r['win_rate']:5.1f}% "
          f"pnl=${r['total_pnl']:>+10.2f} PF={r['profit_factor']:5.2f} "
          f"maxDD=${r['max_drawdown']:>8.2f} days={r['days_traded']}")


def trade_key(t):
    return (str(t.date), t.symbol)


def main():
    start, end = sys.argv[1], sys.argv[2]
    cfg = TRIAL_211_CONFIG
    print(f"\nIssue #23 ablation | Trial 211 (deployed) | {start} -> {end}")
    print(f"config: gap>={cfg.min_gap_pct}% rv>={cfg.min_relative_volume}x "
          f"float<={cfg.max_float/1e6:.0f}M price<={cfg.max_price} "
          f"news={cfg.require_news} mode={cfg.entry_mode}")
    print("=" * 100)

    print("\n[1/2] BASELINE (fallback -> 10.0, current behavior)...")
    base = run_scalp_date_range_multi(cfg, start, end, verbose=False)

    print("[2/2] VARIANT (fallback -> excluded)...")
    ScalpSimulationRunner._enrich_candidates = _enrich_exclude_fallback
    try:
        var = run_scalp_date_range_multi(cfg, start, end, verbose=False)
    finally:
        ScalpSimulationRunner._enrich_candidates = _original_enrich

    print()
    summarize('BASELINE (10.0)', base)
    summarize('VARIANT (excluded)', var)

    print(f"\nFallback candidates zeroed: {_ablation_stats['fallback_candidates']} "
          f"across {len(_ablation_stats['days_with_fallback'])} days")

    base_keys = {trade_key(t): t for t in base['trades']}
    var_keys = {trade_key(t): t for t in var['trades']}
    gone = [base_keys[k] for k in base_keys.keys() - var_keys.keys()]
    new = [var_keys[k] for k in var_keys.keys() - base_keys.keys()]

    if gone:
        print(f"\nTrades REMOVED by the filter ({len(gone)}):")
        for t in sorted(gone, key=lambda t: str(t.date)):
            print(f"  {t.date} {t.symbol:6} pnl=${t.pnl:+9.2f} rv={t.rel_vol:.1f}x")
        removed_pnl = sum(t.pnl for t in gone)
        print(f"  removed P&L total: ${removed_pnl:+.2f}")
    else:
        print("\nNo trades removed.")

    if new:
        print(f"\nTrades ADDED by the filter (slot freed for next-ranked) ({len(new)}):")
        for t in sorted(new, key=lambda t: str(t.date)):
            print(f"  {t.date} {t.symbol:6} pnl=${t.pnl:+9.2f} rv={t.rel_vol:.1f}x")
        print(f"  added P&L total: ${sum(t.pnl for t in new):+.2f}")

    delta = var['total_pnl'] - base['total_pnl']
    print(f"\nNET EFFECT: ${delta:+.2f} "
          f"({var['total_trades'] - base['total_trades']:+d} trades, "
          f"PF {base['profit_factor']:.2f} -> {var['profit_factor']:.2f})")


if __name__ == '__main__':
    main()
