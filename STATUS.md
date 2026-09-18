# STATUS — where the project is right now

**One-screen current state. Rewrite the top sections each working session.**
History goes in `docs/PROJECT_HISTORY.md`; durable facts in `memory/`; this file is
the "what's true today / what's next / what's blocking" snapshot an agent reads first.

_Updated: 2026-09-18 (Fri) — post deep review_

---

## ⚠️ The headline

**Deep review (2026-09-18) verdict: the sealed backtests are not evidence of an edge.**
Full write-up in `docs/DEEP_REVIEW_2026_09.md`. The simulator fills every stop at the
exact stop price with no gap-through; scalp Trial 211's whole sealed edge lives in that
assumption. Under the most live-favorable realistic fill model (V5: resting broker stop
with gap-through, other exits at next bar open):

| | Sealed (V0) | Honest (V5) | Live (43 trades) |
|---|--:|--:|--:|
| Scalp 211, 2025 | +$4,675 / PF 3.31 | **−$6,163 / PF 0.58** | — |
| Scalp 211, 2026 YTD | +$1,013 / PF 5.04 | −$573 / PF 0.71 | — |
| VWAP 188, 2025 | +$13 / PF 1.00 (seal 2.19 no longer reproduces) | −$851 / PF 0.91 | — |
| avg loser | −$3.82 | −$28 | **−$32.15** |

Live losers match the honest sim, not the sealed one. The sim→live gap indicts the
simulator, then the strategy. Execution is a distant third.

**Decisions taken by the review (owner to confirm or override):**
1. Do **not** fund Tradier yet. Zero-dollar work first.
2. Retire Trial 211 / 188 / 167 as live configs (stopping needs no backtest gate).
3. Gate 0 by **2026-10-09**: make the honest fill model the sim default, re-score.
4. Gate 1 by **2026-11-20**: re-optimize under it with structural stops; nothing passes
   → stop jTrader. Kill criteria and gate bars are in the review §4.
5. Fund Tradier and go live with tiny real money only after Gate 1 passes.

Secondary: the system has not placed a trade since 2026-07-20 (Tradier data feed dead,
see Blockers). Total live trades ever recorded: **49** (43 after removing one duplicated
session).

## Deployed / live (paper)

- **jTrader** on Render (`https://jtrader-api.onrender.com`): daily session =
  Opening Bell Scalp (9:30–9:40) → Micro-Pullback (9:40–10:00) → VWAP Reclaim
  (10:00–11:30).
- **Split broker architecture** (this trips people up):
  - **Orders/fills → Alpaca paper** (websocket `trade_updates` stream). Working.
  - **Market data → Tradier production token.** Dead since Jul 22.
  - Alpaca's free tier is IEX-only and does not serve same-day premarket volume —
    that gap is the entire reason Tradier is in the stack.
- Dashboard: `jtrader-dashboard.vercel.app`. Falls back to DEMO mode with fake
  symbols (ABCD/EFGH) when the API fetch fails — check the DEMO badge before
  believing any number on it.

## Live configs in use

