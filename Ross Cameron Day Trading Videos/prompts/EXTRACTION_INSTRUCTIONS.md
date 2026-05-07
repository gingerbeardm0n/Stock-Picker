# Ross Cameron Transcript Extraction Instructions

---

## 1. OUTPUT FILE STRUCTURE

Extractions are written to **chunk files**. Each chunk file covers 100 videos and is named:

```
TRANSCRIPT_SUMMARIES_XXXX-XXXX.md
```

**Examples:**
- FILES 1100–1199 → `TRANSCRIPT_SUMMARIES_1100-1199.md`
- FILES 1200–1299 → `TRANSCRIPT_SUMMARIES_1200-1299.md`
- FILES 1300–1399 → `TRANSCRIPT_SUMMARIES_1300-1399.md`
- FILES 1400–1499 → `TRANSCRIPT_SUMMARIES_1400-1499.md`

When appending a FILE, determine which chunk covers that file number range and write to that file only. If the chunk file does not yet exist, create it with no header — just start appending entries.

`TRANSCRIPT_SUMMARIES_MASTER.md` is frozen. **Never write to it.**

---

## 2. BATCH WORKFLOW

Extractions run in **batches of 10 files, sequentially**. A Haiku agent handles extraction for each batch of 10. A Sonnet agent reviews and corrects after each batch before the next begins.

**Rules:**
- Never run two extraction batches concurrently against the same chunk file — this causes ordering corruption
- Always complete one batch (extract → append → Sonnet review → corrections) before starting the next
- Append each FILE to the chunk file immediately after extraction — do not hold multiple in memory
- Every entry must end with `---` on its own line

**Haiku agent chat reporting (one line per file, nothing else):**
- Success: `FILE XXXX: ✓`
- Failure: `FILE XXXX FAILED — [one sentence reason]`

Do not paste the extraction into chat. Do not narrate steps.

---

## 3. DETERMINING FILE TYPE

Read the filename first — it gives strong signal:

- Contains "Recap", stock tickers, "Profit", "Loss", "Green Day", "Red Day" → likely `Daily Recap`
- Contains "Morning Show", "Live Trading", "LIVE" → likely `Live Trading`
- Contains "Watch List", "Watchlist", "Game Plan", "Monday Morning", "Week Ahead", "Strategy", "Training", "Guide", "Tutorial", "Year in Review" → likely `Educational`
- Still ambiguous → read the first 200 words of the transcript

**Decision rule:** If Ross executed at least one real-money trade in the video → use `Daily Recap` or `Live Trading`. If he did not execute any trades → use `Educational`.

If you still cannot determine TYPE with confidence after reading → default to `Educational`.

---

## 4. CONTROLLED VOCABULARY

All allowed values for every field. Use **only** the values listed here. Do not invent new values.

**TYPE:**
`Daily Recap` | `Live Trading` | `Educational`

**Fields for FORMAT: Daily Recap / Live Trading:**

| Field | Allowed Values |
|-------|----------------|
| SECTOR | `biotech` `pharma` `tech` `chinese` `cannabis` `general` |
| SCANNER | `gap-scanner` `high-day-momo` `premarket-scan` `watching` `unknown` |
| NEWS | `yes` `no` |
| OUTCOME | `WIN` `LOSS` `BE` |
| size_context | `"full"` `"reduced"` `"oversized"` |
| max_loss_hit | `true` `false` |
| behavioral_deviation | `"fomo-entry"` `"revenge-trade"` `"oversize"` `"avg-down"` `"broke-rules"` `"late-exit"` `"overtrading"` `null` |
| prior_day | `"big-win"` `"win"` `"loss"` `"big-loss"` `null` |

**Shared fields (all formats):**

| Field | Allowed Values |
|-------|----------------|
| market | `"hot"` `"cold"` `"neutral"` |
| volume | `"high"` `"normal"` `"low"` `null` |
| acct_state | `"building-cushion"` `"in-drawdown"` `"at-goal"` `"exceeded-goal"` `"normal"` `null` |
| month_context | `"up-big"` `"on-pace"` `"slow"` `"in-drawdown"` `"record-pace"` `null` |

---

## 5. SHARED METADATA FIELDS

These four fields appear in both FORMAT sections. These definitions are authoritative.

---

**market**
The overall market environment that day. Use Ross's own commentary as the signal.

