#!/usr/bin/env python3
"""Extract trade mechanics from transcript summaries."""

import re
import json
from pathlib import Path
from typing import List, Dict, Tuple

PATTERN_TYPES = {
    'gap-and-go', 'micro-pullback', 'vwap-reclaim', 'halt-resume',
    'dip-buy', 'flat-top', 'bull-flag', 'abcd', 'red-to-green',
    'whole-dollar-break', 'unknown'
}

MACD_STATES = {'positive', 'negative', 'unknown'}
HOLD_DURATIONS = {'scalp', 'short', 'extended', 'unknown'}

def extract_trades_from_text(text: str) -> List[Dict]:
    """Parse a single file's trade data."""
    trades = []

    # Check if NO TRADES TAKEN
    if 'TRADES: NO TRADES TAKEN' in text or 'TRADES:\nNO TRADES TAKEN' in text:
        return trades

    # Extract trades section
    trades_match = re.search(r'TRADES:\n(.*?)\nSUMMARY:', text, re.DOTALL)
    if not trades_match:
        return trades

    trades_section = trades_match.group(1)

    # Parse table rows (skip header)
    lines = trades_section.split('\n')
    in_table = False

    for line in lines:
        if line.startswith('|') and '---' not in line and 'SYMBOL' not in line:
            in_table = True

        if in_table and line.startswith('|') and '---' not in line:
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

def extract_metadata(text: str) -> Dict:
    """Extract metadata from file."""
    meta = {}

    # File number
    file_match = re.search(r'^FILE (\d+)', text, re.MULTILINE)
    if file_match:
        meta['file'] = file_match.group(1)

    # Type
    type_match = re.search(r'TYPE: ([^\n]+)', text)
    if type_match:
        meta['type'] = type_match.group(1).strip()

    return meta

def parse_file_range(file_path: Path, start_line: int, end_line: int) -> Tuple[List[Dict], List[Dict]]:
    """Parse lines from file containing multiple file entries."""
    with open(file_path, 'r', encoding='utf-8-sig') as f:
        lines = f.readlines()

    text = ''.join(lines[start_line:end_line])

    # Split by FILE entries
    file_blocks = re.split(r'(?=^FILE \d+)', text, flags=re.MULTILINE)

    all_trades = []
    all_metadata = []

    for block in file_blocks:
        if not block.strip():
            continue

        meta = extract_metadata(block)
        trades = extract_trades_from_text(block)

        # Add file number to each trade
        for trade in trades:
            trade['file'] = meta.get('file', '-')

        all_trades.extend(trades)
        if trades:  # Only add metadata if there are trades
            all_metadata.append({**meta, 'trade_count': len(trades)})

    return all_trades, all_metadata

def format_trade_mechanics(trade: Dict) -> Dict:
    """Convert trade data to TRADE_MECHANICS format."""
    # These would need to be extracted from entry_setup, exit, etc.
    # For now, we'll keep placeholders and extract what we can

    return {
        'num': trade['num'],
        'symbol': trade['symbol'],
        'float': '-',  # Not in basic trade table
        'gap_pct': '-',  # Not in basic trade table
        'rel_vol': '-',  # Not in basic trade table
        'pattern_type': 'unknown',  # Would need to parse from entry_setup
        'entry_trigger': '-',  # Would need to parse from entry_setup
        'add_on_mechanic': '-',
        'stop_criteria': '-',  # Would need to parse from entry_setup/exit
        't1_target': '-',  # Would need to parse from entry_setup
        'time_of_entry': '-',
        'macd_state': 'unknown',
        'hold_duration': 'unknown',
    }

if __name__ == '__main__':
    input_file = Path(r'C:\Repositories\Stock-Picker\Ross Cameron Day Trading Videos\extractions\TRANSCRIPT_SUMMARIES_0400-0499.md')
    output_file = Path(r'C:\Repositories\Stock-Picker\Ross Cameron Day Trading Videos\haiku_output_0400-0449.txt')

    # Process lines 0-1264 (FILE 0400-0449)
    trades, metadata = parse_file_range(input_file, 0, 1265)

    print(f"Found {len(metadata)} files with trades")
    print(f"Total trades extracted: {len(trades)}")

    # Generate output
    output = []
    current_file = None
    file_trades = []

    for trade in trades:
        if trade['file'] != current_file:
            if current_file and file_trades:
                output.append(f"\n=== FILE {current_file} ===")
                output.append("TRADE_MECHANICS:")
                output.append("| # | FLOAT | GAP% | REL_VOL | PATTERN_TYPE | ENTRY_TRIGGER | ADD_ON_MECHANIC | STOP_CRITERIA | T1_TARGET | TIME_OF_ENTRY | MACD_STATE | HOLD_DURATION |")
                output.append("|---|-------|------|---------|--------------|---------------|-----------------|---------------|-----------|---------------|------------|---------------|")
                for t in file_trades:
                    output.append(f"| {t['num']} | {t['float']} | {t['gap_pct']} | {t['rel_vol']} | {t['pattern_type']} | {t['entry_trigger']} | {t['add_on_mechanic']} | {t['stop_criteria']} | {t['t1_target']} | {t['time_of_entry']} | {t['macd_state']} | {t['hold_duration']} |")
            current_file = trade['file']
            file_trades = []

        file_trades.append(format_trade_mechanics(trade))

    # Write last file
    if current_file and file_trades:
        output.append(f"\n=== FILE {current_file} ===")
        output.append("TRADE_MECHANICS:")
        output.append("| # | FLOAT | GAP% | REL_VOL | PATTERN_TYPE | ENTRY_TRIGGER | ADD_ON_MECHANIC | STOP_CRITERIA | T1_TARGET | TIME_OF_ENTRY | MACD_STATE | HOLD_DURATION |")
        output.append("|---|-------|------|---------|--------------|---------------|-----------------|---------------|-----------|---------------|------------|---------------|")
        for t in file_trades:
            output.append(f"| {t['num']} | {t['float']} | {t['gap_pct']} | {t['rel_vol']} | {t['pattern_type']} | {t['entry_trigger']} | {t['add_on_mechanic']} | {t['stop_criteria']} | {t['t1_target']} | {t['time_of_entry']} | {t['macd_state']} | {t['hold_duration']} |")

    # Write TSV audit
    output.append("\n=== TSV_AUDIT ===")
    output.append("file\ttrade\tsymbol\tFLOAT\tGAP%\tREL_VOL\tPATTERN_TYPE\tENTRY_TRIGGER\tADD_ON_MECHANIC\tSTOP_CRITERIA\tT1_TARGET\tTIME_OF_ENTRY\tMACD_STATE\tHOLD_DURATION")

    for trade in trades:
        output.append(f"{trade['file']}\t{trade['num']}\t{trade['symbol']}\t-\t-\t-\tunknown\t-\t-\t-\t-\t-\tunknown\tunknown")

    # Save output
    with open(output_file, 'w') as f:
        f.write('\n'.join(output))

    print(f"\nOutput written to: {output_file}")
