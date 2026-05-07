import re
from pathlib import Path

input_file = Path("C:/Repositories/Stock-Picker/Ross Cameron Day Trading Videos/extractions/TRANSCRIPT_SUMMARIES_0400-0499.md")
output_file = Path("C:/Repositories/Stock-Picker/Ross Cameron Day Trading Videos/haiku_output_0450-0499.txt")

content = input_file.read_text(encoding='utf-8', errors='replace')

# Split into lines and extract range 1265-2519
lines = content.split('\n')
extract_lines = lines[1265:2519]
extract_text = '\n'.join(extract_lines)

# Initialize output
output_lines = []
tsv_rows = []

# Regex to split files
file_pattern = r'FILE (\d{4})[^\n]*\n(.*?)(?=\nFILE \d{4}|$)'
files_found = list(re.finditer(file_pattern, extract_text, re.DOTALL))

print(f"Found {len(files_found)} files in range 0450-0499")

for match in files_found:
    file_id = match.group(1)
    file_content = match.group(2)
    
    # Skip if no trades
    if 'TRADES: NO TRADES TAKEN' in file_content or 'no trades' in file_content.lower():
        continue
    
    # Extract TRADES section
    trades_match = re.search(r'TRADES:\n(.*?)(?=\nSUMMARY:|$)', file_content, re.DOTALL)
    if not trades_match:
        continue
    
    trades_block = trades_match.group(1).strip()
    
    # Parse trade rows (pipe-separated tables)
    trade_rows = []
    for line in trades_block.split('\n'):
        # Skip headers, empty lines, and separator lines
        if not line.strip():
            continue
        if '---' in line or 'SYMBOL' in line or 'Ticker' in line or 'Direction' in line or 'Entry' in line:
            continue
        # Keep data rows
        if '|' in line:
            trade_rows.append(line)
    
    if not trade_rows:
        continue
    
    # Output file header
    output_lines.append(f"=== FILE {file_id} ===")
    output_lines.append("TRADE_MECHANICS:")
    
    # Process each trade row
    for row_idx, row in enumerate(trade_rows, 1):
        output_lines.append(row)
        
        # Extract fields for TSV
        parts = [p.strip() for p in row.split('|')]
        parts = [p for p in parts if p]
        
        # Basic extraction - try to get key fields
        if len(parts) >= 2:
            try:
                trade_num = parts[0] if parts[0].isdigit() else str(row_idx)
                symbol = parts[1] if len(parts) > 1 else '-'
                
                # Try to extract additional fields from row
                float_val = '-'
                gap_pct = '-'
                rel_vol = '-'
                pattern_type = '-'
                entry_trigger = '-'
                add_on = '-'
                stop_criteria = '-'
                t1_target = '-'
                entry_time = '-'
                macd = '-'
                hold_duration = '-'
                
                # Look for common patterns in the row
                row_lower = row.lower()
                if 'gap' in row_lower:
                    pattern_type = 'gap-and-go'
                elif 'pullback' in row_lower or 'dip' in row_lower:
                    pattern_type = 'micro-pullback'
                elif 'halt' in row_lower:
                    pattern_type = 'halt-resume'
                elif 'vwap' in row_lower:
                    pattern_type = 'vwap-reclaim'
                elif 'flag' in row_lower:
                    pattern_type = 'bull-flag'
                elif 'abcd' in row_lower:
                    pattern_type = 'abcd'
                
                if 'squeeze' in row_lower or 'pop' in row_lower:
                    entry_trigger = 'scanner'
                elif 'premarket' in row_lower:
                    entry_trigger = 'premarket-scan'
                elif 'news' in row_lower:
                    entry_trigger = 'news'
                
                if 'scaled' in row_lower or 'add' in row_lower:
                    add_on = 'S'
                
                if 'profit' in row_lower or 'prof' in row_lower.lower():
                    stop_criteria = '-'
                elif 'stop' in row_lower:
                    stop_criteria = 'stop'
                
                if 'scalp' in row_lower or '5-min' in row_lower:
                    hold_duration = 'scalp'
                elif 'short' in row_lower:
                    hold_duration = 'short'
                
                # Create TSV row
                tsv_parts = [
                    file_id,
                    trade_num,
                    symbol,
                    float_val,
                    gap_pct,
                    rel_vol,
                    pattern_type,
                    entry_trigger,
                    add_on,
                    stop_criteria,
                    t1_target,
                    entry_time,
                    macd,
                    hold_duration
                ]
                tsv_rows.append(tsv_parts)
            except Exception as e:
                pass

# Build final output
output_lines.append('')
output_lines.append('=== TSV_AUDIT ===')
output_lines.append('file\ttrade\tsymbol\tFLOAT\tGAP%\tREL_VOL\tPATTERN_TYPE\tENTRY_TRIGGER\tADD_ON_MECHANIC\tSTOP_CRITERIA\tT1_TARGET\tTIME_OF_ENTRY\tMACD_STATE\tHOLD_DURATION')

for row in tsv_rows:
    output_lines.append('\t'.join(row))

# Write output
output_file.write_text('\n'.join(output_lines), encoding='utf-8')
print(f"Extraction complete: {output_file}")
print(f"Total TSV rows: {len(tsv_rows)}")
