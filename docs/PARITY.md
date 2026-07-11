# Sim / Live Parity Ledger

Canonical list of every known divergence between the **simulators** and the **live
runners** for the two standalone strategies (Opening Bell Scalp, VWAP Reclaim).
The backtested edge is only real live if the live runner makes the *same decisions*
on the *same inputs*. This file is the single place that truth is tracked.

**Status key:** ✅ fixed · 🟡 open (logic) · ⚪ inherent (cross-vendor / live-timing,
can't be fully closed) · 📌 known override (intentional, must revert before live money)

Last audited: **2026-07-10** (VWAP re-enabled with Trial 188, require_news=False).

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
| 1 | News gate | both | ✅ `4ae4cf7` | Live excluded `tier3`; sim kept it. Unified via `has_news_catalyst()` / `NEWS_CATALYST_TIERS` in news_fetcher.py. Live now includes tier3 (matches validated sim). |
| 2 | Float filter | scalp | ✅ `4ae4cf7` | Live had `float_shares=None` (gate never ran); sim filters on `stock_fundamentals`. Export now ships a `floats` map; live scalp applies the same `max_float` gate. |
| 3 | Rel-vol numerator timing | vwap | ✅ `4ae4cf7` | Live divided by instantaneous quote volume at its ~9:45 scan (2-3x the 9:25 cumulative); baseline denominator is cumulative-through-9:25. Now reconstructs cumulative-through-9:25 from session bars. |
| 4 | `bars_since_open` off-by-one | scalp | 🟡 open | Sim first 9:30 bar = `bars_since_open=0`; live increments to `1` before first `evaluate_entry`. Harmless for `first_green` (current config); **`market_open` mode can never enter live** (only fires at `==0`). Fix when/if config changes. live_scalp_runner.py:~433 |
| 5 | Account balance / sizing | both | ⚪ inherent | Sim hardcodes `account_size=5000`; live reads broker balance (paper = $100k). Same formula → 20x shares → P&L not directly comparable. **When validating a specific day, run the sim at the live account size.** |
| 6 | VWAP seed data vendor | vwap | ⚪ inherent | Live builds session VWAP from Tradier `get_bars_since_4am`; sim from Alpaca historical minute bars. Different vendor volume/typical-price → VWAP value can differ → different reclaim trigger. Validate with a bar diff; can't be "fixed". |
| 7 | Gap reference price | both | ⚪ inherent | Live gap% uses real-time `q.last` at scan time; sim uses the daily open via `find_gappers`. Live can't know the 9:30 open at 9:25. Shifts candidate ranking. |
| 8 | Paper rel-vol staleness | both | ⚪ inherent (paper only) | Paper data feed is 15-min delayed, so a 9:25 quote ≈ 9:10 cumulative. Live real-time is correct; only the paper-mode numerator is stale. (#3's bar-sum reconstruction sidesteps this for VWAP.) |
| 9 | Simultaneous-signal tiebreak | vwap | 🟡 low | Sim takes earliest signal across watchlist, ties broken by rank. Live enters whichever bar pops off the poller queue first. Differs only when two symbols signal on the same minute. |
| 10 | `max_entry_bars=30` | scalp | 📌 override | Paper-only: validated value is **4**. Extended to 30 to harvest more paper data. **MUST restore to 4 before live money.** live_scalp_runner.py:~70 |
| 11 | Market-order fallback | MP | ⚪ immaterial | Live retries with market order when limit misses (0.5% cap). Sim now supports `market_fallback_pct` flag. Sealed 2025 comparison: 0 extra trades, $0 P&L delta — breakout entries gap past cap every time. |

---

## Cross-cutting strategic risk (not a code gap)

- **VWAP Trial 188 deployed** (2026-07-10) — `require_news=False`, pure price/volume
  edge. Walk-forward validated: train +$7,994/PF 2.54, select +$4,788/PF 2.71,
  sealed +$3,299/PF 2.19. Previous trials (184, 173, 56) all deprecated due to
  news-lookahead bias or data drift. Live validation needed (1 week).

---

## Deploy dependencies for the open ✅ fixes to take effect live

1. Re-push the data branch so the `floats` map ships:
   `python production/data/live_capture/export_rel_vol_baseline.py --push`
2. `GITHUB_TOKEN` set on Render (private repo) so the runner can fetch the baseline.
3. Render redeploy (off-hours; deploys wipe ephemeral capture — pull bars first).
