# jTrader Project Brief
### Ross Cameron Data → Algorithm Development

**Last updated:** 2026-05-05
**Status:** Phase 2 in progress — statistics baseline complete, jTrader audit next

---

## What This Document Is

Everything a new session needs to get up to speed and execute Phase 2 work without re-reading prior conversations. Read this first. Then read the files referenced in the file map.

---

## Current State (Phase 1 Complete)

**All ~1,800 Ross Cameron video transcripts have been extracted** into structured markdown summaries. Zero gaps remain.

### Folder Structure
```
C:\Users\joelb\Ross Cameron Day Trading Videos\
│
├── JTRADER_PROJECT_BRIEF.md          ← you are here
├── EXTRACTION_INSTRUCTIONS.md        ← authoritative format guide for extractions
├── ROUTINE_PROGRESS.md               ← batch tracker (all 14 batches DONE)
├── ROUTINE_PROMPT.md                 ← autonomous agent instructions (extractions phase)
├── RC_STRATEGY_STATISTICS.py         ← Python script: parses all chunk files → produces stats report
├── RC_STRATEGY_STATISTICS.md         ← Generated stats report (re-run .py to refresh)
│
├── extractions\                      ← all extraction outputs (the wiki layer)
│   ├── TRANSCRIPT_SUMMARIES_0001-0099.md
│   ├── TRANSCRIPT_SUMMARIES_0100-0199.md
│   ├── ... (19 chunk files total, 0001–1799)
│   ├── TRANSCRIPT_SUMMARIES_MASTER.md    ← historical archive, mixed formats
│   └── TRANSCRIPT_SUMMARIES_TITLE_MAP.json
│
├── Text transcriptions\              ← raw source transcripts (~1,800 .txt files, immutable)
├── Initial 78\                       ← early project docs, strategy guides, Python scripts
└── Older\                            ← legacy batch files, superseded trackers
```

### Chunk File Format (per FILE entry)
Each entry in the chunk files has three sections:
```
FILE XXXX | TYPE: Daily Recap / Watchlist / Educational / Live Trading
---

TRADES:
| # | SYMBOL | SECTOR | PRICE | SCANNER | NEWS | ENTRY SETUP | EXIT | RESULT | OUTCOME |

SUMMARY:
[3-5 sentence narrative — verbose by design, preserved for re-processing]

METADATA:
{"p&l": "...", "record": "...", "market": "hot/cold/neutral", "volume": "high/normal/low",
 "acct_state": "...", "prior_day": "...", "month_context": "...", "size_context": "...",
 "session_end": "...", "max_loss_hit": true/false, "behavioral_deviation": "..."}

---
```

---

## The Two-Dataset Reality

We actually have two overlapping datasets:

| Dataset | Location | Format | What it captures | Coverage |
|---|---|---|---|---|
| **Chunk files** | `extractions/TRANSCRIPT_SUMMARIES_XXXX.md` | TRADES table + SUMMARY + METADATA | What happened — trade events, outcomes, market context | ~1,800 entries, complete |
| **MASTER (Zone 5 portion)** | `extractions/TRANSCRIPT_SUMMARIES_MASTER.md` | SCRN/ENTRY/STOP/PROF pipe headers + narrative | Decision rules — screening criteria, entry mechanics, stop triggers, profit mechanics | ~318 entries (files 0281–0600 range) |

The chunk files are the **authoritative event log**. The MASTER is a historical artifact — useful for reference but superseded by chunk files for structured data.

---

## The LLM Wiki Framing (Key Concept for Phase 2)

This project maps directly to Andrej Karpathy's LLM Wiki pattern (April 2026):

| Karpathy's Layer | This Project |
|---|---|
| **Raw Sources** (immutable) | `Text transcriptions/` — 1,800 transcripts, never modified |
| **The Wiki** (LLM-maintained) | `extractions/` — 19 chunk files, per-source summaries |
| **Synthesis Layer** (missing) | Concept pages, entity pages — **not yet built** |

