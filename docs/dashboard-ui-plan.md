# jTrader Dashboard UI — Improvement Plan

## Overview

The current dashboard surfaces a minimal view: the active watchlist (1 stock per strategy), server logs, and total P&L. This plan expands the UI into a full **Decision Transparency Dashboard** — showing all candidate stocks being evaluated, the live metrics driving decisions, the algo's current reasoning state for each ticker, and real-time position sizing calculations.

The goal is dual-purpose: operational awareness during live trading, and a learning tool to understand how the algorithm behaves tick by tick.

---

## Current State (Baseline)

| Section     | What It Shows                              |
| ----------- | ------------------------------------------ |
| Watchlist   | 1 stock per active strategy (the "winner") |
| Server Logs | Raw backend log stream                     |
| P&L         | Total realized/unrealized P&L              |

**Key gap:** The algo is evaluating many stocks and making complex decisions every minute. None of that intermediate reasoning is visible.

---

## Proposed Dashboard Layout

The dashboard is organized into **four sections**, designed for a widescreen monitor during market hours.

```
┌──────────────────────────────────────────────────────────┐
│  HEADER: Market Temp | Session Clock | P&L Summary        │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  [1] CANDIDATE TABLE (top ~70% of screen width)          │
│      Top 10–20 stocks being evaluated, all metrics       │
│                                                          │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  [2] DECISION ENGINE PANEL (full width)                  │
│      Per-ticker stage + reasoning + entry threshold      │
│                                                          │
├─────────────────────────┬────────────────────────────────┤
│  [3] POSITION MONITOR   │  [4] SERVER LOGS               │
│  Active/pending trades  │  Raw log stream (scrollable)   │
└─────────────────────────┴────────────────────────────────┘
```

---

## Section 1: Candidate Table

Replaces the current single-stock watchlist. Shows all stocks being actively scanned and scored, ranked by composite score descending.

**Columns:**

| Column        | Description                                              |
| ------------- | -------------------------------------------------------- |
| Rank          | Current composite score rank                             |
| Symbol        | Ticker                                                   |
| Price         | Current price (live)                                     |
| % Change      | Pre-market or intraday % gain                            |
| Rel. Vol      | Relative volume (e.g. 4.2x)                              |
| Float         | Share float in millions                                  |
| News          | Catalyst flag (✓ / — / source tag)                       |
| Gap %         | Pre-market gap percentage                                |
| Score         | Composite algo score (0–100 or weighted)                 |
| Threshold Gap | **How far the stock is from triggering** (e.g. −0.8 pts) |
| Stage         | Current pipeline stage (see Section 2)                   |

The **Threshold Gap** column is the highest-value addition — it shows not just where each stock ranks, but how close it is to the decision line. This lets you see momentum building in real time before a trigger fires.

Rows should be color-coded by stage:

- Gray: SCANNING
- Blue: QUALIFYING
- Yellow: WATCHING
- Orange: ARMED
- Green: ENTERED
- Red/dim: EXITED or DROPPED

---

## Section 2: Decision Engine Panel

This is the new centerpiece of the dashboard. For each stock in the candidate table, it shows the algo's current decision state, reasoning, and what would need to happen to advance to the next stage.

### Stage Pipeline

Every stock moves through this state machine:

```
SCANNING → QUALIFYING → WATCHING → ARMED → ENTERED → EXITED
                                                   ↘ DROPPED (criteria miss)
```

### Per-Ticker Decision Card

Each ticker in the WATCHING or ARMED stage gets an expanded card:

```
┌─────────────────────────────────────────────────────────┐
│  TICKER: ABCD   Stage: ARMED   ⬆ 14.3%   $7.18        │
├─────────────────────────────────────────────────────────┤
│  ✓ Rel Vol: 5.1x (threshold: 2x)                       │
│  ✓ Float: 6.2M shares (threshold: <10M)                 │
│  ✓ Gap: 14.3% (threshold: >10%)                         │
│  ✓ News catalyst: Press release 6:42 AM                 │
│  ✓ Market temp: HOT                                     │
├─────────────────────────────────────────────────────────┤
│  ENTRY TRIGGER: First 1-min candle close above $7.42   │
│  Current price: $7.18  →  $0.24 away from trigger      │
├─────────────────────────────────────────────────────────┤
│  POSITION SIZE: 500 shares @ $7.42 limit               │
│  Total cost: $3,710  |  14.8% of daily risk capital    │
└─────────────────────────────────────────────────────────┘
```

