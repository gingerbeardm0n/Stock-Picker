#!/usr/bin/env python3
import re
import sys
import json

# Read batch content from file
with open('batch_0600_0649_content.txt', 'r', encoding='utf-8', errors='replace') as f:
    content = f.read()

# Split by FILE entries
file_blocks = re.split(r'(?=^FILE \d{4})', content, flags=re.MULTILINE)

output_lines = []
tsv_rows = []

for block in file_blocks:
    if not block.strip():
        continue

    # Extract FILE number
    file_match = re.match(r'FILE (\d{4})', block)
    if not file_match:
        continue

    file_num = file_match.group(1)

    # Check if this file has "NO TRADES TAKEN"
    if 'NO TRADES TAKEN' in block:
        continue

    # Extract TRADES table
    trades_section = re.search(r'TRADES:\n(.*?)(?=\nSUMMARY:)', block, re.DOTALL)
    if not trades_section:
        continue

    trades_text = trades_section.group(1)

    # Check if there are actual trades (not just header)
    if not re.search(r'^\|\s*\d+\s*\|', trades_text, re.MULTILINE):
        continue

    # Extract SUMMARY section
    summary_match = re.search(r'SUMMARY:\n(.*?)(?=\nMETADATA:)', block, re.DOTALL)
    summary_text = summary_match.group(1) if summary_match else ""

    # Extract METADATA
    metadata_match = re.search(r'METADATA:\n(.*?)(?=\n---|\Z)', block, re.DOTALL)
    metadata_text = metadata_match.group(1) if metadata_match else "{}"

    # Parse trades from TRADES table
    trades_pattern = r'\|\s*(\d+)\s*\|\s*(\w+)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|'

    trades_data = []
    for match in re.finditer(trades_pattern, trades_text):
        if match.group(1).isdigit():  # Only take actual data rows
            trade_num = match.group(1)
            symbol = match.group(2)
            sector = match.group(3).strip()
            price = match.group(4).strip()
            scanner = match.group(5).strip()
            news = match.group(6).strip()
            entry_setup = match.group(7).strip()
            exit_info = match.group(8).strip()
            result = match.group(9).strip()

            trades_data.append({
                'num': trade_num,
                'symbol': symbol,
                'sector': sector,
                'price': price,
                'scanner': scanner,
                'news': news,
                'entry_setup': entry_setup,
                'exit_info': exit_info,
                'result': result
            })

    if not trades_data:
        continue

    # Now extract mechanics from SUMMARY for each trade
    output_lines.append(f"=== FILE {file_num} ===")
    output_lines.append("TRADE_MECHANICS:")
    output_lines.append("| # | FLOAT | GAP% | REL_VOL | PATTERN_TYPE | ENTRY_TRIGGER | ADD_ON_MECHANIC | STOP_CRITERIA | T1_TARGET | TIME_OF_ENTRY | MACD_STATE | HOLD_DURATION |")
    output_lines.append("|---|-------|------|---------|--------------|---------------|-----------------|---------------|-----------|---------------|------------|---------------|")

    for trade in trades_data:
        trade_num = trade['num']
        symbol = trade['symbol']
        entry_setup = trade['entry_setup'].lower()
        summary_lower = summary_text.lower()

        # Extract fields from summary and table
        # FLOAT - look in summary for share count mentions
        float_val = "-"
        if "million" in summary_lower or "m share" in summary_lower:
            float_match = re.search(r'(\d+(?:\.\d+)?)\s*m(?:illion)?.*share', summary_lower)
            if float_match:
                float_val = f"{float_match.group(1)}M"
        elif "sub-1m" in summary_lower or "under 1m" in summary_lower:
            float_val = "sub-1M"

        # GAP% - look for gap percentages
        gap_val = "-"
        gap_patterns = [
            rf'{symbol}.*(?:gapped?|gap)\s+(?:up|down)?\s*(\d+(?:\.\d+)?%)',
            r'gapped?\s+(?:up|down)?\s*(\d+(?:\.\d+)?%)',
            r'(\d+(?:\.\d+)?%)\s+gap'
        ]
        for pattern in gap_patterns:
            gap_match = re.search(pattern, summary_lower)
            if gap_match:
                gap_val = gap_match.group(1)
                break

        # REL_VOL - look for volume mentions
        rel_vol = "-"
        if "high volume" in summary_lower or "exceptional.*volume" in summary_lower:
            rel_vol = "high"
        elif re.search(r'(\d+)x\s*vol', summary_lower):
            vol_match = re.search(r'(\d+)x', summary_lower)
            if vol_match:
                rel_vol = f"{vol_match.group(1)}x"

        # PATTERN_TYPE from entry_setup
        pattern_map = {
            'gap-and-go': 'gap-and-go',
            'dip buy': 'dip-buy',
            'dip-buy': 'dip-buy',
            'micro pullback': 'micro-pullback',
            'vwap': 'vwap-reclaim',
            'halt': 'halt-resume',
            'red-to-green': 'red-to-green',
            'whole dollar': 'whole-dollar-break',
            'bull flag': 'bull-flag',
            'abcd': 'abcd',
            'flat-top': 'flat-top',
            'flat top': 'flat-top',
        }

        pattern_type = "unknown"
        for key, val in pattern_map.items():
            if key in entry_setup:
                pattern_type = val
                break

        # ENTRY_TRIGGER
        entry_trigger = "-"
        entry_setup_short = entry_setup[:50] if len(entry_setup) > 0 else "-"

        # ADD_ON_MECHANIC
        add_on = "n/a"
        if "scaled" in summary_lower or "added" in summary_lower or "add" in summary_lower:
            if "scaled" in summary_lower:
                add_on = "scaled entry"
            else:
                add_on = "added on move"

        # STOP_CRITERIA
        stop_criteria = "-"
        if "stop:" in trade['exit_info'].lower() or "loss" in trade['result'].lower():
            if "reversal" in summary_lower:
                stop_criteria = "reversal"
            elif "failed" in summary_lower:
                stop_criteria = "failed breakout"
            elif "sold off" in summary_lower:
                stop_criteria = "sold off"
            else:
                stop_criteria = "stop loss"

        # T1_TARGET
        t1_target = "-"
        target_patterns = [
            r'scaled.*?\$?([\d.]+)',
            r'to.*?\$?([\d.]+)',
            r'reach(?:ed)?\s+\$?([\d.]+)',
        ]
        for pattern in target_patterns:
            target_match = re.search(pattern, summary_lower)
            if target_match:
                t1_target = f"${target_match.group(1)}"
                break

        # TIME_OF_ENTRY
        time_entry = "-"

        # MACD_STATE
        macd_state = "unknown"

        # HOLD_DURATION
        hold_duration = "unknown"
        if "scalp" in summary_lower or "quick" in summary_lower:
            hold_duration = "scalp"
        elif "5-minute" in summary_lower or "5 minute" in summary_lower:
            hold_duration = "short"
        elif "extended" in summary_lower or "held through" in summary_lower:
            hold_duration = "extended"

        # Build TSV audit
        tsv_row = [
            file_num,
            trade_num,
            symbol,
            "S" if float_val != "-" else "-",
            "S" if gap_val != "-" else "-",
            "S" if rel_vol != "-" else "-",
            "S" if pattern_type != "unknown" else "-",
            "S" if entry_trigger != "-" else "-",
            "N" if add_on == "n/a" else ("S" if add_on != "-" else "-"),
            "S" if stop_criteria != "-" else "-",
            "S" if t1_target != "-" else "-",
            "S" if time_entry != "-" else "-",
            "S" if macd_state != "unknown" else "-",
            "S" if hold_duration != "unknown" else "-",
        ]
        tsv_rows.append(tsv_row)

        # Add to mechanics table
        row = f"| {trade_num} | {float_val} | {gap_val} | {rel_vol} | {pattern_type} | {entry_setup_short} | {add_on} | {stop_criteria} | {t1_target} | {time_entry} | {macd_state} | {hold_duration} |"
        output_lines.append(row)

# Add TSV audit section
output_lines.append("")
output_lines.append("=== TSV_AUDIT ===")
output_lines.append("file\ttrade\tsymbol\tFLOAT\tGAP%\tREL_VOL\tPATTERN_TYPE\tENTRY_TRIGGER\tADD_ON_MECHANIC\tSTOP_CRITERIA\tT1_TARGET\tTIME_OF_ENTRY\tMACD_STATE\tHOLD_DURATION")

for row in tsv_rows:
    output_lines.append("\t".join(str(x) for x in row))

# Write output
with open('haiku_output_0600-0649.txt', 'w', encoding='utf-8') as f:
    f.write("\n".join(output_lines))

print("Output written to haiku_output_0600-0649.txt")
print(f"Processed {len(set(r[0] for r in tsv_rows))} files with {len(tsv_rows)} total trades")
