import re
from pathlib import Path

input_file = Path("C:/Repositories/Stock-Picker/Ross Cameron Day Trading Videos/extractions/TRANSCRIPT_SUMMARIES_0400-0499.md")
output_file = Path("C:/Repositories/Stock-Picker/Ross Cameron Day Trading Videos/haiku_output_0450-0499.txt")

content = input_file.read_text(encoding='utf-8', errors='replace')

# Split by FILE markers
file_blocks = re.split(r'(FILE \d{4}[^\n]*\n)', content)

output_lines = []
tsv_rows = []

i = 1
while i < len(file_blocks):
    if not file_blocks[i].startswith('FILE'):
        i += 1
        continue
    
    file_header = file_blocks[i]
    file_content = file_blocks[i+1] if i+1 < len(file_blocks) else ""
    
    match = re.search(r'FILE (\d{4})', file_header)
    if not match:
        i += 2
        continue
    
    file_id = match.group(1)
    
    # Skip if NO TRADES
    if 'TRADES: NO TRADES TAKEN' in file_content:
        i += 2
        continue
    
    # Extract TRADES table
    trades_match = re.search(r'TRADES:\n(.*?)(?:\n[A-Z]+:|$)', file_content, re.DOTALL)
    if not trades_match:
        i += 2
        continue
    
    trades_text = trades_match.group(1)
    
    # Extract trade rows (lines starting with |)
    trade_rows = [line for line in trades_text.split('\n') if line.strip().startswith('|')]
    
    # Filter out header rows and separator rows
    trade_rows = [line for line in trade_rows if not any(x in line for x in ['---', 'SYMBOL', 'ENTRY', '#'])]
    
    if not trade_rows:
        i += 2
        continue
    
    # Found trades
    output_lines.append(f"=== FILE {file_id} ===")
    output_lines.append("TRADE_MECHANICS:")
    
    for idx, row in enumerate(trade_rows, 1):
        output_lines.append(row)
        
        # Extract fields from row for TSV
        parts = [p.strip() for p in row.split('|')]
        parts = [p for p in parts if p]  # Remove empty
        
        if len(parts) >= 11:
            try:
                trade_num = parts[0]
                symbol = parts[1]
                # Create TSV row with file, trade, symbol, and placeholders
                tsv_parts = [file_id, trade_num, symbol]
                # Add remaining fields as placeholders (S for found, - for not found)
                for _ in range(11):  # 11 more fields
                    tsv_parts.append('-')
                tsv_rows.append(tsv_parts)
            except:
                pass
    
    output_lines.append('')
    i += 2

# Build output
output_lines.append('=== TSV_AUDIT ===')
output_lines.append('file\ttrade\tsymbol\tFLOAT\tGAP%\tREL_VOL\tPATTERN_TYPE\tENTRY_TRIGGER\tADD_ON_MECHANIC\tSTOP_CRITERIA\tT1_TARGET\tTIME_OF_ENTRY\tMACD_STATE\tHOLD_DURATION')

for row in tsv_rows:
    output_lines.append('\t'.join(row))

output_file.write_text('\n'.join(output_lines), encoding='utf-8')
print(f"Done. Output: {output_file}")
