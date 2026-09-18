# Deep Review — September 2026

_Written 2026-09-18 by a Fable 5.1 review session. Inputs: `docs/FABLE_BRIEFING.md`,
`STATUS.md`, one code-map pass (haiku), two quant passes (sonnet) against the local
TimescaleDB. No production code was changed. Scratch scripts and per-trade JSON are in
`research/maintenance/diagnostics/_scratch/` (gitignored)._

---

## 0. Verdict (read this if nothing else)

**The sealed backtests are not evidence of an edge. The simulator fills every stop at the
exact stop price with no gap-through, and for a strategy whose stop sits inside 1-minute
bar noise that assumption is the entire profit.** Replacing it with the most live-favorable
realistic fill (resting broker stop, gap-through allowed, discretionary exits at next bar
open) turns scalp Trial 211's sealed 2025 result from **+$4,675 / PF 3.31** into
**−$6,163 / PF 0.58**. 2026 YTD goes from +$1,013 / PF 5.04 to −$573 / PF 0.71. VWAP
Trial 188 is negative under the same treatment, and its sealed PF 2.19 no longer even
reproduces on the current database (PF 1.00).

The live result (−$650, payoff 0.42, losers averaging −$32) is therefore **not a
sim→live gap. It is what the strategy does.** The honest sim predicts losers of −$28; live
delivered −$32. The five-month walk-forward apparatus was calibrated against a fill model
that cannot exist, and every config it selected was selected *for* exploiting that model.

**Recommendation, in order:**

1. **Do not fund Tradier yet.** Funding buys live data for strategies whose honest
   backtest is already negative. Zero-dollar work comes first.
2. **Retire Trial 211 / 188 / 167 as live configs now.** Stopping needs no backtest gate.
   Leave the scheduler running only if the loud-auth-failure fix is also shipped; otherwise
   turn it off so it stops generating 4,000 lines of NO TRADE per day.
3. **Make the honest fill model the simulator's default** (V5 + exit slippage, defined in
   §1.3). This is roughly one day of work; the logic already exists as a post-hoc script.
4. **Re-optimize under the honest sim with structural (Ross) stops**, walk-forward as per
   the playbook. If nothing clears the Gate 1 bar in §4 by **2026-11-20**, stop jTrader.
5. **Fund Tradier and go live with tiny real money only after Gate 1 passes.** That honors
   the owner's "real money early, skip extended paper" preference without pretending a
   candidate exists today.

Downside if this verdict is wrong: a delay of three to six weeks on a system that has
traded nothing for 60 days. Downside if it is right and ignored: another cycle of
funding, deploying, and reading a −$15/trade tape as "execution noise."

---

## 1. Q1 — Is the simulator's exit modeling systematically optimistic?

**Yes, and it is the general case, not a trail-width special case.** The trail-width
blind spot and the stop-fill blind spot are two instances of one root defect: the sim
treats a 1-minute OHLC bar as a continuous path on which any level in `[low, high]` is
fillable at exactly that level, and it knows the bar's extremes before it decides.

### 1.1 What the code does (all three engines, verified by line)

| Behavior | Scalp / VWAP / MP | Live runner |
|---|---|---|
| Stop hit test | `bar_low <= stop_price` → fill **at `stop_price`** | Resting broker stop; fills at next print, gaps through |
| Target hit test | `bar_high >= target_price` → fill at `target_price` | Runner sees bar, cancels stop, market sell (≈ next open) |
| Trail | peak from **same bar's high**, tested vs **same bar's low** | peak known only after bar closes |
| Gap-through | none | yes |
| Exit slippage | none (`fill_model.py` slips entries only) | full spread + latency, up to 120s wait |
| Intra-bar ordering | none; stop checked first | n/a |

`production/trading/scalp_engine.py:158-177`, `vwap_engine.py:217-236`,
`micro_pullback_engine.py:205-227`, `production/simulator/fill_model.py:61-63`,
`production/trading/live_scalp_runner.py:777-789, 1043-1071`.

