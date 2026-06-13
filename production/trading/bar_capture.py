"""
bar_capture.py — record every live bar the runners see to a daily JSONL file.

Purpose: live/sim parity. The bars Tradier sandbox delivers during a session
are otherwise used and discarded. This module appends each bar to
$JTRADER_STATE_DIR/bars_YYYYMMDD.jsonl so a post-session script can pull them
(via the /bars_dump API endpoint) and insert into TimescaleDB
(stock_candles_live_1m) for comparison against the historical training data.

Render free tier has ephemeral disk — the file survives the session but not a
redeploy. That's fine: this is diagnostic data, pulled daily after the close.
"""

from __future__ import annotations
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

_STATE_DIR = Path(os.getenv("JTRADER_STATE_DIR", "/tmp/jtrader"))
_lock = threading.Lock()


def _capture_path(day: datetime | None = None) -> Path:
    d = (day or datetime.now(timezone.utc)).strftime("%Y%m%d")
    return _STATE_DIR / f"bars_{d}.jsonl"


def record_bar(symbol: str, bar_dict: dict, source: str) -> None:
    """Append one bar to today's capture file. Never raises."""
    try:
        row = {
            "symbol": symbol,
            "t": bar_dict.get("t") or bar_dict.get("time"),
            "o": bar_dict.get("o") or bar_dict.get("open"),
            "h": bar_dict.get("h") or bar_dict.get("high"),
            "l": bar_dict.get("l") or bar_dict.get("low"),
            "c": bar_dict.get("c") or bar_dict.get("close"),
            "v": bar_dict.get("v") or bar_dict.get("volume"),
            "vw": bar_dict.get("vw") or bar_dict.get("vwap"),
            "source": source,
            "received_at": datetime.now(timezone.utc).isoformat(),
        }
        path = _capture_path()
        with _lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, default=str) + "\n")
    except Exception:
        pass  # capture must never break trading


def read_today() -> list[dict]:
    """Return all rows captured today (for the /bars_dump endpoint)."""
    return _read_jsonl(_capture_path())


def read_bars_for_date(day_str: str) -> list[dict]:
    """Return bars captured on a specific day. day_str: 'YYYY-MM-DD' or 'YYYYMMDD'.

    Lets a post-session pull fetch a PRIOR day still on disk (the endpoint was
    today-only, which stranded e.g. Friday's capture when pulled Saturday).
    """
    return _read_jsonl(_capture_path(_parse_day(day_str)))


def _news_path(day: datetime | None = None) -> Path:
    d = (day or datetime.now(timezone.utc)).strftime("%Y%m%d")
    return _STATE_DIR / f"news_{d}.jsonl"


def record_news(symbol: str, articles: list[dict], tier: str) -> None:
    """Append the articles a live runner fetched for one symbol.

    Same parity rationale as record_bar: the live news decision is otherwise
    made and discarded, leaving live-vs-historical news mismatches unprovable.
    Never raises.
    """
    try:
        now = datetime.now(timezone.utc).isoformat()
        rows = [{
            "symbol": symbol,
            "headline": a.get("headline", ""),
            "source": a.get("source"),
            "created_at": str(a.get("created_at") or ""),
            "summary": a.get("summary"),
            "url": a.get("url"),
            "symbol_count": a.get("symbol_count"),
            "is_specific": a.get("is_specific", True),
            "news_tier": tier,
            "received_at": now,
        } for a in articles]
        path = _news_path()
        with _lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                for row in rows:
                    f.write(json.dumps(row, default=str) + "\n")
    except Exception:
        pass  # capture must never break trading


def read_today_news() -> list[dict]:
    """Return all news rows captured today (for the /news_dump endpoint)."""
    return _read_jsonl(_news_path())


def read_news_for_date(day_str: str) -> list[dict]:
    """Return news captured on a specific day. day_str: 'YYYY-MM-DD' or 'YYYYMMDD'."""
    return _read_jsonl(_news_path(_parse_day(day_str)))


def available_dates(kind: str = "bars") -> list[str]:
    """List capture dates still on disk as 'YYYY-MM-DD'. kind: 'bars' or 'news'.

    Lets the puller see what prior days survive before a redeploy wipes them.
    """
    prefix = "bars_" if kind == "bars" else "news_"
    if not _STATE_DIR.exists():
        return []
    out = []
    for p in _STATE_DIR.glob(f"{prefix}*.jsonl"):
        stem = p.stem[len(prefix):]  # YYYYMMDD
        if len(stem) == 8 and stem.isdigit():
            out.append(f"{stem[:4]}-{stem[4:6]}-{stem[6:]}")
    return sorted(out)


def _parse_day(day_str: str) -> datetime:
    """Parse 'YYYY-MM-DD' or 'YYYYMMDD' into a UTC datetime for path building."""
    s = day_str.replace("-", "")
    return datetime.strptime(s, "%Y%m%d").replace(tzinfo=timezone.utc)


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return rows
