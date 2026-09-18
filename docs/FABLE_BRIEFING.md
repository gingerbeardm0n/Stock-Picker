# Fable Briefing — jTrader Deep Review

**Read this file and `STATUS.md` completely before taking any other action.**
Together they are the full context. Do not explore the codebase to rebuild state
that is already written down here — that is the single largest way to waste the
budget this session exists to conserve.

_Written 2026-09-18 for a deep-reasoning review session._

---

## 1. Why you are here

jTrader is an autonomous day-trading system built on Ross Cameron's methodology.
Five months of engineering. **Zero profitable live evidence.** It has not placed a
trade in 60 days because a data-feed account was deactivated.

You are not here to write code or fix bugs. You are here to answer whether this
system is on a path to profitability, and what the owner should do next — including
the possibility that the honest answer is "stop, or change something fundamental."

The owner is funding this session with expiring credits. He wants judgment, not
activity. A thorough survey that ends without a recommendation is a failed session.

## 2. Token discipline — non-negotiable

Your output tokens cost roughly 5× a Sonnet subagent's. **Stop doing work that a
cheaper model can do.** Your job is to decide; their job is to fetch.

**Delegate — never do these yourself:**

| Need | Spawn | Model |
|---|---|---|
| "Where is X / what calls Y / map this area" | `cavecrew-investigator` | haiku |
| Any backtest, sweep, or DB query | `quant-runner` | sonnet |
| Correctness review of order/fill/P&L code | `trade-logic-reviewer` | opus |

**Rules:**
- Do not `Grep`/`Glob` the codebase yourself. Spawn the investigator.
- Do not run a simulation yourself. Spawn `quant-runner`.
- **Batch your asks.** Decide everything you need from a subagent, then make one
  request. Each round-trip re-pays the cold-start cost.
- Do not delegate anything answerable from this file or `STATUS.md`. Delegation
  under ~3 tool calls costs more than doing it inline.
- Think in long silent stretches; write short. Reasoning is cheap for you to *do*
  and expensive for you to *print*.

**Produce a written artifact.** End the session by writing your conclusions to
`docs/DEEP_REVIEW_2026_09.md` and updating `STATUS.md`. A verdict that exists only
in chat scrollback will be lost and re-derived at full price later.

## 3. Settled questions — do NOT re-derive these

Each cost real time to establish. Treat as given unless you find direct
contradicting evidence.

- **The simulator cannot rank trailing-stop width.** It scores exits against 1-min
  bars with perfect hindsight of each bar's peak → monotonically prefers tighter
  trails, no interior optimum. Verified on 2025 (250d), 2026 YTD, and against the
  structural-exit variant. Its P&L verdict on exit-width questions is not evidence.
- **Ross Cameron uses no percentage trailing stop at all.** Corpus (1,799 sessions):
  scale out at resistance (~1,764 occurrences, the single most common exit), runner
  trails structurally (prior 5-min candle low; above EMA-9). Stops are structural
  too (below pullback low, VWAP−$0.10), never a flat %.
- **The Optuna near-zero trails (0.0014%) were overfit artifacts**, not a discovery —
  they game 1-min bar granularity and scratch every live winner on tick noise.
  Replaced with a hand-set 2.0% that has never traded live.
- **Tradier's lockout is a funding gate, not a token bug.** $0 balance + 0 trades →
  account inactive → API access revoked. Needs ~$2,000 funded. No code fixes this.
- **No free real-time premarket-volume source exists.** Alpaca free = IEX-only, no
  same-day premarket. Finnhub free = `/quote` has no volume field and
  `/stock/candle` returns 403. Both tested directly, not assumed.
- **News "presence" tier was a false signal** (generic movers-roundup articles);
  removed as a catalyst.
- **VWAP's apparent news edge was a lookahead artifact** — fixed by capping the
  backtest news window at 9:30 ET; strategy re-optimized to Trial 188.
- **Alpaca paper's REST `get_order` lags minutes**; fills must come from the
  `trade_updates` websocket. Paper also streams partial fills for ~2 minutes before
  the terminal fill.

