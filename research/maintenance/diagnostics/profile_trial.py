#!/usr/bin/env python3
"""
Profile a single simulation day to find the real CPU bottleneck.

Usage:
    python research/maintenance/diagnostics/profile_trial.py [--date 2025-01-08] [--top 30]
    python research/maintenance/diagnostics/profile_trial.py --best-trial  # use opt_5yr_v5 best params

Output: top N functions by cumulative CPU time.
Run from repo root.
"""

import sys, os, argparse, cProfile, pstats, io, warnings
sys.path.insert(0, os.path.abspath('production'))
sys.path.insert(0, os.path.abspath('research'))

from simulator.simulation_engine import SimulationRunner, load_memory_cache

CACHE_PATH = 'data/cache/memory_cache.pkl'
OPTUNA_STORAGE = 'postgresql://postgres:changeme123@localhost:5432/optuna'


def _build_config_from_best_trial(study_name: str = 'opt_5yr_v5'):
    """Load best trial params from Optuna and build a RunConfig."""
    warnings.filterwarnings('ignore')
    import optuna
    study = optuna.load_study(study_name=study_name, storage=OPTUNA_STORAGE)
    params = study.best_trial.params
    print(f'  Using best trial #{study.best_trial.number}  obj={study.best_trial.value:.4f}')

    # RunConfig.from_flat_dict expects a_/b_/c_ prefixed keys
    from optimizer.run_config import RunConfig
    try:
        cfg = RunConfig.from_flat_dict(params)
    except TypeError as e:
        # Some params may be unrecognised (e.g. new fields added after trial ran).
        # Build manually with only the known a_/b_/c_ fields.
        print(f'  Warning: from_flat_dict error ({e}) — filtering unknown fields')
        from production.trading.models import ScannerConfig, EntryConfig, ExitConfig
        from dataclasses import fields
        sc_keys = {f.name for f in fields(ScannerConfig)}
        ec_keys = {f.name for f in fields(EntryConfig)}
        xc_keys = {f.name for f in fields(ExitConfig)}
        scanner_fields = {k[2:]: v for k, v in params.items() if k.startswith('a_') and k[2:] in sc_keys}
        entry_fields   = {k[2:]: v for k, v in params.items() if k.startswith('b_') and k[2:] in ec_keys}
        exit_fields    = {k[2:]: v for k, v in params.items() if k.startswith('c_') and k[2:] in xc_keys}
        cfg = RunConfig(
            scanner=ScannerConfig(**scanner_fields),
            entry=EntryConfig(**entry_fields),
            exit_=ExitConfig(**exit_fields),
        )
    return cfg


def run_simulation(sim_date: str, cfg=None) -> None:
    if cfg is not None:
        runner = SimulationRunner(
            date=sim_date,
            account_size=5000,
            risk_pct=2.0,
            max_position_pct=20,
            verbose=False,
            debug=False,
            cache_data=True,
            enable_news_cache=False,
            scanner_config=cfg.scanner,
            entry_config=cfg.entry,
            exit_config=cfg.exit_,
        )
    else:
        runner = SimulationRunner(
            date=sim_date,
            account_size=5000,
            risk_pct=2.0,
            max_position_pct=20,
            verbose=False,
            debug=False,
            cache_data=True,
            enable_news_cache=False,
        )
    runner.run()


def main():
    parser = argparse.ArgumentParser(description='Profile a single sim day')
    parser.add_argument('--date', default='2025-01-08',
                        help='Date to profile (default: 2025-01-08, most active in cache)')
    parser.add_argument('--top', type=int, default=30,
                        help='Show top N functions (default: 30)')
    parser.add_argument('--output', default=None,
                        help='Optional: dump .prof file path (view with snakeviz)')
    parser.add_argument('--best-trial', action='store_true',
                        help='Use best trial params from opt_5yr_v5 (realistic load)')
    parser.add_argument('--study', default='opt_5yr_v5',
                        help='Optuna study name (default: opt_5yr_v5)')
    args = parser.parse_args()

    # Load cache into global (shares with SimulationRunner)
    n = load_memory_cache(CACHE_PATH)
    if n == 0:
        print(f'ERROR: No cache loaded from {CACHE_PATH}')
        sys.exit(1)
    print(f'Cache loaded: {n} days')

    cfg = None
    if args.best_trial:
        print(f'Loading best trial config from {args.study}...')
        cfg = _build_config_from_best_trial(args.study)

    print(f'Profiling: {args.date}  ({"best trial params" if cfg else "default params"})')
    print()

    # Run once without profiling to warm Python internals (JIT, import caches)
    print('Warm-up run...')
    run_simulation(args.date, cfg)
    print('Warm-up done. Running profiler...')
    print()

    # Profile the real run
    profiler = cProfile.Profile()
    profiler.enable()
    run_simulation(args.date, cfg)
    profiler.disable()

    if args.output:
        profiler.dump_stats(args.output)
        print(f'Raw profile saved to: {args.output}')
        print(f'  View with: snakeviz {args.output}')
        print()

    # ── Print sorted results ──────────────────────────────────────────────────
    stream = io.StringIO()

    print('=' * 80)
    print(f'TOP {args.top} FUNCTIONS BY CUMULATIVE TIME')
    print('=' * 80)
    ps = pstats.Stats(profiler, stream=stream).sort_stats('cumulative')
    ps.print_stats(args.top)
    print(stream.getvalue())

    stream2 = io.StringIO()
    print('=' * 80)
    print(f'TOP {args.top} FUNCTIONS BY TOTAL SELF TIME')
    print('=' * 80)
    ps2 = pstats.Stats(profiler, stream=stream2).sort_stats('tottime')
    ps2.print_stats(args.top)
    print(stream2.getvalue())

    # ── Summary: where time buckets fall ─────────────────────────────────────
    print('=' * 80)
    print('BUCKET SUMMARY (cumulative time in key modules)')
    print('=' * 80)
    buckets = {
        'patterns.py':        0.0,
        'entry_engine.py':    0.0,
        'exit_engine.py':     0.0,
        'orchestrator.py':    0.0,
        'indicators.py':      0.0,
        'momentum_scanner.py': 0.0,
        'simulation_engine.py': 0.0,
    }
    stats_dict = profiler.getstats()
    for stat in stats_dict:
        fn = stat.code.co_filename if hasattr(stat.code, 'co_filename') else ''
        for key in buckets:
            if key in fn:
                buckets[key] += stat.totaltime
    total = sum(buckets.values()) or 1.0
    for k, v in sorted(buckets.items(), key=lambda x: -x[1]):
        bar = '#' * int(v / total * 40)
        print(f'  {k:<25}  {v:6.2f}s  {v/total*100:5.1f}%  {bar}')


if __name__ == '__main__':
    main()