**The gap:** We have the per-source summary layer (chunk files). We're missing the cross-session synthesis layer — pages that cut across all 1,800 sessions to answer questions like "what is Ross's VWAP entry win rate across all sessions?" or "how does his behavior change in hot vs cold markets?"

That synthesis layer is what jTrader actually needs — not a list of 1,800 individual outcomes, but distilled, validated decision logic.

---

## What's Already Been Researched

Two high-quality research documents already exist in `Older/`:

### `Older/RC_Strategy_Research_Report.md`
- **43 specific rules** extracted from ~80 transcripts (Phase 1 deep dive)
- **9 pilot findings** from 20 live session videos with direct jTrader actions:
  - MACD line below zero = hard VETO on entry (not histogram — the line itself)
  - Float sweet spot: <5M preferred, <1M = maximum squeeze potential
  - Cold/Hot market framework with position sizing adjustments
  - Front Side (MACD positive) vs Back Side (MACD negative) as primary entry gate
  - Give back 50% of peak daily profit = hard stop
  - Trading window: 9:30–10:30am primary, 11am–2pm dead zone
  - Order spoofing detection (wall that reprices away = ignore, size up)
  - Sector theme as catalyst amplifier
  - The "Obvious Trade" standard — only trade the unambiguous leader

### `Older/Phase2_New_Rules_Report.md`
- **19 rule candidates** across Psychology, Risk Management, Market Conditions, Trade Management
- Confidence tiers: 🔴 Critical (8 rules), 🟠 High (10 rules), 🟡 Medium (1 rule)
- Key insight: existing 43 rules cover *what to trade* well. What's missing is *when to stop trading* and *how to behave after things go wrong* — exactly what an algorithm enforces that a human under stress cannot

### `RC_STRATEGY_STATISTICS.md` ← NEW — supersedes the 80-transcript reports
Generated by `RC_STRATEGY_STATISTICS.py` from all 19 chunk files. **1,787 sessions, 5,261 trades.**
Key findings validated at scale:

