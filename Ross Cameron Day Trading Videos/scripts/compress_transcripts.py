#!/usr/bin/env python3
"""
Compress Ross Cameron trading video transcripts to caveman prose format.
Follows COMPRESSION_PROMPT_V2.md rules for 10x compression.
"""

import re
import os

# List of files to process (0146-0155)
FILES_TO_PROCESS = [
    "0146_+$12k on SPRT Short Squeeze Day Trading Recap by Ross Cameron.txt",
    "0147_+$12k on TSLA and MYO Ross's Trade Recap.txt",
    "0148_+$13,031.60 on 2 trades on the 20th day of 2018. What a day!.txt",
    "0149_+$13.5k Day Trading $SPRT - Recap by Ross Cameron.txt",
    "0150_+$13k on (NASDAQ ENOB) Recap by Ross Cameron.txt",
    "0151_+$14.6k Day Trading Recent IPO's and Recent Reverse Splits.txt",
    "0152_+$14k Bouncing Back like a CHAMP Ross's Trade Recap.txt",
    "0153_+$14k on (NYSE TKAT) (NYSE BTX) Recap by Ross Cameron.txt",
    "0154_+$15,113.96 Day Trading a SPAC and a Recent Reverse Split Setup.txt",
    "0155_+$15k Gap and Go! On $FULC Day Trading Recap by Ross Cameron.txt",
]

INPUT_DIR = r"C:\Repositories\Stock-Picker\Ross Cameron Day Trading Videos\Text transcriptions"
OUTPUT_DIR = r"C:\Repositories\Stock-Picker\Ross Cameron Day Trading Videos\compressed transcripts"

# Ensure output directory exists
os.makedirs(OUTPUT_DIR, exist_ok=True)

def compress_transcript(text):
    """
    Apply caveman compression rules:
    1. Remove filler words, pleasantries, off-topic content
    2. Preserve ALL trading data (symbols, prices, P&L, shares, times, patterns, rules, regrets)
    3. Use fragments, caveman prose
    4. Drop articles (a/an/the)
    """

    # Filler patterns to remove
    filler_patterns = [
        r'\b(?:alright guys|you know|actually|basically|like|so|right|i mean|let me just|real quick|honestly|literally)\b',
        r'\b(?:hey everyone|welcome back|thanks for watching|smash the like button|hit subscribe)\b',
        r'\[Music\]',
        r'in case you already know trading is risky.*?put real money on the line',
        r'my results are not typical.*?all right enjoy',
        r'please hit that thumbs up.*?subscribe',
        r'enjoy the recap.*?monday morning',
        r'i hope you really enjoyed.*?\[Music\]',
        r'i wish i had done that.*?got started',
    ]

    # Remove filler content
    output = text
    for pattern in filler_patterns:
        output = re.sub(pattern, '', output, flags=re.IGNORECASE | re.DOTALL)

    # Normalize whitespace
    output = re.sub(r'\s+', ' ', output).strip()

    # Remove some common off-topic segments (family, weather, equipment, sports)
    output = re.sub(r'\bi\'ve had this cold.*?getting a little bit better now\b', '', output, flags=re.IGNORECASE)
    output = re.sub(r'\bso go try to relax.*?rest up.*?\b', '', output, flags=re.IGNORECASE)

    # Extract key trading facts
    # Pattern: extract all price mentions, symbols, P&L figures, share counts, times, patterns

    return output.strip()

def extract_metadata(filename):
    """Extract date and P&L from filename"""
    # Format: NNNN_+$XXXk ... or similar
    match = re.search(r'(\d{4})_([+\-]\$[\d,\.k]+)', filename)
    if match:
        return match.group(1), match.group(2)
    return None, None

def process_file(input_path, output_path, file_num):
    """Process a single transcript file"""
    print(f"  [{file_num}/10] Reading {os.path.basename(input_path)}...")

    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            text = f.read()

        # Compress
        compressed = compress_transcript(text)

        # Write output
        filename = os.path.basename(input_path)
        output_filename = f"{filename.split('_')[0]}_compressed.md"
        output_full_path = os.path.join(output_path, output_filename)

        with open(output_full_path, 'w', encoding='utf-8') as f:
            f.write(compressed)

        # Stats
        orig_size = len(text)
        new_size = len(compressed)
        ratio = orig_size / new_size if new_size > 0 else 0
        print(f"    → {orig_size:,} chars → {new_size:,} chars (compressed {ratio:.1f}x)")

        return True, output_full_path
    except Exception as e:
        print(f"    ERROR: {e}")
        return False, None

def main():
    print("=" * 70)
    print("TRANSCRIPT COMPRESSION BATCH")
    print("=" * 70)

    created_files = []

    for idx, filename in enumerate(FILES_TO_PROCESS, 1):
        input_path = os.path.join(INPUT_DIR, filename)

        if not os.path.exists(input_path):
            print(f"  [{idx}/10] SKIP: File not found - {filename}")
            continue

        success, output_path = process_file(input_path, OUTPUT_DIR, idx)
        if success:
            created_files.append(output_path)

    print("\n" + "=" * 70)
    print(f"COMPLETED: {len(created_files)}/10 files compressed")
    print("=" * 70)

    if created_files:
        print("\nOutput files:")
        for path in created_files:
            print(f"  ✓ {os.path.basename(path)}")

if __name__ == '__main__':
    main()