| Value | Ross says things like... |
|-------|--------------------------|
| `"hot"` | "Lots of momentum," "stocks everywhere," "incredible day," high volatility, many halts, large sizing |
| `"cold"` | "Slow day," "nothing moving," "grinding," "low volume," conservative sizing, few setups |
| `"neutral"` | Neither clearly hot nor cold, or cannot be determined from the transcript |

---

**volume**
Overall market participation and liquidity quality.

| Value | Signals |
|-------|---------|
| `"high"` | Clean fills, tight spreads, stocks following through, heavy volume mentioned |
| `"normal"` | Typical conditions, no strong commentary either way |
| `"low"` | Wide spreads, poor fills, stocks not following through, post-holiday, summer slowness |
| `null` | Educational entries only — use null if not mentioned |

For Daily Recap / Live Trading: default to `"normal"` if volume is not specifically commented on.

---

**acct_state**
Ross's account state and psychological orientation relative to his goals.

| Value | Use When |
|-------|----------|
| `"building-cushion"` | He is being conservative, accumulating profit gradually, mentions building a cushion |
| `"in-drawdown"` | He is trying to recover from recent losses (day, week, or month level) |
| `"at-goal"` | He has hit his daily goal and is considering or has stopped trading |
| `"exceeded-goal"` | He has significantly surpassed his daily goal |
| `"normal"` | No specific goal-related state is mentioned (Daily Recap default) |
| `null` | Educational format — use null if not stated |

---

**month_context**
⚠️ **Only populate if Ross explicitly mentions his month-to-date performance IN THIS TRANSCRIPT. If he does not mention it, set to `null`. Do not infer. Do not derive from other files.**

| Value | Use When |
|-------|----------|
| `"up-big"` | He says he's had a great month, up a lot, ahead of pace |
| `"on-pace"` | Normal progress toward monthly goal |
| `"slow"` | Below expectations but not in deep trouble |
| `"in-drawdown"` | Down on the month, trying to recover |
| `"record-pace"` | Best month ever or close to it |
| `null` | Month performance not mentioned in this transcript |

JSON format: no quotes around null → `"month_context": null`

---

## 6. FORMAT: Daily Recap / Live Trading

> **Scope:** Everything in this section applies only to TYPE: `Daily Recap` and TYPE: `Live Trading`.

### What to Extract

Read the full transcript. Identify all trades Ross personally made that day. Produce output in the exact format below.

**You are extracting Ross's trades only. Do NOT include:**
- Trades made by students, chat room members, or any other person he mentions
- Paper trades or simulator trades
- Stocks he watched, evaluated, or had on his watchlist but never entered
- Stocks he says he "should have" traded or "missed"
- Positions carried from a prior day that he did not actively trade today

---

### Output Template

Copy this structure exactly. Every section must be present. Every field must be populated. **Never skip a section. Never reorder sections. Never add extra sections.**

```
FILE [NUMBER] | TYPE: [TYPE]
---

TRADES:
| #  | SYMBOL | SECTOR  | PRICE  | SCANNER        | NEWS | ENTRY SETUP                    | EXIT                              | RESULT | OUTCOME |
|----|--------|---------|--------|----------------|------|--------------------------------|-----------------------------------|--------|---------|
| 1  | [SYM]  | [SECT]  | [PRC]  | [SCANNER]      | [Y/N]| [SETUP DESCRIPTION]            | [PROF/STOP: REASON]               | [+/-$] | [W/L/BE]|

SUMMARY:
[150-200 words of prose, third person, no bullet points]

METADATA:
{"p&l": "[VALUE]", "record": "[VALUE]",
 "market": "[VALUE]", "volume": "[VALUE]",
 "acct_state": "[VALUE]",
 "prior_day": VALUE,
 "month_context": VALUE,
 "size_context": "[VALUE]",
 "session_end": "[VALUE]",
 "max_loss_hit": VALUE,
 "behavioral_deviation": VALUE}

---
```

---

### File Header

**Format:** `FILE [NUMBER] | TYPE: [TYPE]`

**[NUMBER]:** Use the number from the filename exactly.
Example: filename `0513_Some Title.txt` → `FILE 0513`

**[TYPE]:** `Daily Recap` or `Live Trading` — see Section 3.

---

### Trades Table

The table always has exactly **10 columns** in exactly this order:

