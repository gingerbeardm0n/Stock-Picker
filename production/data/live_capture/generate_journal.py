#!/usr/bin/env python3
"""
generate_journal.py — Build a human-readable trade journal from captured session JSON.

Reads data/sessions/{DATE}_*.json  →  writes data/sessions/{DATE}_journal.md

One markdown file per trading day. Designed to be committed to the data
branch so the full history accumulates and can be browsed on GitHub.

Usage:
    python generate_journal.py --date 2026-06-22 --session-dir data/sessions/
    python generate_journal.py  # auto-detects today's date
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, date, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load(path: Path) -> dict | list | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _fmt_pnl(pnl) -> str:
    if pnl is None:
        return "—"
    try:
        v = float(pnl)
        sign = "+" if v >= 0 else ""
        return f"{sign}${v:,.2f}"
    except Exception:
        return str(pnl)


def _fmt_float(fs) -> str:
    if fs is None:
        return "—"
    try:
        v = int(fs)
        if v >= 1_000_000:
            return f"{v / 1_000_000:.1f}M"
        if v >= 1_000:
            return f"{v / 1_000:.0f}K"
        return str(v)
    except Exception:
        return str(fs)


def _fmt_rv(rv) -> str:
    if rv is None:
        return "—"
    try:
        return f"{float(rv):.2f}x"
    except Exception:
        return str(rv)


def _fmt_gap(g) -> str:
    if g is None:
        return "—"
    try:
        return f"{float(g):.1f}%"
    except Exception:
        return str(g)


def _news_label(c: dict) -> str:
    if c.get("has_news"):
        tier = c.get("news_tier") or ""
        return f"✓ {tier}" if tier else "✓"
    return "✗"


def _filter_reason(c: dict, config: dict) -> str:
    """Explain why a candidate didn't advance past screening."""
    reasons = []
    rv = c.get("rel_vol")
    min_rv = config.get("min_relative_volume")
    if rv is not None and min_rv is not None:
        try:
            if float(rv) < float(min_rv):
                reasons.append(f"rv {_fmt_rv(rv)} < {_fmt_rv(min_rv)}")
        except Exception:
            pass

    gap = c.get("gap_pct")
    min_gap = config.get("min_gap_pct")
    if gap is not None and min_gap is not None:
        try:
            if float(gap) < float(min_gap):
                reasons.append(f"gap {_fmt_gap(gap)} < {_fmt_gap(min_gap)}")
        except Exception:
            pass

    fs = c.get("float_shares")
    max_float = config.get("max_float")
    if fs is not None and max_float is not None:
        try:
            if float(fs) > float(max_float):
                reasons.append(f"float {_fmt_float(fs)} > {_fmt_float(max_float)}")
        except Exception:
            pass

    if not c.get("has_news") and config.get("require_news"):
        reasons.append("no news")

    price = c.get("open_price")
    max_price = config.get("max_price")
    if price is not None and max_price is not None:
        try:
            if float(price) > float(max_price):
                reasons.append(f"price ${float(price):.2f} > ${float(max_price):.2f}")
        except Exception:
            pass

    return "; ".join(reasons) if reasons else "passed screening"


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def _strategy_section(
    name: str,
    state: dict,
    trades: list[dict],
    label: str,
) -> list[str]:
    lines: list[str] = []
    lines.append(f"## {label}")

    stage = state.get("stage") or state.get("last_result") or "unknown"
    last_run = (state.get("last_run") or "")[:19]
    lines.append(f"**Stage:** {stage}  |  **Last run:** {last_run or '—'}")
    lines.append("")

    # Candidates table
    candidates = state.get("candidates") or state.get("watchlist") or []
    config = state.get("config") or {}
    top_pick = state.get("top_pick") or state.get("symbol")

    if candidates:
        lines.append("### Candidates Evaluated")
        lines.append("| # | Symbol | Gap% | Rel Vol | Float | News | Stage | Filter |")
        lines.append("|---|--------|------|---------|-------|------|-------|--------|")
        for i, c in enumerate(candidates, 1):
            sym = c.get("symbol", "?")
            is_top = " ⭐" if sym == top_pick else ""
            cstage = c.get("stage") or "—"
            reason = _filter_reason(c, config) if cstage in ("DROPPED", "WATCHING") else cstage
            lines.append(
                f"| {i} | **{sym}**{is_top} | {_fmt_gap(c.get('gap_pct'))} "
                f"| {_fmt_rv(c.get('rel_vol'))} | {_fmt_float(c.get('float_shares'))} "
                f"| {_news_label(c)} | {cstage} | {reason} |"
            )
        lines.append("")

        # Config thresholds for reference
        if config:
            thresholds = []
            if config.get("min_gap_pct") is not None:
                thresholds.append(f"gap ≥ {_fmt_gap(config['min_gap_pct'])}")
            if config.get("min_relative_volume") is not None:
                thresholds.append(f"rv ≥ {_fmt_rv(config['min_relative_volume'])}")
            if config.get("max_float") is not None:
                thresholds.append(f"float ≤ {_fmt_float(config['max_float'])}")
            if config.get("require_news"):
                thresholds.append("news required")
            if config.get("max_price") is not None:
                thresholds.append(f"price ≤ ${config['max_price']:.2f}")
            if thresholds:
                lines.append(f"*Thresholds: {', '.join(thresholds)}*")
                lines.append("")
    else:
        lines.append("*No candidates evaluated.*")
        lines.append("")

    # Strategy trades
    strat_trades = [t for t in trades if t.get("strategy") == name]
    if not strat_trades:
        # Check if position info is in state
        ep = state.get("entry_price")
        xp = state.get("exit_price")
        if ep and float(ep) > 0:
            strat_trades = [state]  # treat state itself as one trade record

    if strat_trades:
        lines.append("### Trades")
        for t in strat_trades:
            sym = t.get("symbol") or t.get("top_pick") or "?"
            ep = t.get("entry_price")
            xp = t.get("exit_price")
            sh = t.get("shares")
            pnl = t.get("pnl")
            bh = t.get("bars_held")
            reason = t.get("exit_reason") or t.get("last_result") or "—"
            lines.append(f"- **{sym}**: entry ${float(ep):.2f} → exit ${float(xp):.2f}"
                         f"  |  {sh} shares  |  {bh} bars  |  {_fmt_pnl(pnl)}  |  _{reason}_"
                         if ep and xp else f"- {sym}: incomplete trade data")
        lines.append("")
    else:
        lines.append("*No trades this session.*")
        lines.append("")

    return lines


