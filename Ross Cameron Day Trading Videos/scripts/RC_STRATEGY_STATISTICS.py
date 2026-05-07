"""
RC_STRATEGY_STATISTICS.py
Parses all chunk files in extractions/ and produces a statistics markdown report.
Output: RC_STRATEGY_STATISTICS.md
Re-run anytime to refresh stats as chunk files are updated.
"""

import re
import json
from collections import defaultdict, Counter
from pathlib import Path

EXTRACTIONS_DIR = Path(r"C:\Repositories\Stock-Picker\Ross Cameron Day Trading Videos\extractions")
OUTPUT_FILE = Path(r"C:\Users\joelb\Ross Cameron Day Trading Videos\RC_STRATEGY_STATISTICS.md")


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def parse_result_to_float(result_str):
    """Convert '+$1,234' or '-$567.89' to float. Returns None if unparseable."""
    if not result_str:
        return None
    s = result_str.strip()
    if s in ['-', '', 'unknown', 'N/A', 'n/a']:
        return None
    cleaned = re.sub(r'[$,\s]', '', s)
    try:
        return float(cleaned)
    except ValueError:
        return None


def normalize_entry_setup(setup):
    """Map free-text ENTRY SETUP to a controlled category."""
    s = setup.lower()
    if 'gap-and-go' in s or 'gap and go' in s:
        return 'gap-and-go'
    if 'vwap reclaim' in s:
        return 'vwap-reclaim'
    if 'vwap break' in s or 'break of vwap' in s or 'vwap curl' in s:
        return 'vwap-break/curl'
    if 'vwap' in s:
        return 'vwap-other'
    if 'halt' in s:
        return 'halt-resume'
    if 'bull flag' in s or 'flat-top' in s or 'flat top' in s:
        return 'bull-flag/flat-top'
    if 'micro-pullback' in s or 'micro pullback' in s or ('pullback' in s and 'micro' in s):
        return 'micro-pullback'
    if 'pullback' in s or 'dip' in s:
        return 'pullback/dip'
    if 'whole dollar' in s or 'whole-dollar' in s:
        return 'whole-dollar-break'
    if 'continuation' in s:
        return 'continuation'
    if 'reverse split' in s:
        return 'reverse-split'
    if 'red-to-green' in s or 'red to green' in s:
        return 'red-to-green'
    if 'breakout' in s:
        return 'breakout'
    if 'opening range' in s or 'open' in s:
        return 'opening-range'
    if 'abcd' in s:
        return 'abcd-pattern'
    return 'other'


def parse_trades_table(table_text):
    """Parse a TRADES markdown table block into a list of dicts."""
    trades = []
    for line in table_text.split('\n'):
        line = line.strip()
        if not line.startswith('|'):
            continue
        # Skip separator lines
        if re.match(r'^\|[-| ]+\|$', line):
            continue
        cells = [c.strip() for c in line.split('|')[1:-1]]
        if not cells:
            continue
        # Skip header row
        if cells[0] == '#':
            continue
        # Only process numbered rows
        if not cells[0].isdigit():
            continue
        if len(cells) < 10:
            continue

        result_raw = cells[8]
        outcome_raw = cells[9].upper().strip()

        trade = {
            'num':            cells[0],
            'symbol':         cells[1].upper().strip(),
            'sector':         cells[2].lower().strip(),
            'price':          cells[3],
            'scanner':        cells[4].lower().strip(),
            'news':           cells[5].lower().strip(),
            'entry_setup':    cells[6],
            'exit':           cells[7],
            'result':         result_raw,
            'outcome':        outcome_raw if outcome_raw in ('WIN', 'LOSS', 'BE') else 'UNKNOWN',
            'result_value':   parse_result_to_float(result_raw),
            'entry_category': normalize_entry_setup(cells[6]),
        }
        trades.append(trade)
    return trades


def parse_metadata(block_text):
    """Extract and parse the JSON object from a METADATA block."""
    try:
        m = re.search(r'\{.+?\}', block_text, re.DOTALL)
        if m:
            return json.loads(m.group())
    except (json.JSONDecodeError, ValueError):
        pass
    return {}


