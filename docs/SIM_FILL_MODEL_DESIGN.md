# Sim Fill Model — Design (awaiting approval)

**Status:** DRAFT — engine changes require user approval per operating rules.
**Date:** 2026-07-02
**Prompted by:** Jul 2 live session — 12/15 scalp entries unfilled in 12s; the
2 that filled came on falling bars and both stopped out.

---

## 1. Problem

All three simulators (scalp, VWAP, micro-pullback) fill every entry **at the
signal bar's close, instantly, for free**. Every Optuna study, walk-forward
validation, and sealed test optimized against that assumption.

Live reality (scalp, pre-fix): a limit order at the signal close, cancelled
after 12s. On a stock moving 5-10%/minute this creates **adverse selection**:

- Price keeps running → limit never fills → *the winners sim counts never
  happen live*.
- Price falls back through the limit → fill → *live disproportionately holds
  the losers*.

Jul 2 evidence: CWD tried at $1.47 (missed, rising), filled at $1.24 on the
way down, stopped out. USDE tried 5 times, filled at $3.89 falling, stopped
out. Sim would have counted the runners at their signal closes.

### Slippage budget is tiny

`research/analysis/outputs/slippage_sensitivity.txt` (Trial 173, multi
arm-10/max-3, entry price shifted, stops not re-simulated):

| entry slip | 2024 select | 2025 sealed | 2025 WR |
|-----------:|------------:|------------:|--------:|
| 0.00% | +$2,287 | +$3,314 | 70.7% |
| 0.25% | +$1,638 | +$2,349 | 65.7% |
| 0.50% | +$990 | +$1,383 | 60.3% |
| 1.00% | −$306 | −$548 | 50.2% |
| 2.00% | −$2,898 | −$4,410 | 36.8% |

Average edge ≈ **0.87% per trade** — the strategy cannot pay more than that
in fill costs. Consequences already acted on:

- Scalp interim fix shipped: marketable limit at signal close × 1.0025.
- MP/VWAP's existing market-fallback **2% slippage caps are suspect**
  (VWAP per-trade edge ≈ 1.0%, MP ≈ 2.2%; a 2% cap can eat the whole edge).
  These caps were never backtested. Flagged for re-review under this model.

---

## 2. Goal

1. Sims model entries the way the live runners actually order.
2. Re-run validation + future Optuna studies against realistic fills, so
   surviving configs have enough per-trade edge to pay real fill costs.
3. Keep a zero-slippage mode for continuity with historical results.

---

## 3. Design options

### A. Constant slippage parameter (cheap, blunt)
`entry_price *= (1 + entry_slippage_pct)`. One line, optimizer-friendly.
Misses the fill/no-fill dimension entirely (still 100% fill rate), so it
under-models adverse selection. Useful as a robustness knob, not sufficient
alone.

### B. Strict limit-fill model (models the OLD live behavior)
Limit at signal close; walk the NEXT bar (12s live wait ≈ sub-bar, one bar is
the conservative sim equivalent): filled iff `next_bar.low <= limit`; fill at
`min(limit, next_bar.open)`. Unfilled → re-signal on later bars (mirrors
live retry loop). Models exactly what live did through Jul 2 — worth running
once as a diagnostic ("how bad was limit-at-close historically") but it's the
behavior we just abandoned.

### C. Marketable-limit fill model (models CURRENT live behavior) ← recommended
Limit `L = signal_close × (1 + headroom)`, headroom = 0.25% (matches the
shipped interim fix). On the next bar:

- `next.open <= L` → filled at `next.open` (you pay the gap, capped by L)
- `next.open > L` but `next.low <= L` → filled at `L`
- else → miss; the symbol re-enters signal evaluation on subsequent bars
  (same as live: cancel, keep watching until max_entry_bars)

Entry timestamp shifts one bar later; stop/target/max-hold all anchor to the
actual fill price and bar, so exits re-simulate correctly (no first-order
approximation like the sensitivity script).

### D. Spread/liquidity model (most realistic, most work)
Estimate bid-ask spread per price bucket (sub-$2: ~1-2%, $2-5: ~0.5-1%, …)
from the captured live bars (`stock_candles_live_1m` + quote captures), apply
spread/2 on entry AND exit, scale fill probability by bar volume vs order
size. Defer: needs a spread dataset we're only now starting to capture.

---

## 4. Recommendation

**C + A together:**

- Implement option C in the three sim engines behind a config flag
  (`fill_model: 'perfect' | 'marketable_limit'`, default `'perfect'` so all
  historical results stay reproducible).
- Keep `entry_slippage_pct` (option A) as an extra optimizer robustness knob
  on top (default 0).
- Exits: market/stop exits keep perfect fills for now (stops filled
  server-side at trigger already match live closely; Jul 2 stops filled at
  ~0.2% past trigger — revisit under option D).

### Parameters added
| param | default | meaning |
|-------|---------|---------|
| `fill_model` | `perfect` | `marketable_limit` enables option C |
| `entry_headroom_pct` | 0.25 | marketable-limit headroom above signal close |
| `entry_slippage_pct` | 0.0 | flat extra slippage (robustness knob) |

---

## 5. Validation & rollout plan

1. **Implement** behind flags; unit tests for the three fill branches.
2. **Diagnostic run:** Trial 173/56/167 on 2024+2025 with
   `fill_model=marketable_limit`. Expect: fewer trades (misses), lower PnL
   than perfect, but *positive* — if a config goes negative here, it cannot
   trade live as-is.
3. **Live parity check:** compare sim fill/miss decisions vs actual live
   order outcomes day-by-day for ~1 week (we now log limit price, fill
   price, misses).
4. **Re-optimize:** new Optuna walk-forward studies (2021-23 train / 2024
   select / 2025 SEALED) with the fill model ON. Plateau-select per
   anti-overfitting playbook. Expect optimal configs to shift toward larger
   profit targets / wider stops (bigger per-trade edge to pay fill costs).
5. **Re-review MP/VWAP market-fallback 2% caps** against slippage-sensitivity
   runs for those strategies; likely tighten to ≤0.5%.

## 6. Known limitations

- Minute bars can't see intra-bar sequencing; "next bar low ≤ L" is
  optimistic about queue position but pessimistic about the 12s sub-bar wait.
  Net direction of bias unknown; the live parity check (step 3) measures it.
- Partial fills not modeled (all-or-nothing). Live logs show partial fills
  are rare but do occur (CWD Jul 2 was partial → full within seconds).
- Exit-side slippage untouched until option D.
