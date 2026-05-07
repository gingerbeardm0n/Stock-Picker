# Haiku Extraction Prompt — Trade Mechanics Pass 1 (Summary Only)

**Last updated:** 2026-05-05  
**Purpose:** Template prompt for Haiku agents extracting TRADE_MECHANICS tables from chunk files  
**Pass type:** Summary-only (no transcript reads)  
**Batch size:** 25 FILE entries per agent call (Read tool has 2000-line default limit — 25 entries ≈ 625 lines, safely within limit)

---

## How to Use This Prompt

1. Split the chunk file into batches of 25 FILE entries (use line offsets with the Read tool)
2. For each batch, send this prompt + batch content to a Haiku agent
3. Collect all batch outputs into a single file (e.g. `haiku_output_0001-0099.txt`)
4. Run `enrichment_inserter.py` to insert mechanics tables into chunk file and write TSV rows

---

## The Prompt (send this verbatim to Haiku, followed by the batch content)

---

You are processing Ross Cameron day trading video transcript summaries to extract structured trade mechanics data. This is a **strict summary-only pass** — extract only from the SUMMARY text and TRADES table. Do NOT infer, fabricate, or use outside knowledge.

### Input Format

Each FILE entry has this structure:
```
FILE XXXX | TYPE: ...
---

TRADES:
| # | SYMBOL | SECTOR | PRICE | SCANNER | NEWS | ENTRY SETUP | EXIT | RESULT | OUTCOME |

SUMMARY:
[narrative text]

METADATA:
{json}

---
```

Some entries have `TRADES: NO TRADES TAKEN` — skip those entirely, output nothing for them.

### Your Task

For each FILE entry that has trades: produce a `TRADE_MECHANICS` table with one row per trade, extracting mechanics from the SUMMARY and TRADES table.

### TRADE_MECHANICS Table Schema

```
| # | FLOAT | GAP% | REL_VOL | PATTERN_TYPE | ENTRY_TRIGGER | ADD_ON_MECHANIC | STOP_CRITERIA | T1_TARGET | TIME_OF_ENTRY | MACD_STATE | HOLD_DURATION |
```

### Column Definitions

| Column | What to extract | Example values |
|--------|----------------|----------------|
| `#` | Trade row number — matches TRADES table | `1`, `2`, `3` |
| `FLOAT` | Share float of the stock | `1.6M`, `50M`, `sub-1M` |
| `GAP%` | Premarket gap percentage | `329%`, `37%`, `50%` |
| `REL_VOL` | Relative volume at time of trade | `15x`, `8x`, `high` |
| `PATTERN_TYPE` | Setup type — use controlled vocab only | see vocab below |
| `ENTRY_TRIGGER` | Specific price level or candle signal that triggered entry | `break $4.50 pm-high`, `first 1m candle to new high`, `VWAP reclaim at $3.00` |
| `ADD_ON_MECHANIC` | How Ross added to position after initial entry | `added every $0.10`, `added on pullback to $X`, `scaled in $3K→$6K→$9K` |
| `STOP_CRITERIA` | Stop conditions being watched (hit or not) | `below $1.50 support`, `MACD neg cross`, `below VWAP` |
| `T1_TARGET` | First profit target | `$2.00 whole-dollar`, `$5.00 resistance`, `VWAP test` |
| `TIME_OF_ENTRY` | Time of entry if mentioned | `9:31am`, `8:22am premarket`, `pre-open` |
| `MACD_STATE` | MACD state at time of entry — controlled vocab | `positive`, `negative`, `unknown` |
| `HOLD_DURATION` | How long position was held — controlled vocab | `scalp`, `short`, `extended`, `unknown` |

### Controlled Vocabulary

**PATTERN_TYPE** (pick closest match):
`gap-and-go` | `micro-pullback` | `vwap-reclaim` | `halt-resume` | `dip-buy` | `flat-top` | `bull-flag` | `abcd` | `red-to-green` | `whole-dollar-break` | `unknown`

**MACD_STATE:**
`positive` | `negative` | `unknown`

**HOLD_DURATION:**
- `scalp` = seconds to ~5 minutes
- `short` = 5–30 minutes  
- `extended` = 30 minutes+
- `unknown` = cannot determine

### Fill Rules

- Use `-` when the data is not found anywhere in the summary
- Use `n/a` when the field is genuinely not applicable to this trade (e.g. ADD_ON_MECHANIC for a pure scalp with no adds mentioned)
- Keep cell values SHORT — brief phrases only, not full sentences
- FLOAT/GAP%/REL_VOL often apply to all trades in the same session (same stock) — carry them across rows
- PATTERN_TYPE should match the ENTRY SETUP column in the TRADES table where possible, mapped to controlled vocab

### Output Format

For each FILE entry with trades, output:

```
=== FILE 0002 ===
TRADE_MECHANICS:
| # | FLOAT | GAP% | REL_VOL | PATTERN_TYPE | ENTRY_TRIGGER | ADD_ON_MECHANIC | STOP_CRITERIA | T1_TARGET | TIME_OF_ENTRY | MACD_STATE | HOLD_DURATION |
|---|-------|------|---------|--------------|---------------|-----------------|---------------|-----------|---------------|------------|---------------|
| 1 | sub-1M | - | - | micro-pullback | break $3.00, micro pullback at $2.90 | dip re-entries | MACD neg cross, sellers stacking | $3.00 | - | positive | short |
```

After ALL file entries, output the TSV audit block:

```
=== TSV_AUDIT ===
file	trade	symbol	FLOAT	GAP%	REL_VOL	PATTERN_TYPE	ENTRY_TRIGGER	ADD_ON_MECHANIC	STOP_CRITERIA	T1_TARGET	TIME_OF_ENTRY	MACD_STATE	HOLD_DURATION
0002	1	NVE	S	-	-	S	S	S	S	S	-	S
```

**TSV audit values:**
- `S` = value was found and extracted from summary
- `-` = not found in summary (cell contains `-` in mechanics table)
- `N` = not applicable (cell contains `n/a` in mechanics table)

### Rules

- Output ONLY the `=== FILE XXXX ===` blocks and the `=== TSV_AUDIT ===` block
- No commentary, no explanations, no preamble
- Do not rewrite or repeat the original TRADES table or SUMMARY
- Do not skip any FILE entry that has trades
- FILE entries with `TRADES: NO TRADES TAKEN` — output nothing
- **CRITICAL — TSV column count:** Every TSV data row MUST have exactly 11 data values after the symbol column (14 tab-separated values total: file, trade, symbol + 11 data columns). Never output fewer. If MACD_STATE is unknown, output `-` for that column — do not skip it. Column order is fixed: FLOAT, GAP%, REL_VOL, PATTERN_TYPE, ENTRY_TRIGGER, ADD_ON_MECHANIC, STOP_CRITERIA, T1_TARGET, TIME_OF_ENTRY, MACD_STATE, HOLD_DURATION.

---

## Now process the following FILE entries (batch of 25):

[INSERT BATCH CONTENT HERE]