### 1.2 The stress test (2025 sealed window, full 250 days, entries unchanged)

Exit price recomputed per trade from the actual 1-min bars; candidate selection and entry
timing identical across variants. 0 unmatched bars out of 712 / 928.

| Variant | Scalp 211 PF | Scalp pnl | Scalp payoff | VWAP 188 PF | VWAP pnl |
|---|--:|--:|--:|--:|--:|
| V0 sealed (exact-level fills) | **3.31** | **+4,675** | 9.63 | 1.00 | +13 |
| V1 fill at trigger-bar close | 0.76 | −3,387 | 1.10 | 0.98 | −167 |
| V2 fill at next-bar open | 0.77 | −3,317 | 1.13 | 0.98 | −210 |
| V3a exact level −0.5% slippage | 1.46 | +1,888 | 4.77 | 0.65 | −3,461 |
| V3b exact level −1.0% slippage | 0.86 | −898 | 3.32 | 0.44 | −6,936 |
| V4 gap-through on stop/trail only | 0.63 | −3,548 | 1.90 | 0.52 | −4,532 |
| **V5 live-favorable hybrid** | **0.58** | **−6,163** | **1.75** | **0.91** | **−851** |
| V6 = V5 + 0.3% exit slippage | 0.51 | −7,802 | 1.58 | 0.72 | −2,934 |

V5 = stops fill at `min(stop, next open)` (a resting broker stop, gap-through allowed);
target / trail / time exits fill at next bar open (runner observes the bar, then sends a
market order). This is the *most generous* model consistent with how the live runner
actually works. V6 adds a spread proxy.

2026 YTD (Jan 2 – Jun 12, 94 trades) tells the same story: V0 PF 5.04 → V1 0.81 → V5 0.71.

### 1.3 Where the profit was hiding: the stop leg

Scalp by exit reason, 2025:

| reason | n | V0 sum | V0 avg | V5 sum | V5 avg |
|---|--:|--:|--:|--:|--:|
| stop_loss | 518 | −2,011 | **−3.88** | −14,516 | **−28.02** |
| profit_target | 51 | +3,772 | +73.97 | +4,895 | +95.99 |
| trailing_stop | 92 | +2,324 | +25.26 | +2,923 | +31.77 |
| time_stop | 51 | +590 | +11.56 | +535 | +10.50 |

98% of the V0→V1 swing is stop_loss. Targets and trails actually get slightly *better*
under realistic fills (a bar that tags a target usually keeps running). The sealed edge is
not "we pick good entries"; it is "73% of trades stop out, and the sim says each costs
$3.88." With gap-through each costs $28. The stop is roughly 0.5% below entry on names
whose 1-minute bars routinely range 3–5%. It is inside the noise, and a stop inside the
noise is only survivable in a simulator that fills it at par.

### 1.4 Why this is general and not trail-specific

- The mechanism (exact-level fill on an intra-bar touch) is shared by stop, target, and
  trail code paths in all three engines.
- The degradation lands on the stop leg, which the earlier trail-width investigation never
  touched. Two independent symptoms, one cause.
- The Optuna near-zero trail (0.0014%) and the 0.5% stop are the same discovery: the
  optimizer found the two levers that extract the most value from a par-fill assumption.
  Any re-optimization under the current fill model will find them again.

### 1.5 Red flags that were visible in the sealed stats themselves

Payoff ratio 9.63. Average holding period 1.00 bars for winners *and* losers. Max drawdown
$70 on +$4,675 across 712 trades. 73% stop-out rate with a $3.88 average loss. Each of
these alone is a "too good" signal; together they describe a strategy that lives entirely
inside single 1-minute bars, which no 1-minute-bar simulator can price. Add a "too-good
checklist" and a mandatory fill-degradation stress test to the anti-overfitting playbook
before any future seal.

### 1.6 What could still be wrong with this analysis

