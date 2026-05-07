#!/usr/bin/env python3
"""Extract detailed trade mechanics from transcript summaries."""

import re
from pathlib import Path
from typing import List, Dict, Tuple, Optional

def parse_file_blocks(text: str) -> List[Tuple[Dict, List[Dict]]]:
    """Parse text into file blocks with metadata and trades."""
    blocks = []
    file_pattern = r'^FILE (\d+) \| TYPE: ([^\n]+)\n---\n'
    matches = list(re.finditer(file_pattern, text, re.MULTILINE))

    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i+1].start() if i+1 < len(matches) else len(text)

        file_num = match.group(1)
        file_type = match.group(2).strip()
        block_text = text[start:end]

        meta = {'file': file_num, 'type': file_type}
        trades = parse_trades_from_block(block_text)

        if trades:  # Only include files with trades
            blocks.append((meta, trades))

    return blocks

def parse_trades_from_block(text: str) -> List[Dict]:
    """Extract individual trades from a file block."""
    trades = []

    # Check for NO TRADES TAKEN
    if 'NO TRADES TAKEN' in text:
        return trades

    # Find TRADES section
    trades_match = re.search(r'TRADES:\n(.*?)\nSUMMARY:', text, re.DOTALL)
    if not trades_match:
        return trades

    trades_section = trades_match.group(1)
    lines = trades_section.split('\n')

    # Parse table rows (skip header and separator)
    for line in lines:
        if line.startswith('|') and '---' not in line and 'SYMBOL' not in line and '#' not in line[1:4]:
            parts = [p.strip() for p in line.split('|')[1:-1]]
            if len(parts) >= 10:
                trade = {
                    'num': parts[0] if parts[0] else '-',
                    'symbol': parts[1] if len(parts) > 1 else '-',
                    'sector': parts[2] if len(parts) > 2 else '-',
                    'price': parts[3] if len(parts) > 3 else '-',
                    'scanner': parts[4] if len(parts) > 4 else '-',
                    'news': parts[5] if len(parts) > 5 else '-',
                    'entry_setup': parts[6] if len(parts) > 6 else '-',
                    'exit': parts[7] if len(parts) > 7 else '-',
                    'result': parts[8] if len(parts) > 8 else '-',
                    'outcome': parts[9] if len(parts) > 9 else '-',
                }
                trades.append(trade)

    return trades

def extract_float_gap_from_summary(summary: str, symbol: str) -> Tuple[str, str]:
    """Extract float and gap % from summary text."""
    float_val = '-'
    gap_pct = '-'

    # Look for float info (e.g., "3.8 million share float")
    # Escape symbol for regex
    escaped_symbol = re.escape(symbol)
    float_match = re.search(rf'{escaped_symbol}.*?(\d+(?:\.\d+)?)\s+(?:million|billion)\s+share', summary, re.IGNORECASE)
    if float_match:
        float_val = float_match.group(1) + 'M'

    # Look for gap % (e.g., "50% pre-market move", "6% gap")
    gap_match = re.search(r'(\d+(?:\.\d+)?)\%\s+(?:pre-market|gap|move)', summary, re.IGNORECASE)
    if gap_match:
        gap_pct = gap_match.group(1) + '%'

    return float_val, gap_pct

def infer_pattern_type(entry_setup: str) -> str:
    """Infer pattern type from entry setup text."""
    entry_lower = entry_setup.lower()

    if 'gap-and-go' in entry_lower or 'gap and go' in entry_lower:
        return 'gap-and-go'
    elif 'micro-pullback' in entry_lower or 'micro pullback' in entry_lower:
        return 'micro-pullback'
    elif 'vwap' in entry_lower:
        return 'vwap-reclaim'
    elif 'halt' in entry_lower and 'resume' in entry_lower:
        return 'halt-resume'
    elif 'dip' in entry_lower:
        return 'dip-buy'
    elif 'flat-top' in entry_lower or 'flat top' in entry_lower:
        return 'flat-top'
    elif 'bull-flag' in entry_lower or 'bull flag' in entry_lower:
        return 'bull-flag'
    elif 'abcd' in entry_lower:
        return 'abcd'
    elif 'red-to-green' in entry_lower or 'red to green' in entry_lower:
        return 'red-to-green'
    elif 'whole-dollar' in entry_lower or 'whole dollar' in entry_lower:
        return 'whole-dollar-break'
    else:
        return 'unknown'

