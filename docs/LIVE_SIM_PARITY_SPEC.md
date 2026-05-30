# Sim De-Logic-ing Plan (a.k.a. Live/Sim Parity)

**Status:** plan. Rewritten 2026-05-29 to match the standing architecture rule.
**Supersedes** the earlier "make live match sim" framing — that was backwards.

## The rule (non-negotiable)

> **There is ZERO trading logic in the simulator.** All logic for how stocks are
> found, evaluated, entered, sized, added to, and exited lives in `trading/`. The
> simulator is ONLY two things: a **data-feed adapter** (replays DB bars one minute at
> a time) and a **broker adapter** (simulates fills + tracks P&L). When we go live we
> stop using the simulator entirely — we swap in a live data feed and a real broker,
> and the engine is byte-for-byte the same.

If a change adds an `if`/threshold/indicator/decision to `simulator/`, it is in the
wrong place. Full stop.

---

## Why this keeps regressing

The pure *evaluators* are already extracted and good:
`entry_engine.evaluate_entry`, `exit_engine.evaluate_exit`,
`add_on_engine.evaluate_add_on`, `scoring_engine`, `market_temperature`,
`patterns`, `indicators`, `portfolio_manager`, `trading_engine` (Trade/PositionManager).

What is NOT extracted is the **orchestration** — the per-minute loop that calls those
evaluators in the right order, builds the indicator dicts, picks the best signal,
composes the size multipliers, runs the temperature state machine, and gates on
portfolio rules. That orchestration currently lives **inside
`simulation_engine.py`** (`_process_minute` + `_scan_for_entry`), and a thinner,
*different* copy lives in `live_scanner.py`. Two copies → they drift → bugs like H0
(dead MACD) get written into the sim. The fix is to extract the orchestration into
`trading/` so there is exactly ONE copy.

---

## Target architecture

```
trading/                          ← THE ENGINE (all logic, one copy)
  orchestrator.py   (NEW)         ← the per-minute decision pipeline
  data_feed.py      (NEW)         ← DataFeed interface (Protocol)
  broker.py         (NEW or reuse broker/base.py) ← Broker interface
  entry_engine / exit_engine / add_on_engine / scoring_engine
  market_temperature / patterns / indicators
  portfolio_manager / trading_engine (Trade) / sizing.py (NEW, extracted math)

simulator/                        ← ONLY adapters, ZERO logic
  replay_feed.py    (NEW)         ← DataFeed: yields DB minute bars in time order
  sim_broker.py     (NEW)         ← Broker: instant fills, P&L, balance (wraps PositionManager)
  simulation_engine.py            ← SHRINKS to: load bars → feed → orchestrator → sim_broker

live/ (live_scanner.py)           ← ONLY adapters, ZERO logic
  live_feed   = Alpaca/Tradier stream      (DataFeed)
  live_broker = LiveTradeManager           (Broker)
  → constructs the SAME orchestrator
```

### The two interfaces the sim shrinks down to

```python
class DataFeed(Protocol):
    def bars(self) -> Iterator[tuple[datetime, list[BarDict]]]:
        """Yield (minute_ts, [bars for that minute]) in chronological order.
        Sim: replay from DB.  Live: block on the stream until the minute closes."""

class Broker(Protocol):
    def has_position(self) -> bool: ...
    @property
    def position(self) -> Trade | None: ...
    def enter(self, signal, *, float_shares, size_multiplier, ref_price) -> Trade | None: ...
    def exit(self, exit_signal, when) -> float: ...
    def add_on(self, add_on_signal, when) -> int: ...
    def balance(self) -> float: ...
```

`SimBroker` wraps `PositionManager`; `LiveBroker` wraps `LiveTradeManager`. The
orchestrator only ever touches these two interfaces — never the simulator, never a
broker SDK.

---

## Inventory — every piece of logic to MOVE OUT of `simulation_engine.py`

Source: line-level audit of `_process_minute` (561-778) + `_scan_for_entry` (780-1001).