`# | SYMBOL | SECTOR | PRICE | SCANNER | NEWS | ENTRY SETUP | EXIT | RESULT | OUTCOME`

Always include the header row and the `|---|` separator row beneath it. Add one data row per trade.

**What Counts as One Trade:**
A trade starts when Ross first enters a position and ends when he is completely flat (zero shares held).
- Partial exits and add-ons are part of the same trade — do not create separate rows
- Only create a new row for the same ticker if he fully exited and then re-entered at a later time

---

**Column 1: #**
Sequential integer starting at 1. One number per complete trade.

---

**Column 2: SYMBOL**
The stock ticker exactly as mentioned (e.g., `RKDA`, `CODX`, `APT`).
If unclear or never stated: `???`

---

**Column 3: SECTOR**
Classify the stock based on what the company does or what Ross says about it.

| Value | Use When |
|-------|----------|
| `biotech` | Drug/biotech/medical companies, FDA catalysts, clinical trials |
| `pharma` | Pharmaceutical companies without specific biotech/FDA angle |
| `tech` | Technology companies |
| `chinese` | Chinese or Hong Kong listed stocks — **this classification always takes precedence over industry**. If the company is Chinese-listed, use `chinese` even if it operates in biotech, tech, or any other sector. Ross often flags these explicitly. |
| `cannabis` | Marijuana/cannabis-related companies |
| `general` | Everything else, including energy companies, or when sector cannot be determined |

---

**Column 4: PRICE**
The entry price or price range for this trade.
- Single entry price: `$4.00`
- Multiple entries at different prices: `$16.11-$16.41`
- Price not mentioned: `unknown`

Do not use `~` approximation markers. If the price is mentioned but imprecise, use your best estimate as an exact number.

---

**Column 5: SCANNER**
How did Ross find or become aware of this stock?

| Value | Use When |
|-------|----------|
| `gap-scanner` | He says it was the "leading gapper," found on "gap scan," or "gapping up X%" |
| `high-day-momo` | He says it "hit the scanner," "popped up on my scanner," or "hit the high of day momentum scanner" |
| `premarket-scan` | He was already watching it before the open as part of his morning prep |
| `watching` | He was monitoring it from a prior day or prior session (continuation play) |
| `unknown` | He does not say how he found it |

**Important:** `premarket-scan` means he identified it before the open. `high-day-momo` means it appeared unexpectedly during the session. This distinction matters. `continuation` is **not** a valid value — use `watching` instead.

---

**Column 6: NEWS**
Was there a news catalyst specifically for this stock?

| Value | Use When |
|-------|----------|
| `yes` | He mentions a headline, press release, FDA approval/rejection, earnings, offering, CEO change, partnership, or any external news event |
| `no` | He says there was no news, or does not mention any news for this stock |

---

**Column 7: ENTRY SETUP**
A short description (aim for under 10 words) of the pattern or signal that caused Ross to enter. Use lowercase. Use `/` to separate multiple factors.

Common patterns to recognize and label:
- `gap-and-go / break of premarket high`
- `VWAP reclaim / micro-pullback dip`
- `halt resume / continuation long`
- `whole-dollar break / momentum surge`
- `consolidation breakout / flag pattern`
- `dip buy / bounce off support`
- `red-to-green move`
- `second entry / dip re-entry`
- `opening range breakout`
- `news pop / first candle momentum`

If he added to the position, capture it briefly: `starter $11 / add on dip $15.57`

---

**Column 8: EXIT**
Always begins with either `PROF:` or `STOP:` followed by a short description.

**EXIT prefix must match OUTCOME — this is a hard rule:**
- `PROF:` → OUTCOME must be `WIN` or `BE` only
- `STOP:` → OUTCOME must be `LOSS` only
- Never use `PROF:` on a losing trade. Never use `STOP:` on a winning trade.

For profitable exits: `PROF: [brief reason]`
- `PROF: scaled at resistance $4.50`
- `PROF: took profits at whole-dollar target`
- `PROF: sold into momentum spike`

For losing exits: `STOP: [sub-type] - [brief reason]`

| Sub-type | Use When |
|----------|----------|
| `failed-breakout` | Breakout attempt failed, stock reversed |
| `reversal` | Momentum turned against him |
| `BE` | Exited at roughly breakeven |
| `halt-down` | Stock halted going down while he held long — trapped until resumption |
| `halt-pending` | Stock halted on pending news while he held — outcome unknown until resume |
| `max-loss` | He hit his maximum daily loss limit and was forced to exit |

