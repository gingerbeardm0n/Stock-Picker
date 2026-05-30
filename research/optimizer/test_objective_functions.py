"""
test_objective_functions.py — demonstrate how the candidate objective formulas
rank synthetic strategy regimes differently. Plain-assert script (no pytest dep):

    python optimizer/test_objective_functions.py

The fixtures encode the core debate:
  - tiny_win      : many small wins + few big losses. Low payoff (~0.1), fragile,
                    but a respectable RAW total_pnl. THE DISEASE.
  - fat_fragile   : profitable ONLY because of one monster day; otherwise bleeds.
                    High per-trade payoff but a single day carries it. Should score LOW.
  - fat_distributed: a genuinely good fat-tail — high payoff spread across many days,
                    no single dominant day. The regime we WANT the optimizer to pick.
"""

from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from optimizer.objective_functions import (
    compute_objective, payoff_ratio, ObjectiveParams,
    green_day_rate, worst_fold_objective,
)


def _fixture(trade_pnls, daily_pnls, max_drawdown):
    return {
        'total_pnl': round(sum(trade_pnls), 2),
        'max_drawdown': max_drawdown,
        'trade_pnls': trade_pnls,
        'daily_pnls': daily_pnls,
    }


# ── Fixtures ──────────────────────────────────────────────────────────────────
# tiny_win: 80 wins @ +$10, 7 losses @ -$95  -> total +$135, payoff ~0.105
TINY = _fixture(
    trade_pnls=[10.0] * 80 + [-95.0] * 7,
    daily_pnls=[15, 20, 50, 10, 5, 25, 10],          # best day +50 (modest)
    max_drawdown=200.0,
)
# fat_fragile: one +$300 day, otherwise loses. Low raw total but a single day made it.
FAT_FRAGILE = _fixture(
    trade_pnls=[300.0] + [20.0] * 7 + [-10.0] * 38,  # +440 wins, -380 losses -> +60
    daily_pnls=[320, -30, -40, -50, -40, -30, 10],   # best day +320 dominates
    max_drawdown=300.0,
)
# fat_distributed: high payoff spread across days, no single dominant day. total +$300.
FAT_DIST = _fixture(
    trade_pnls=[30.0] * 20 + [-10.0] * 30,           # +600 wins, -300 losses -> +300
    daily_pnls=[60, 55, 40, 45, 50, 30, 20],         # best day +60 of +300 total (20%)
    max_drawdown=80.0,
)


def _obj(formula, fx, **kw):
    return compute_objective(
        formula=formula,
        total_pnl=fx['total_pnl'],
        max_drawdown=fx['max_drawdown'],
        trade_pnls=fx['trade_pnls'],
        daily_pnls=fx['daily_pnls'],
        **kw,
    )


