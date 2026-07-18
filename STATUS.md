# STATUS — where the project is right now

**One-screen current state. Rewrite the top sections each working session.**
History goes in `docs/PROJECT_HISTORY.md`; durable facts in `memory/`; this file is
the "what's true today / what's next / what's blocking" snapshot an agent reads first.

_Updated: 2026-07-17 (Fri evening)_

---

## Deployed / live (paper)

- **jTrader** on Render (`https://jtrader-api.onrender.com`): daily session =
  Opening Bell Scalp (9:30–9:40) → Micro-Pullback (9:40–10:00) → VWAP Reclaim
  (10:00–11:30). **Alpaca paper orders** (websocket `trade_updates` fill stream),
  Tradier production for data. Dashboard: `jtrader-dashboard.vercel.app`
  (falls back to DEMO mode with fake symbols when the API fetch fails — check
  the DEMO badge before believing numbers).
- **Fills work as of Jul 16** — first confirmed live fill (ATPC) via the
  websocket stream after a 0%-fill drought Jul 7–15 (REST `get_order` lags
  minutes on paper; only-IEX matching means zero-volume tickers never fill).

## Live configs in use

- **Scalp**: Trial 211 (`require_news=False`, market orders, non-blocking
  pending entries `dc78541`). Post-filter sealed expectation: **+$4,675 / PF 3.31**
  (2025) — re-baselined by issue #23 (was +$5,956/2.70 incl. phantom fallback fills).
- **VWAP**: Trial 188 (`require_news=False`, sealed PF 2.19 / +$3,299), deployed
  Jul 10 — in 1-week live validation.
- **Micro-Pullback**: live in paper, market-fallback retry shipped; strategy
  UNDER-REVIEW for viability (fill-model re-opt failed seal; stays on 167).

## In-flight validation gates

1. **Rel-vol fallback exclusion (issue #23)** — backtested (PF 2.70→3.31 2025,
   3.45→5.04 2026 YTD, maxDD −64/−77%), implemented in sim + live scalp runner
   Jul 17; **verification rerun + deploy pending**, then watch first live session.
2. **Fill-parity check (issue #10)** — Trial 211 live fills vs sim fill model,
   1 week of data needed. Jul 16 data point: +2.1% entry slippage pre-fix.
3. **Off-by-one live validation (issue #16)** — 3 clean trading days needed.
4. **Deploy-during-cron double-fire fix** — verified via Neon session_flags;
   keep the **NO-pushes-before-12:00-ET** rule permanently.

## Next actions

1. **Deploy the rel-vol exclusion** (worktree branch → main, off-hours) after
   the verification backtest confirms new-baseline == ablation variant.
2. **Watch next live session** for: stream fills confirming <30s, no phantom
   fallback symbols armed, accurate exit P&L (120s fill wait, `dc78541`).
3. **Trade-history duplication bug** — dashboard shows Jul 6/Jul 7 as identical
   trade sets; parser/dedup issue, not yet root-caused.
4. Backlog after validation matures: **P1 safety nets** (circuit breakers,
   market-temp gate — deferred by choice, tasks #22/#23), then **P3
   Ross-fidelity upgrades** (VWAP scaled exits first — biggest upside).

## Priority backlog (docs/STRATEGY_ROADMAP.md)

- **P0 data integrity** ✅ done (fingerprinting + VWAP re-validation → Trial 184/188)
- **P1 fixed-rule safety nets** ⏸ deferred until strategies proven individually live
- **P2 micro-pullback coverage** ✅ built + live (viability under review)
- **P3 Ross-fidelity upgrades** ❌ not started (each = full re-opt cycle)

## Blockers / watch

- **News coverage gap (issue #17)**: Finnhub/Alpaca miss microcap catalysts
  (CHAI +451% = 0 articles). Squeeze-class detection needs a paid source —
  user cost decision pending. Follow-ups #18–21.
- **Local backtest DB** lives in Docker Desktop (`stockdata-timescale`,
  TimescaleDB pg16). Docker Desktop crash-loops on ghost unix-socket files
  after unclean shutdown — fix: kill all docker procs, `wsl --shutdown`,
  rename `%LOCALAPPDATA%\Docker\run` + `docker-secrets-engine`, single restart.
- DB coverage: rel_vol_cum_cache through **2026-06-12** — top up before
  running sims against recent weeks.

## Parity status

See `docs/PARITY.md`. Fill model shipped in all 3 sims; scalp entries/exits now
book actual fill averages via websocket. Known audit failure: "VWAP sim checks
max_float" (1/25, pre-existing). Rel-vol fallback parity closed by issue #23
(sim + live both exclude no-baseline symbols; live keeps fail-open 10.0 only
when the whole rel-vol system is down).
