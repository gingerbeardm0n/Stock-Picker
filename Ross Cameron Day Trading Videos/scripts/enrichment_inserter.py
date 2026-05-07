"""
enrichment_inserter.py

Takes Haiku agent output (mechanics tables + TSV audit rows) and:
1. Inserts TRADE_MECHANICS tables into the target chunk file
2. Appends TSV rows to the audit file

Usage:
    python enrichment_inserter.py --chunk extractions/TRANSCRIPT_SUMMARIES_0001-0099.md
                                  --haiku-output haiku_output_batch1.txt
                                  --audit enrichment_audit_pass1.tsv

The haiku output file should contain the raw text output from the Haiku agent,
with === FILE XXXX === blocks and a === TSV_AUDIT === block at the end.
"""

import re
import sys
import os
import argparse


def parse_haiku_output(haiku_output_text):
    """Parse Haiku agent output into mechanics tables dict and TSV rows list."""
    mechanics = {}  # file_num -> mechanics table markdown string
    tsv_rows = []

    # Split on === FILE XXXX === markers
    file_pattern = re.compile(r'=== FILE (\d{4}) ===\s*\n(.*?)(?===|$)', re.DOTALL)
    tsv_pattern = re.compile(r'=== TSV_AUDIT ===\s*\n(.*?)$', re.DOTALL)

    for match in file_pattern.finditer(haiku_output_text):
        file_num = match.group(1)
        content = match.group(2).strip()
        mechanics[file_num] = content

    tsv_match = tsv_pattern.search(haiku_output_text)
    if tsv_match:
        tsv_block = tsv_match.group(1).strip()
        lines = tsv_block.split('\n')
        for line in lines:
            if line.strip() and not line.startswith('file\t'):  # skip header
                tsv_rows.append(line.strip())

    return mechanics, tsv_rows


def insert_mechanics_into_chunk(chunk_path, mechanics_dict):
    """
    Insert TRADE_MECHANICS tables into chunk file after each TRADES table.
    Inserts after the trades table rows, before the SUMMARY: line.
    Skips files that already have TRADE_MECHANICS section.
    """
    with open(chunk_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Split into FILE entries
    # Each entry starts with "FILE XXXX |" and ends at the next "FILE" or end of file
    file_split_pattern = re.compile(r'(?=^FILE \d{4} \|)', re.MULTILINE)
    entries = file_split_pattern.split(content)

    result_parts = []
    modified_count = 0
    skipped_count = 0

    for entry in entries:
        if not entry.strip():
            result_parts.append(entry)
            continue

        # Extract file number
        file_num_match = re.match(r'FILE (\d{4}) \|', entry)
        if not file_num_match:
            result_parts.append(entry)
            continue

        file_num = file_num_match.group(1)

        # Skip if already has TRADE_MECHANICS
        if 'TRADE_MECHANICS:' in entry:
            skipped_count += 1
            result_parts.append(entry)
            continue

        # Skip if no mechanics data for this file
        if file_num not in mechanics_dict:
            result_parts.append(entry)
            continue

        # Find insertion point: after TRADES table, before SUMMARY:
        # The TRADES table ends at the last pipe-delimited row before SUMMARY:
        summary_pos = entry.find('\nSUMMARY:')
        if summary_pos == -1:
            result_parts.append(entry)
            continue

        mechanics_block = mechanics_dict[file_num]

        # Insert mechanics block before SUMMARY:
        new_entry = (
            entry[:summary_pos]
            + '\n\n'
            + mechanics_block
            + '\n'
            + entry[summary_pos:]
        )
        result_parts.append(new_entry)
        modified_count += 1

    new_content = ''.join(result_parts)

    with open(chunk_path, 'w', encoding='utf-8') as f:
        f.write(new_content)

    print(f"Modified {modified_count} entries, skipped {skipped_count} (already enriched)")
    return modified_count


def write_tsv_rows(audit_path, tsv_rows):
    """Append TSV rows to audit file, writing header if file doesn't exist."""
    header = 'file\ttrade\tsymbol\tFLOAT\tGAP%\tREL_VOL\tPATTERN_TYPE\tENTRY_TRIGGER\tADD_ON_MECHANIC\tSTOP_CRITERIA\tT1_TARGET\tTIME_OF_ENTRY\tMACD_STATE\tHOLD_DURATION'

    file_exists = os.path.exists(audit_path)

    with open(audit_path, 'a', encoding='utf-8') as f:
        if not file_exists:
            f.write(header + '\n')
        for row in tsv_rows:
            f.write(row + '\n')

    print(f"Wrote {len(tsv_rows)} TSV rows to {audit_path}")


def main():
    parser = argparse.ArgumentParser(description='Insert Haiku mechanics output into chunk files')
    parser.add_argument('--chunk', required=True, help='Path to chunk file to modify')
    parser.add_argument('--haiku-output', required=True, help='Path to Haiku agent output text file')
    parser.add_argument('--audit', required=True, help='Path to TSV audit file (appended)')
    args = parser.parse_args()

    if not os.path.exists(args.chunk):
        print(f"ERROR: Chunk file not found: {args.chunk}")
        sys.exit(1)

    if not os.path.exists(args.haiku_output):
        print(f"ERROR: Haiku output file not found: {args.haiku_output}")
        sys.exit(1)

    with open(args.haiku_output, 'r', encoding='utf-8') as f:
        haiku_text = f.read()

    print(f"Parsing Haiku output...")
    mechanics, tsv_rows = parse_haiku_output(haiku_text)
    print(f"Found mechanics tables for {len(mechanics)} files, {len(tsv_rows)} TSV rows")

    print(f"Inserting mechanics tables into {args.chunk}...")
    insert_mechanics_into_chunk(args.chunk, mechanics)

    print(f"Writing TSV audit rows to {args.audit}...")
    write_tsv_rows(args.audit, tsv_rows)

    print("Done.")


if __name__ == '__main__':
    main()
