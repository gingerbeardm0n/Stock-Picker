# TranscriptCompression.ps1
# Automated overnight run: 15 batches of 20 files (300 files), /compact every 3 batches
# Scheduled: 11pm and 4am one-time runs

$prompt = @'
Read the full instructions from this file before doing anything:
C:\Repositories\Stock-Picker\Ross Cameron Day Trading Videos\prompts\COMPRESSION_PIPELINE.md

Then execute an automated compression run with these exact parameters:

STEP 1 - Find resume point:
Glob "C:\Repositories\Stock-Picker\Ross Cameron Day Trading Videos\compressed transcripts\*_compressed.md"
Sort results, find the highest NNNN number. Next file to compress = NNNN + 1.
If NNNN is 1799 or higher: output "ALL DONE - all 1799 files complete" and stop immediately.

STEP 2 - Fix special-char filenames before each batch:
Before spawning each batch agent, run this Python script from the source directory
"C:\Repositories\Stock-Picker\Ross Cameron Day Trading Videos\Text transcriptions\" to rename any
problem files in the upcoming 20-file range (Unicode apostrophes, !, $, commas, etc.):

  import os, glob, re
  for f in glob.glob('*'):
      if re.search(r"[^\w\s\-_\.\(\)]", f):
          clean = re.sub(r"[^\w\s\-_\.\(\)]", "", f).strip()
          if clean and clean != f:
              os.rename(f, clean)
              print("Renamed: " + f + " -> " + clean)

STEP 3 - Run 15 sequential batches of 20 files each (300 files total):
- Use subagent_type: caveman:cavecrew-builder for every batch
- Use the abbreviated prompt from COMPRESSION_PIPELINE.md Section 2
- Complete each batch fully before starting the next
- After batches 3, 6, 9, and 12: run /compact to reset conversation context
- If any batch agent reports a skipped file (unreadable name, missing source): note it and continue
- If file numbers reach or exceed 1799 before all 15 batches are done: stop and report

STEP 4 - Final report (output when done):
- Total files compressed this run
- List of any skipped files and reasons
- New highest compressed file number
- Whether all 1799 files are now complete
'@

Set-Location "C:\Repositories\Stock-Picker"
claude --dangerously-skip-permissions -p $prompt