def infer_entry_trigger(entry_setup: str) -> str:
    """Extract entry trigger from setup."""
    # Look for specific keywords
    if 'breakout' in entry_setup.lower():
        return 'breakout'
    elif 'scalp' in entry_setup.lower():
        return 'scalp'
    elif 'squeeze' in entry_setup.lower():
        return 'squeeze'
    elif 'pop' in entry_setup.lower():
        return 'pop'
    elif 'spike' in entry_setup.lower():
        return 'spike'
    elif 'dip' in entry_setup.lower():
        return 'dip'
    elif 'resume' in entry_setup.lower():
        return 'resume'
    else:
        return entry_setup[:30] if len(entry_setup) > 0 else '-'

def infer_stop_criteria(exit: str) -> str:
    """Extract stop criteria from exit text."""
    exit_lower = exit.lower()

    if 'stop' in exit_lower or 'reversal' in exit_lower:
        if 'failed' in exit_lower or 'reject' in exit_lower:
            return 'failed-breakout'
        elif 'reversal' in exit_lower:
            return 'reversal'
        else:
            return 'stop'
    elif 'profit' in exit_lower or 'prof' in exit_lower or 'scaled' in exit_lower:
        return 'profit-target'
    elif 'time' in exit_lower:
        return 'time-decay'
    else:
        return 'exit'

def infer_t1_target(entry_setup: str, exit: str) -> str:
    """Extract T1 target price from entry setup or exit."""
    # Look for dollar amounts in exit
    matches = re.findall(r'\$[\d.]+', exit)
    if matches:
        return matches[-1]  # Return last price found
    matches = re.findall(r'\$[\d.]+', entry_setup)
    if matches:
        return matches[0]
    return '-'

def infer_macd_state(summary: str, symbol: str) -> str:
    """Try to infer MACD state from summary (usually not explicit)."""
    # Look for momentum descriptions
    summary_lower = summary.lower()
    if 'momentum' in summary_lower and ('strong' in summary_lower or 'building' in summary_lower):
        return 'positive'
    elif 'reversal' in summary_lower or 'decline' in summary_lower:
        return 'negative'
    return 'unknown'

def infer_hold_duration(exit: str, result: str) -> str:
    """Infer hold duration from exit and result."""
    exit_lower = exit.lower()

    # Look for time indicators
    if 'quick' in exit_lower or 'scalp' in exit_lower or 'seconds' in exit_lower:
        return 'scalp'
    elif 'minute' in exit_lower:
        if any(int_val in exit_lower for int_val in ['5', '10', '15', '20', '30']):
            if any(x in exit_lower for x in ['first 5', 'quick']):
                return 'scalp'
            return 'short'
    elif 'resistance' in exit_lower or 'dip' in exit_lower:
        if 'quick' in exit_lower:
            return 'scalp'
        return 'short'
    elif 'extended' in exit_lower or 'hold' in exit_lower:
        return 'extended'

    # Default based on result (quick exits often indicate scalps)
    if result and '+' in result:
        try:
            amount = int(result.replace('+$', '').replace(',', ''))
            if amount < 300:
                return 'scalp'
            elif amount < 2000:
                return 'short'
        except:
            pass

    return 'unknown'

