# Sim / Live Parity Ledger

Canonical list of every known divergence between the **simulators** and the **live
runners** for the two standalone strategies (Opening Bell Scalp, VWAP Reclaim).
The backtested edge is only real live if the live runner makes the *same decisions*
on the *same inputs*. This file is the single place that truth is tracked.

**Status key:** ✅ fixed · 🟡 open (logic) · ⚪ inherent (cross-vendor / live-timing,
can't be fully closed) · 📌 known override (intentional, must revert before live money)
· 🔴 suspended

Last audited: **2026-07-10** (updated for #14 findings + off-by-one fix).

---

## Architecture note (why most things CAN'T drift)

Entry/exit math lives in shared pure functions — `scalp_engine.py`,
`vwap_engine.py` — called by **both** the sim and the live runner. So stop /
target / trailing / time-stop / VWAP-reclaim logic cannot diverge by
construction. **Every gap below is in the data-feeding or filter layer** around
those engines, which is duplicated per side.

---

## Ledger

| # | Area | Strategy | Status | Summary |
|---|------|----------|--------|---------|
| 1 | News gate | both | ✅ `4ae4cf7` + `c766488` | Unified via `has_news_catalyst()`. Scalp: `require_news=False` (issue #14 proved price/volume edge real without news). VWAP: suspended. |
| 2 | Float filter | scalp | ✅ `4ae4cf7` | Live had `float_shares=None` (gate never ran); sim filters on `stock_fundamentals`. Export now ships a `floats` map; live scalp applies the same `max_float` gate. |
| 3 | Rel-vol numerator timing | vwap | 🔴 suspended | Live divided by instantaneous quote volume at its ~9:45 scan; baseline denominator is cumulative-through-9:25. Now reconstructs cumulative-through-9:25 from session bars. VWAP suspended (issue #14). |
| 4 | `bars_since_open` off-by-one | scalp | ✅ `f99771b` | Fixed Jul 9. Live passed `n` (1-based) to `evaluate_entry`; sim passes 0-based `enumerate()` index. Now live passes `n - 1`. Validating: 3 clean live days (day 0/3 as of Jul 10). |
| 5 | Account balance / sizing | both | ⚪ inherent | Sim hardcodes `account_size=5000`; live reads broker balance (paper = $100k). Same formula → 20x shares → P&L not directly comparable. **When validating a specific day, run the sim at the live account size.** |
| 6 | VWAP seed data vendor | vwap | 🔴 suspended | Live builds session VWAP from Tradier `get_bars_since_4am`; sim from Alpaca historical minute bars. VWAP suspended (issue #14). |
| 7 | Gap reference price | both | ⚪ inherent | Live gap% uses real-time `q.last` at scan time; sim uses the daily open via `find_gappers`. Live can't know the 9:30 open at 9:25. Shifts candidate ranking. |
| 8 | Paper rel-vol staleness | both | ⚪ inherent (paper only) | Paper data feed is 15-min delayed, so a 9:25 quote ≈ 9:10 cumulative. Live real-time is correct; only the paper-mode numerator is stale. |
| 9 | Simultaneous-signal tiebreak | vwap | 🔴 suspended | Sim takes earliest signal across watchlist, ties broken by rank. Live enters whichever bar pops off the poller queue first. VWAP suspended (issue #14). |
| 10 | `max_entry_bars` | scalp | ✅ resolved | Was `📌 override` at 30 for paper data harvesting. Trial 211 config uses `max_entry_bars=5` (validated value). No override needed. |
| 11 | Wall-clock fallback | scalp | ⚪ inherent | `5a1f0e0` (Jul 1): live marks bar-starved symbols done after wall-clock timeout. Sim always has complete bars. Both produce "no trade" for illiquid tickers — outcome equivalent. Issue #9. |
| 12 | MP market-order fallback | micro-pullback | 🟡 open | `2a6bdba` (Jul 1): live falls back to market order (0.5% cap) when limit misses. Sim assumes limit-only. MP already UNDER-REVIEW (fill model). Issue #8. |

---

## Cross-cutting strategic risk (not a code gap)

- **VWAP SUSPENDED** (issue #14, Jul 10) — sealed edge was entirely from news
  lookahead bias. `VWAP_SUSPENDED=True` in `session_job.py`. Needs full
  re-optimization with `require_news=False`. All VWAP parity gaps (3, 6, 9)
  suspended until strategy is re-validated.

- **Micro-pullback UNDER-REVIEW** — fill model re-opt failed sealed (Trial 197
  +$521/PF 1.30 vs Trial 167 +$686/PF 1.45 under fills). MP market-order
  fallback (gap #12) compounds the risk. Issue #8.

---

## Deploy dependencies for the open ✅ fixes to take effect live

1. Re-push the data branch so the `floats` map ships:
   `python production/data/live_capture/export_rel_vol_baseline.py --push`
2. `GITHUB_TOKEN` set on Render (private repo) so the runner can fetch the baseline.
3. Render redeploy (off-hours; deploys wipe ephemeral capture — pull bars first).
