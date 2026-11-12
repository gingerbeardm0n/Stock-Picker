# Plan: a model that learns to trade like Ross (imitation model)

_Written 2026-11-12 by Fable for an Opus orchestrator. Joel's idea, Joel's direction. Nothing here has been run._

## The goal in Joel's words

jTrader is a **day trading bot**. Train a model on how Ross Cameron trades, using the ~1,800 video transcripts and
the extraction work from early 2026, so it can (1) pick the stock premarket, (2) get in fast, within 1-5 seconds of
when Ross would, and (3) get out fast. Later: add other day traders, each tagged by name, so the model can learn
the best of each.

This has **not** been tested before. The October "pick model" was a logistic regression on 1-minute bar numbers; it
never saw a transcript and never saw anything faster than a minute.

## How to start (Joel)

Switch to Opus, then paste:

> Read `docs/PLAN_2026_11_ROSS_IMITATION_MODEL.md` and follow the orchestrator prompt in it. Start Phase 1.

---

## Orchestrator prompt (Opus)

You are orchestrating the Ross imitation-model project for Joel in the Stock-Picker repo. You plan, judge and
write the short decisions. You do **not** do bulk reading yourself.

**Read first, and only these:** `STATUS.md`, this file, `docs/DECISION_2026_10_ROSS_EDGE.md` (sections 1-2),
`Ross Cameron Day Trading Videos/JTRADER_PROJECT_BRIEF.md`. Do not open transcripts or extraction files yourself.

**Delegation**
- Bulk reading, parsing, counting and data pulls go to **Sonnet subagents** (`general-purpose` or `quant-runner`
  with `model: sonnet`). Simple file location goes to Haiku (`caveman:cavecrew-investigator`).
- One subagent at a time. Spawn, wait, review its report, then spawn the next. Run agents in parallel only if Joel
  says so in words.
- Every subagent brief names the exact files, the exact output file and its columns, and a report limit
  (under 300 words plus one small table). Subagents write results to disk; they do not paste data back.
- Spot-check each subagent result yourself on 5-10 rows before trusting it.

**Hard rules**
- This is a day trading project. No holds past the close. No drifting to swing or multi-day ideas.
- No spending without Joel's explicit yes naming a dollar amount (Databento credit about $124, any paid feed).
- Never place, change or cancel broker orders. Never create or handle API keys or passwords. Never print secrets.
- Live sessions stay off (`SESSIONS_SUSPENDED = True`) until Joel says otherwise.
- Never push to `main` before 12:00 ET on a trading day. Check ET with Python `zoneinfo`, not Git Bash `TZ=`.
- File placement per `.claude/CLAUDE.md`: scripts in `research/analysis/scripts/`, outputs in
  `research/analysis/outputs/` (gitignored), docs in `docs/`.
- Before any model is scored on held-out data, a pre-registration doc with the pass bar is committed. One look.
- Long jobs run detached (`Start-Process pwsh -WindowStyle Hidden`), with resume markers. The laptop has 14 GB RAM
  and often under 2 GB free: process in batches, never load everything at once.
- Stop and ask Joel at every **GATE** below. Report in plain words: what was found, what it means, what you
  recommend, what you need from him.
- Update `STATUS.md` and memory at the end of each phase.

---

## What exists already

Folder `Ross Cameron Day Trading Videos/` (in the main checkout, `C:\Repositories\Stock-Picker`):

| Path | What |
|---|---|
| `Text transcriptions/` | 1,799 raw transcripts |
| `compressed transcripts/` | 1,855 compressed versions |
| `extractions/` | 27 files, about 100 videos each: prose summary, trades table, other fields (template format) |
| `concepts/` | 17 concept write-ups (entry triggers, add-ons, dip buys, risk rules, ...) |
| `RC_STRATEGY_STATISTICS.md`, `jTrader_Audit_Against_Statistics.md` | statistics from that work |
| `prompts/`, `scripts/`, `reference/` | how the extraction was done |

DB (`stockdata-timescale`, DSN via `liquid_gap_orb_test.DSN`): `ross_*` tables hold a ledger of his dated trades and
1-minute bars for 82% of them (October backfill). Entry times there are **estimates**.

## Design (two parts)

1. **Labels from the extractions.** One row per trade: trader, date, ticker, direction, entry time and how precise it
   is, exit time, entry trigger type, exit reason, result, plus the day's context (why this stock, news, market mood).
   The big language model work is already done; this step only parses and checks it.
2. **A small, fast network on market data.** Input: the last few minutes of second-by-second trades and quotes for a
   stock (plus daily context features). Output: "enter now", "exit now", "do nothing". Trained to match the labelled
   moments, tested on days it never saw. It answers in milliseconds; a language model is not in the live loop.

A `trader` column exists from day one so other traders can be added later without rebuilding.

## Phases

### Phase 1: label audit (Sonnet subagents, free, no market data)
- Subagent A: read `prompts/` and `scripts/` and 1 extraction file; report the template and every field in it.
- Subagents B1..Bn (one per 3-5 extraction files, sequential): parse every trade into
  `research/analysis/outputs/ross_imitation/trades_raw.csv`. Columns: `trader, video_id, video_date, trade_date,
  ticker, side, entry_time, entry_time_precision (second / minute / approx / none), entry_price, exit_time,
  exit_price, shares, pnl, entry_trigger, exit_reason, stock_reason, source_file`.