| Currently in sim | What it is | Moves to |
|---|---|---|
| 9:25 `classify_premarket` + apply temp params (576-594) | temperature state machine | `orchestrator` (calls `market_temperature`) |
| Build exit indicators dict — ema9/macd/avg_buy_vol (619-653) | indicator assembly | `orchestrator` (calls `indicators`) |
| `evaluate_exit` call + apply + trade_log (655-706) | exit orchestration | `orchestrator` → `broker.exit()` |
| `time_decay_exits` / `stop_hit_counts` tracking (680-686) | re-entry/cooldown state | `orchestrator` session-state object |
| `update_from_trade_result` on close (687-699) | temperature update | `orchestrator` |
| Add-on indicators + `evaluate_add_on` + apply (712-758) | add-on orchestration | `orchestrator` → `broker.add_on()` |
| `session_high_at_add` watermark advance (755-758) | position bookkeeping | `Trade`/`orchestrator` |
| portfolio rule gate `any_rule_fired` (760-778) | risk gating | `orchestrator` (calls `portfolio_manager`) |
| session-stop `is_session_over` gate (765-767) | entry gating | `orchestrator` |
| `_scan_for_entry`: price/gain pre-filter, hot-symbol filter (812-844) | candidate screen | `orchestrator` (or a `candidate_filter` in trading/) |
| rel-vol resolution (precomputed col + DB fallback) (848-893) | data lookup | DataFeed should ATTACH `rel_vol` to each bar; orchestrator just reads `bar['rel_vol']` |
| `evaluate_entry` loop + best-signal selection (899-939) | entry orchestration | `orchestrator` |
| size multiplier composition gap14×score×cushion (947-967) | sizing logic | `sizing.py` (called by orchestrator) |
| `enter_position(...)` + trade_log (969-999) | entry execution | `orchestrator` → `broker.enter()` |

What **STAYS** in `simulator/` (legitimately its job):
- `load_minute_bars`, the time-indexed bar arrays, the persistent parquet cache →
  these become the **ReplayFeed** (data-feed adapter).
- `PositionManager` fills + balance + daily-loss tracking → wrapped by **SimBroker**.
  (Note: `PositionManager` currently lives in `trading/trading_engine.py`, which is
  correct — the SimBroker just adapts it. Live uses LiveTradeManager the same way.)

After the move, `simulation_engine.run()` is essentially:
```python
feed = ReplayFeed(self.date, ...)        # loads bars, attaches rel_vol per bar
broker = SimBroker(account_size, ...)
orch = Orchestrator(configs..., broker=broker)
for minute_ts, bars in feed.bars():
    orch.on_minute(minute_ts, bars)
return broker.summary()
```

---

## Increment plan (safe, ordered — test after each step)

Do NOT do this as one big-bang commit. Each step keeps sim P&L identical (a
golden-day regression check) before moving on.

0. **Fold in the MACD fix.** The other session fixed H0 (uncommitted, won't commit).
   Bring those edits in here, but as part of the extraction — the fixed
   indicator-build code moves to the orchestrator, not back into the sim.
1. **Establish a golden-day baseline.** Pick 3-5 representative days; record exact
   trades + P&L from the current sim. This is the regression oracle for every step.
2. **Define interfaces** `trading/data_feed.py`, `trading/broker.py` (+ `sizing.py`
   with `compute_shares` extracted from PositionManager).
3. **Create `SimBroker`** wrapping PositionManager; route the sim's enter/exit/add_on
   through it. No logic moves yet — just the call indirection. Re-run golden days.
4. **Create `Orchestrator.on_minute`** and move `_process_minute`'s body into it
   verbatim, calling `broker.*` instead of `self.position_manager.*`. Sim's
   `_process_minute` becomes a one-line delegate. Re-run golden days (must match).
5. **Create `ReplayFeed`** from `load_minute_bars` + the rel-vol resolution, so each
   yielded bar already carries `rel_vol`. Orchestrator stops doing DB lookups.
   Re-run golden days.
6. **Point `live_scanner` at the same Orchestrator** via `LiveBroker` + a live
   DataFeed. Delete the duplicated decision code in `live_scanner.process_bar`.
7. **Parity regression test** `research/optimizer/parity_check.py`: feed the SAME
   recorded bars to (a) ReplayFeed+SimBroker and (b) live DataFeed-stub+LiveBroker in
   dry-run; assert identical entries/exits/sizes/P&L. This guard stops the drift from
   ever returning.

## Prereqs / coupling
- H0 (MACD) — DONE in the other session (uncommitted). Fold into step 0.
- H1 (PositionManager balance double-counts partials) — fix while building SimBroker
  (step 3); it's broker accounting, exactly where it belongs.

## Risks
- Big refactor; the golden-day regression check after every step is mandatory.
- Keep ALL live-only concerns (broker latency, `time.sleep`, order polling) inside
  `LiveBroker` — never in the orchestrator, or the sim slows to a crawl.
- `rel_vol` attachment: the sim precomputes `rel_vol_30d`; live computes it live. Both
  must satisfy the same `bar['rel_vol']` contract so the orchestrator stays clean.

*Plan by the elated-euclid worktree session (Opus 4.8).*
