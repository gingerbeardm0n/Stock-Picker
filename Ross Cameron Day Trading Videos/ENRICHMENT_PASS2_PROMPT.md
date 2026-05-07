# Enrichment Pass 2 Prompt — Transcript Re-Read (Fill Missing Fields)

**Last updated:** 2026-05-06  
**Purpose:** Fill in FLOAT, GAP%, REL_VOL, and TIME_OF_ENTRY fields that were blank (-) in pass 1 summary-only extraction.  
**Output:** UPDATE blocks only — one per FILE, containing only the rows/fields that changed.

---

## The Prompt (send this verbatim, followed by the FILE batch content)

---

You are performing a **targeted enrichment pass** on Ross Cameron day trading video transcripts. Pass 1 already extracted trade mechanics from summaries. Your job is to read the raw transcript and fill in specific fields that were missing.

### Fields to fill (ONLY these four — ignore all others)

| Field | What to look for in transcript |
|-------|-------------------------------|
| `FLOAT` | Phrases like "X million share float", "sub-1M float", "low float", "float of X million", "X million shares outstanding", "X million shares available". Also look for: Ross mentioning the stock is "small float", "micro float", "under 1 million". |
| `GAP%` | Phrases like "up X%", "gapping X%", "gapped X%", "up over X percent", "up 1500%", "300% gapper". This is the premarket gap percentage. |
| `REL_VOL` | Phrases like "Xk relative volume", "X times relative volume", "Xk compared to Y avg", "relative volume of X", "volume is X times higher", explicit volume numbers compared to average. Also: "heavy volume", "5x relative volume". If only vague terms ("high volume", "strong volume") without a number — use "high". |
| `TIME_OF_ENTRY` | Exact time Ross entered the trade: "9:31am", "7:30am", "at the open", "premarket at 8am". Look for phrases like "I got in at [time]", "entered at [time]", "trade at [time]", "8:30 in the morning". |

### Input format

Each FILE block has:
1. **EXISTING TRADE_MECHANICS table** — shows which rows have `-` in the 4 target fields
2. **TRANSCRIPT** — the raw video transcript text

### Your task

For each FILE:
1. Read the EXISTING TRADE_MECHANICS table to know how many trades there are and what's missing
2. Read the transcript
3. For each trade row, try to match the entry trigger/symbol/context to find the 4 target fields
4. If a field is mentioned in the transcript → fill it in
5. If a field is NOT in the transcript → keep it as `-`

### Matching trades to transcript

The transcript is NOT structured — Ross talks about stocks in rough chronological order but jumps around. Use these signals to match:
- Symbol names mentioned (e.g., "BMR", "SNDE")  
- Price levels that match ENTRY_TRIGGER (e.g., "broke $3.90" → matches ENTRY_TRIGGER "breakout through $3.90")
- Order of trades (trade #1 is usually first stock discussed at open, etc.)

### Output format

For each FILE, output ONLY an UPDATE block. Use `-` if still not found.

```
=== FILE 0037 UPDATE ===
| # | FLOAT | GAP% | REL_VOL | TIME_OF_ENTRY |
|---|-------|------|---------|---------------|
| 1 | sub-1M | 1500% | high | 7:30am |
| 2 | sub-1M | 1500% | high | 7:45am |
| 3 | sub-1M | 1500% | high | - |
... (one row per trade, all trades)
```

FLOAT and REL_VOL often apply to ALL trades on the same symbol — carry the value across rows for the same symbol.

After ALL FILE blocks, output a brief DATA_QUALITY note:

```
=== DATA_QUALITY ===
FILE 0037: FLOAT not in transcript | GAP% found for BMR (1500%), MGI (1000%) | REL_VOL vague only | TIME found for trades 1,3,6
FILE 0660: ...
```

### Rules

- Output ONLY the `=== FILE XXXX UPDATE ===` blocks and `=== DATA_QUALITY ===`
- No commentary, no preamble, no re-stating the existing TRADE_MECHANICS table
- If transcript has NO data for any of the 4 fields → output the UPDATE block anyway with all `-`
- FLOAT: prefer numeric (e.g., "2.5M") over vague ("low float"). If Ross says "sub-1M" use that. If he says "million share float" without a number but it's clearly low-float context, use "low-float"
- GAP%: use the gap% at the time Ross traded it (premarket gap), not the intraday high
- REL_VOL: prefer specific multiples (e.g., "15x") over vague labels. Only use "high"/"very-high" if no number given
- TIME_OF_ENTRY: use 12h format with am/pm (e.g., "7:30am", "9:31am")

---

## Now process the following FILE entries (batch of up to 5):

[INSERT BATCH HERE — format: "FILE XXXX" header + EXISTING TRADE_MECHANICS table + "TRANSCRIPT:" header + transcript text]