These are the only valid STOP: sub-types. Do not invent others.

---

**Column 9: RESULT**
The dollar profit or loss on this specific trade.
- Profit: `+$400`
- Loss: `-$1,200`
- Breakeven: `$0`
- Unknown: `unknown`

Always include the `+` or `-` sign. Always include the `$`. Use commas for thousands.

**Never use `~` approximation markers in the RESULT column.** If the exact amount is not stated, use your best estimate as a plain number. If genuinely unknown, use `unknown`.

---

**Column 10: OUTCOME**

| Value | Use When |
|-------|----------|
| `WIN` | Trade was profitable (positive RESULT) — must pair with `PROF:` exit |
| `LOSS` | Trade was a loss (negative RESULT) — must pair with `STOP:` exit |
| `BE` | Trade was breakeven (zero or near-zero) — must pair with `PROF:` exit |

---

### Summary

Write **150-200 words** of flowing prose. Always write in **third person** — use "Ross" not "I." Never use bullet points.

The summary must address the following, using only information present in the transcript:
1. **Stock discovery** — For each trade, was the stock on his premarket watchlist or did it appear mid-session?
2. **Entry reasoning** — What specifically gave him conviction to enter?
3. **Exit reasoning** — Was the exit planned (target hit) or reactive (reversal, halt, stop)?
4. **Behavioral observations** — Did he follow his rules? Any FOMO, hesitation, or emotional decisions noted?
5. **Market context** — How did overall conditions or sector behavior influence his approach?
6. **Key lesson or takeaway** — If he states one explicitly, include it.

Do NOT simply restate the trade table. The summary adds context, reasoning, and nuance that the table cannot capture.

---

### Metadata — Daily Recap / Live Trading

The METADATA block is a JSON object with exactly **11 fields** in exactly **this order**. Never add, remove, or reorder fields.

```json
{"p&l": "VALUE", "record": "VALUE",
 "market": "VALUE", "volume": "VALUE",
 "acct_state": "VALUE",
 "prior_day": VALUE,
 "month_context": VALUE,
 "size_context": "VALUE",
 "session_end": "VALUE",
 "max_loss_hit": VALUE,
 "behavioral_deviation": VALUE}
```

For `market`, `volume`, `acct_state`, and `month_context` definitions → see Section 5: Shared Metadata Fields.

---

**p&l**
Total net profit or loss for the entire day.
Format: `"+$1,839"` or `"-$4,500"`. Always include `+` or `-` sign, `$`, and comma for thousands.

⚠️ **The p&l value must equal the arithmetic sum of all RESULT column values exactly.** Calculate the sum before writing the metadata. If there is a discrepancy between the sum and the stated day total, adjust individual RESULT values to reconcile — do not leave a mismatch. Never use `~` in the p&l field.

---

**record**
The win-loss record for the day.
Format: `"XW-XL"` — include BE only if breakeven trades occurred: `"XW-XL-XBE"`
Examples: `"6W-0L"` | `"3W-2L"` | `"4W-1L-1BE"`

---

**prior_day**
⚠️ **Only populate if Ross explicitly mentions the prior trading day IN THIS TRANSCRIPT. If he does not mention it: `null`. Do not infer. Do not derive from other files.**

| Value | Use When |
|-------|----------|
| `"big-win"` | He says yesterday was a great, large, or record day |
| `"win"` | He mentions yesterday was green or a normal winning day |
| `"loss"` | He mentions yesterday was red or a losing day |
| `"big-loss"` | He describes yesterday as a significant, painful, or large loss |
| `null` | Prior day not mentioned in this transcript |

JSON format: no quotes around null → `"prior_day": null`

---

**size_context**
Was his position sizing normal, reduced, or inflated that day?

| Value | Use When |
|-------|----------|
| `"full"` | Trading his normal share sizes, no commentary about adjusting size |
| `"reduced"` | He explicitly mentions trading smaller than usual |
| `"oversized"` | He took larger positions than typical |

Default to `"full"` if he does not comment on sizing.

---

**session_end**
When and/or why did Ross stop trading that day? Short free text. Include approximate time if stated plus the reason.
- `"09:38 - no momentum"`
- `"10:15 - hit daily goal"`
- `"09:45 - max loss hit"`
- `"unknown"` — if not mentioned