- Subagent C: summary counts only: trades total, by year, with ticker+date, with entry time at each precision, with
  prices, with exit info; overlap with the `ross_*` ledger.
- **GATE 1 (Joel):** do we have enough labels, and how precise are the times? Likely outcomes:
  - Thousands of trades with second-level times: go to Phase 3.
  - Times mostly approximate: go to Phase 2.
  - Too few trades overall: discuss more sources (more Ross videos, other traders) before going on.

### Phase 2: recover precise entry times (only if Gate 1 says so)
- Entry **prices** are often stated exactly. With second-level trade data, the first moment the stock traded at that
  price inside the stated time window pins the entry to a few seconds. Test this on 50 trades before scaling.
- Fallback: his recap videos show the executions on screen; reading those frames is a larger job. Price it first.
- **GATE 2 (Joel):** precision achieved, and cost of any data needed.

### Phase 3: market data for the labelled trades
- First check what is free: Alpaca historical trades and quotes (SIP) for the trade days. A Sonnet subagent pulls
  5 symbol-days and reports size, speed and whether quotes are included.
- If free data is not enough, bring Joel a price for Databento (per symbol-day) **before** buying anything.
- Pull only the labelled symbol-days, plus the same day's other premarket movers (the stocks Ross did not pick are
  the comparison set). Store in the DB in tables prefixed `rim_`.
- **GATE 3 (Joel):** data coverage and any spend.

### Phase 4: pre-registration
Write `docs/PREREG_2026_xx_ROSS_IMITATION.md` and commit it before any held-out scoring. It fixes:
- Split by date: train on the earliest years, tune on the next, **seal** the most recent year.
- Features, model family and size (start with a gradient-boosted baseline, then a small 1D convolutional or
  recurrent network), and how thresholds are chosen (on the tuning year only).
- Two pass bars, both required:
  - **Imitation:** on sealed days, the model fires within 5 seconds of Ross's entry far more often than a baseline
    (random moments in the same stock, and the October bar model).
  - **Money:** trading the model's own entries and exits on sealed days, filled at the real quotes (buy at the ask,
    sell at the bid, plus a latency delay of 1 second), mean return per trade above zero with the day-clustered
    confidence range above zero.
- Honest limits: his recap trades are the ones he chose to show; his audience may move the stock after he calls it.

### Phase 5: build, train, score once
- Dataset builder and training scripts in `research/analysis/scripts/ross_imitation_*.py`, each with a `selftest`.
- Train on the laptop CPU (small models only). One sealed look, result recorded in the prereg doc.
- **GATE 4 (Joel):** pass or fail, and what it means.

### Phase 6 (only on a pass): into the bot, on paper
- Live feed decision (Joel's): the old real-time feed (Tradier) has been dead since July 22. Options and prices to be
  brought to him then.
- Wire the model into the existing jTrader runner on paper, measure real fills against the sealed test.

## Track B: get the paper bot running (Joel chose this on Nov 12)

Blocked on one decision from Joel: which real-time premarket data feed to pay for or fund. The orchestrator should
bring current prices and what each provides premarket (Tradier funded account, Alpaca paid feed, Databento live) as a
short table, then wait. No live or paper session is switched on without his yes.

## Later: other traders

Same pipeline per trader: transcripts, extraction with the existing prompts, label audit, same columns with a
different `trader` value. Do not start this before Gate 1 shows the Ross labels are usable.

---

## Progress log

**2026-11-12, Phase 1 + pilot (Opus orchestrating, Sonnet extracting).**
- Gate 1: the 19 extraction files (1,787 videos, 5,424 trades) have no per-trade timestamps: 0 to the second,
  72% no time at all, no exit times; 724 videos undated. Raw transcripts do narrate executions in order
  (shares, price, buy/add/sell) but give no real clock times.
- Free Alpaca historical tick trades work: millisecond timestamps, premarket, back to at least 2019.
- Pilot (50 dated transcripts, `research/analysis/scripts/ross_exec_match_pilot.py`): 493 executions extracted,
  349 priced. Matching the narrated price sequence to tick data found a consistent day for 55 of 81 priced
  ticker-groups (44 of them on exactly one candidate day), but pinned only **7 executions (2%) to within 5 s**.
  Median feasible window about 19 minutes; the stated price prints about 11 separate times in that window.
  Price order alone does not pin the second. Next candidates: share-size fingerprints in the tick data, or the
  screen in the recap videos. Joel decides (Gate 1b).
- Size fingerprint (`ross_exec_size_pilot.py`): 47 executions with a stated size >= 1,000 shares. Seconds at his
  price with summed size >= half his order: median about 14 per execution; **2 of 47 (4%) pinned to one second**.
  On the days he trades, his order sizes are ordinary for the tape, and some stated sizes never print at that price
  at all. The tape cannot pick him out. Remaining route to second-level labels: the 240 videos tagged
  `TYPE: Live Trading` in the extractions (screen shows clock, chart, Level 2 and order entry as it happens).