- V5 assumes every stop gaps to next open. In liquid names a resting stop fills closer to
  level. Counter-evidence: live losers averaged −$32.15, worse than V5's −$28.02.
- Variants recompute exit prices post hoc rather than re-running the event loop, so a
  trade that would have re-entered after an earlier exit is not modeled. This cuts both
  ways and does not change sign.
- Micro-pullback (Trial 167) was not stress-tested. It shares the engine pattern and is the
  worst live performer; assume it is in the same class until shown otherwise.
- The per-trade `paper_pnl` vs `cf_pnl` comparison in Neon `live_trades` could not be
  pulled: the subagent sandbox had no SOPS age key. It would corroborate, not overturn.
  See §5 for the five-minute query the owner can run.

### 1.7 Addendum (same day): live counterfactual data pulled, hypothesis supported

The Neon `live_trades` pull ran after the draft above (49 rows; the six rows stamped
2026-07-07 are a re-insert of the 07-06 session, leaving 43). Export at
`research/analysis/outputs/live_trades_2026-07.csv` (gitignored).

- **Real stop-outs:** on the rows where paper actually exited via a stop (STOP_LOSS n=7,
  STOP_FILLED_SERVER n=2, STOP_REJECTED_MARKET_EXIT n=1), paper lost **−$48.88 /
  −$62.90 / −$24.60** on average while the sim replay of the same tape lost **−$23.39 /
  −$18.55 / −$9.02**. Decomposition: exit-side gap −$41.64 per trade vs entry-side +$5.63.
  The sim's stop fill is better than the realized stop fill by roughly $25–45 per trade,
  and the gap is on the exit, not the entry. This is the live fingerprint of §1.3, and it
  is *larger* than the honest sim's −$28 estimate.
- **Trail scratches:** most live exits (25 of 43) were TRAILING_STOP under the old
  near-zero trail, averaging −$3.89. That config no longer exists; those rows say
  nothing about the current 2.0% configs and are the previously documented
  trail-overfit effect, not a counter-signal.
- **Sim cannot predict the same trade on the same tape:** 22 of 43 trades (51%) have
  opposite-sign paper vs counterfactual P&L. Whatever the strategy's true expectancy, a
  replay that disagrees with reality on direction half the time is not a validation
  instrument.
- Per-strategy paper vs cf totals (43 trades): scalp −$138 vs −$51, VWAP −$147 vs −$409,
  MP −$366 vs −$140. Small samples; directional only.

---

## 2. Q2 — Does the sim→live gap indict the strategy or the execution?

**It indicts the simulator first, the strategy second, execution a distant third.**