def _log_highlights(logs: list[dict]) -> list[str]:
    lines = ["## Log Highlights"]
    warnings = [l for l in logs if l.get("level") in ("WARNING", "WARN")]
    errors   = [l for l in logs if l.get("level") == "ERROR"]
    key_msgs = [l for l in logs if any(kw in l.get("msg", "") for kw in
                ("SESSION STARTING", "SESSION COMPLETE", "ENTRY:", "EXIT:", "FILLED",
                 "Trigger", "VWAP", "SCALP", "MICRO", "top_pick", "No candidates"))]

    if errors:
        lines.append(f"### Errors ({len(errors)})")
        for e in errors[:10]:
            lines.append(f"- `{e.get('t','')}` {e.get('msg','')}")
        if len(errors) > 10:
            lines.append(f"- *…{len(errors)-10} more*")
        lines.append("")

    if warnings:
        lines.append(f"### Warnings ({len(warnings)})")
        for w in warnings[:15]:
            lines.append(f"- `{w.get('t','')}` {w.get('msg','')}")
        if len(warnings) > 15:
            lines.append(f"- *…{len(warnings)-15} more*")
        lines.append("")

    if key_msgs:
        lines.append("### Key Events")
        for m in key_msgs[:20]:
            lines.append(f"- `{m.get('t','')}` {m.get('msg','')}")
        lines.append("")

    if not errors and not warnings and not key_msgs:
        lines.append("*No warnings or errors.*")
        lines.append("")

    return lines


# ---------------------------------------------------------------------------
# Main journal builder
# ---------------------------------------------------------------------------

