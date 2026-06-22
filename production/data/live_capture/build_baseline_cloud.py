"""
build_baseline_cloud.py — Cloud-native rel-vol baseline builder.

Primary output: Neon PostgreSQL (NEON_CONNECTION_STRING env var)
  - rel_vol_baselines table  — 30-day avg cumulative premarket vol at 9:25 ET per symbol
  - active_symbols table     — running symbol universe (grows via gapper detection)
  - pipeline_runs table      — audit log of each run

Fallback output: JSON files in --output-dir (data/ branch, backup only)
  rel_vol_baseline.json        — same data as DB for runners without DB access
  active_gapper_symbols.json   — symbol universe snapshot

Runs in GitHub Actions daily at 4:30 PM ET. Pure Alpaca API for bar data.
Alpaca free tier: iex feed, same-day bars blocked, 200 req/min.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

import requests

try:
    import psycopg2
    from psycopg2.extras import execute_values
    _PSYCOPG2_AVAILABLE = True
except ImportError:
    _PSYCOPG2_AVAILABLE = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALPACA_BASE = "https://data.alpaca.markets/v2"
SCREENER_URL = f"{ALPACA_BASE}/screener/stocks/most-actives"
SEED_SYMBOLS_PATH = os.path.join(os.path.dirname(__file__), "baseline_seed_symbols.json")

MINUTE_OF_DAY = 565    # 9:25 AM ET = 9*60+25 (rel-vol checkpoint)
LOOKBACK_DAYS = 30
MIN_DAYS_REQUIRED = 5  # skip symbol if fewer days of data (recent IPO, ticker change)
BATCH_SIZE = 50        # Alpaca multi-bar endpoint limit
GAP_THRESHOLD = 0.05   # 5% gap to qualify as gapper
REQ_DELAY_S = 0.35     # ~2.8 req/s → under 200 req/min free tier
MAX_RETRIES = 3
RETRY_BACKOFF_S = 5


# ---------------------------------------------------------------------------
# Alpaca API helpers
# ---------------------------------------------------------------------------

def _alpaca_headers() -> dict[str, str]:
    key = os.environ.get("APCA_API_KEY_ID", "")
    secret = os.environ.get("APCA_API_SECRET_KEY", "")
    if not key or not secret:
        sys.exit("ERROR: APCA_API_KEY_ID and APCA_API_SECRET_KEY must be set in environment.")
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret, "Accept": "application/json"}


def _get(url: str, params: dict, retries: int = MAX_RETRIES) -> Any:
    headers = _alpaca_headers()
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=30)
            if r.status_code == 429:
                wait = RETRY_BACKOFF_S * (attempt + 1)
                print(f"  Rate limited — sleeping {wait}s")
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            if attempt == retries - 1:
                raise
            wait = RETRY_BACKOFF_S * (attempt + 1)
            print(f"  Request error ({e}) — retry in {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"Exhausted {retries} retries for {url}")


def _paginate_bars(url: str, params: dict, key: str) -> dict[str, list[dict]]:
    """Accumulate all pages from a multi-symbol bar endpoint → {symbol: [bar, ...]}."""
    result: dict[str, list[dict]] = {}
    next_token = None
    while True:
        p = dict(params)
        if next_token:
            p["page_token"] = next_token
        data = _get(url, p)
        for sym, bars in data.get(key, {}).items():
            result.setdefault(sym, []).extend(bars)
        next_token = data.get("next_page_token")
        if not next_token:
            break
        time.sleep(REQ_DELAY_S)
    return result


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def _last_n_trading_days(n: int, as_of: date) -> list[date]:
    """Last n weekdays ending on or before as_of (most recent first).
    Holidays are not excluded — sparse days are handled by MIN_DAYS_REQUIRED."""
    days: list[date] = []
    d = as_of
    while len(days) < n:
        if d.weekday() < 5:  # Mon=0 … Fri=4
            days.append(d)
        d -= timedelta(days=1)
    return days


def _minute_of_day_et(ts_str: str) -> int:
    """Parse Alpaca bar timestamp → minute-of-day in ET (EDT=UTC-4, EST=UTC-5)."""
    dt_utc = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).astimezone(timezone.utc)
    et_offset = -4 if 3 <= dt_utc.month <= 10 else -5
    dt_et = dt_utc + timedelta(hours=et_offset)
    return dt_et.hour * 60 + dt_et.minute


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def _cumulative_vol_at_925(bars: list[dict]) -> float | None:
    """Sum volumes 4:00 AM ET → 9:25 AM ET (mod 240–565). None if no bars in window."""
    total = 0.0
    found = False
    for bar in bars:
        mod = _minute_of_day_et(bar["t"])
        if 240 <= mod <= MINUTE_OF_DAY:
            total += bar.get("v", 0) or 0
            found = True
    return total if found else None


def compute_baselines(minute_bars: dict[str, dict[str, list[dict]]]) -> dict[str, float]:
    """Avg 9:25 ET cumulative vol across days per symbol. {sym: {date: [bars]}} → {sym: avg}."""
    baselines: dict[str, float] = {}
    for sym, days in minute_bars.items():
        vols = [v for v in (_cumulative_vol_at_925(bars) for bars in days.values()) if v is not None]
        if len(vols) >= MIN_DAYS_REQUIRED:
            baselines[sym] = sum(vols) / len(vols)
    return baselines


# ---------------------------------------------------------------------------
# Fetch functions
# ---------------------------------------------------------------------------

def fetch_minute_bars_batch(
    symbols: list[str],
    trading_days: list[date],
) -> dict[str, dict[str, list[dict]]]:
    """Fetch minute bars for a batch of symbols. Returns {sym: {date_iso: [bars]}}."""
    if not symbols or not trading_days:
        return {}
    # 4:00 AM ET = 8:00 UTC (EDT). End at 13:31 UTC = 9:31 AM EDT.
    start_str = f"{trading_days[-1].isoformat()}T08:00:00Z"
    end_str   = f"{trading_days[0].isoformat()}T13:31:00Z"
    raw = _paginate_bars(
        f"{ALPACA_BASE}/stocks/bars",
        {"symbols": ",".join(symbols), "timeframe": "1Min",
         "start": start_str, "end": end_str, "limit": 10000, "feed": "iex", "sort": "asc"},
        key="bars",
    )
    day_set = {d.isoformat() for d in trading_days}
    result: dict[str, dict[str, list[dict]]] = {}
    for sym, bars in raw.items():
        by_day: dict[str, list[dict]] = {}
        for bar in bars:
            dt_utc = datetime.fromisoformat(bar["t"].replace("Z", "+00:00")).astimezone(timezone.utc)
            et_offset = -4 if 3 <= dt_utc.month <= 10 else -5
            dt_et = dt_utc + timedelta(hours=et_offset)
            d_str = dt_et.date().isoformat()
            if d_str not in day_set:
                continue
            mod = dt_et.hour * 60 + dt_et.minute
            if 240 <= mod <= MINUTE_OF_DAY:
                by_day.setdefault(d_str, []).append(bar)
        if by_day:
            result[sym] = by_day
    return result


def fetch_daily_bars_batch(symbols: list[str], start: date, end: date) -> dict[str, list[dict]]:
    """Fetch daily bars for a batch of symbols. Returns {symbol: [bars]}."""
    if not symbols:
        return {}
    return _paginate_bars(
        f"{ALPACA_BASE}/stocks/bars",
        {"symbols": ",".join(symbols), "timeframe": "1Day",
         "start": start.isoformat(), "end": end.isoformat(), "limit": 10000,
         "feed": "iex", "sort": "asc"},
        key="bars",
    )


def detect_new_gappers(existing_symbols: set[str], yesterday: date) -> list[str]:
    """Find stocks that gapped >5% yesterday via most-actives screener. Returns new symbols only."""
    print("  Checking most-actives screener for new gappers...")
    try:
        data = _get(SCREENER_URL, {"top": 100, "by": "volume"})
        candidates = [s["symbol"] for s in data.get("most_actives", []) if s.get("symbol")]
        print(f"    Got {len(candidates)} most-active candidates")
    except Exception as e:
        print(f"    WARNING: screener fetch failed ({e}) — skipping new gapper detection")
        return []

    day_before = yesterday - timedelta(days=1)
    while day_before.weekday() >= 5:
        day_before -= timedelta(days=1)

    new_candidates = [s for s in candidates if s not in existing_symbols]
    if not new_candidates:
        print("    All most-active candidates already in symbol list")
        return []

    print(f"    Fetching daily bars for {len(new_candidates)} new candidates...")
    daily = fetch_daily_bars_batch(new_candidates, day_before, yesterday)

    new_gappers: list[str] = []
    for sym, bars in daily.items():
        yday_bars  = [b for b in bars if b["t"].startswith(yesterday.isoformat())]
        prior_bars = [b for b in bars if b["t"].startswith(day_before.isoformat())]
        if not yday_bars or not prior_bars:
            continue
        open_price  = yday_bars[0].get("o", 0)
        prior_close = prior_bars[-1].get("c", 0)
        if prior_close > 0 and open_price > 0:
            gap = (open_price - prior_close) / prior_close
            if gap >= GAP_THRESHOLD:
                new_gappers.append(sym)

    print(f"    Found {len(new_gappers)} new gappers (gap >{GAP_THRESHOLD*100:.0f}%): {new_gappers[:10]}")
    return new_gappers


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------

def load_active_symbols(output_dir: str) -> list[str]:
    """Load symbols: Neon → active_gapper_symbols.json → seed file → empty."""
    # Try Neon first
    neon_symbols = load_active_symbols_from_neon()
    if neon_symbols:
        return neon_symbols
    # Fall back to JSON file (data branch)
    active_path = os.path.join(output_dir, "active_gapper_symbols.json")
    if os.path.exists(active_path):
        data = json.load(open(active_path))
        symbols = data.get("symbols", [])
        print(f"Loaded {len(symbols)} symbols from {active_path} (as_of={data.get('as_of','?')})")
        return symbols
    if os.path.exists(SEED_SYMBOLS_PATH):
        seed = json.load(open(SEED_SYMBOLS_PATH))
        symbols = seed if isinstance(seed, list) else seed.get("symbols", [])
        print(f"Loaded {len(symbols)} symbols from seed file {SEED_SYMBOLS_PATH}")
        return symbols
    print("WARNING: No Neon, no JSON, no seed file — starting empty.")
    return []


def write_baseline(output_dir: str, baselines: dict[str, float], as_of: date) -> str:
    """Write rel_vol_baseline.json. Returns the file path."""
    path = os.path.join(output_dir, "rel_vol_baseline.json")
    os.makedirs(output_dir, exist_ok=True)
    with open(path, "w") as f:
        json.dump({"as_of": as_of.isoformat(), "minute_of_day": MINUTE_OF_DAY,
                   "baselines": baselines, "floats": {}}, f, separators=(",", ":"))
    print(f"Wrote {path}: {len(baselines):,} symbols, as_of={as_of.isoformat()}")
    return path


def write_active_symbols(output_dir: str, symbols: list[str], added: list[str], as_of: date) -> str:
    """Write active_gapper_symbols.json. Returns the file path."""
    path = os.path.join(output_dir, "active_gapper_symbols.json")
    deduped = sorted(set(symbols))
    os.makedirs(output_dir, exist_ok=True)
    with open(path, "w") as f:
        json.dump({"as_of": as_of.isoformat(), "symbols": deduped,
                   "added": added, "total": len(deduped)}, f, separators=(",", ":"), indent=2)
    print(f"Wrote {path}: {len(deduped)} symbols (+{len(added)} new)")
    return path


# ---------------------------------------------------------------------------
# Neon DB write
# ---------------------------------------------------------------------------

def write_to_neon(
    baselines: dict[str, float],
    symbols: list[str],
    new_gappers: list[str],
    as_of: date,
) -> bool:
    """Upsert baselines + symbols into Neon. Returns True on success."""
    conn_str = os.environ.get("NEON_CONNECTION_STRING", "")
    if not conn_str:
        print("  NEON_CONNECTION_STRING not set — skipping Neon write")
        return False
    if not _PSYCOPG2_AVAILABLE:
        print("  psycopg2 not installed — skipping Neon write")
        return False

    try:
        conn = psycopg2.connect(conn_str)
        cur = conn.cursor()

        # Upsert rel_vol_baselines (updated_at defaults to now())
        baseline_rows = [(sym, vol, as_of) for sym, vol in baselines.items()]
        execute_values(cur, """
            INSERT INTO rel_vol_baselines (symbol, avg_volume, as_of)
            VALUES %s
            ON CONFLICT (symbol) DO UPDATE SET
                avg_volume = EXCLUDED.avg_volume,
                as_of      = EXCLUDED.as_of,
                updated_at = now()
        """, baseline_rows)

        # Upsert active_symbols (updated_at defaults to now())
        symbol_rows = [(sym, as_of) for sym in sorted(set(symbols))]
        execute_values(cur, """
            INSERT INTO active_symbols (symbol, added_on)
            VALUES %s
            ON CONFLICT (symbol) DO UPDATE SET
                updated_at = now()
        """, symbol_rows)

        # Log the run
        cur.execute("""
            INSERT INTO pipeline_runs
                (run_date, symbol_count, baseline_count, new_symbols, status)
            VALUES (%s, %s, %s, %s, 'ok')
        """, (as_of, len(symbols), len(baselines), len(new_gappers)))

        conn.commit()
        conn.close()
        print(f"  Neon write OK: {len(baselines):,} baselines, {len(symbols):,} symbols")
        return True

    except Exception as e:
        print(f"  Neon write FAILED: {e}")
        # Log failure if we can
        try:
            conn2 = psycopg2.connect(conn_str)
            cur2 = conn2.cursor()
            cur2.execute("""
                INSERT INTO pipeline_runs
                    (run_date, symbol_count, baseline_count, new_symbols, status, error_msg)
                VALUES (%s, %s, %s, %s, 'error', %s)
            """, (as_of, len(symbols), len(baselines), len(new_gappers), str(e)))
            conn2.commit()
            conn2.close()
        except Exception:
            pass
        return False


def load_active_symbols_from_neon() -> list[str]:
    """Load symbol universe from Neon. Returns empty list on failure."""
    conn_str = os.environ.get("NEON_CONNECTION_STRING", "")
    if not conn_str or not _PSYCOPG2_AVAILABLE:
        return []
    try:
        conn = psycopg2.connect(conn_str)
        cur = conn.cursor()
        cur.execute("SELECT symbol FROM active_symbols ORDER BY symbol")
        symbols = [r[0] for r in cur.fetchall()]
        conn.close()
        if symbols:
            print(f"Loaded {len(symbols)} symbols from Neon active_symbols")
        return symbols
    except Exception as e:
        print(f"  Neon symbol load failed ({e}) — falling back to JSON")
        return []


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Build rel-vol baseline from Alpaca API.")
    ap.add_argument("--output-dir", default="data/", help="Directory for output JSON files")
    ap.add_argument(
        "--lookback", type=int, default=LOOKBACK_DAYS,
        help=f"Number of trading days to average (default: {LOOKBACK_DAYS})",
    )
    ap.add_argument(
        "--skip-gapper-detection", action="store_true",
        help="Skip new-gapper detection (faster, useful for debug runs)",
    )
    args = ap.parse_args()

    output_dir = args.output_dir
    today = date.today()
    # Alpaca free tier: same-day bars blocked → use yesterday as the most recent day
    yesterday = today - timedelta(days=1)
    while yesterday.weekday() >= 5:
        yesterday -= timedelta(days=1)

    print(f"=== build_baseline_cloud.py  {today.isoformat()} ===")
    print(f"Output dir : {output_dir}")
    print(f"Using data through: {yesterday.isoformat()} (yesterday, SIP-clamp safe)")

    # ---- 1. Load symbol universe ----
    symbols = load_active_symbols(output_dir)
    if not symbols:
        print("No symbols to process — exiting.")
        sys.exit(1)

    # ---- 2. Detect new gappers (add to universe) ----
    new_gappers: list[str] = []
    if not args.skip_gapper_detection:
        new_gappers = detect_new_gappers(set(symbols), yesterday)
        if new_gappers:
            symbols = list(set(symbols) | set(new_gappers))
            print(f"Universe expanded to {len(symbols)} symbols (+{len(new_gappers)} new gappers)")
    time.sleep(REQ_DELAY_S)

    # ---- 3. Determine trading days ----
    trading_days = _last_n_trading_days(args.lookback, yesterday)
    print(f"\nFetching minute bars for {len(symbols)} symbols across {len(trading_days)} days")
    print(f"Date range: {trading_days[-1].isoformat()} → {trading_days[0].isoformat()}")

    # ---- 4. Fetch minute bars in batches ----
    all_bars: dict[str, dict[str, list[dict]]] = {}  # {sym: {date: [bars]}}
    batches = [symbols[i:i + BATCH_SIZE] for i in range(0, len(symbols), BATCH_SIZE)]
    total_batches = len(batches)

    for batch_idx, batch in enumerate(batches, 1):
        print(f"\nBatch {batch_idx}/{total_batches}: {len(batch)} symbols ...", end=" ", flush=True)
        t0 = time.time()
        try:
            batch_bars = fetch_minute_bars_batch(batch, trading_days)
            for sym, by_day in batch_bars.items():
                all_bars[sym] = by_day
            elapsed = time.time() - t0
            print(f"got bars for {len(batch_bars)}/{len(batch)} symbols ({elapsed:.1f}s)")
        except Exception as e:
            print(f"ERROR: {e} — skipping this batch")
        # Rate-limit guard: stay under 200 req/min
        time.sleep(REQ_DELAY_S)

    # ---- 5. Compute baselines ----
    print(f"\nComputing baselines ({MIN_DAYS_REQUIRED}+ day minimum)...")
    baselines = compute_baselines(all_bars)
    skipped = len(symbols) - len(baselines)
    print(
        f"  {len(baselines):,} symbols have baselines, "
        f"{skipped:,} skipped (<{MIN_DAYS_REQUIRED} days of data)"
    )

    # ---- 6. Write outputs ----
    print("\nWriting outputs...")

    # Primary: Neon DB
    neon_ok = write_to_neon(baselines, symbols, new_gappers, today)
    if not neon_ok:
        print("  WARNING: Neon write failed — runners will fall back to JSON or rv=10.0")

    # Backup: JSON files to data branch (kept for backward compat + manual recovery)
    write_baseline(output_dir, baselines, today)
    write_active_symbols(output_dir, symbols, new_gappers, today)

    print("\nDone.")


if __name__ == "__main__":
    main()
