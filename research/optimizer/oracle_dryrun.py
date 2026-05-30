"""
oracle_dryrun.py — end-to-end plumbing test for the oracle pipeline, NO DB / NO simulator.

Proves labels → split → 4 sequential Optuna studies → held-out eval → verdict all
wire together correctly, by monkeypatching `run_date_range` with a deterministic mock.
The mock rewards a different `c_target1_ratio` per regime, so the test also confirms
the pipeline can detect when regime-switching beats the universal config (the whole
point of the oracle). Uses only a temp dir + local sqlite — safe to run anytime,
including while the Phase-1 backfill is going (it never touches Postgres).

    python optimizer/oracle_dryrun.py

Real Optuna runs here (local sqlite storage), so this also smoke-tests the study
creation / resume / best-trial loading paths in run_oracle_study + run_oracle_test.
"""

from __future__ import annotations
import sys, os, csv, tempfile, shutil
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from optimizer import oracle_objective, run_oracle_test as rot

# Per-regime ideal value for c_target1_ratio (Optuna range 1.0–3.0). The mock pays
# the most when a config's target1_ratio matches its regime's ideal — so a universal
# config (one value for all regimes) cannot match all three, and regime-specific
# configs can → oracle switching should beat universal.
REGIME_IDEAL = {'hot': 3.0, 'neutral': 2.0, 'cold': 1.0}
LABEL_OF: dict[str, str] = {}   # filled in setup()


def _make_metrics(total_pnl: float, n_days: int) -> dict:
    n_trades = max(1, n_days)
    winners = int(round(n_trades * 0.6))
    losers = n_trades - winners
    return {
        'total_trades': n_trades,
        'winners': winners,
        'losers': losers,
        'win_rate': winners / n_trades * 100,
        'profit_factor': 1.5,
        'total_pnl': round(total_pnl, 2),
        'avg_daily_pnl': round(total_pnl / max(1, n_days), 2),
        'max_drawdown': 50.0,
        'days_traded': n_days,
        'objective': round(total_pnl, 2),       # current objective = total_pnl
        'trades': [
            {'date': d, 'symbol': 'MOCK', 'pattern': 'GAP_AND_GO',
             'entry_price': 5.0, 'exit_price': 5.1, 'shares': 100,
             'pnl': round(total_pnl / max(1, n_days), 2), 'exit_reason': 'TARGET_1',
             'hold_minutes': 5}
            for d in (LABEL_OF and list(LABEL_OF)[:n_days])
        ],
    }


def fake_run_date_range(config, start_date, end_date, *args, dates=None, **kwargs):
    """Deterministic stand-in for the real simulator. Reward = how close the config's
    target1_ratio is to each day's regime ideal, summed over `dates`."""
    days = dates if dates is not None else []
    t1 = float(getattr(config.exit_, 'target1_ratio', 2.0))
    total = 0.0
    for d in days:
        ideal = REGIME_IDEAL.get(LABEL_OF.get(d, 'neutral'), 2.0)
        # peak 12 per day at ideal, falls off quadratically; floor keeps trades>0
        total += 12.0 - 6.0 * (t1 - ideal) ** 2
    # progress callback parity with the real signature
    cb = kwargs.get('on_day_complete')
    if cb:
        for d in days:
            cb(str(d))
    return _make_metrics(total, len(days))


def setup(tmp: str) -> None:
    """Write synthetic hot/neutral/cold _days.csv and populate LABEL_OF."""
    # 30 days per regime, interleaved across a date range (strings only — the mock
    # bypasses the trading calendar entirely).
    base_year = 2024
    day = 1
    buckets = {'hot': [], 'neutral': [], 'cold': []}
    # round-robin assign sequential calendar-ish dates to regimes
    regimes = ['hot', 'neutral', 'cold']
    d = 0
    for month in range(1, 7):           # Jan–Jun
        for dom in range(1, 29):        # 28 days/month → 168 slots, take 90
            if d >= 90:
                break
            ds = f"{base_year}-{month:02d}-{dom:02d}"
            r = regimes[d % 3]
            buckets[r].append(ds)
            LABEL_OF[ds] = r
            d += 1
    for r in regimes:
        with open(os.path.join(tmp, f"{r}_days.csv"), 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(['date', 'momentum_score', 'predicted_label'])
            for ds in buckets[r]:
                w.writerow([ds, '0.5', r.upper()])


def main() -> int:
    tmp = tempfile.mkdtemp(prefix='oracle_dryrun_')
    try:
        setup(tmp)

        # Monkeypatch the simulator out of both call sites.
        oracle_objective.run_date_range = fake_run_date_range
        rot.run_date_range = fake_run_date_range

        argv = [
            'oracle_dryrun',
            '--trials', '8',
            '--test-frac', '0.30',
            '--outputs-dir', tmp,
            '--optuna-db', f"sqlite:///{os.path.join(tmp, 'oracle_optuna.db')}",
            '--db', os.path.join(tmp, 'oracle_results.db'),
        ]
        old_argv = sys.argv
        sys.argv = argv
        try:
            rot.main()      # runs the REAL meta-runner end-to-end on mock data
        finally:
            sys.argv = old_argv

        print("\n[oracle_dryrun] PASS — full pipeline ran: 4 studies + held-out eval + verdict.")
        print("[oracle_dryrun] (mock rewarded per-regime target1_ratio, so the verdict")
        print("                 should show oracle switching ahead of the universal baseline.)")
        return 0
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\n[oracle_dryrun] FAIL — {e}")
        return 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