- **Scalp**: Trial 211. Sealed 2025 expectation **+$4,675 / PF 3.31** (re-baselined
  by issue #23; the older +$5,956/PF 2.70 included phantom fallback fills).
- **VWAP**: Trial 188 (sealed PF 2.19 / +$3,299), deployed Jul 10.
- **Micro-Pullback**: Trial 167. UNDER REVIEW — worst live performer.
- All three carry a hand-set **2.0% trailing stop** (`d01a7d5`), replacing Optuna's
  near-zero values. **This config has never executed a single live trade.**
  (Discrepancy: `live_scalp_runner.py:69-84` shows `trailing_stop_pct=2.70` — reconcile.)
- **All three are slated for retirement** per the deep review; none survives a realistic
  exit-fill model. Do not deploy or re-tune them under the current simulator.

## Blockers

1. **🔴 Tradier account is deactivated — this blocks everything.**
   `401 Access Token not approved` on every endpoint since Jul 22. Root cause is
   **not** a token bug: the Tradier brokerage account has $0 balance and zero
   executed trades, and Tradier gates API/data access on funding status
   ("Your Login Is Inactive... fund your account to regain active status on your
   account and api access"). Documented policy: <$2,000 balance AND <2 trades/year
   → inactive + $50/yr fee. **Fix requires funding the account (~$2,000) — a human
   decision, not a code change.** No free alternative found for real-time premarket
   volume (Finnhub's free tier 403s on the volume endpoint; Alpaca free is IEX-only).

2. **🟠 Silent-failure amplifier.** `_fetch_timesales` catches all exceptions and
   returns `[]`, which is indistinguishable downstream from "symbol genuinely had no
   prints." Combined with the issue #23 exclusion filter, a broken token silently
   excludes the entire universe. Three weeks passed before anyone noticed. Fixing
   this so auth failure is loud is cheap and should happen regardless of #1.

3. **🟡 Orphaned BIYA position** — 7 shares on the Alpaca paper account since Jul 20,
   now −$34.81. The *bug* that created it is fixed (`6a876ca`), but the stranded
   shares need a manual close.

## Live results to date (the number that matters)

43 clean trades, 8 sessions, Jun 30 – Jul 20:

| | avg | count |
|---|---|---|
| Winners | **+$13.61** | 16 |
| Losers | **−$32.15** | 27 |

**Total −$650. Win rate 37%. Payoff ratio 0.42.** Breakeven at 37% WR needs ~1.7,
so the live payoff profile is roughly 4× away from viable. Per strategy:
micro-pullback −$365 (17% WR), VWAP −$147, scalp −$138.

**Critical caveat on that sample:** fills were broken for most of it. Limit entries
had a 0% fill rate Jul 7–14; the websocket fill fix landed Jul 16; the rel-vol junk
filter landed Jul 17. **Only Jul 16 and Jul 20 ran anything close to the corrected
pipeline** — roughly 7 trades. This sample cannot cleanly separate "bad strategy"
from "broken execution."

## Known-bad tooling (do not trust these)

- **The simulator's exit fill model is structurally optimistic (deep review §1).**
  Stops, targets, and trails all fill at the exact trigger level on an intra-bar touch,
  no gap-through, no exit slippage, trail peak taken from the same bar being tested.
  98% of the sealed scalp edge is stop fills at par (518 stops avg −$3.88; realistic
  −$28). **No P&L number from the current sim is evidence until Gate 0 ships the honest
  fill model.** The earlier trail-width finding below is one instance of this.
- **The simulator cannot rank trailing-stop width.** It scores exits against 1-minute
  bars with perfect hindsight of each bar's peak, so it monotonically prefers tighter
  trails with no interior optimum — verified across both 2025 (250d) and 2026 YTD,
  and again against the structural-exit variant. Its P&L verdict on any exit-width
  question is not evidence.
- **VWAP Trial 188 sealed number (PF 2.19 / +$3,299) does not reproduce** on the current
  DB (PF 1.00 / +$13). Check `research/optimizer/vwap/fp_2025_sealed.json` before citing.
- **Dashboard DEMO mode** silently serves fabricated symbols when the API is down.

## Next actions (from deep review, in order)

1. **Gate 0 — DONE 2026-09-18 (same day).** `exit_fill_mode='honest'` is now the sim
   default (`fill_model.py::resolve_honest_exit_fill`, wired in all three simulators;
   `'par'` = legacy, bit-identical). Re-score, 2025 full year:

   | config | par | honest |
   |---|--:|--:|
   | Scalp 211 | +$4,675 / PF 3.31 | **−$5,137 / PF 0.61** |
   | VWAP 188 | +$13 / PF 1.00 | **−$4,039 / PF 0.66** |
   | MP 167 | +$1,640 / PF 1.28 | **−$636 / PF 0.93** |

   All three retired. Optimizer scripts pass configs through, so they inherit honest
   mode with no change. Still open from Gate 0: loud auth failure in `_fetch_timesales`;
   `test_scalp_engine.py::test_param_count` is stale (pre-existing, expects 14, config
   has 19 fields incl. non-tunables) — fix by counting tunables only.
2. **Owner, 5 min:** run the `live_trades` counterfactual query in review §5 on a machine
   with the SOPS age key; export the 49 rows to `research/analysis/outputs/` (gitignored).
3. **Gate 1 (≤ 2026-11-20, $0):** walk-forward re-opt under honest sim, structural stops,
   ≤ 15 params, no % trail. Pass bar in review §4.
4. Close orphaned BIYA; reconcile scalp trail 2.70 vs 2.0.

## Open issues

| # | Title | State |
|---|---|---|
| 24 | Structural Ross exits (scale-out + candle-low/EMA-9 trail) | stage 1 **merged, inert** (`trail_mode` opt-in); stage 2 (scale-out) not started; backtest inconclusive |
| 16 | Off-by-one `bars_since_open` live validation | needs 3 clean trading days |
| 13 | Audit backlog: remaining known TODOs | open |
| 10 | Trial 211 live fill-parity check | needs 1 week of live fills |

Note: #16 and #10 both require live trading days, which are blocked on Tradier.

## Structural-exit work (issue #24 stage 1) — merged, inert

Structural trail (prior-N-bar low for VWAP, EMA-9 for MP) is on main behind an opt-in
`trail_mode` config, wired through both engines, both sims, both live runners, 8 tests.
**No deployed config sets `trail_mode='structural'`, so it changes no live behavior.**
The sim cannot judge this class of change, so its worse-than-2% result is not evidence
either way — only live data can settle it. Stage 2 (scale-out at resistance) needs
partial-position accounting across sim and live and has not been started.

## Agent roster (added Sep 9)

`strategy-architect` (fable) · `quant-runner` (sonnet) · `trade-logic-reviewer` (opus)
· `cavecrew-investigator` (haiku). Routing rules and delegation economics in
`.claude/CLAUDE.md`. `defaultSubagentModel` = sonnet.

## Operational runbook notes

- **Never push to main before 12:00 ET on trading days.** A deploy at 11:55 once
  launched a second concurrent live session.
- Local backtest DB is Docker (`stockdata-timescale`). Docker Desktop crash-loops on
  ghost socket files after an unclean shutdown — kill all docker procs,
  `wsl --shutdown`, rename `%LOCALAPPDATA%\Docker\run` and `docker-secrets-engine`,
  start once.
- Neon/Alpaca creds come from SOPS-encrypted `production/.env.render`. Never echo a
  secret value.
- DB coverage: `rel_vol_cum_cache` through 2026-06-12 — top up before running sims
  against recent weeks.