def main():
    p = ObjectiveParams()
    print(f"params: dd_penalty={p.dd_penalty} min_trades={p.min_trades} "
          f"target_payoff={p.target_payoff} concentration_cap={p.concentration_cap}\n")

    rows = [('tiny_win', TINY), ('fat_fragile', FAT_FRAGILE), ('fat_distributed', FAT_DIST)]
    print(f"{'regime':<16}{'raw_total':>10}{'payoff':>8} | "
          f"{'total_pnl':>10}{'drop_best':>11}{'payoff_r':>10}{'hybrid':>9}")
    print('-' * 86)
    vals = {}
    for name, fx in rows:
        v = {f: _obj(f, fx) for f in ('total_pnl', 'drop_best_day', 'payoff_ratio', 'hybrid')}
        vals[name] = v
        print(f"{name:<16}{fx['total_pnl']:>10.0f}{payoff_ratio(fx['trade_pnls']):>8.2f} | "
              f"{v['total_pnl']:>10.0f}{v['drop_best_day']:>11.0f}"
              f"{v['payoff_ratio']:>10.0f}{v['hybrid']:>9.0f}")
    print()

    checks = []
    def check(desc, cond):
        checks.append((desc, cond))
        print(f"  [{'PASS' if cond else 'FAIL'}] {desc}")

    # A. THE DISEASE: raw total_pnl prefers the fragile tiny-win over the genuinely
    #    better-quality fat_fragile (lower raw $ despite far higher payoff).
    check("raw total_pnl ranks tiny_win > fat_fragile (disease reproduced)",
          vals['tiny_win']['total_pnl'] > vals['fat_fragile']['total_pnl'])

    # B. THE FIX: payoff_ratio rewards a genuine distributed fat-tail over tiny-win.
    check("payoff_ratio ranks fat_distributed > tiny_win (fix rewards real tail)",
          vals['fat_distributed']['payoff_ratio'] > vals['tiny_win']['payoff_ratio'])

    # C. THE CRITIQUE: drop_best_day under-credits a DISTRIBUTED tail vs payoff_ratio
    #    (it strips a good day that wasn't carrying the result).
    check("drop_best_day under-credits fat_distributed vs payoff_ratio",
          vals['fat_distributed']['drop_best_day'] < vals['fat_distributed']['payoff_ratio'])

    # D. HYBRID: keeps the distributed tail but punishes the fragile one-day-wonder.
    check("hybrid ranks fat_distributed >> fat_fragile (concentration guard works)",
          vals['fat_distributed']['hybrid'] > vals['fat_fragile']['hybrid'])

    # E. status quo passthrough
    check("formula='total_pnl' returns raw total unchanged",
          _obj('total_pnl', FAT_DIST) == FAT_DIST['total_pnl'])

    # F. small-sample shrink
    small = _fixture([20.0] * 10, [40, 30, 20], 50.0)   # 10 trades < min_trades 30
    full  = _fixture([20.0] * 60, [40, 30, 20], 50.0)   # 60 trades >= 30
    so = _obj('payoff_ratio', small)
    fo = compute_objective(formula='payoff_ratio', total_pnl=full['total_pnl'],
                           max_drawdown=full['max_drawdown'], trade_pnls=full['trade_pnls'],
                           daily_pnls=full['daily_pnls'])
    check("small-sample (<min_trades) objective shrunk vs full-sample per-$",
          (so / small['total_pnl']) < (fo / full['total_pnl']))

    # G. per-regime min_trades override lifts the shrink for thin oracle regimes
    so_override = _obj('payoff_ratio', small, min_trades_override=10)
    check("min_trades_override removes the thin-regime shrink",
          so_override > so)

    # ── Consistency formula: same total/payoff, more green days = higher score ──
    same_trades = [30.0] * 20 + [-10.0] * 30          # total +300, payoff 3.0
    steady = {'total_pnl': 300.0, 'max_drawdown': 40.0, 'trade_pnls': same_trades,
              'daily_pnls': [40, 40, 40, 40, 40, 50, 50]}          # green_rate 1.0
    lumpy  = {'total_pnl': 300.0, 'max_drawdown': 40.0, 'trade_pnls': same_trades,
              'daily_pnls': [300, -20, -20, -20, 40, 30, -10]}      # green_rate ~0.57
    print(f"\n  green_rate steady={green_day_rate(steady['daily_pnls']):.2f} "
          f"lumpy={green_day_rate(lumpy['daily_pnls']):.2f}")
    check("consistency ranks steady > lumpy at equal total/payoff/dd",
          _obj('consistency', steady) > _obj('consistency', lumpy))

    # H. worst-fold: a config that blows up in one fold scores below a steady one
    consistent_folds = [
        {'total_pnl': 100, 'max_drawdown': 30, 'trade_pnls': [20]*8 + [-10]*6,
         'daily_pnls': [25, 20, 30, 25]},
        {'total_pnl': 90,  'max_drawdown': 35, 'trade_pnls': [18]*8 + [-10]*6,
         'daily_pnls': [20, 25, 20, 25]},
        {'total_pnl': 110, 'max_drawdown': 25, 'trade_pnls': [22]*8 + [-10]*6,
         'daily_pnls': [30, 25, 30, 25]},
    ]
    overfit_folds = [
        {'total_pnl': 400, 'max_drawdown': 30, 'trade_pnls': [50]*8 + [-10]*6,
         'daily_pnls': [120, 100, 90, 90]},                 # great fold
        {'total_pnl': 90,  'max_drawdown': 35, 'trade_pnls': [18]*8 + [-10]*6,
         'daily_pnls': [20, 25, 20, 25]},
        {'total_pnl': -200, 'max_drawdown': 260, 'trade_pnls': [10]*3 + [-30]*9,
         'daily_pnls': [-60, -50, -40, -50]},               # blows up here
    ]
    wf_consistent = worst_fold_objective(consistent_folds, formula='consistency',
                                         min_trades_override=10)
    wf_overfit    = worst_fold_objective(overfit_folds, formula='consistency',
                                         min_trades_override=10)
    print(f"  worst_fold consistent={wf_consistent:.0f} overfit={wf_overfit:.0f}")
    check("worst-fold ranks consistent > one-fold-wonder (anti-overfit)",
          wf_consistent > wf_overfit)

    n_fail = sum(1 for _, c in checks if not c)
    print(f"\n{'ALL PASS' if n_fail == 0 else f'{n_fail} FAILED'} "
          f"({len(checks) - n_fail}/{len(checks)})")
    return 1 if n_fail else 0


if __name__ == '__main__':
    sys.exit(main())
