# production/trading/ Engine Audit — 2026-05-29

Systematic line-level read of the trading engine, done autonomously while the
Phase-1 backfill ran. Read-only — **no engine code was changed.** Severity-tagged.
Companion to the two earlier findings in `memory/live_sim_parity_gap.md` and
`memory/optimizer_objective_fix.md` (not repeated in full here).

Format: `SEVERITY | file:line | problem | fix`.

---

## CRITICAL (latent)

### H0 — Sim reads `macd['macd_line']`, but `calculate_macd` returns `'macd'` → MACD is dead in the simulator, and a KeyError is one config change away
`simulation_engine.py:642` and `:723` do `macd['macd_line']`.
`indicators.calculate_macd` (`indicators.py:94-98`) returns keys
`{'macd', 'signal', 'histogram'}` — there is **no `'macd_line'` key** (verified at
runtime: `KeyError: 'macd_line'`).

Why it hasn't crashed: `BAR_HISTORY_SIZE = 30` (`simulation_engine.py:53`) but
`calculate_macd` needs `slow + signal = 26 + 9 = 35` bars, so in the sim it **always
returns `None`**, and the guarded `macd['macd_line'] if macd else None` takes the
`None` branch every time. The bug is masked, not absent.

Two consequences:
1. **MACD is functionally dead in the simulator.** Every MACD-dependent path silently
   degrades to the None/"unknown" branch:
   - exit MACD-flip gate never fires (histogram + prev both None);
   - add-on WHOLE_DOLLAR gate (`macd_line > 0`) never fires;
   - entry MACD-line gate is never enforced; `scoring_engine` always awards
     `macd_unknown_pts`; dip-buy Trick 2 is always skipped.
   The Optuna toggle `c_enable_macd_flip_exit` and the entry MACD gate are therefore
   **no-ops during tuning** — the optimizer cannot see them.
2. **Live ≠ sim again.** `live_scanner.BAR_HISTORY_DEPTH = 40` (≥35), so LIVE *does*
   compute MACD and *does* enforce the MACD-line entry gate / histogram exit. A config
   tuned in the sim (MACD inert) will behave differently live (MACD actively gating).
3. **Landmine:** the obvious "improvement" of raising `BAR_HISTORY_SIZE` to ≥35 to
   enable MACD will immediately surface the `KeyError` and crash every sim day with an
   open position past 35 minutes.

**Fix:** (a) change both sim accesses to `macd['macd']` (the real key); and
(b) raise `BAR_HISTORY_SIZE` to ≥35 so MACD actually computes; then (c) re-tune,
since enabling MACD changes the entry/exit surface. Do (a)+(b) together — doing (b)
alone crashes, doing (a) alone leaves MACD dead.

---

## HIGH

### H1 — `PositionManager` double-counts partial scale-outs in `current_balance`
`trading_engine.py:200-252` (`apply_exit_signal`).
On a partial scale-out (e.g. TARGET_1) the scale branch does
`self.current_balance += pnl` for that fill. When the SAME trade later fully closes
via the `is_full_close` branch (STOP_HIT, TIME_DECAY, or `qty >= shares_remaining`),
it does `trade_pnl = pos.get_pnl()` — which sums **all** fills again — and adds the
whole thing to `current_balance`. The earlier partial is counted twice.

- Example: T1 partial +$25, then STOP on remainder −$60. True trade P&L = −$35.
  `current_balance` change = +$25 (scale) + (−$35) (get_pnl on close) = −$10. Overstated by +$25.
- **Impact:** the `objective = total_pnl` Optuna metric is NOT affected (it sums
  `trade['pnl']` = `get_pnl()`, correct). But `avg_daily_pnl` in
  `simulate_one.py:159` IS computed from `current_balance - account_size`, so the
  reported daily P&L is inflated for every trade that scales out before closing.
  Any per-day analysis (e.g. the "Dec 2025 −$257/day") is biased by this.
- **Fix:** stop updating `current_balance` incrementally on partials. Realize P&L
  once, at trade completion, via `get_pnl()`. Track `daily_loss` the same way.
- **Note:** the LIVE path (`order_manager.py`) does NOT have this bug — it adds each
  fill's pnl exactly once. So sim and live disagree on balance accounting → another
  live≠sim divergence, and here the SIM is the wrong side.

### H2 — Live `_calculate_shares` omits all advanced sizing (confirms parity gap)
`order_manager.py:388-409`.
Risk% + max_position_pct only. No float-bucket caps (FLOAT_BUCKET_CAPS), no
score/cushion multiplier, no GAP-14 cooldown, no GAP-16 first-loss half-size, no
temperature sizing. Sim's `PositionManager.enter_position` has all of these. Already
in `live_sim_parity_gap.md`; re-confirmed at the code level. Live will size very
differently from every backtest.

---

## MEDIUM

