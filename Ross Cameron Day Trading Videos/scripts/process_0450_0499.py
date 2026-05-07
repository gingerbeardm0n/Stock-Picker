import re
from pathlib import Path

# Read the file
input_file = Path("C:/Repositories/Stock-Picker/Ross Cameron Day Trading Videos/extractions/TRANSCRIPT_SUMMARIES_0400-0499.md")
output_file = Path("C:/Repositories/Stock-Picker/Ross Cameron Day Trading Videos/haiku_output_0450-0499.txt")

content = input_file.read_text(encoding='utf-8')

# Extract lines 1266-2519 (FILE 0450-0499)
lines = content.split('\n')
extract_lines = lines[1265:2519]  # 0-indexed
extract_text = '\n'.join(extract_lines)

# Split into individual files
file_pattern = r'FILE (\d{4})[^\n]*\n(.*?)(?=FILE \d{4}|$)'
files_match = list(re.finditer(file_pattern, extract_text, re.DOTALL))

output = []

for match in files_match:
    file_id = match.group(1)
    file_content = match.group(2)
    
    # Skip if no trades
    if 'TRADES: NO TRADES TAKEN' in file_content:
        continue
    
    # Check for TRADES: section
    trades_match = re.search(r'TRADES:\n(.*?)(?=\nSUMMARY:|$)', file_content, re.DOTALL)
    if not trades_match:
        continue
    
    trades_block = trades_match.group(1).strip()
    
    # Check if it has trade rows (not just headers)
    if '|' not in trades_block or trades_block.count('|') < 3:
        continue
    
    output.append(f"=== FILE {file_id} ===")
    output.append("TRADE_MECHANICS:")
    
    # Extract table rows
    lines_in_trades = trades_block.split('\n')
    for line in lines_in_trades:
        # Skip headers and empty lines
        if not line.strip() or '---' in line:
            continue
        if 'SYMBOL' in line or 'ENTRY' in line:
            continue
        # Keep trade rows
        if line.strip().startswith('|'):
            output.append(line)

output.append("\n=== TSV_AUDIT ===")
output.append("file\ttrade\tsymbol\tFLOAT\tGAP%\tREL_VOL\tPATTERN_TYPE\tENTRY_TRIGGER\tADD_ON_MECHANIC\tSTOP_CRITERIA\tT1_TARGET\tTIME_OF_ENTRY\tMACD_STATE\tHOLD_DURATION")

# Write output
output_file.write_text('\n'.join(output), encoding='utf-8')
print(f"Extracted to {output_file}")
