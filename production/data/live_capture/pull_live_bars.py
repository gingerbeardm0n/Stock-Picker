"""
pull_live_bars.py — pull today's captured live bars from the jTrader API and
insert them into TimescaleDB (stock_candles_live_1m).

Run once per day after the session (any time before the next Render redeploy —
the capture file lives on ephemeral disk).

The table mirrors stock_candles_1m plus `source` (poller / vwap_seed) and
`received_at`, so live Tradier-sandbox data can be diffed against the
historical Alpaca data used for training:

    SELECT l.symbol, l.time, l.close AS live_close, h.close AS hist_close
    FROM stock_candles_live_1m l
    JOIN stock_candles_1m h USING (symbol, time);

Usage:
    python pull_live_bars.py
    python pull_live_bars.py --api https://jtrader-api.onrender.com
"""
import argparse
import os
import sys
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras
import requests
from dotenv import load_dotenv

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
load_dotenv(os.path.join(REPO_ROOT, '.env.paper'))

DB_DSN = os.getenv('DB_DSN') or os.getenv('OPTUNA_STORAGE')
if not DB_DSN:
    sys.exit("Set DB_DSN (postgresql://user:pass@host:5432/stockdata) in env or .env.paper")

CREATE_NEWS_SQL = """
CREATE TABLE IF NOT EXISTS stock_news_live (
    id           BIGSERIAL PRIMARY KEY,
    symbol       TEXT NOT NULL,
    headline     TEXT NOT NULL,
    source       TEXT,
    created_at   TIMESTAMPTZ,
    summary      TEXT,
    url          TEXT,
    symbol_count INT,
    is_specific  BOOLEAN,
    news_tier    TEXT,
    received_at  TIMESTAMPTZ NOT NULL,
    UNIQUE(symbol, headline, created_at)
);
CREATE INDEX IF NOT EXISTS idx_news_live_symbol_time
    ON stock_news_live (symbol, created_at DESC);
"""

INSERT_NEWS_SQL = """
INSERT INTO stock_news_live
    (symbol, headline, source, created_at, summary, url,
     symbol_count, is_specific, news_tier, received_at)
VALUES %s
ON CONFLICT (symbol, headline, created_at) DO NOTHING
"""

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS stock_candles_live_1m (
    time        TIMESTAMPTZ      NOT NULL,
    symbol      VARCHAR(10)      NOT NULL,
    open        NUMERIC(12,4)    NOT NULL,
    high        NUMERIC(12,4)    NOT NULL,
    low         NUMERIC(12,4)    NOT NULL,
    close       NUMERIC(12,4)    NOT NULL,
    volume      BIGINT           NOT NULL,
    vwap        NUMERIC(12,6),
    source      TEXT             NOT NULL,
    received_at TIMESTAMPTZ      NOT NULL,
    PRIMARY KEY (time, symbol, source)
);
CREATE INDEX IF NOT EXISTS idx_live_1m_symbol_time
    ON stock_candles_live_1m (symbol, time DESC);
"""

INSERT_SQL = """
INSERT INTO stock_candles_live_1m
    (time, symbol, open, high, low, close, volume, vwap, source, received_at)
VALUES %s
ON CONFLICT (time, symbol, source) DO NOTHING
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--api', default=os.getenv('JTRADER_API_URL', 'https://jtrader-api.onrender.com'))
    ap.add_argument('--date', default=None,
                    help='YYYY-MM-DD to pull a prior day still on disk (default: today)')
    args = ap.parse_args()

    headers = {}
    api_key = os.getenv('JTRADER_API_KEY', '')
    if api_key:
        headers['X-API-Key'] = api_key

    params = {'date': args.date} if args.date else {}

    print(f"Fetching {args.api}/bars_dump (date={args.date or 'today'}) ...")
    r = requests.get(f"{args.api}/bars_dump", headers=headers, params=params, timeout=60)
    r.raise_for_status()
    payload = r.json()
    bars = payload.get('bars', [])
    print(f"  {len(bars)} bars captured (available on disk: {payload.get('available')})")

    rows = []
    for b in bars:
        try:
            rows.append((
                b['t'], b['symbol'],
                float(b['o']), float(b['h']), float(b['l']), float(b['c']),
                int(b['v'] or 0), float(b['vw'] or 0) or None,
                b.get('source', 'unknown'),
                b.get('received_at') or datetime.now(timezone.utc).isoformat(),
            ))
        except (KeyError, TypeError, ValueError) as e:
            print(f"  skipping malformed row: {e} — {b}", file=sys.stderr)

    print(f"Fetching {args.api}/news_dump (date={args.date or 'today'}) ...")
    news_rows = []
    try:
        rn = requests.get(f"{args.api}/news_dump", headers=headers, params=params, timeout=60)
        rn.raise_for_status()
        news = rn.json().get('news', [])
        print(f"  {len(news)} news articles captured")
        for a in news:
            try:
                news_rows.append((
                    a['symbol'], a.get('headline', ''), a.get('source'),
                    a.get('created_at') or None, a.get('summary'), a.get('url'),
                    a.get('symbol_count'), a.get('is_specific'),
                    a.get('news_tier', 'none'),
                    a.get('received_at') or datetime.now(timezone.utc).isoformat(),
                ))
            except (KeyError, TypeError) as e:
                print(f"  skipping malformed news row: {e} — {a}", file=sys.stderr)
    except requests.RequestException as e:
        print(f"  news_dump unavailable ({e}) — older API build? continuing", file=sys.stderr)

    if not rows and not news_rows:
        return

    conn = psycopg2.connect(DB_DSN)
    try:
        with conn, conn.cursor() as cur:
            cur.execute(CREATE_SQL)
            cur.execute(CREATE_NEWS_SQL)
            if rows:
                psycopg2.extras.execute_values(cur, INSERT_SQL, rows, page_size=1000)
            if news_rows:
                psycopg2.extras.execute_values(cur, INSERT_NEWS_SQL, news_rows, page_size=1000)
            cur.execute("SELECT COUNT(*) FROM stock_candles_live_1m")
            total = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM stock_news_live")
            news_total = cur.fetchone()[0]
        print(f"  inserted {len(rows)} bars + {len(news_rows)} news rows (duplicates skipped); "
              f"totals: bars={total}, news={news_total}")
    finally:
        conn.close()


if __name__ == '__main__':
    main()