| Finding | Data |
|---|---|
| Overall win rate | 64.8% |
| Cold market avg result | **-$63/trade** (net losing — don't trade cold markets) |
| Oversized position avg result | **-$176/trade** (net losing — oversizing destroys edge) |
| Win rate WITH behavioral deviation | **49.2%** vs 73.1% without — biggest argument for the algorithm |
| In-drawdown win rate | **39.7%** — deeply negative, validates drawdown rules |
| Gap-and-go win rate | **78.2%**, +$3,791 avg — top setup by frequency + performance |
| VWAP break/curl win rate | **78.1%**, +$7,126 avg — highest avg result of any setup |
| With news catalyst | **73.4%** win rate vs 60.7% without — validates news as Pillar 4 |
| Max loss hit sessions | **30.9%** win rate, -$4,454 avg — catastrophic, never exceed max loss |

**Note:** `RC_STRATEGY_STATISTICS.md` contains raw statistics tables. Full analysis connecting numbers to jTrader rule changes is the next session's task (do alongside the jTrader audit).

---

## Phase 2 Plan

### Step 1 — jTrader Audit (Do This First)
Walk through jTrader's current logic and map it against what the data supports:
- What signals does jTrader currently use for stock selection, entry, exit, sizing?
- Which of the 43 known rules are already implemented?
- Which are missing entirely?
- What questions does jTrader's logic raise that our data can't yet answer?

**Why first:** The audit reveals the gaps. The gaps define what concept pages we need. Building concept pages without knowing jTrader's questions is working blind.

### Step 2 — TRADE_DECISION_LOGIC Enrichment Pass
The chunk files capture *what happened* but not always *why the decision was made*. Each trade row currently has a brief ENTRY SETUP and EXIT field. The goal is to enrich these with the specific decision mechanics:

**Current (thin):**
```
| VVPR | $4.50 | gap-and-go / break of premarket high | PROF: scaled at whole dollar target |
```

**Target (enriched):**
```
| VVPR | $4.50 | gap-and-go: break of $4.50 premarket pivot; added every $0.10 on micro pullbacks; confirmed first 1-min candle to new high | PROF: scaled at $5.00, $5.50 whole-dollar targets; time exit 10:15am | STOP criteria: MACD negative cross; spread >$0.20; topping tail at resistance |
```

A new `TRADE_DECISION_LOGIC:` section gets added to each FILE entry (after METADATA) capturing:
- **SCRN:** what screening criteria made this stock selectable
- **ENTRY:** specific entry mechanic with price levels and confirmation signals
- **STOP:** stop criteria that were active (whether triggered or not)
- **PROF:** profit mechanics and targets
- **confidence:** `high` / `medium` / `low` (based on how much detail the SUMMARY contained)
- **source:** `summary` / `transcript` (whether extracted from summary alone or needed raw transcript)

**Approach:**
- First pass: Haiku agents extract TRADE_DECISION_LOGIC from SUMMARY + TRADES table alone (no transcript re-read). Flag `confidence: low` where summary is too thin.
- Second pass (later): Re-read transcripts only for `confidence: low` entries.
- Start with a sample batch of 20-30 entries to validate quality before running at scale.

### Step 3 — Concept / Entity Pages (Synthesis Layer)
After enrichment, build cross-session synthesis pages that answer jTrader's questions directly. Examples:

- **`concept_vwap_entry.md`** — Every session where VWAP reclaim was the entry, win rate, average gain, conditions it failed
- **`concept_market_temperature.md`** — Hot vs cold market definitions, sizing adjustments, which setups work in each
- **`concept_halt_resume.md`** — All halt-resume trades, win rate by halt type, position sizing patterns
- **`entity_float_buckets.md`** — Win rate and average P&L by float range (<1M, 1–5M, 5–10M, 10–20M, 20M+)
- **`concept_front_back_side.md`** — Front side vs back side framework, MACD definition, examples of each

These concept pages become the direct input to jTrader rule refinement — validated by real outcomes across 1,800 sessions.

---

## Key Decisions Made (Don't Re-Litigate These)

- **Chunk files are authoritative** — MASTER is reference only
- **SUMMARY fields are verbose by design** — preserved specifically to enable re-processing without going back to raw transcripts
- **TRADE_DECISION_LOGIC** is the name for the re-extraction section (not "Zone 5")
- **Haiku for mechanical tasks** (enrichment pass, per-entry processing), **Sonnet for synthesis** (concept pages, jTrader audit mapping, reasoning tasks)
- **Single source of truth** — all enrichment gets added to the chunk files themselves, not separate documents

---

## Controlled Vocabulary Reference

For any agents continuing extraction or enrichment work:
- **market:** `"hot"` | `"cold"` | `"neutral"`
- **volume:** `"high"` | `"normal"` | `"low"` | `null`
- **acct_state:** `"building-cushion"` | `"in-drawdown"` | `"at-goal"` | `"exceeded-goal"` | `"normal"` | `null`
- **month_context:** `"up-big"` | `"on-pace"` | `"slow"` | `"in-drawdown"` | `"record-pace"` | `null`
- **size_context:** `"full"` | `"reduced"` | `"oversized"`
- **OUTCOME:** `WIN` | `LOSS` | `BE`
- **SECTOR:** `biotech` | `pharma` | `tech` | `chinese` | `general`
- **SCANNER:** `gap-scanner` | `high-day-momo` | `premarket-scan` | `watching` | `unknown`
- **EXIT prefix:** `PROF:` → WIN or BE. `STOP:` → LOSS only. BE pairs with `PROF:` not `STOP:`

---

## Next Session Starting Point

1. Read this document
2. Read `RC_STRATEGY_STATISTICS.md` — the full stats baseline (1,787 sessions, 5,261 trades)
3. Read `Older/RC_Strategy_Research_Report.md` — the 43 rules + pilot findings (context for the audit)
4. Open jTrader codebase
5. Begin the audit: for each rule jTrader currently implements, check it against the statistics
6. For each gap or contradiction found, note it — those gaps define the concept pages needed
7. Produce an updated analysis doc: which rules are statistically validated, which need changing, which are missing entirely

---

*This document should be updated as Phase 2 progresses. It is the single source of truth for project state and direction.*