Do not use `~` prefix. If the time is approximate, write your best estimate as a plain value.

---

**max_loss_hit**
Did Ross hit his maximum daily loss limit? JSON boolean — no quotes: `true` or `false`

Set to `true` if he says he hit his max loss, triggered his max loss rule, or was forced to stop opening new positions due to losses. Set to `false` in all other cases.

---

**behavioral_deviation**
Did Ross exhibit a clear behavioral deviation from his own stated rules today?
⚠️ Only populate if clearly present. Otherwise `null`.

| Value | Use When |
|-------|----------|
| `"fomo-entry"` | He entered past the ideal entry point out of fear of missing the move |
| `"revenge-trade"` | He traded to emotionally recover a loss rather than on setup quality |
| `"oversize"` | He took a position larger than conditions or his rules warranted |
| `"avg-down"` | He added to a losing position (generally against his rules) |
| `"broke-rules"` | He explicitly says he broke one of his own rules |
| `"late-exit"` | He held past his planned exit, usually costing profit or turning win to loss |
| `"overtrading"` | He took too many low-quality trades, forcing setups that weren't there |
| `null` | No behavioral deviation identified |

**Always a single string value or null.** If multiple deviations apply, combine them into one descriptive string using "and": `"revenge-trade and oversize"`. Never use a JSON array.

---

### Critical Rules — Daily Recap / Live Trading

These rules apply only to this format. Violating any is an error.

1. **FORMAT IS FIXED.** Every output must have all four sections in this order: FILE HEADER → `---` → TRADES TABLE → SUMMARY → METADATA → `---`. Never omit a section. Never reorder sections. Never add extra sections.

2. **METADATA FIELD ORDER IS FIXED.** The 11 JSON fields must always appear in the same order. Never add, remove, or reorder metadata fields.

3. **TABLE COLUMN ORDER IS FIXED.** The 10 columns must always appear in the same order. Never add, remove, or reorder columns.

4. **NULL IS JSON NULL.** In METADATA, null means the actual JSON null value with no quotes: `"prior_day": null` NOT `"prior_day": "null"`. Booleans also have no quotes: `"max_loss_hit": false` NOT `"max_loss_hit": "false"`.

5. **ONLY ROSS'S TRADES.** Never include trades made by students, chat room members, or any other person mentioned in the transcript.

6. **NO PHANTOM TRADES.** Only include trades Ross explicitly says he made. Do not include stocks he only watched, mentioned in passing, or said he should have traded. A row in the TRADES table must represent a real-money entry and exit.

7. **PRIOR_DAY AND MONTH_CONTEXT ARE SELF-REPORTED ONLY.** Only populate if Ross explicitly mentions them in this transcript. Do not infer. Do not derive from other files. If not mentioned: `null`.

8. **NO `~` ANYWHERE.** Never use the `~` approximation marker in any output — not in RESULT, not in p&l, not in PRICE, not in session_end, not anywhere. If a value is stated but imprecise, write your best estimate as a plain number. If a value is not mentioned at all, use `unknown` (table columns) or `null` (metadata).

9. **P&L MUST EQUAL THE SUM OF RESULT VALUES.** Calculate the arithmetic sum of all RESULT column values before writing the p&l metadata field. They must match exactly. If they do not, adjust RESULT values to reconcile.

10. **EXIT PREFIX MUST MATCH OUTCOME.** `PROF:` exits must always pair with WIN or BE outcomes. `STOP:` exits must always pair with LOSS outcomes. This is a hard rule — never mismatch them.

11. **ONE ROW = ONE COMPLETE TRADE.** A trade ends only when Ross is fully flat. Adds and partial exits belong in the same row. Only create a new row for the same ticker if he fully exited and re-entered.

12. **SUMMARY IS PROSE ONLY.** The summary must be 150-200 words of flowing sentences. Never use bullet points, numbered lists, or headers inside the summary.

13. **TABLE COLUMNS VS METADATA PLACEHOLDERS.** In table columns, use `unknown` for missing values. In METADATA JSON, use `null` for missing values. Never use `"unknown"` in metadata. Never use null in table columns.

14. **NEVER REJECT A FILE.** Every transcript must produce an output and be appended to the chunk file. If the transcript is unusual or complex, adapt using the appropriate edge case. Rejection is never acceptable.