def build_journal(session_date: date, session_dir: Path) -> str:
    prefix = str(session_date)
    dashboard = _load(session_dir / f"{prefix}_dashboard.json") or {}
    trades_raw = _load(session_dir / f"{prefix}_trades.json") or []
    logs_raw   = _load(session_dir / f"{prefix}_logs.json") or []

    # Normalise trades (GET /trades returns {"trades": [...]} wrapper, not a bare list)
    if isinstance(trades_raw, dict):
        trades_raw = trades_raw.get("trades") or []

    # Normalise logs (may be list of dicts or {"logs": [...]} wrapper)
    if isinstance(logs_raw, dict):
        logs_raw = logs_raw.get("logs") or []

    dow = session_date.strftime("%A")
    lines: list[str] = []

    # ── Header ──────────────────────────────────────────────────────────────
    lines.append(f"# Trade Journal — {dow} {session_date.strftime('%B %-d, %Y')}")
    lines.append("")

    # ── Session summary ──────────────────────────────────────────────────────
    total_pnl = dashboard.get("session_pnl") or 0
    trade_count = dashboard.get("trade_count") or len(trades_raw)
    result_str = "No trades" if trade_count == 0 else f"{trade_count} trade{'s' if trade_count != 1 else ''}"

    lines.append("## Session Summary")
    lines.append("")
    lines.append("| | |")
    lines.append("|---|---|")
    lines.append(f"| Date | {dow}, {session_date.strftime('%B %-d, %Y')} |")
    lines.append(f"| Result | {result_str} |")
    lines.append(f"| Session P&L | {_fmt_pnl(total_pnl)} |")
    lines.append(f"| Strategies | Opening Bell Scalp + VWAP Reclaim + Micro-Pullback |")
    lines.append("")

    # ── Individual strategy sections ─────────────────────────────────────────
    scalp_state = dashboard.get("scalp") or {}
    vwap_state  = dashboard.get("vwap")  or {}
    micro_state = dashboard.get("micro_pullback") or {}

    if scalp_state:
        lines.extend(_strategy_section("opening_bell_scalp", scalp_state, trades_raw, "Opening Bell Scalp"))
    if vwap_state:
        lines.extend(_strategy_section("vwap_reclaim", vwap_state, trades_raw, "VWAP Reclaim"))
    if micro_state:
        lines.extend(_strategy_section("micro_pullback", micro_state, trades_raw, "Micro-Pullback"))

    # ── Completed trades detail ────────────────────────────────────────────
    if trades_raw:
        lines.append("## All Trades")
        lines.append("")
        lines.append("| # | Strategy | Symbol | Entry | Exit | Shares | Bars | P&L | Reason |")
        lines.append("|---|----------|--------|-------|------|--------|------|-----|--------|")
        total = 0.0
        for i, t in enumerate(trades_raw, 1):
            sym = t.get("symbol") or "?"
            strat = (t.get("strategy") or "?").replace("_", " ").title()
            ep  = t.get("entry_price")
            xp  = t.get("exit_price")
            sh  = t.get("shares") or "—"
            bh  = t.get("bars_held") or "—"
            pnl = t.get("pnl") or 0
            total += float(pnl) if pnl else 0
            reason = t.get("exit_reason") or "—"
            ep_s = f"${float(ep):.2f}" if ep else "—"
            xp_s = f"${float(xp):.2f}" if xp else "—"
            lines.append(
                f"| {i} | {strat} | {sym} | {ep_s} | {xp_s} | {sh} | {bh} "
                f"| {_fmt_pnl(pnl)} | {reason} |"
            )
        lines.append(f"| | | | | | | | **{_fmt_pnl(total)}** | |")
        lines.append("")

    # ── Log highlights ────────────────────────────────────────────────────
    if logs_raw:
        lines.extend(_log_highlights(logs_raw))

    # ── Footer ────────────────────────────────────────────────────────────
    captured_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines.append("---")
    lines.append(f"*Captured {captured_at} · Generated by session-capture workflow*")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Generate trade journal from session JSON.")
    ap.add_argument("--date", default=None, help="Session date YYYY-MM-DD (default: today)")
    ap.add_argument("--session-dir", default="data/sessions", help="Directory with session JSON files")
    args = ap.parse_args()

    session_date = date.fromisoformat(args.date) if args.date else date.today()
    session_dir  = Path(args.session_dir)

    if not session_dir.exists():
        print(f"ERROR: session dir not found: {session_dir}")
        sys.exit(1)

    print(f"Generating journal for {session_date.isoformat()} from {session_dir}/")
    journal = build_journal(session_date, session_dir)

    out_path = session_dir / f"{session_date.isoformat()}_journal.md"
    out_path.write_text(journal)
    print(f"Written: {out_path} ({len(journal):,} chars)")

    # Print summary line for Actions log
    first_lines = "\n".join(journal.splitlines()[:8])
    print("\n--- Journal preview ---")
    print(first_lines)


if __name__ == "__main__":
    main()
