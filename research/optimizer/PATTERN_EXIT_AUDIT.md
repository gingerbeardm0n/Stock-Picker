# Pattern Detection & Exit Logic Audit

**Date:** 2026-05-27  
**Scope:** `production/trading/patterns.py`, `production/trading/exit_engine.py`, `production/trading/entry_engine.py`  
**Source truth:** Concept pages (corpus-derived, 1,799 sessions) + TRANSCRIPT_SUMMARIES_0001-1799  

---

## Summary

| Issue | File | Severity | Status |
|---|---|---|---|
| Flat-top stop = consol_low (too wide, kills R/R) | patterns.py | 🔴 HIGH | **FIXED** |
| ABCD stop = b_low (too wide, should be d_low) | patterns.py | 🟡 MOD | **FIXED** |
| MACD bug (histogram vs macd_line) | entry_engine.py | 🔴 HIGH | Already fixed |
| ABCD entry at C-break instead of A-break | patterns.py | 🟡 LOW | Documented |
| R2G no 10:00 AM hard cutoff | patterns.py | 🟡 LOW | Documented |
| `_explain_dip_buy` checks ema9 that detector doesn't | patterns.py | 🟢 DIAG | Noted |
| Exit logic vs corpus | exit_engine.py | ✅ PASS | No changes needed |

---

## Issue 1 — Flat-Top Stop (FIXED)

### What was wrong
`detect_flat_top_breakout()` was using the entire **consolidation low** as the stop:
```python
consol_low = min(_low(b) for b in window)
stop = consol_low - cfg.stop_buffer   # BUG: too wide
```

`concept_stop_management.md §3.2`:
> "Stop below the flat-top resistance line that was just broken (now support)."

### Why it matters
Say a stock consolidates at $5.00 (flat top) with consolidation range $4.60–$5.00:
- **Old stop**: $4.60 − buffer ≈ $4.58 → stop_dist = $5.05 − $4.58 = **$0.47** → T1 at **$5.99**
- **New stop**: $5.00 − buffer ≈ $4.92 → stop_dist = $5.05 − $4.92 = **$0.13** → T1 at **$5.31**

The old stop made flat-top almost impossible to hit T1 (required 19% extension). The new stop produces realistic scalp targets. This was probably suppressing flat-top trades entirely in simulation via the R/R gate.

### Fix applied
```python
# Before
stop = consol_low - cfg.stop_buffer

# After
stop = best_resistance - cfg.stop_buffer  # below the broken level, now support
```

---

## Issue 2 — ABCD Stop (FIXED)

### What was wrong
`detect_abcd_pattern()` was using the **B-leg low** as the stop:
```python
stop = b_low - cfg.stop_buffer   # BUG: original pullback low, too wide
```

`concept_stop_management.md §3.4`:
> "Stop: Below the prior higher low (the C-point in ABCD, or the last touch of the ascending trendline)."

In the code's ABCD, D-bars are the most recent higher-low area (the "C-point" in the corpus's terminology). B is the original deep pullback — way below where the action is at entry.

### Fix applied
```python
# Before
stop = b_low - cfg.stop_buffer

# After
stop = d_low - cfg.stop_buffer   # D-bars = most recent higher low before entry
```

---

## Issue 3 — ABCD Entry Logic (Documented, Not Fixed)

### The mismatch
The code enters when price breaks **above C** (the secondary rally high). The corpus ABCD (concept_pattern_playbook.md §9) says:
> "D leg trigger: break above A high on expanding volume"
> "Entry: Price breaks above the A-leg high"

The code's ABCD is actually entering at the C-break (secondary high), not the final D-leg breakout above A.

### Why not fixed now
- n=26 in corpus, no win rate recorded → very low sample size
- `enable_abcd: bool = False` in EntryConfig defaults (Trial 193 had it disabled)
- The code's variant (entry at C-break with D as consolidation) is actually a reasonable setup, just not the textbook ABCD
- Fixing requires substantial rework of the detection algorithm

### Impact when enabled
The code fires "ABCD" on what is actually a "break of secondary high with higher-low structure" — still a valid momentum continuation pattern. The stop improvement in Issue 2 makes it more mechanically sound regardless.

---

## Issue 4 — Red-to-Green Time Cutoff (Low Priority)

### The mismatch
`concept_pattern_playbook.md` table shows R2G primary window as **9:30–10:00 AM**. The code uses the global 11:00 AM gate from `entry_engine.py` Gate 1.

### Impact
R2G signals can fire between 10:00–11:00 AM when the corpus suggests they degrade. However R2G fires before 10:00 on most qualifying days so this is a minor edge effect.

### If you want to enforce it
Add to `detect_red_to_green()` or apply in `entry_engine.py` similar to the micro-pullback cutoff:
```python
r2g_ok = (
    ecfg.enable_red_to_green
    and et_time.hour < 10  # R2G only in first 30 minutes
)
```

---

## Exit Logic Audit — PASS

Exit engine matches concept_stop_management.md §6 implementation rules:

| Corpus Rule | Code Implementation | Match |
|---|---|---|
| T1: cover 33–50%, stop → breakeven | `target1_qty_pct=0.50`, `move_stop_to_breakeven=True` | ✅ |
| T2: cover 25% more, stop → T1 | `target2_qty_pct=0.25`, `new_stop_price=t1_price` | ✅ |
| MACD flip → exit 75% immediately | `macd_flip_qty_pct=0.75`, histogram crossover check | ✅ |
| COLD/CHOP → full exit at T1 | `TARGET_1_COLD` full-position exit | ✅ |
| Time decay → exit all at 12 PM | `time_decay_hour=12`, in-profit guard | ✅ |
| Hard stop always first | Gate 1, unconditional | ✅ |
| Trailing stop (post-T1) | `trailing_stop_distance`, activates after partial exit | ✅ |

**Note on MACD in exit vs entry:**
- Entry gate uses **macd_line** (EMA12 − EMA26 > 0) — correct (front-side check)
- Exit gate uses **macd_histogram** crossover (prev > 0, now ≤ 0) — correct (momentum flip is leading signal)
- These are intentionally different indicators and both match corpus intent

**Entry time window:**
The global 11:00 AM cutoff in entry_engine matches `Temperature.NEUTRAL` session stop. COLD/CHOP session stops (10:30/10:00) are enforced by market temperature system — this is the correct design.

---

## Pattern Frequency Mismatch (Informational)

Corpus n-counts vs code priority:

| Pattern | Corpus n | Win% | Code Priority | Code Status |
|---|---|---|---|---|
| gap-and-go | 1,177 | 69% | #1 (first check) | ✅ enabled |
| dip-buy | 712 | 63% | #4 | ✅ enabled |
| whole-dollar-break | 428 | 59% | #7 | ✅ enabled |
| micro-pullback | 387 | 70% | #2 (10:30 cutoff) | ✅ enabled |
| halt-resume | 319 | 67% | ❌ not implemented | — |
| vwap-reclaim | 153 | 75% | #0b (first after gap) | ✅ enabled |
| red-to-green | 143 | 65% | #6 | ✅ enabled |
| flat-top | 82 | 64% | #5 | ✅ enabled (stop now fixed) |
| abcd | 26 | — | disabled | — |
| bull-flag | 26 | — | #3 | ✅ enabled (default off) |

**halt-resume** (n=319, 67% win rate) is the only high-volume unimplemented pattern. It requires halt detection data (not in minute bars). Documented in plan as "deferred."

---

## Files Changed

- `production/trading/patterns.py` — 2 stop bug fixes (flat-top, ABCD)

*End of audit*