15. **SCAN THE FULL TRANSCRIPT BEFORE WRITING.** Do not begin writing the extraction until you have read the entire file.

---

### Edge Cases — Daily Recap / Live Trading

**Ross took no trades that day (slow day, decided not to trade):**
Replace the TRADES table with the plain header:
```
TRADES: NO TRADES TAKEN
```
Set `"p&l": "$0"` and `"record": "0W-0L"`. Fill remaining METADATA fields normally.

---

**Ross mentions a trade but gives no details:**
Create a row with the information available. Use `unknown` for all missing columns. Do not skip the trade.

---

**The same stock ticker appears multiple times (he fully exited and re-entered):**
Create a separate numbered row for each complete entry-to-exit cycle.

Example — RKDA traded three separate times:
```
| 1  | RKDA | biotech | $11.00        | gap-scanner | yes | gap-and-go / break of premarket high | PROF: scaled $13.84-$14.10     | +$3,000 | WIN |
| 2  | RKDA | biotech | $15.57-$16.00 | watching    | yes | dip re-entry / second attempt        | PROF: exit on rejection $15.98 | +$250   | WIN |
| 3  | RKDA | biotech | $16.11-$16.41 | watching    | yes | third entry / flag breakout          | PROF: scaled $17.63-$18.00     | +$700   | WIN |
```

---

**Ross trades a stock with multiple adds and partial exits in one continuous position:**
One row. Capture the price range in PRICE, note the adds briefly in ENTRY SETUP.

Example:
`| 1 | RKDA | biotech | $11.00-$16.41 | gap-scanner | yes | gap-and-go starter $11 / adds on pullbacks $15.57 & $16.41 | PROF: scaled out $13.84, $17.63, final exit $17 | +$4,100 | WIN |`

---

**Ross is trading from a different location (California, traveling, hotel):**
This does not change anything. Extract trades normally.

---

**Ross mentions simulator or paper trading:**
Do NOT include paper/simulator trades in the TRADES table. Only real-money trades.

---

**Ross took more than 10 trades:**
Include all of them. The table can have as many rows as needed.

---

**P&L figures are contradictory:**
Use the final or most specific figure he states. Adjust RESULT values so they sum to that figure exactly.

---

**Ross mentions a halt:**
Do not create a separate column for halts. Capture halt information in the EXIT column:
- He was long and stock halted going down: `STOP: halt-down - [what happened on resumption]`
- Stock halted going up while he held: note in EXIT as part of the PROF description
- Halt pending news while he held: `STOP: halt-pending - [outcome on resumption]`

---

**Ross explicitly mentions yesterday's result:**
Populate `prior_day` with the appropriate value. Even a passing mention counts — "after yesterday's red day..." → `"prior_day": "loss"`.

---

**The transcript has very poor quality (garbled words, repeated phrases from auto-transcription):**
Do your best. Use `unknown` for fields you cannot determine. Never skip a section or field.

---

### Worked Example

**Input (excerpt from transcript):**
*"...finishing the day up thirty-three hundred dollars. So that was a really solid green day. The main trade today was RKDA — someone called it out this morning, said keep an eye on it because it was strong into Friday's close. I put it on the watchlist at eleven dollars and when the bell rang I tried to get three thousand shares but only got partial fill, about a thousand. I got in at eleven and it squeezed all the way up to eighteen dollars. I sold most of it around fourteen and some at fourteen ten. So I made about three thousand on that. Then I took a quick trade on CPAH, five thousand shares at four twenty two, sold at four thirty, made about three hundred bucks on that. Market was a little slow today but RKDA was straight off the watchlist and it just worked perfectly..."*

**Output:**