### M1 — Add-on cost basis ignored in live realized P&L
`order_manager.py:248,262,460`. `pnl = fill_qty * (fill_price - trade.entry_price)`
prices add-on shares as if bought at entry. `Trade.get_pnl()` has the
`add_on_premium` correction but live accounting never calls it — it uses the raw
per-fill delta. Overstates P&L on any add-on trade. (Sim uses `get_pnl()`, so sim
is correct here — opposite of H1.)

### M2 — Live premarket screen hardcodes thresholds, ignores ScannerConfig
`live_scanner.py:662,670,714,719` + module constants `PREMARKET_MIN_GAIN_PCT=10`,
`PREMARKET_MIN_REL_VOL=5`, `PREMARKET_MAX_FLOAT=100M`, and `1.0 <= price <= 20.0`.
The optimized `ScannerConfig` (min_price/max_price/min_premarket_gain/
min_relative_volume/max_float) is never consulted in the premarket DB snapshot. So
the tuned Category-A thresholds do not reach live. Wire ScannerConfig fields into
`_run_premarket_db_snapshot`.

### M3 — Live entry-diagnostic checks MACD histogram; real gate uses MACD line
`live_scanner.py:498` (`macd_data['histogram'] <= 0`) vs the actual entry gate in
`entry_engine` which gates on MACD **line > 0**. The diagnostic will report a
different blocking reason than the one that actually fired. Logging-only, but
misleads debugging. (Already noted in parity memo; confirmed.)

### M4 — Stale dip-buy diagnostic explains the pre-GAP-A algorithm
`patterns.py:1362-1393` (`explain_pattern_rejection._explain_dip_buy`).
Describes the OLD detector: requires `ema9`, checks light-volume pullback via
`cfg.dip_buy_light_vol`. The real `detect_dip_buy` (line 710) was rewritten to use
named support levels + `has_news` + `dip_buy_support_tolerance` and has NO ema9
requirement. No crash (field kept at `models.py:122` for Optuna compat) but the
diagnostic is wrong for the shipping algorithm. Rewrite the explainer to match.

### M5 — Best-signal selection keys on coarse static `confidence`, not entry score
`live_scanner.py:394` selects the candidate with the highest
`pattern.confidence` — but confidence is a hardcoded 3-5 int per pattern type
(`patterns.py`). It is a priority ranking, not setup quality. The composite
`scoring_engine.compute_entry_score` exists precisely to grade quality, but live
never calls it (parity gap). Result: live effectively always prefers GAP_AND_GO/
VWAP_RECLAIM (conf 5) and breaks ties by arrival order. Wire scoring into live.

### M6 — Add-on can fire repeatedly off a stale watermark on the entry bar
`add_on_engine.py:138-148` NEW_HIGH gate vs `trading_engine.py:78`
(`apply_add_on` advances `session_high_at_add` only to `price`, not the bar high).
`session_high_at_add` starts at `entry_price`. The gate compares `bar_high >
session_high_at_add`, but after an add it advances the watermark to the add **price**
(close), not the bar **high**. A bar whose high exceeded its close can let the next
bar re-trigger NEW_HIGH cheaply. Minor over-adding pressure; the 3×-initial cap in
`apply_add_on` bounds the damage. Consider advancing the watermark to `bar high`.

---

## LOW / NOTES

- **L1** `scoring_engine.py:160` `h == 9 and m < 60` is always true given the prior
  `m < 45` branch — redundant but harmless.
- **L2** `scoring_engine` total can exceed 100 once Optuna raises component caps
  (relvol 100x→20, news→20, etc.). Thresholds are tuned in the same space so not a
  bug, but "0-100 score" in docs is no longer literally true.
- **L3** `patterns.py` `flat_top_resistance_tol` is an ABSOLUTE dollar tolerance
  (line 875) — 5¢ is 2.5% on a $2 stock vs 0.25% on a $20 stock. Consider making it
  a percentage of price for cross-price consistency.
- **L4** `live_scanner.py:438` enters using the previous minute's bar close as
  `ask_price` (signal collected last minute, executed at the next minute boundary).
  ~1 min stale vs the live ask — realistic-fill concern, not a correctness bug.
- **L5** `order_manager._wait_for_fill` treats broker status `'filled'` as complete
  but does not reconcile partial fills (filled_qty < requested) on exits — a
  partially-filled market sell could orphan shares. Live-robustness edge case.
- **L6** Stops themselves look healthy: every pattern uses a tight structure-based
  stop (premarket high / VWAP / flag low / named support − buffer). This CORROBORATES
  the other session's conclusion that the win:loss problem is the EXIT side
  (time_decay amputating winners), not stops being too wide.

---

## What was NOT re-read this session
`entry_engine.py`, `exit_engine.py`, `market_temperature.py`, `portfolio_manager.py`,
`models.py`, `broker/*` — covered in prior summaries; only spot-checked here. A
follow-up pass on `exit_engine.py` (the time_decay logic the other session flagged as
P2) would be the highest-value next audit.

*Audit by the elated-euclid worktree session (Opus 4.8), read-only.*
