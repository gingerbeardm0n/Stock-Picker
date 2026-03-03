"""
sweep.py — One-at-a-time (OAT) sensitivity analysis.

For each parameter, sweeps a range of values while holding all others at
their strategy defaults. Writes every run to the results SQLite DB.

Purpose: quickly identify which ~15 params actually drive results before
spending hours on Optuna. Flat params (no effect on objective) can be
excluded from the Optuna search space to speed up convergence.

Run time: ~90 min for 18 params × 5 values ≈ 90 runs on a 14-day date range.
         With --workers 6: ~15-20 min for the same 90 runs.
         Scale linearly with date range length.

Usage:
    python optimizer/sweep.py --start 2025-01-13 --end 2025-01-31
    python optimizer/sweep.py --start 2025-01-13 --end 2025-01-31 --workers 6
    python optimizer/sweep.py --start 2025-01-13 --end 2025-01-31 --workers 6 --resume
    python optimizer/sweep.py --start 2025-01-02 --end 2025-09-30 --db results_train.db

Parallelism notes:
    - Each worker runs a full date-range simulation in a separate process (bypasses GIL).
    - TimescaleDB handles concurrent reads natively (PostgreSQL MVCC).
    - SQLite writes happen only in the main process — no write contention.
    - Recommended: --workers 6 on an 8-core machine (leaves headroom for OS/Docker).
    - Docker container needs --shm-size 256m for 6 workers (default 64m is too small).
"""

from __future__ import annotations
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import argparse
import multiprocessing
import textwrap
import threading
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime

from optimizer.run_config import RunConfig
from optimizer.results_db import init_db, write_run, run_exists
from optimizer.simulate_one import run_date_range
from utils.trading_calendar import get_trading_days

try:
    from tqdm import tqdm as _tqdm
    _HAS_TQDM = True
except ImportError:
    _HAS_TQDM = False

# ── Sweep parameter definitions ───────────────────────────────────────────────
# Format: (category_attr, field_name, [values_to_try])
# category_attr: 'scanner', 'entry', or 'exit_'
# Values should bracket the default with sensible variation.
# Include the default in the list so the default run is always captured.

SWEEP_PARAMS = [
    # ── Category A: Scanner / 5-Pillar thresholds ─────────────────────────
    # All 4 numeric pillars. Pillar 5 (news) is not numeric — skip.
    ('scanner', 'min_relative_volume', [2.0, 3.0, 5.0, 7.0, 10.0, 15.0]),
    ('scanner', 'min_premarket_gain',  [5.0, 7.5, 10.0, 15.0, 20.0]),
    ('scanner', 'min_buying_volume',   [10_000, 25_000, 50_000, 75_000, 100_000]),
    ('scanner', 'max_float',           [5_000_000, 10_000_000, 15_000_000, 20_000_000, 30_000_000]),

    # ── Category C: Exit thresholds ────────────────────────────────────────
    # Selection rationale: all 7 currently-active params. Phase 3/4 features
    # (MACD flip, resistance exit, volume dry-up) are disabled via booleans —
    # sweeping their sub-params would have no effect, so they are excluded.
    # trailing_stop_distance is 0.0 (disabled) — let Optuna explore it later.
    ('exit_', 'target1_ratio',          [1.5, 1.8, 2.0, 2.5, 3.0]),
    ('exit_', 'target2_ratio',          [2.0, 2.5, 3.0, 4.0, 5.0]),
    ('exit_', 'target1_qty_pct',        [0.25, 0.40, 0.50, 0.60, 0.75]),
    ('exit_', 'target2_qty_pct',        [0.10, 0.20, 0.25, 0.35, 0.50]),
    ('exit_', 'time_decay_hour',        [10, 11, 12, 13]),
    ('exit_', 'selling_pressure_ratio', [1.5, 1.8, 2.0, 2.5, 3.0, 4.0]),
    ('exit_', 'selling_pressure_qty_pct', [0.25, 0.40, 0.50, 0.65, 0.80]),

    # ── Category B: Pattern detection thresholds ───────────────────────────
    # Selection rationale: 2 global gates (affect every entry) + 1 "champion"
    # param per pattern (the threshold most likely to drive whether the pattern
    # fires at all). Secondary thresholds within each pattern are left to Optuna.
    #
    # Global gates:
    ('entry', 'min_rr_ratio',           [1.5, 2.0, 2.5, 3.0]),      # default 2.0
    ('entry', 'stop_buffer',            [0.01, 0.02, 0.03, 0.05, 0.08]),  # default 0.02
    # Champion per pattern:
    ('entry', 'bull_flag_light_vol',    [0.50, 0.60, 0.70, 0.80, 0.90]),  # default 0.70
    ('entry', 'micro_pb_green_pct',     [0.40, 0.50, 0.60, 0.70, 0.80]),  # default 0.60
    ('entry', 'abcd_min_pullback_pct',  [0.05, 0.10, 0.15, 0.20, 0.30]),  # default 0.15
    ('entry', 'dip_buy_light_vol',      [0.40, 0.50, 0.65, 0.75, 0.90]),  # default 0.65
    ('entry', 'flat_top_resistance_tol', [0.02, 0.03, 0.05, 0.08]),       # default 0.03
]