def format_output(file_blocks: List[Tuple[Dict, List[Dict]]], summary_map: Dict) -> str:
    """Format output as markdown tables with TSV audit."""
    output = []

    for meta, trades in file_blocks:
        file_num = meta['file']
        summary = summary_map.get(file_num, '')

        output.append(f"\n=== FILE {file_num} ===")
        output.append("TRADE_MECHANICS:")
        output.append("| # | FLOAT | GAP% | REL_VOL | PATTERN_TYPE | ENTRY_TRIGGER | ADD_ON_MECHANIC | STOP_CRITERIA | T1_TARGET | TIME_OF_ENTRY | MACD_STATE | HOLD_DURATION |")
        output.append("|---|-------|------|---------|--------------|---------------|-----------------|---------------|-----------|---------------|------------|---------------|")

        for trade in trades:
            float_val, gap_pct = extract_float_gap_from_summary(summary, trade['symbol'])
            pattern = infer_pattern_type(trade['entry_setup'])
            trigger = infer_entry_trigger(trade['entry_setup'])
            stop_crit = infer_stop_criteria(trade['exit'])
            t1_target = infer_t1_target(trade['entry_setup'], trade['exit'])
            macd = infer_macd_state(summary, trade['symbol'])
            hold = infer_hold_duration(trade['exit'], trade['result'])

            output.append(
                f"| {trade['num']} | {float_val} | {gap_pct} | - | {pattern} | {trigger} | - | {stop_crit} | {t1_target} | - | {macd} | {hold} |"
            )

    # TSV audit section
    output.append("\n=== TSV_AUDIT ===")
    output.append("file\ttrade\tsymbol\tFLOAT\tGAP%\tREL_VOL\tPATTERN_TYPE\tENTRY_TRIGGER\tADD_ON_MECHANIC\tSTOP_CRITERIA\tT1_TARGET\tTIME_OF_ENTRY\tMACD_STATE\tHOLD_DURATION")

    for meta, trades in file_blocks:
        file_num = meta['file']
        summary = summary_map.get(file_num, '')
        for trade in trades:
            float_val, gap_pct = extract_float_gap_from_summary(summary, trade['symbol'])
            pattern = infer_pattern_type(trade['entry_setup'])
            trigger = infer_entry_trigger(trade['entry_setup'])
            stop_crit = infer_stop_criteria(trade['exit'])
            t1_target = infer_t1_target(trade['entry_setup'], trade['exit'])
            macd = infer_macd_state(summary, trade['symbol'])
            hold = infer_hold_duration(trade['exit'], trade['result'])

            # TSV status: S=found, -=not found, N=n/a
            float_s = 'S' if float_val != '-' else '-'
            gap_s = 'S' if gap_pct != '-' else '-'
            rel_vol_s = '-'  # Usually not explicit in tables
            pattern_s = 'S' if pattern != 'unknown' else '-'
            trigger_s = 'S' if trigger != '-' else '-'
            stop_s = 'S' if stop_crit != '-' else '-'
            t1_s = 'S' if t1_target != '-' else '-'
            time_s = '-'  # Not usually in summaries
            macd_s = 'S' if macd != 'unknown' else '-'
            hold_s = 'S' if hold != 'unknown' else '-'

            output.append(
                f"{file_num}\t{trade['num']}\t{trade['symbol']}\t{float_s}\t{gap_s}\t{rel_vol_s}\t{pattern_s}\t{trigger_s}\t-\t{stop_s}\t{t1_s}\t{time_s}\t{macd_s}\t{hold_s}"
            )

    return '\n'.join(output)

def extract_summaries(text: str) -> Dict[str, str]:
    """Extract summary text for each file."""
    summaries = {}
    pattern = r'^FILE (\d+).*?SUMMARY:\n(.*?)\nMETADATA:'
    for match in re.finditer(pattern, text, re.MULTILINE | re.DOTALL):
        file_num = match.group(1)
        summary = match.group(2)
        summaries[file_num] = summary
    return summaries

if __name__ == '__main__':
    input_file = Path(r'C:\Repositories\Stock-Picker\Ross Cameron Day Trading Videos\extractions\TRANSCRIPT_SUMMARIES_0400-0499.md')
    output_file = Path(r'C:\Repositories\Stock-Picker\Ross Cameron Day Trading Videos\haiku_output_0400-0449.txt')

    # Read file
    with open(input_file, 'r', encoding='utf-8-sig') as f:
        content = f.read()

    # Extract only first 1265 lines (FILES 0400-0449)
    lines = content.split('\n')
    content = '\n'.join(lines[:1265])

    # Parse
    file_blocks = parse_file_blocks(content)
    summaries = extract_summaries(content)

    print(f"Found {len(file_blocks)} files with trades")
    total_trades = sum(len(trades) for _, trades in file_blocks)
    print(f"Total trades extracted: {total_trades}")

    # Generate output
    output = format_output(file_blocks, summaries)

    # Write output
    with open(output_file, 'w') as f:
        f.write(output)

    print(f"Output written to: {output_file}")