## 4. The questions, ranked

### Q1 — Is the simulator's exit modeling systematically optimistic, and if so, is every sealed profit factor inflated?

This is the deepest question and probably the most important.

Known: the sim assumes exits fill at exactly the trail/stop/target price. Known: it
has one *proven* structural blind spot around exit width. Observed live: the payoff
ratio problem is **entirely an exit-shape problem** — winners cut to +$13.61, losers
run to −$32.15.

If the sim systematically overestimates exit quality, then the sealed numbers
(scalp PF 3.31, VWAP PF 2.19) are measuring something that cannot survive real
exits, and the entire walk-forward validation apparatus — the thing this project
has invested most heavily in — is calibrated against a fantasy.

Consider: is the blind spot specific to trail width, or is it the general case of
which this is one instance? What would distinguish those two possibilities using
data already in hand?

### Q2 — Does the sim→live gap indict the strategy, or the execution?

Sealed backtest says scalp = **+$4,675 / PF 3.31** (250 days, 2025).
Live says **−$650 / payoff 0.42 / 37% WR** (43 trades).

But that live sample is badly contaminated: limit entries had a **0% fill rate
Jul 7–14**, the websocket fill fix landed Jul 16, the junk-symbol filter landed
Jul 17. **Only ~7 trades ran the corrected pipeline.**

What can honestly be concluded from 43 mostly-broken trades? What is the
statistical power here to distinguish PF 3.31 from PF 0.4? Be rigorous rather than
rhetorical — the owner has been burned by confident conclusions from thin samples.

### Q3 — Is funding Tradier ~$2,000 a justified bet, and what is the decision tree?

This is the concrete near-term decision. It unblocks everything, but it is real
money committed to a system with no demonstrated edge.

Frame it as a bet: what does it buy, what does it cost if the answer comes back
negative, and is there a cheaper experiment that reaches the same conclusion?
Note that the funded balance is not *spent* — it sits in a brokerage account — so
the true cost is opportunity cost plus the $50/yr inactivity fee, not $2,000.

### Q4 — What are the kill criteria?

Five months in, zero profitable live evidence, and the owner has drifted into a
pattern of long gaps between check-ins. Force the question he has not asked:
**what would have to be true to stop?**

Define continue/stop criteria concretely — trade count, payoff ratio, elapsed time,
dollar drawdown. A project without kill criteria ends by exhaustion rather than
decision. This is a service to him even if the answer is "continue."

## 5. Constraints on any recommendation

- **Anti-overfitting is the prime directive.** `docs/ANTI_OVERFITTING_PLAYBOOK.md`.
  A 126-param monolith once went train +497 → validate median −1593. Strategies are
  now ~13 params each, walk-forward (train / select / SEALED). Any proposal adding
  tunable parameters carries the burden of proof.
- **Strategy changes require a backtest gate** (`strategy-change` label). *Stopping*
  a strategy does not; starting or altering one does.
- **Live > sim when they disagree.** Live is ground truth; the sim approximates it.
- **The owner's stated preference** (from memory): *"real money early, tiny positions
  (1% risk), skip extended paper."* This is in direct tension with "we have no valid
  live evidence yet." Address that tension explicitly — do not quietly pick a side.
- Real money is the eventual destination. For each recommendation, state the
  downside if you are wrong.

## 6. Suggested opening sequence

1. Read `STATUS.md` and this file. (Done — you are here.)
2. Batch one request to `quant-runner`: the live-vs-counterfactual divergence on all
   49 rows of `live_trades` (the `paper_pnl` vs `cf_pnl` columns are the richest
   signal available — `cf_pnl` is what the sim says the *same* trade should have
   done), plus whatever exit-quality comparison you want for Q1.
3. Batch one request to `cavecrew-investigator` for any code locations you need.
4. Think. Decide. Write `docs/DEEP_REVIEW_2026_09.md`.

Lead with the recommendation. Evidence second. The reader is technical, owns the
system, and wants the answer first.