The framing in the briefing ("43 mostly-broken trades cannot separate bad strategy from
broken execution") is correct for *mean P&L* and wrong for *loss size*. The contaminated
entry pipeline affects which trades got in. It does not affect what happened after they
were in, and that is where the signal is:

| | Sealed sim (V0) | Honest sim (V5) | Live (43 trades) |
|---|--:|--:|--:|
| avg loser | −$3.82 | −$28 | **−$32.15** |
| avg winner | +$36.81 | ~+$45 | +$13.61 |
| payoff | 9.63 | 1.75 | 0.42 |
| WR | 25.6% | 24.9% | 37% |
| per-trade mean | +$6.57 | −$8.65 | −$15.1 |

Under the sealed model a stop fills at par, so 27 losers averaging −$32 is not a tail
event, it is impossible. The loss-size statistic rejects the sealed exit model on its own,
with no appeal to sample size. Under the honest model live losers are exactly where they
should be.

Power on the mean, for completeness. Live per-trade SD is about $22; SE over 43 trades is
about $3.4. Live mean −$15.1 sits roughly 6 SE below the sealed +$6.57 and roughly 2 SE
below the honest −$8.65: it rejects the sealed number and is consistent with the honest
one. Restricting to the ~7 post-fix trades, SE is about $8; that sample alone cannot
distinguish anything, which is why the argument above rests on loss size, not mean.

What live adds beyond the honest sim: winners are smaller (+$13.6 vs ~+$45) and WR is
higher. That pattern is limit-entry adverse selection (you get filled when price comes
back through you) plus spread. It is a real execution cost, but it is a second-order
effect on top of a strategy that is already negative before it.

For Q4 sizing: detecting a modest real edge of +$3/trade at SD $22 with 80% power needs
roughly 340 trades. At the observed ~5 trades/session that is about 65 sessions. Live
gates should be written in R-multiples (per-trade P&L divided by planned risk) so that
sizing changes do not invalidate the count.

---

## 3. Q3 — Is funding Tradier ~$2,000 a justified bet?

**Not now. Yes, conditionally, after Gate 1.**

Framed as a bet:

- **What it buys:** real-time premarket volume, which unblocks the scanner, which unblocks
  live trading of the *current* configs. Also enables Tradier as a real-money broker.
- **What it costs:** ~$50/yr inactivity fee if idle, opportunity cost on $2,000 (call it
  $80–100/yr), and the real cost: it restarts the "system is running, let's see what the
  tape says" loop for strategies the honest sim already prices negative. That loop has
  consumed five months.
- **Cheaper experiment reaching the same conclusion:** already run. It took 35 seconds
  against the local DB. The honest-fill stress test *is* the cheap experiment, and it came
  back negative for every deployed config.

Decision tree:

```
Gate 0: honest fill model shipped as sim default        ($0, ~1 day)
  └─ re-score Trial 211/188/167 under it
       ├─ any PF ≥ 1.3 on sealed 2025?  → unlikely; if yes, skip to Gate 2 for that one
       └─ none                            → retire all three (expected)
Gate 1: re-optimize under honest sim, structural stops  ($0, ≤ 6 weeks, deadline 2026-11-20)
  ├─ a config clears §4 Gate 1 bar   → FUND TRADIER, go to Gate 2
  └─ nothing clears                  → STOP jTrader (keep infra; jSwing is the pivot)
Gate 2: live, tiny real money, R-multiple accounting     (~$2,000 parked, ≤ 3 months)
  ├─ passes §4 Gate 2 bar            → scale per risk plan
  └─ fails                           → STOP
```

On the owner's stated preference ("real money early, tiny positions, skip extended paper"):
this review agrees with it as a *validation philosophy*. Alpaca paper's REST lag and
partial-fill streaming are themselves noise sources; tiny real money is a cleaner
instrument and the tuition at 1% risk is small. The preference presupposes a candidate
worth validating. Today there is none, and the ones on deck were selected by a scorer that
rewarded exactly the behavior that loses live. So: real money should start the day a
config passes Gate 1, and it should be real rather than paper. Not before.

---

## 4. Q4 — Kill criteria

A project without these ends by exhaustion. These are proposed as defaults the owner can
tighten but should not loosen without writing down why.

**Gate 0 — Honest simulator. Deadline 2026-10-09. → DONE 2026-09-18.** Event-loop
implementation (not post-hoc) re-scores 2025: scalp 211 −$5,137 / PF 0.61, VWAP 188
−$4,039 / PF 0.66, MP 167 −$636 / PF 0.93. `par` mode reproduces the sealed anchors
bit-for-bit. All three configs retired. 13 new tests.
- Ship: stops fill at `min(stop, next bar open)`; target/trail/time exits fill at next bar
  open; exit slippage ≥ 0.3%; trail peak computed from *completed prior* bars only.
- Re-score the three deployed configs. Retire any with sealed-2025 PF < 1.3 (expected: all).
- Ship the loud-auth-failure fix for `_fetch_timesales` regardless.
- Kill: if Gate 0 is not done by the deadline, the project is paused until it is.

**Gate 1 — Re-optimization under the honest sim. Deadline 2026-11-20.**
- Walk-forward exactly as the playbook: train 2021–23, select 2024, seal 2025, with 2026
  YTD as a second untouched check. Structural stops (below pullback low / VWAP−$0.10),
  ≤ 15 params, no % trail.
- Pass bar, all required: sealed-2025 PF ≥ 1.5 on ≥ 250 trades; 2026 YTD positive; payoff
  ≥ 1.2; max DD ≤ 20% of annual P&L; PBO < 0.5 or deflated Sharpe > 0 per playbook §2.5–2.6;
  survives V6 (extra slippage) with PF ≥ 1.3.
- Kill: no strategy passes by the deadline → stop jTrader development. Archive, keep
  infra, redirect effort to jSwing.

**Gate 2 — Live, tiny real money. Fund Tradier only on Gate 1 pass. Runs ≤ 3 months.**
- Account in R-multiples; planned risk per trade fixed and logged.
- Check at 40 trades: kill if cumulative ≤ −15R or payoff < 0.8.
- Check at 100 trades or 60 sessions, whichever first: kill if PF < 1.1, or if
  `paper_pnl` vs `cf_pnl` divergence exceeds 40% of gross profit (meaning the honest sim
  is still lying and the loop must return to Gate 0).
- Continue/scale: PF ≥ 1.3 at 100 trades with payoff ≥ 1.2.

**Inactivity kill (addresses the drift pattern).**
- Any gate 30 days past deadline with no check-in → STATUS.md gets a `PAUSED` headline.
- Three consecutive missed check-ins → project is stopped by default, not by decision.

**Hard stop date.** If no live PF ≥ 1.2 over ≥ 100 real-money trades exists by
**2027-03-31**, stop.

---

## 5. Follow-ups the owner can do in minutes

1. **Pull the counterfactual table.** On a machine with the SOPS age key:
   ```
   sops -d production/.env.render | grep DB_DSN   # then, with psql against it:
   SELECT strategy, exit_reason, count(*), avg(paper_pnl), avg(cf_pnl),
          avg(cf_pnl - paper_pnl), avg(paper_exit - cf_exit) AS exit_gap
   FROM live_trades GROUP BY 1,2 ORDER BY 1,2;
   ```
   Expect `cf_pnl > paper_pnl` concentrated in stop-loss rows with a positive `exit_gap`.
   That is the live-side fingerprint of §1.3. Also dump all 49 rows to
   `research/analysis/outputs/live_trades_2026-07.csv` (gitignored) so future agents do
   not need Neon.
2. **Close the orphaned BIYA position** on Alpaca paper.
3. **Reconcile the scalp trail value.** `live_scalp_runner.py:69-84` shows
   `trailing_stop_pct=2.70`; STATUS says all three run 2.0%. One of them is wrong.
4. **VWAP seal is stale.** Trial 188 reproduces at PF 1.00 on the current DB against a
   sealed 2.19. Per `data_versioning_sealed_tests`, compare against
   `research/optimizer/vwap/fp_2025_sealed.json` before citing that number again.

---

## 6. Appendix — sources

- Code map: `production/trading/{scalp,vwap,micro_pullback}_engine.py`,
  `production/simulator/{scalp,vwap,micro_pullback}_simulation.py`,
  `production/simulator/fill_model.py`, `production/trading/live_scalp_runner.py`,
  `production/data/live_capture/session_report.py:51-70, 448-466`.
- Runs: `research/maintenance/diagnostics/_scratch/{run_baseline,run_exit_variants,
  f1_by_reason,f2_f3_v5v6,f4_2026}.py`; outputs `baseline.json`, `variants.json`,
  `scalp_2026.json`. Full-year runs took ~35 s each.
- Sim sizing: `shares = min(risk_amount / stop_distance, max_position_value / entry)`;
  Trial 211 risk_pct 2.30% of a $5,000 default account, capped by a ~$778/slot position
  ceiling. The cap binds almost always, which is why the "risk" parameter and the $3.88
  average stop loss can coexist.
