# Corpus Threshold Audit — code config vs concept pages (2026-05-29)

Compares the shipping config defaults (`production/trading/models.py`) against the 17
distilled concept pages (full 1,799-session corpus). **Analysis only — no code changed.**
Each finding: code value → corpus says → severity → proposed action. "Tunable" = expose/let
Optuna decide; "Verify" = check another file; "Change" = corpus contradicts code.
DB-validation needed before adopting anything that alters entry/exit behavior.

Severity: 🔴 corpus contradicts code · 🟡 likely improvement · 🟢 aligned (logged for confidence).

---

## 🔴 F1 — COLD-day entries can pass without a news catalyst
- **Code:** `ScoringConfig.threshold_cold=70`. Max score WITHOUT news = pattern25 + relvol20 +
  float15 + gap10 + macd5 + time5 = **80** (news worth 0). So a no-news setup can hit 70 on a cold day.
- **Corpus** (`concept_market_temperature.md` §6 "Cold Market Rules", `concept_news_catalyst.md`):
  cold-day A+ **must have a news catalyst** ("Must have news catalyst (not just technical)").
  No-news trades win 60.7% vs 73.4% with news (−12.7pp).
- **Action (Change, needs DB):** on COLD/CHOP, require `news_tier != none/unknown`, OR add a
  cold-day news sub-gate in scoring (e.g. zero the score if cold and no news). Backtest caveat:
  news is unavailable historically (`news_unknown_pts=4`), so this gate can only bite LIVE — wire it
  behind the live news feed, not the backtest.

## 🔴 F2 — Flat rel-vol gate (5×) ignores temperature; corpus uses 2× hot / 3× cold
- **Code:** `ScannerConfig.min_relative_volume=5.0`, flat for all regimes.
- **Corpus** (`concept_market_temperature.md` §6, `concept_float_analysis.md`): cold-day A+ wants
  **3×+**, "2× acceptable on hot day." 86% of coded rel_vol entries are "high"; the 5× floor may
  over-filter HOT-day setups Ross would take at 2–3×.
- **Action (Tunable, needs DB):** lower the hard gate to ~3× and let `ScoringConfig.relvol_pts_*`
  (already 5×=8 → 100×=20) grade magnitude; or make the gate temperature-aware. Strong Optuna candidate.

## 🟡 F3 — HOT-symbols-count threshold mismatch (3 vs 4)
- **Code:** `MarketTemperatureConfig.hot_symbols_min=3`.
- **Corpus** (`concept_market_temperature.md` §9): "gapper ≥50% AND symbols **≥4** → HOT."
- **Action (Tunable):** minor; 3 vs 4 is within tuning range. Note for the temp re-tune. Do NOT
  edit the classifier itself without the user (standing rule).

## 🟡 F4 — Ultra-low float (sub-500K) scored highest with no volatility/spread haircut
- **Code:** `ScoringConfig.float_sub1m_pts=15` (max) — sub-1M gets the top score.
- **Corpus** (`concept_float_analysis.md` `float_size_multiplier`): sub-500K = **0.5× size**
  (wide spreads, slippage); `concept_position_sizing.md` §3 "start smaller than usual" on sub-1M.
- **Action (Tunable, needs DB):** add a size haircut for sub-~500K float (high *score* but reduced
  *size*), separating "quality" from "tradeable size." Sizing lives in `sizing.py` (already extracted).

## 🟡 F5 — No hard "stop at daily profit goal" (corpus Rule 4)
- **Code:** `PortfolioManager` enforces MAX_LOSS / GREEN_TO_RED / GIVE_BACK_HALF (peak ≥ target then
  gave back 50%). No pure "halt when `daily_pnl ≥ goal`."
- **Corpus** (`concept_daily_risk_rules.md` Rule 4): "daily goal reached" is the #1 session-end reason
  (831 sessions); continuing past goal creates give-back risk.
- **Action (Design choice, needs DB):** GIVE_BACK_HALF already protects most of this. A hard goal-stop
  may cut HOT-day runners (concept itself says HOT can extend goal +50%). Recommend: keep give-back-half;
  optionally add a goal-stop ONLY on COLD/CHOP. Tunable, low priority.