# ── Worker setup ──────────────────────────────────────────────────────────────
# _day_counter is a multiprocessing.Value shared across all worker processes.
# Each worker increments it once per simulation day completed. The main process
# reads it every 300ms to drive the progress bar — near-zero overhead.

_day_counter = None  # set in each worker process by _init_worker


def _init_worker(counter):
    """Called once in each worker process at startup to install the shared counter."""
    global _day_counter
    _day_counter = counter


def _run_one_job(job: tuple) -> dict:
    """
    Run a single sweep configuration. Executes in a worker process.

    Returns a dict with metrics, trades, and metadata — the main process
    handles all SQLite writes so there is no DB contention.
    """
    # Silence INFO-level logging from simulation_engine (bar-load messages,
    # SIMULATION headers, etc.) so worker output doesn't interleave with the
    # main process progress lines.
    import logging
    logging.getLogger().setLevel(logging.WARNING)

    run_id, category, field_name, val, start_date, end_date = job

    cfg = RunConfig.defaults()
    setattr(getattr(cfg, category), field_name, val)

    def _tick():
        """Increment the shared day counter — called after each simulated day."""
        if _day_counter is not None:
            with _day_counter.get_lock():
                _day_counter.value += 1

    t0 = time.perf_counter()
    result = run_date_range(cfg, start_date, end_date, verbose=False, on_day_complete=_tick)
    elapsed = time.perf_counter() - t0

    trades = result.pop('trades')  # separate out before returning

    return {
        'run_id':     run_id,
        'category':   category,
        'field_name': field_name,
        'val':        val,
        'metrics':    result,
        'trades':     trades,
        'params':     cfg.to_flat_dict(),
        'elapsed':    elapsed,
    }


# ── Main sweep ────────────────────────────────────────────────────────────────

