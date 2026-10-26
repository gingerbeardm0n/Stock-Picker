# STATUS — where the project is right now

**One-screen current state. Rewrite the top sections each working session.**
History goes in `docs/PROJECT_HISTORY.md`; durable facts in `memory/`; this file is
the "what's true today / what's next / what's blocking" snapshot an agent reads first.

_Updated: 2026-10-26 (Mon) — after the Level 2 pilot and no-news fade tests_

---

## The headline

**jTrader is a research project right now, not a live trader.** Joel is continuing it
(he is not pivoting to jSwing). Nothing trades: the daily live session is switched off
(`SESSIONS_SUSPENDED = True`, confirmed in the Oct 20 log: cron fired, "sessions SUSPENDED").

What we know (details: `docs/DECISION_2026_10_ROSS_EDGE.md`, `docs/PREREG_2026_10_LIQUID_NEWS_GAP.md`):

1. **The old strategies were never real.** The simulator filled stops at the exact stop
   price; under honest fills scalp 211 / VWAP 188 / MP 167 all lose (deep review, Sep 18).
2. **Ross Cameron's measurable edge is premarket stock selection on news days**, about +1%
   per trade vs other flagged movers, roughly the size of premarket trading costs (median
   spread 0.71%). A model can recognize which stock he picks, but its picks lose.
3. **Every mechanical rule tested on minute bars loses after costs**: entries, breakouts,
   pullbacks, news, AI headline ratings, float, market temperature, the tape (pre-registered,
   FAIL 10-19), and liquid news gap-ups with an opening-range breakout (pre-registered, FAIL 10-20:
   -0.38%/trade over 4,382 trades, negative all 6 years, flat even before costs), and the published
   "Stocks in Play" 5-minute opening-range breakout (pre-registered, FAIL 10-22: -1.01R/trade over 41,815
   trades 2016-2026, negative every year; about zero even with no costs, so the paper's gross edge did not
   reproduce; `docs/PREREG_2026_10_STOCKS_IN_PLAY_ORB.md`), and SPY/QQQ market intraday momentum (pre-registered,
   FAIL 10-23: first half hour does not predict the last half hour on 2016-2026, gross about zero, 0 of 11 years
   positive after costs; `docs/PREREG_2026_10_MARKET_INTRADAY_MOMENTUM.md`), and shorting liquid no-news gap-ups
   on fresh 2016-2020 data (pre-registered, FAIL 10-23: +0.29%/trade but CI -0.92% to +1.61%, negative at
   0.30%/side; `docs/PREREG_2026_10_NO_NEWS_GAP_FADE.md`), and the Level 2 pilot (Nasdaq order-book depth
   imbalance at the premarket flag, pre-registered, FAIL 10-26: bid-heavy minus ask-heavy +0.09%, CI spans 0;
   bid-heavy -1.24%/trade net; `docs/PREREG_2026_10_L2_BOOK_PILOT.md`).
4. **The one result that keeps repeating:** stocks moving on real news beat stocks moving
   without news, in small caps and liquid stocks alike. It has never been profitable on its own.

## Deployed / live

- **Render API** (`https://jtrader-api.onrender.com`): up, but `run_daily_sessions()` returns
  immediately (kill switch in `production/api/session_job.py`). Resume = set the flag to False
  and redeploy, but only with a strategy that passed a pre-registered test.
- **Tradier data feed: dead since Jul 22** (unfunded login). Not funded by decision.
- GitHub Actions (watchdog, capture, report, rel-vol baseline) still run; they treat "not
  triggered" as normal and capture empty days. Harmless; could be disabled.
- Dashboard: `jtrader-dashboard.vercel.app` (DEMO mode shows fake symbols if the API fetch fails).

## Next actions

1. **Next research idea (Joel's call):** nothing queued. Databento account live (Oct 23): about $124 credit
   left, $100 monthly limit; any spend needs Joel's explicit OK. Candidates: a Level 2 order-book pilot
   (Databento free credit; needs Joel to create the account), Ross's audience effect, futures
   (single order book), or what to add on top of the news effect. Every new idea gets a
   pre-registered test committed before its data is pulled.
2. Reddit follow-up to u/keeganm181 with the tape and liquid results (drafts in `community/`).
3. Cleanup: `parity_results.json` churn, move `community/` under `docs/`, refresh `docs/PARITY.md`,
   stale `test_scalp_engine.py::test_param_count`.

## Known-bad tooling (do not trust these)

- **Any P&L from the `par` fill mode.** The honest exit fill model is the default; `par` exists
  only to reproduce old numbers.
- **The simulator cannot rank trailing-stop width** (perfect hindsight of each 1-minute bar).
- **Absolute returns in tests 2, 4-7, 9-12 of the decision doc** charged slippage on exits only
  (about 0.3% too generous). Paired comparisons are unaffected.
- **VWAP Trial 188 sealed number does not reproduce** on the current DB.
- **Our main minute-bar DB is not a full universe:** snapshot $1-$20 ticker list (survivorship),
  08:00-12:00 only. Research since Oct 8 uses its own SIP backfills (`ross_*`, `liq_*` tables).

## Open issues

| # | Title | State |
|---|---|---|
| 24 | Structural Ross exits | stage 1 merged, inert; stage 2 not started |
| 16 | Off-by-one `bars_since_open` live validation | blocked (no live sessions) |
| 13 | Audit backlog | open |
| 10 | Trial 211 live fill-parity check | moot (211 retired) |

## Operational runbook notes

- **Never push to main before 12:00 ET on trading days.**
- Local backtest DB is Docker (`stockdata-timescale`). If Docker Desktop shows an error on start,
  check the backend log for `dockerInference`: stop all docker processes, `wsl --shutdown`, rename
  `%LOCALAPPDATA%\Docker\run`, start Docker Desktop ONCE.
- Alpaca free key: SIP bars, quotes and trades older than 15 minutes are free; read `/assets` via
  raw REST (alpaca-py rejects the new `TXSE` exchange). SEC requests need `SEC_USER_AGENT`.
- Secrets: SOPS-encrypted `production/.env.render`. Never echo a secret value.
- Agent roster: `.claude/agents/` (strategy-architect, quant-runner, trade-logic-reviewer);
  routing rules in `.claude/CLAUDE.md`.