## 🟢 F6 — Float cap 20M + filter ON — aligned
- Code `max_float=20M`, `enable_float_filter=True`. Corpus: "≤20M" exact match; 87% of coded floats
  sub-20M. Scoring sub1m15/1-5m12/5-20m6/20m+0 mirrors the bucket behavior. ✓

## 🟢 F7 — Pattern enable/disable matches corpus win rates
- Disabled: `abcd` (corpus 42.9% = net-losing ✓), `bull_flag` (n=26, thin ✓).
- Enabled: gap_and_go (69%), micro_pullback (74%), vwap_reclaim (75%), dip_buy (63%), flat_top (64%),
  red_to_green (66%), whole_dollar (64%), ORB (70.8%) — all ≥ corpus threshold. ✓
- Scoring base points ordered by corpus win rate (gap_and_go/vwap_break_curl 25 → abcd 15). ✓

## 🟢 F8 — Entry gain gate + gap scoring aligned
- `min_premarket_gain=10%` matches corpus "10% min, 20% preferred, 40%+ ideal." Gap scoring
  10-20→4 / 20-40→7 / 40+→10. ✓

## 🟢 F9 — Time windows aligned
- `ExitConfig.time_decay_hour=11` (exit profitable after 11 = dead zone ✓), `AddOnConfig` cutoff 10:30
  (corpus: adds <2% after 10:30 ✓), `gap_and_go_max_bars_since_open=15` (first 15 min ✓),
  scoring `time_after_1030_pts=0` ✓. Matches `concept_time_of_day.md`.

## 🟢 F10 — Temperature per-regime sizing matches concept §9 table
- pos% hot20/neutral15/cold10/chop5 — exact match to concept_market_temperature.md §9. ✓

---

## 🔴 F11 — VWAP-reclaim is wrongly MACD-gated (was V2, now CONFIRMED)
- **Code:** `entry_engine.py:276-278` applies the MACD line>0 gate to **all** non-gap-and-go
  patterns; `detect_vwap_reclaim` runs at line 289, AFTER the gate. So when `enable_macd=True`
  (default) and `macd_line` is not None (≥35 bars, ~10:05 AM+), a VWAP reclaim with `macd_line ≤ 0`
  is blocked.
- **Corpus:** `concept_vwap_reclaim.md` — "Do NOT require MACD > 0 for VWAP reclaim entry" (the
  reclaim itself IS the front-side signal; gating filters out valid early reclaims before 12EMA crosses
  26EMA). `concept_front_side_back_side.md` — exempt **gap-and-go AND vwap-reclaim** (only the comment
  exempts gap-and-go). Bounded impact: only late-morning reclaims (≥35 bars) with a not-yet-crossed MACD.
- **Action (Change, needs DB):** exempt `vwap_reclaim` (and likely `vwap_break_curl`, same family)
  from the MACD gate — move their detection ahead of the gate, like gap-and-go. Behavior-changing →
  re-tune/validate (enable_macd is a Trial-193 param). **NOT applied unattended.**

## VERIFY — resolved / remaining
- **V1 — RESOLVED (aligned):** hard 11:00 ET entry cutoff exists (`entry_engine.py:59 TRADING_END_HOUR=11`,
  Gate 1 blocks entries outside 9:30–11:00); micro-pullback has an extra hard 10:30 cutoff. No issue.
- **V2 — RESOLVED → promoted to F11 above** (confirmed real, not just a doc check).
- **V3 (audit L3, open):** `flat_top_resistance_tol=0.03` is an ABSOLUTE dollar tol (2.5% on a $2 stock,
  0.25% on $20). Consider %-of-price for cross-price consistency. Tunable, low priority.

## Priority for the user (highest leverage first)
1. **F1** (cold-day news requirement) — directly targets the +12.7pp news edge; LIVE-only gate.
2. **F11** (un-MACD-gate VWAP reclaim) — corpus-explicit; restores valid late-morning reclaims. Clean code change, needs re-tune.
3. **F2** (temperature-aware rel-vol gate) — likely unblocks HOT-day setups; clean Optuna param.
4. **F4** (sub-500K size haircut), **F5** (cold-only goal-stop), **F3** (symbols 3→4), **V3** (%-tol flat-top) — refinements.