def parse_chunk_file(filepath):
    """Return a list of entry dicts from one chunk file."""
    with open(filepath, 'r', encoding='utf-8', errors='replace') as fh:
        content = fh.read()

    entries = []
    pattern = re.compile(r'^(FILE (\d{4}) \| TYPE: (.+))$', re.MULTILINE)
    matches = list(pattern.finditer(content))

    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        block = content[start:end]

        file_num = int(match.group(2))
        entry_type = match.group(3).strip()

        if 'NEEDS_EXTRACTION' in entry_type:
            continue

        # Trades table
        trades = []
        tm = re.search(r'TRADES:\n(.+?)(?=\nSUMMARY:|\nMETADATA:|\n---)', block, re.DOTALL)
        if tm:
            trades = parse_trades_table(tm.group(1))

        # Metadata
        metadata = {}
        mm = re.search(r'METADATA:\n(\{.+?\})', block, re.DOTALL)
        if mm:
            metadata = parse_metadata(mm.group(1))

        entries.append({
            'file_num':   file_num,
            'type':       entry_type,
            'trades':     trades,
            'metadata':   metadata,
            'num_trades': len(trades),
        })

    return entries


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------

def win_stats(trade_list):
    outcomes = [t['outcome'] for t in trade_list]
    results  = [t['result_value'] for t in trade_list if t['result_value'] is not None]
    wins     = outcomes.count('WIN')
    losses   = outcomes.count('LOSS')
    bes      = outcomes.count('BE')
    total    = wins + losses + bes
    return {
        'total':      total,
        'wins':       wins,
        'losses':     losses,
        'bes':        bes,
        'win_rate':   (wins / total * 100) if total else 0,
        'avg_result': (sum(results) / len(results)) if results else 0,
        'total_pnl':  sum(results),
    }


def fmt(value):
    return (f'+${value:,.0f}' if value >= 0 else f'-${abs(value):,.0f}')


def table_row(label, s):
    return (f"| {label} | {s['total']} | {s['wins']} | {s['losses']} | {s['bes']} "
            f"| {s['win_rate']:.1f}% | {fmt(s['avg_result'])} | {fmt(s['total_pnl'])} |")


