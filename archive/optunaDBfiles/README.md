# Optuna Optimization Results Archive

This folder contains SQLite databases from parameter optimization runs. They are NOT needed for live trading, but kept as historical reference for understanding which parameter combinations were tested and their results.

## Database Files

| File | Size | Purpose | Run Details |
|------|------|---------|-------------|
| `pillar23_results.db` | 44M | **ACTIVE** — Main optimization results from pillar23_v2 run | 249 trials, best config is Trial 193: `micro_pullback + dip_buy + flat_top` |
| `pillar23_optuna.db` | 1.4M | Optuna trial metadata for pillar23_v2 | Trial records, params, scores (backup of results) |
| `pillar23_numeric.db` | 704K | Numeric fine-tuning confirmation | 199 additional trials after pillar23_v2 (confirmed no better config exists) |
| `robust_results.db` | 3.3M | Older full-year optimization | Results from robust_fullyear run (Jan 2026 window, superseded by pillar23) |
| `robust_optuna.db` | 1.3M | Optuna metadata from robust run | Supplementary trial data |
| `optuna.db` | 3.8M | Early experimentation | From debug/fast50 run (historical reference) |
| `results.db` | 7.4M | Early results database | From Jan 2026 window run (superseded) |
| `meta_optuna.db` | 168K | Meta-optimizer trials | Experimental meta-parameter tuning |
| `meta_results.db` | 72K | Meta-optimizer results | Supplementary meta-optimization data |
| `results_feb2025.db` | 212K | Feb 2025 parameter sweeps | Very early param sweep results |
| `results_mar2025.db` | 212K | Mar 2025 parameter sweeps | Very early param sweep results |

## How to Use

### If you need to check a trial result:
```bash
# Query the best config (Trial 193)
sqlite3 pillar23_results.db "SELECT * FROM runs WHERE run_id LIKE '%00193%';"

# View all trials
sqlite3 pillar23_results.db "SELECT run_id, total_pnl, win_rate, objective FROM runs ORDER BY objective DESC;"

# View trades from Trial 193
sqlite3 pillar23_results.db "SELECT * FROM trades WHERE run_id LIKE '%00193%' LIMIT 10;"
```

### If you want to re-optimize:
1. Run `python research/optimizer/optuna_run.py` with new date ranges
2. It will create a NEW results.db with fresh trials
3. Keep this archive as historical reference

## Can You Delete These?

**Short answer**: Not yet.

**Technically**: Yes, you can regenerate them by re-running Optuna optimization (takes days). The raw stock data is in TimescaleDB.

**Practically**: Keep them for:
- Checking what was tested before (avoid re-testing)
- Understanding trial history
- Reference if you need to compare against old runs
- Safety net in case future optimization goes wrong

**When to delete**: Once you're fully confident in your current trading config and have several months of live trading data, you can safely delete these.

## Notes

- These files are in `.gitignore` (not pushed to GitHub)
- They're kept locally as a safety/reference net
- Total size: ~62MB (can be zipped if needed)
- Last updated: March 3, 2026