All behavior-changing items (F1-F5) must be validated on a backtest run before adoption — deferred to
when the user is back + DB free. This doc is the proposal set, not applied changes.

---

# Exit-side findings (`exit_engine.py` + `ExitConfig`) — the flagged "winners amputated" area

Prior session flagged exits (not stops) as the win:loss problem (audit L6: stops are healthy).
Comparing exit logic to `concept_stop_management.md` + `concept_time_of_day.md` + `concept_market_temperature.md`.

## 🔴 E1 — `time_decay_hour=11` is FLAT; concept sets it per-temperature
- **Code:** `exit_engine.py:218` — `if in_profit and et_time.hour >= 11: exit ALL remaining`. Same hour
  every regime.
- **Corpus** (`concept_market_temperature.md` §9 session_stop_time): **HOT=12:00, NEUTRAL=11:00,
  COLD=10:30, CHOP=10:00.** A flat 11:00 cuts HOT-day runners ~1h early (concept: HOT = "hold 30-60min,
  through halts") and lets COLD-day positions run 30min too long.
- **Interaction to verify:** the sim also has a temperature `is_session_over()` force-close (used in
  the entry gate). Need to confirm how exit_engine's flat-11 time_decay and the temp session-stop combine
  (one may already override). **Likely the highest-value exit fix** (directly the "amputated winners"
  symptom on HOT days). Behavior-changing → DB-validate. NOT applied.

## 🔴 E4 — MACD-negative-at-highs exit is DISABLED (corpus calls it a primary exit)
- **Code:** `ExitConfig.enable_macd_flip_exit=False`. Also H0 (engine audit) found MACD was dead in the
  SIM (`BAR_HISTORY_SIZE=30 < 35`) — so even the scoring/exit MACD paths got no signal in backtest.
- **Corpus** (`concept_stop_management.md` §5.6, `concept_market_temperature.md` §4): "Negative MACD at
  or near highs = close 75%+ immediately" — and it's the **key exit signal EVEN on hot days.** Currently off.
- **Action (needs DB + H0 fix first):** the sim must compute MACD (raise BAR_HISTORY_SIZE to ≥35, fix the
  key) before this exit can be tuned/enabled. Coupled to H0. Behavior-changing.

## 🟡 E3 — Losers not force-closed at the dead-zone cutoff (only winners are)
- **Code:** time_decay (line 218) and early_time_decay (line 204) both gate on `in_profit`. A *losing*
  open position at/after 11:00 is NOT closed by exit_engine — it rides to its stop.
- **Corpus** (`concept_time_of_day.md`): after 11 AM morning momentum is gone for everything. A red
  position post-11 is unlikely to recover intraday. (The sim's temp session-stop may force-close it —
  verify, same as E1.) Possible improvement: dead-zone flat-exit regardless of P&L. Needs DB.

## 🟡 E2 — STALE comments: exit_engine says "12 PM / midday", code fires at 11  → FIXED (doc-only)
- `exit_engine.py` header (line 18) said "after 12 PM ET" and the §9 block (line 216-217) said
  "after 12:00 PM ET" / "before the midday cutoff", but `ExitConfig.time_decay_hour=11` and the code is
  `>= 11`. Misleading. **Fixed the comments to say 11:00** (no behavior change). Default was 12→11 at
  some point (matches concept NEUTRAL=11); docstrings weren't updated.

## 🟢 E5 — T1/T2 scaling + trailing aligned
- T1 @ 2.19R sell 30% + stop→breakeven, T2 @ 3.0R sell 25% + stop→T1, trail 0.262 after T1, COLD/CHOP
  full-exit at T1. Matches `concept_stop_management.md` §6.2 + `concept_market_temperature.md` §4. ✓
- selling_pressure / resistance / volume_dry_up disabled by default — consistent with prior tuning notes
  (selling_pressure fired too early). Tunable later. 🟢

**Exit priority for the user:** E1 (per-temperature session stop — likely the amputated-winner fix) →
E4 (MACD exit, blocked on H0) → E3 (dead-zone losers). All need DB validation. E2 already fixed (docs).