```
FILE 0530 | TYPE: Daily Recap
---

TRADES:
| #  | SYMBOL | SECTOR  | PRICE  | SCANNER        | NEWS | ENTRY SETUP                          | EXIT                              | RESULT  | OUTCOME |
|----|--------|---------|--------|----------------|------|--------------------------------------|-----------------------------------|---------|---------|
| 1  | RKDA   | biotech | $11.00 | premarket-scan | no   | gap-and-go / break of premarket high | PROF: scaled at $13.84 and $14.10 | +$3,000 | WIN     |
| 2  | CPAH   | general | $4.22  | unknown        | no   | quick scalp / momentum               | PROF: quick exit at $4.30         | +$300   | WIN     |

SUMMARY:
Ross finished the day up $4,430 on two trades. RKDA was the primary winner and had
been on his premarket watchlist — a chat room member flagged it the prior evening
based on its strength into Friday's close, and Ross added it to his watchlist at the
$11 level. At the open he attempted a 3,000-share entry but received only a 1,010-share
partial fill, a disappointment given the stock's eventual move to $18. He sold the
majority of his position around $13.84-$14.10, capturing roughly $3,000 on the trade.
The partial fill, while frustrating, may have been protective — a full 3,000-share
position facing the stock's volatile swings could have resulted in larger losses on a
failed breakout. CPAH was a secondary scalp: 5,000 shares entered at $4.22, exited at
$4.30 for a quick $300 gain. Market conditions were described as slow overall, with
RKDA being the clear standout opportunity of the day. Ross stayed disciplined, taking
only two trades rather than forcing setups in a quiet environment.

METADATA:
{"p&l": "+$3,300", "record": "2W-0L",
 "market": "cold", "volume": "normal",
 "acct_state": "building-cushion",
 "prior_day": null,
 "month_context": null,
 "size_context": "full",
 "session_end": "unknown",
 "max_loss_hit": false,
 "behavioral_deviation": null}

---
```

*(Note: p&l is +$3,300 because that is the arithmetic sum of the RESULT column: +$3,000 + +$300 = +$3,300, which matches the stated day total. Always verify the sum before writing the metadata.)*

---

## 7. FORMAT: Educational

> **Scope:** Use this format when TYPE is `Educational` — game plans, watchlists, year-in-review videos, strategy tutorials, interviews, and any video where Ross did not execute real-money trades.

### Output Template

```
FILE [NUMBER] | TYPE: Educational
---

TRADES: NO TRADES TAKEN

SUMMARY:
[150-200 words of prose, third person, no bullet points]

METADATA:
{"p&l": null, "record": null,
 "market": null, "volume": null,
 "acct_state": VALUE,
 "prior_day": null,
 "month_context": VALUE,
 "size_context": null,
 "session_end": null,
 "max_loss_hit": false,
 "behavioral_deviation": null}

---
```

---

### Summary — Educational

Write **150-200 words** of flowing prose. Third person. No bullet points.

Cover what the video is actually about: the topic, any specific trading lessons or strategies discussed, market observations referenced, and any actionable insights relevant to momentum day trading.

---

### Metadata — Educational

The METADATA block uses the same 11-field structure as Daily Recap. The following fields are **always null** for Educational entries:

- `p&l` → `null`
- `record` → `null`
- `market` → `null`
- `volume` → `null`
- `size_context` → `null`
- `session_end` → `null`

The following fields may be non-null **only if Ross explicitly mentions them in this transcript:**
- `acct_state` — populate if he references his account state or goal status
- `month_context` — populate if he references his month-to-date performance

The following are always fixed values:
- `prior_day` → `null`
- `max_loss_hit` → `false`
- `behavioral_deviation` → `null`

---

### Critical Rules — Educational

1. **TRADES: NO TRADES TAKEN is mandatory.** Always write this exact line in place of the trades table. Never use a table with a dummy row. Never write "TRADES:" followed by a table.

2. **market AND volume ARE ALWAYS NULL.** Even if Ross comments on market conditions during the video, set both to null for Educational entries.

3. **p&l AND record ARE ALWAYS NULL.** No exceptions.

4. **SAME 11-FIELD METADATA.** Use the same JSON structure as Daily Recap — same fields, same order. Never use a different metadata format.

---

## 8. OVERALL CONTEXT AND PURPOSE

Ross Cameron is a professional momentum day trader. He records daily recap videos where he reviews every trade he made that morning — his entries, exits, reasoning, and lessons learned. He also records live trading sessions and educational content including game plans, strategy tutorials, and year-in-review videos. These transcripts are those videos converted to text.

The goal of this extraction project is to build a structured dataset from approximately 1,800 videos that can be used for programmatic analysis to identify Ross's trading patterns, scanner methodology, and decision-making frameworks — ultimately informing the development of jTrader, an algorithmic trading system that emulates his strategy.

**Format consistency is the single most important requirement.** Every output must look identical in structure within its format type, regardless of what is in the transcript. A reviewer should be able to look at any two entries of the same TYPE and see the exact same structure every time.

---

*End of Instructions*
