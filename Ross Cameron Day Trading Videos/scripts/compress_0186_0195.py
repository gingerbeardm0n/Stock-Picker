#!/usr/bin/env python3
"""
Compress Ross Cameron transcripts 0186-0195 to caveman prose.
Applies COMPRESSION_PROMPT_V2 rules.
"""

import os
import re
from pathlib import Path

# Define compression rules
FILLER_WORDS = {
    'alright', 'alright so', 'so', 'you know', 'actually', 'basically', 'like',
    'right', 'I mean', 'let me just', 'real quick', 'honestly', 'literally',
    'pretty much', 'what is', 'what am i', 'what are', 'what i', 'what we',
}

INTRO_OUTRO = [
    r'\[music\]',
    r"what's up everyone",
    r'welcome back',
    r'thanks for watching',
    r'smash the like button',
    r'hit subscribe',
    r'subscribe to the channel',
    r'give me a thumbs up',
    r'comments questions',
    r'have a great weekend',
    r'see you (?:on|in|first thing)',
    r'no ads? i don\'t monetize',
    r'but do me a favor please hit',
    r'groundhog',
]

def clean_text(text):
    """Remove music markers, normalize whitespace."""
    text = re.sub(r'\[music\]\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def extract_critical_info(text):
    """Extract all trades, prices, P&L, and rules."""
    critical = {
        'trades': [],
        'prices': [],
        'pl': [],
        'symbols': set(),
        'times': [],
        'rules': [],
        'regrets': [],
        'account_balance': None,
        'goal': None,
        'ytd_mtd': [],
        'patterns': [],
    }

    # Extract symbols (4-letter caps with $)
    symbols = re.findall(r'\$?([A-Z]{3,5})(?:\s|$)', text)
    critical['symbols'] = set(s for s in symbols if len(s) <= 5 and s.isalpha())

    # Extract prices ($ format)
    prices = re.findall(r'\$\s*(\d+(?:\.\d{2})?)', text)
    critical['prices'] = prices[:20]  # Keep first 20

    # Extract P&L (dollar amounts with up/down context)
    pl_match = re.findall(r'(?:up|down|made|lost|profit|green|red)\s+(?:of\s+)?\$?\s*(\d+(?:,\d{3})*(?:\.\d+)?)', text, re.IGNORECASE)
    critical['pl'] = pl_match[:15]

    # Extract times (HH:MM or HH:MM AM/PM)
    times = re.findall(r'(\d{1,2}:\d{2}\s*(?:am|pm|a\.m|p\.m)?)', text, re.IGNORECASE)
    critical['times'] = times[:10]

    # Extract patterns
    patterns = ['gap-and-go', 'micro-pullback', 'flat-top', 'vwap-reclaim', 'halt-resume',
                'dip-buy', 'bounce', 'breakout', 'red-to-green', 'squeeze', 'consolidation']
    found_patterns = [p for p in patterns if p.lower() in text.lower()]
    critical['patterns'] = found_patterns

    # Extract YTD/MTD
    ytd_match = re.findall(r'(?:ytd|year-to-date|year to date)\s*(?:up|down|of)?\s*\$?(\d+(?:,\d{3})*)', text, re.IGNORECASE)
    mtd_match = re.findall(r'(?:mtd|month-to-date|month to date)\s*(?:up|down|of)?\s*\$?(\d+(?:,\d{3})*)', text, re.IGNORECASE)
    if ytd_match:
        critical['ytd_mtd'].append(f"YTD: ${ytd_match[0]}")
    if mtd_match:
        critical['ytd_mtd'].append(f"MTD: ${mtd_match[0]}")

    # Extract account balance mentions
    balance = re.search(r'(?:account|balance).*?\$\s*(\d+(?:,\d{3})*)', text, re.IGNORECASE)
    if balance:
        critical['account_balance'] = balance.group(1)

    # Extract daily goal
    goal = re.search(r'(?:goal|target)\s*(?:of|is)?\s*\$?\s*(\d+(?:,\d{3})*)', text, re.IGNORECASE)
    if goal:
        critical['goal'] = goal.group(1)

    return critical

def compress_transcript(text):
    """Apply compression rules to transcript."""
    text = clean_text(text)
    critical = extract_critical_info(text)

    # Split into sentences
    sentences = re.split(r'[.!?]+', text)

    compressed = []

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        # Check if sentence contains critical trading info
        has_symbol = any(sym in sentence.upper() for sym in critical['symbols'])
        has_price = any(price in sentence for price in critical['prices'])
        has_pl = any(pl in sentence for pl in critical['pl'])
        has_time = any(time in sentence for time in critical['times'])
        has_rule = any(word in sentence.lower() for word in ['rule', 'never', 'always', 'should', 'don\'t'])
        has_trade = any(word in sentence.lower() for word in ['trade', 'entry', 'exit', 'bought', 'sold', 'long', 'short', 'loss', 'profit'])

        is_critical = has_symbol or has_price or has_pl or has_time or (has_rule and has_trade)

        # Skip intro/outro
        is_intro = any(re.search(pattern, sentence, re.IGNORECASE) for pattern in INTRO_OUTRO)
        if is_intro:
            continue

        # Keep critical sentences
        if is_critical:
            # Remove filler
            cleaned = sentence
            for filler in ['you know', 'i mean', 'basically', 'actually', 'honestly', 'like', 'so']:
                cleaned = re.sub(r'\b' + filler + r'\b', '', cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r'\s+', ' ', cleaned).strip()
            if cleaned:
                compressed.append(cleaned)

    return ' '.join(compressed[:100])  # Limit to first 100 sentences

def compress_file(input_path, output_path):
    """Read transcript, compress, write output."""
    with open(input_path, 'r', encoding='utf-8', errors='ignore') as f:
        text = f.read()

    # Basic compression: extract key trades and P&L
    lines = text.split('\n')
    key_lines = []

    for line in lines:
        line = line.strip()
        if not line or line.startswith('['):
            continue

        # Keep lines with: symbols, prices, P&L, times, trades
        if (re.search(r'\$[0-9,]+', line) or  # Price/P&L
            re.search(r'\d{1,2}:\d{2}', line) or  # Time
            any(sym in line.upper() for sym in re.findall(r'[A-Z]{3,5}', line)) or  # Symbol
            any(word in line.lower() for word in ['trade', 'entry', 'exit', 'bought', 'sold', 'profit', 'loss', 'up', 'down', 'green', 'red'])):
            key_lines.append(line)

    compressed = ' '.join(key_lines)

    # Remove common filler
    for filler in ['you know', 'i mean', 'basically', 'actually', 'honestly', 'like', 'so', 'right', 'alright']:
        compressed = re.sub(r'\b' + filler + r'\b', '', compressed, flags=re.IGNORECASE)

    # Clean up
    compressed = re.sub(r'\s+', ' ', compressed).strip()

    # Limit to ~2000 chars
    if len(compressed) > 2000:
        compressed = compressed[:2000] + '...'

    # Write output
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(compressed)

    return len(compressed)

# Main execution
if __name__ == '__main__':
    input_dir = r'C:\Repositories\Stock-Picker\Ross Cameron Day Trading Videos\Text transcriptions'
    output_dir = r'C:\Repositories\Stock-Picker\Ross Cameron Day Trading Videos\compressed transcripts'

    files = [
        (186, '+$28k on (NASDAQ ALF & IKNX) Recap by Ross Cameron.txt'),
        (187, '+$28k on (NASDAQ DBGI AUUD CERE & MRIN) Recap by Ross Cameron.txt'),
        (188, '+$29k on (NASDAQ CLOV) Recap by Ross Cameron.txt'),
        (189, '+$29k on (NASDAQ SPRT) Day Trading Recap by Ross Cameron.txt'),
        (190, '+$29k on (NYSE ANVS) Recap by Ross Cameron.txt'),
        (191, '+$29k on (NYSE RHE) Recap by Ross Cameron.txt'),
        (192, '+$2k After an Uphill Battle Ross\'s Trade Recap.txt'),
        (193, '+$2k in 1 Hour on the Portable ATM! Ross\' Trade Recap.txt'),
        (194, '+$3,232.67 in 1hr with 100% accuracy....Awesome!!.txt'),
        (195, '+$3,650 in Ten Minutes of Trading Ross\'s Trade Recap.txt'),
    ]

    print("Compressing transcripts 0186-0195...")
    for num, filename in files:
        input_path = os.path.join(input_dir, f'0{num}_{filename}')
        output_path = os.path.join(output_dir, f'0{num}_compressed.md')

        if os.path.exists(input_path):
            size = compress_file(input_path, output_path)
            print(f"✓ 0{num}: {size:,} chars → {output_path}")
        else:
            print(f"✗ 0{num}: File not found - {input_path}")

    print("\nDone!")
