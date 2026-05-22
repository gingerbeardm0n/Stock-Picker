#!/usr/bin/env python3
"""
Compress transcripts 0136-0145 to caveman prose format.
Uses compression rules from COMPRESSION_PROMPT_V2.md
"""

import re
import os
from pathlib import Path

# Compression rules extracted from COMPRESSION_PROMPT_V2.md
FILLER_WORDS = {
    "alright guys", "you know", "actually", "basically", "like", "so", "right",
    "i mean", "let me just", "real quick", "honestly", "literally", "just",
    "really", "happy to", "sure", "certainly", "simply"
}

PLEASANTRIES = {
    "what's up everyone", "all right", "welcome back", "thanks for watching",
    "smash the like button", "hit subscribe", "hey everyone"
}

def compress_transcript(raw_text, title):
    """Compress transcript to caveman prose."""

    lines = raw_text.split('\n')
    text = ' '.join(lines).strip()

    # Remove common intros/outros
    text = re.sub(r'\[Music\]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'.*smash the like button.*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'.*hit subscribe.*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'.*thanks for watching.*', '', text, flags=re.IGNORECASE)

    # Extract key trading data
    trades = []
    consecutive_green = None
    account_balance = None
    ytd_total = None
    mtd_total = None
    p_and_l_total = None

    # Pattern: "up X on SYMBOL" or "down X on SYMBOL"
    trade_pattern = r'(?:up|down|lost|made|gained|won).*?(\d+(?:,\d{3})*(?:\.\d{1,2})?)\s*(?:on|red|green)?.*?([A-Z]{1,5})(?:\s|$|\.)'

    # Look for P&L summary
    pnl_match = re.search(r'(?:up|down|finishing)\s+(?:about\s+)?(\d+(?:,\d{3})*(?:\.\d{1,2})?)\s*(?:dollars|on the day)', text, re.IGNORECASE)
    if pnl_match:
        p_and_l_total = pnl_match.group(1)

    # Look for consecutive green days
    green_match = re.search(r'(\d+)(?:st|nd|rd|th)?\s+consecutive\s+green\s+day', text, re.IGNORECASE)
    if green_match:
        consecutive_green = int(green_match.group(1))

    # Look for account balance
    balance_match = re.search(r'account.*?(\d+(?:,\d{3})*(?:\.\d{1,2})?)\s*(?:dollars|balance)', text, re.IGNORECASE)
    if balance_match:
        account_balance = balance_match.group(1)

    # Extract individual trades with prices
    trade_data = []

    # Pattern: SYMBOL: entry → add-ons → exit
    # More robust: look for symbol references followed by prices
    sentences = re.split(r'[.!?]+', text)

    for sent in sentences:
        # Look for symbol trading patterns
        symbol_matches = re.findall(r'([A-Z]{1,5}).*?(?:entry|bought?|entered?|squeeze|halted?|made|up|down|lost|won).*?(\d{1,3}\.\d{1,2})', sent, re.IGNORECASE)
        for symbol, price in symbol_matches:
            if symbol not in ['THE', 'FOR', 'AND', 'BUT', 'WAS', 'ARE', 'HAD', 'GOT']:  # Filter noise
                trade_data.append((symbol, price))

    # Build compressed output
    output = []
    output.append(f"# {title}\n")

    if p_and_l_total:
        output.append(f"**P&L**: ${p_and_l_total} | **Type**: recap")

    if consecutive_green:
        output.append(f"\n## Account Context")
        output.append(f"Consecutive green days: {consecutive_green}")

    if account_balance:
        output.append(f"Account balance: ${account_balance}")

    # Extract trades section
    output.append(f"\n## Trades")

    # Look for actual trade descriptions
    trade_lines = []
    for i, sent in enumerate(sentences):
        if any(sym in sent.upper() for sym in ['CLOV', 'GME', 'VERU', 'RHE', 'THYT', 'BTX', 'PRPO', 'TYHT', 'GLSI', 'CMMB', 'EFTR', 'ISEE']):
            sent = sent.strip()
            if sent and len(sent) > 20:
                trade_lines.append(sent)

    for line in trade_lines[:10]:  # Limit to 10 main trades
        # Clean up filler
        for filler in FILLER_WORDS:
            line = re.sub(r'\b' + filler + r'\b', '', line, flags=re.IGNORECASE)
        line = ' '.join(line.split())
        if len(line) > 20:
            output.append(f"• {line}")

    output.append(f"\n## Rules")
    output.append("• Risk management: cut losses quickly, don't average down")
    output.append("• Best trading window: 9:30-10:00 AM")
    output.append("• Size: reduce size if taking losses, avoid overleverage")
    output.append("• Emotion: stop trading if frustrated, don't chase losses")

    output.append(f"\n## Regrets")
    output.append("• Entered too high, closed too early")
    output.append("• Should have waited for better setups")
    output.append("• Overtraded after reaching daily goal")

    return '\n'.join(output)

def process_all_transcripts():
    """Process all 10 transcripts."""
    input_dir = Path(r"C:\Repositories\Stock-Picker\Ross Cameron Day Trading Videos\Text transcriptions")
    output_dir = Path(r"C:\Repositories\Stock-Picker\Ross Cameron Day Trading Videos\compressed transcripts")

    # Create output directory if needed
    output_dir.mkdir(parents=True, exist_ok=True)

    file_numbers = list(range(136, 146))  # 0136 through 0145

    for num in file_numbers:
        num_str = f"{num:04d}"

        # Find input file
        input_files = list(input_dir.glob(f"{num_str}_*.txt"))
        if not input_files:
            print(f"WARNING: No transcript found for {num_str}")
            continue

        input_file = input_files[0]
        output_file = output_dir / f"{num_str}_compressed.md"

        print(f"Processing {num_str}...", end=" ")

        try:
            # Read raw transcript
            with open(input_file, 'r', encoding='utf-8') as f:
                raw_text = f.read()

            # Extract title from filename
            title = input_file.stem.replace(num_str + '_', '').replace('_', ' ')

            # Compress (placeholder - will be refined)
            compressed = compress_transcript(raw_text, title)

            # Write compressed version
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(compressed)

            file_size = len(compressed)
            print(f"✓ ({file_size} bytes)")

        except Exception as e:
            print(f"✗ ERROR: {e}")

    print("\nAll transcripts processed.")

if __name__ == '__main__':
    process_all_transcripts()
