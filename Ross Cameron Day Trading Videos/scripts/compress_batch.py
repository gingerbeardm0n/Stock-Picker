import os
import re

# Files to compress
files = [
    '0106_$SIDU +50% during the LIVE Day Trading Morning Show.txt',
    '0107_$SINT +72% on PR from 9am ET.txt',
    '0108_$SNGX +322% on breaking news pre-market.txt',
    '0109_$SNTG +50%.txt',
    '0110_$SPRB +130% for a Gap and Go day trade.txt',
    '0111_$SPRO +150%.txt',
    '0112_$SPRO +154% LIVE Day Trading Morning Show with Ross.txt',
    '0113_$SQL +261% Gap and Go Setup!.txt',
    '0114_$SYRA goes from $1.20 to 9.80 in 15 minutes! +800%.txt',
    '0115_$TCBP $OTRK Day Trading from Gap & Momentum Scanners.txt'
]

root = r'C:\Repositories\Stock-Picker\Ross Cameron Day Trading Videos\Text transcriptions'
output_dir = r'C:\Repositories\Stock-Picker\Ross Cameron Day Trading Videos\compressed transcripts'

# Filler words and phrases to remove
fillers = [
    r'\b(alright|guys|you know|actually|basically|like|so|right|i mean|let me just|real quick|honestly|literally)\b',
    r'\b(hey everyone|welcome back|thanks for watching|smash the like button|hit subscribe)\b',
    r'\b(so um|uh|um|you know|i think|i feel|i was|that\'s)'
]

filler_pattern = re.compile('|'.join(fillers), re.IGNORECASE)

def compress(text):
    # Remove filler words
    text = re.sub(r'\b(alright|you know|actually|basically|like|so|right|i mean|let me|real quick|honestly|literally|um|uh)\b', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s+', ' ', text)  # Collapse whitespace
    text = text.strip()
    return text

for filename in files:
    input_path = os.path.join(root, filename)
    output_filename = filename.rsplit('.', 1)[0] + '_compressed.md'
    output_path = os.path.join(output_dir, output_filename)
    
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            raw_text = f.read()
        
        compressed = compress(raw_text)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(compressed)
        
        print(f"✓ {filename}")
    except Exception as e:
        print(f"✗ {filename}: {e}")

print("\nDone!")