Cards in earlier stages (SCANNING, QUALIFYING) can be collapsed — just show the stage label and next unmet criterion. Only WATCHING and ARMED stocks get the full expanded card.

### Why Each Criterion Shows

Every metric displayed shows:

1. The **current value** from the data feed
2. The **threshold** the algo requires
3. A **pass/fail indicator** (✓ or ✗)

This is the core learning mechanism — you can see exactly why a stock is or isn't advancing, in real time.

---

## Section 3: Position Monitor

Shows any positions that are currently open or pending, with live tracking.

**Columns for active positions:**

| Column        | Description                  |
| ------------- | ---------------------------- |
| Symbol        | Ticker                       |
| Entry Price   | Actual fill price            |
| Current Price | Live price                   |
| Shares        | Number of shares held        |
| P&L ($)       | Unrealized dollar gain/loss  |
| P&L (%)       | Unrealized percent gain/loss |
| Stop          | Current stop loss level      |
| Target        | Profit target level          |
| Risk          | $ at risk if stopped out     |

Color: green rows for profitable positions, red for drawdown.

---

## Section 4: Server Logs

Retained from current UI. No major changes needed — just ensure it remains scrollable and timestamped. Consider adding a log-level filter toggle (INFO / WARNING / ERROR) if log volume becomes noisy.

---

## Header Bar

A persistent status bar at the top of the dashboard:

```
jTrader  |  [HOT 🔥]  |  09:47:23  |  Session P&L: +$412.50  |  Trades: 3  |  Risk Used: 38%
```

| Element       | Description                                    |
| ------------- | ---------------------------------------------- |
| Market Temp   | HOT / NEUTRAL / COLD badge from the classifier |
| Session Clock | Live market time                               |
| Session P&L   | Running realized + unrealized                  |
| Trade Count   | Number of completed trades today               |
| Risk Used     | % of daily risk capital deployed or committed  |

---

## Two Display Modes

Cognitive load during live trading is real. The dashboard should support two modes toggled by a button or keyboard shortcut:

**Pre-Market / Research Mode** (before 9:30 AM)

- Full candidate table with all 10–20 stocks
- All columns visible
- All decision cards expanded
- Good for reviewing the scan landscape and validating setup quality

**Live Trading Mode** (9:30 AM+)

- Candidate table narrows to top 5 by score
- Only WATCHING and ARMED cards shown in Decision Engine
- Larger text on key metrics (price, trigger, P&L)
- Log section minimized

---

## Implementation Notes

- The candidate table and decision cards should **auto-refresh every 60 seconds** (or on each scan cycle), with a visible "Last updated: Xs ago" counter
- Stage transitions should **flash briefly** when a stock advances (e.g. QUALIFYING → WATCHING) to draw attention without being disruptive
- All threshold values displayed in the decision cards should be **pulled directly from the algo config** — not hardcoded in the frontend — so they stay in sync as parameters are tuned via Optuna
- Consider logging each stage transition with a timestamp to a separate **decision audit log** (not just the server log) — this will be invaluable for post-session review

---

## Phased Build Order

1. **Phase 1** — Expand watchlist to top 10–20 candidates with all metric columns
2. **Phase 2** — Add stage column and basic stage badge coloring
3. **Phase 3** — Build Decision Engine panel with per-ticker criteria cards
4. **Phase 4** — Add position sizing display to ARMED cards
5. **Phase 5** — Add header bar with market temp, session P&L, risk usage
6. **Phase 6** — Implement Pre-Market vs. Live Trading mode toggle