def sweep(
    start_date: str,
    end_date: str,
    db_path: str | None = None,
    resume: bool = False,
    workers: int = 1,
) -> None:
    """
    Run the OAT sensitivity sweep.

    Args:
        start_date : Simulation start (YYYY-MM-DD)
        end_date   : Simulation end   (YYYY-MM-DD)
        db_path    : SQLite path (default: optimizer/results.db)
        resume     : If True, skip run_ids already in the DB
        workers    : Number of parallel worker processes (1 = sequential)
    """
    conn = init_db(db_path)
    total_runs = sum(len(vals) for _, _, vals in SWEEP_PARAMS)

    # Build work list — skip already-done runs if resuming
    jobs = []
    skipped = 0
    for category, field_name, values in SWEEP_PARAMS:
        for i, val in enumerate(values):
            run_id = f"sweep__{category}__{field_name}__{i:02d}"
            if resume and run_exists(conn, run_id):
                skipped += 1
                continue
            jobs.append((run_id, category, field_name, val, start_date, end_date))

    # Calculate total simulation-days for the progress bar
    _start = datetime.strptime(start_date, '%Y-%m-%d').date()
    _end   = datetime.strptime(end_date,   '%Y-%m-%d').date()
    days_per_job    = len(get_trading_days(_start, _end))
    total_sim_days  = days_per_job * len(jobs)

    print(f"\nSensitivity sweep: {len(SWEEP_PARAMS)} params, {total_runs} total runs")
    print(f"Date range : {start_date} → {end_date}  ({days_per_job} trading days/job)")
    print(f"Workers    : {workers} {'(parallel)' if workers > 1 else '(sequential)'}")
    print(f"DB         : {db_path or 'optimizer/results.db'}")
    if skipped:
        print(f"Skipped    : {skipped} already-completed runs (--resume)")
    print(f"To run     : {len(jobs)} jobs  ({total_sim_days:,} total sim-days)")
    print()

    if not jobs:
        print("Nothing to do — all runs already in DB.")
        conn.close()
        return

    done = skipped
    errors = 0
    wall_start = time.perf_counter()

    if workers == 1:
        # Sequential path — easier to debug, same logic
        pbar = _make_pbar(total_sim_days)
        counter = None  # no shared counter needed; we update pbar directly

        def _tick_sequential():
            if pbar:
                pbar.update(1)

        for job in jobs:
            # Patch the global so _run_one_job can call it inline
            # (sequential mode: we're in the same process, so set global directly)
            global _day_counter
            _day_counter = None  # unused — we use the closure below

            run_id, category, field_name, val, sd, ed = job
            cfg = RunConfig.defaults()
            setattr(getattr(cfg, category), field_name, val)
            t0 = time.perf_counter()
            result = run_date_range(cfg, sd, ed, verbose=False, on_day_complete=_tick_sequential)
            elapsed = time.perf_counter() - t0
            trades = result.pop('trades')
            r = {
                'run_id': run_id, 'category': category, 'field_name': field_name,
                'val': val, 'metrics': result, 'trades': trades,
                'params': cfg.to_flat_dict(), 'elapsed': elapsed,
            }
            done += 1
            _save_and_print(conn, r, done, total_runs, start_date, end_date,
                            write_fn=_tqdm.write if pbar else print)

        if pbar:
            pbar.close()

    else:
        # Parallel path — workers run simulations; main process writes SQLite.
        # No new terminal windows — workers are invisible background processes.
        # Results print as each job completes (order is not guaranteed).
        print(f"Submitting {len(jobs)} jobs to {workers} workers ...")
        print(f"A progress bar will appear once workers start. Results print as each job finishes.\n")

        counter    = multiprocessing.Value('i', 0)
        pbar       = _make_pbar(total_sim_days)
        stop_event = threading.Event()

        def _pbar_updater():
            """Background thread: reads shared counter and pushes updates to tqdm."""
            last = 0
            while not stop_event.is_set():
                current = counter.value
                if pbar and current > last:
                    pbar.update(current - last)
                    last = current
                time.sleep(0.3)

        pbar_thread = threading.Thread(target=_pbar_updater, daemon=True)
        pbar_thread.start()

        write_fn = _tqdm.write if pbar else print

        with ProcessPoolExecutor(
            max_workers=workers,
            initializer=_init_worker,
            initargs=(counter,),
        ) as executor:
            future_to_job = {executor.submit(_run_one_job, job): job for job in jobs}
            write_fn(f"  All {len(future_to_job)} jobs queued. Results will print as each completes ...\n")

            for future in as_completed(future_to_job):
                job = future_to_job[future]
                try:
                    r = future.result()
                    done += 1
                    _save_and_print(conn, r, done, total_runs, start_date, end_date,
                                    write_fn=write_fn)
                except Exception as exc:
                    errors += 1
                    write_fn(f"\n  !! ERROR in job [{job[0]}]")
                    write_fn(f"     param : {job[1]}.{job[2]} = {job[3]}")
                    write_fn(f"     reason: {exc}")
                    write_fn(f"     traceback:\n{textwrap.indent(traceback.format_exc(), '       ')}")
                    write_fn("")

        # Drain the progress bar to 100% and shut down the updater thread
        stop_event.set()
        pbar_thread.join(timeout=1)
        if pbar:
            pbar.update(counter.value - pbar.n)
            pbar.close()

    wall_elapsed = time.perf_counter() - wall_start
    succeeded = done - skipped
    print(f"\n{'='*60}")
    print(f"Sweep complete in {wall_elapsed/60:.1f} min")
    print(f"  Succeeded : {succeeded}")
    if errors:
        print(f"  Errors    : {errors}  ← check messages above")
    if skipped:
        print(f"  Skipped   : {skipped} (already in DB)")
    print(f"  DB        : {db_path or 'optimizer/results.db'}")
    print(f"{'='*60}")
    print("\nAnalyse with:")
    print("  python optimizer/analyze.py summary")
    print("  python optimizer/analyze.py param-sensitivity --param a_min_relative_volume")
    conn.close()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_pbar(total_days: int):
    """Create a tqdm progress bar if tqdm is available, otherwise return None."""
    if not _HAS_TQDM or total_days == 0:
        return None
    return _tqdm(
        total=total_days,
        desc='Days',
        unit='day',
        dynamic_ncols=True,
        bar_format=(
            '{desc}: {percentage:5.1f}%|{bar}| '
            '{n:,}/{total:,} days '
            '[{elapsed}<{remaining}, {rate_fmt}]'
        ),
    )


def _save_and_print(
    conn,
    r: dict,
    done: int,
    total: int,
    start_date: str,
    end_date: str,
    write_fn=print,
) -> None:
    """Write one result to SQLite and print a progress line."""
    write_run(conn, r['run_id'], start_date, end_date,
              r['metrics'], r['params'], r['trades'])

    label = f"[{done}/{total}] {r['category']}.{r['field_name']}={r['val']}"
    m = r['metrics']
    write_fn(
        f"{label:<55}"
        f" PF={m['profit_factor']:.2f}"
        f"  trades={m['total_trades']:3d}"
        f"  pnl=${m['total_pnl']:+7.0f}"
        f"  obj={m['objective']:+.3f}"
        f"  ({r['elapsed']:.0f}s)"
    )


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='OAT sensitivity sweep')
    parser.add_argument('--start',   required=True, help='Start date YYYY-MM-DD')
    parser.add_argument('--end',     required=True, help='End date   YYYY-MM-DD')
    parser.add_argument('--db',      default=None,  help='SQLite DB path (default: optimizer/results.db)')
    parser.add_argument('--resume',  action='store_true',
                        help='Skip run_ids already in the DB (safe to re-run after interruption)')
    parser.add_argument('--workers', type=int, default=1,
                        help='Parallel worker processes (default: 1). '
                             'Recommended: 6 on an 8-core machine.')
    args = parser.parse_args()
    sweep(args.start, args.end, args.db, args.resume, args.workers)