TABLE_HEADER = ("| Category | Trades | W | L | BE | Win Rate | Avg Result | Total P&L |\n"
                "|---|---|---|---|---|---|---|---|")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    chunk_files = sorted(EXTRACTIONS_DIR.glob('TRANSCRIPT_SUMMARIES_[0-9]*.md'))
    print(f"Found {len(chunk_files)} chunk files\n")

    all_entries = []
    all_trades  = []

    for cf in chunk_files:
        print(f"  Parsing {cf.name}...")
        entries = parse_chunk_file(cf)
        all_entries.extend(entries)
        for entry in entries:
            for t in entry['trades']:
                t['file_num']   = entry['file_num']
                t['entry_type'] = entry['type']
                t['metadata']   = entry['metadata']
            all_trades.extend(entry['trades'])

    print(f"\nTotal entries : {len(all_entries)}")
    print(f"Total trades  : {len(all_trades)}")

    # ---- Slice data --------------------------------------------------------

    def group(trades, key_fn):
        d = defaultdict(list)
        for t in trades:
            k = key_fn(t)
            if k and k not in ('', '-', 'null', 'none', 'n/a', 'unknown'):
                d[k].append(t)
        return d

    by_setup   = group(all_trades, lambda t: t['entry_category'])
    by_sector  = group(all_trades, lambda t: t['sector'])
    by_scanner = group(all_trades, lambda t: t['scanner'])
    by_market  = group(all_trades, lambda t: t['metadata'].get('market', ''))
    by_size    = group(all_trades, lambda t: t['metadata'].get('size_context', ''))
    by_acct    = group(all_trades, lambda t: t['metadata'].get('acct_state', ''))
    by_news    = group(all_trades, lambda t: t['news'] if t['news'] in ('yes', 'no') else '')
    by_mc      = defaultdict(list)

    for e in all_entries:
        mc = (e['metadata'].get('month_context') or '').strip()
        if mc and mc not in ('null', 'None', ''):
            for t in e['trades']:
                by_mc[mc].append(t)

    session_by_market = defaultdict(list)
    for e in all_entries:
        if e['type'] in ('Daily Recap', 'Live Trading') and e['trades']:
            m = (e['metadata'].get('market') or '').strip()
            if m and m not in ('null', 'None', ''):
                session_by_market[m].append(e)

    dev_trades    = [t for e in all_entries
                     if e['metadata'].get('behavioral_deviation') not in (None, 'null', 'None', '')
                     for t in e['trades']]
    no_dev_trades = [t for e in all_entries
                     if e['metadata'].get('behavioral_deviation') in (None, 'null', 'None', '')
                     for t in e['trades']]

    ml_hit    = [t for t in all_trades if t['metadata'].get('max_loss_hit') is True]
    ml_no_hit = [t for t in all_trades if t['metadata'].get('max_loss_hit') is False]

    symbol_map = defaultdict(list)
    for t in all_trades:
        symbol_map[t['symbol']].append(t)

    # ---- Build report ------------------------------------------------------

    L = []

    def h(text): L.append(f"\n{text}\n")
    def p(text): L.append(text)

    p("# Ross Cameron Strategy Statistics")
    p(f"### Derived from {len(all_entries)} session entries across {len(chunk_files)} chunk files")
    p(f"**Total individual trades analyzed:** {len(all_trades)}")
    p("\n---")

    # 1. Session type distribution
    h("## 1. Session Type Distribution")
    type_counts = Counter(e['type'] for e in all_entries)
    p("| Type | Count | % |")
    p("|---|---|---|")
    for t, c in type_counts.most_common():
        p(f"| {t} | {c} | {c/len(all_entries)*100:.1f}% |")

    # 2. Overall
    h("## 2. Overall Trade Performance")
    ov = win_stats(all_trades)
    p("| Metric | Value |")
    p("|---|---|")
    p(f"| Total trades | {ov['total']} |")
    p(f"| Wins | {ov['wins']} |")
    p(f"| Losses | {ov['losses']} |")
    p(f"| Breakevens | {ov['bes']} |")
    p(f"| Overall win rate | {ov['win_rate']:.1f}% |")
    p(f"| Average result per trade | {fmt(ov['avg_result'])} |")
    p(f"| Total P&L across all trades | {fmt(ov['total_pnl'])} |")

    # 3. By entry setup
    h("## 3. Win Rate by Entry Setup Category")
    p(TABLE_HEADER)
    for setup, trades in sorted(by_setup.items(), key=lambda x: -len(x[1])):
        p(table_row(setup, win_stats(trades)))

    # 4. By sector
    h("## 4. Win Rate by Sector")
    p(TABLE_HEADER)
    for sector, trades in sorted(by_sector.items(), key=lambda x: -len(x[1])):
        p(table_row(sector, win_stats(trades)))

    # 5. By scanner
    h("## 5. Win Rate by Scanner Source")
    p(TABLE_HEADER)
    for scanner, trades in sorted(by_scanner.items(), key=lambda x: -len(x[1])):
        p(table_row(scanner, win_stats(trades)))

    # 6. By market condition
    h("## 6. Win Rate by Market Condition")
    p(TABLE_HEADER)
    for market in ('hot', 'neutral', 'cold'):
        if market in by_market:
            p(table_row(market, win_stats(by_market[market])))
    p("")
    p("### Sessions by Market Condition (trading days only)")
    p("| Market | Sessions | Avg Trades/Session |")
    p("|---|---|---|")
    for market in ('hot', 'neutral', 'cold'):
        if market in session_by_market:
            sess = session_by_market[market]
            avg  = sum(s['num_trades'] for s in sess) / len(sess)
            p(f"| {market} | {len(sess)} | {avg:.1f} |")

    # 7. By size context
    h("## 7. Win Rate by Position Size Context")
    p(TABLE_HEADER)
    for size in ('full', 'reduced', 'oversized'):
        if size in by_size:
            p(table_row(size, win_stats(by_size[size])))

    # 8. By account state
    h("## 8. Win Rate by Account State")
    p(TABLE_HEADER)
    for acct, trades in sorted(by_acct.items(), key=lambda x: -len(x[1])):
        p(table_row(acct, win_stats(trades)))

    # 9. News catalyst
    h("## 9. News Catalyst vs No News")
    p(TABLE_HEADER)
    labels = {'yes': 'With news catalyst', 'no': 'No news catalyst'}
    for key in ('yes', 'no'):
        if key in by_news:
            p(table_row(labels[key], win_stats(by_news[key])))

    # 10. Max loss hit
    h("## 10. Impact of Max Loss Hit")
    p(TABLE_HEADER)
    if ml_hit:
        p(table_row('Max loss hit = TRUE', win_stats(ml_hit)))
    if ml_no_hit:
        p(table_row('Max loss hit = FALSE', win_stats(ml_no_hit)))

    # 11. Behavioral deviation
    h("## 11. Behavioral Deviation")
    p(f"- Sessions **WITH** behavioral deviation noted: **{len([e for e in all_entries if e['metadata'].get('behavioral_deviation') not in (None,'null','None','')])}**")
    p(f"- Sessions **WITHOUT** behavioral deviation: **{len([e for e in all_entries if e['metadata'].get('behavioral_deviation') in (None,'null','None','')])}**")
    p("")
    p(TABLE_HEADER)
    if dev_trades:
        p(table_row('With behavioral deviation', win_stats(dev_trades)))
    if no_dev_trades:
        p(table_row('Without behavioral deviation', win_stats(no_dev_trades)))
    p("")

    def _dev_str(val):
        if isinstance(val, list):
            return ' / '.join(str(v) for v in val)
        return str(val) if val else ''

    dev_types = Counter(
        _dev_str(e['metadata'].get('behavioral_deviation', ''))
        for e in all_entries
        if e['metadata'].get('behavioral_deviation') not in (None, 'null', 'None', '', [])
    )
    if dev_types:
        p("### Most Common Deviation Types")
        p("| Deviation | Count |")
        p("|---|---|")
        for dev, cnt in dev_types.most_common(25):
            p(f"| {str(dev)[:100]} | {cnt} |")

    # 12. Month context
    h("## 12. Performance by Month Context")
    p("| Month Context | Trades | Win Rate | Avg Result | Total P&L |")
    p("|---|---|---|---|---|")
    mc_rows = [(mc, win_stats(trades)) for mc, trades in by_mc.items()]
    for mc, s in sorted(mc_rows, key=lambda x: -x[1]['total']):
        p(f"| {mc} | {s['total']} | {s['win_rate']:.1f}% | {fmt(s['avg_result'])} | {fmt(s['total_pnl'])} |")

    # 13. Top symbols
    h("## 13. Most Traded Symbols (3+ trades)")
    p("| Symbol | Trades | Win Rate | Total P&L |")
    p("|---|---|---|")
    sym_rows = [(sym, win_stats(trades)) for sym, trades in symbol_map.items() if len(trades) >= 3]
    sym_rows.sort(key=lambda x: -x[1]['total'])
    for sym, s in sym_rows[:40]:
        p(f"| {sym} | {s['total']} | {s['win_rate']:.1f}% | {fmt(s['total_pnl'])} |")

    # Footer
    p("\n---")
    p("*Auto-generated — re-run `RC_STRATEGY_STATISTICS.py` to refresh.*")
    p(f"*Source: {len(chunk_files)} chunk files · {len(all_entries)} entries · {len(all_trades)} trades*")

    OUTPUT_FILE.write_text('\n'.join(L), encoding='utf-8')
    print(f"\nDONE: Report written to: {OUTPUT_FILE}")


if __name__ == '__main__':
    main()
