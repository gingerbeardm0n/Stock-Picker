"""Layout census of Ross's live-looking YouTube videos that are not in our collection.

Input: outputs/ross_imitation/channel_live_candidates.tsv (from the channel listing; in_collection == no).
For each video: get the 1080p stream URL (yt-dlp), grab one frame at 40% of the duration with ffmpeg (seek, no full
download), OCR it and classify:
  esignal_2022  - "Positions" window title in the top-left corner (the layout ross_live_video_batch.py reads)
  positions_elsewhere - "Positions" text somewhere else on screen
  clock_only    - an HH:MM:SS market clock (04-16 h) but no Positions window
  other         - neither (talking head, slides, recap, training)
If the first frame is "other", a second frame at 70% is tried. Frames are kept (small jpg) for spot checks.
Resumable: rows already in the output CSV are skipped.
Run with the OCR venv python:
  python -I ross_live_layout_census.py <frames_dir>
"""
import csv
import os
import re
import subprocess
import sys

import cv2

HERE = os.path.dirname(os.path.abspath(__file__))
OUTD = os.path.abspath(os.path.join(HERE, '..', 'outputs', 'ross_imitation'))
SRC = os.path.join(OUTD, 'channel_live_candidates.tsv')
OUT = os.path.join(OUTD, 'live_layout_census.csv')
CLOCK = re.compile(r'\b(0[4-9]|1[0-6]):[0-5]\d:[0-5]\d\b')
COLS = ['video_id', 'upload_date', 'duration_s', 'tab', 'layout', 'pos_xy', 'clock_xy', 'clock', 'frame_s', 'title']


def grab(py, vid, sec, path):
    r = subprocess.run([py, '-m', 'yt_dlp', '--js-runtimes', 'node', '-q', '--no-warnings',
                        '-f', 'bv*[height<=1080][ext=mp4]/bv*[height<=1080]', '-g',
                        f'https://www.youtube.com/watch?v={vid}'], capture_output=True, text=True, timeout=180)
    url = (r.stdout.strip().splitlines() or [''])[-1]
    if not url.startswith('http'):
        return None
    subprocess.run(['ffmpeg', '-v', 'error', '-ss', str(sec), '-i', url, '-frames:v', '1', '-y', path],
                   capture_output=True, timeout=300)
    return cv2.imread(path) if os.path.exists(path) else None


def classify(ocr, im):
    im = cv2.resize(im, (1920, 1080))
    r, _ = ocr(im, use_cls=False)
    pos, clk = None, None
    for b, txt, _ in r or []:
        x, y = int(b[0][0]), int(b[0][1])
        if pos is None and 'osition' in txt:
            pos = (x, y)
        m = CLOCK.search(txt.replace(' ', ''))
        if clk is None and m:
            clk = (x, y, m.group(0))
    if pos and pos[0] < 120 and pos[1] < 40:
        lay = 'esignal_2022'
    elif pos:
        lay = 'positions_elsewhere'
    elif clk:
        lay = 'clock_only'
    else:
        lay = 'other'
    return lay, pos, clk


def main(fdir):
    from rapidocr_onnxruntime import RapidOCR
    sys.stdout.reconfigure(encoding='utf-8')
    ocr = RapidOCR()
    os.makedirs(fdir, exist_ok=True)
    done = set()
    if os.path.exists(OUT):
        done = {r['video_id'] for r in csv.DictReader(open(OUT, encoding='utf-8'))}
    rows = [r for r in csv.DictReader(open(SRC, encoding='utf-8', errors='replace'), delimiter='\t')
            if r.get('in_collection') == 'no' and r['video_id'] not in done]
    new = not os.path.exists(OUT)
    fh = open(OUT, 'a', newline='', encoding='utf-8')
    w = csv.DictWriter(fh, COLS)
    if new:
        w.writeheader()
    print(f'{len(rows)} to check', flush=True)
    for k, r in enumerate(rows):
        try:
            dur = float(r.get('duration_s') or 0)
        except ValueError:
            dur = 0
        res = dict(video_id=r['video_id'], upload_date=r.get('upload_date'), duration_s=int(dur), tab=r.get('tab'),
                   title=(r.get('title') or '')[:120], layout='error')
        try:
            for q in (0.4, 0.7):
                sec = int(dur * q) if dur > 60 else 30
                path = os.path.join(fdir, f"{r['video_id']}_{sec}.jpg")
                im = grab(sys.executable, r['video_id'], sec, path)
                if im is None:
                    res['layout'] = 'grab failed'
                    continue
                lay, pos, clk = classify(ocr, im)
                cv2.imwrite(path, cv2.resize(im, (960, 540)), [cv2.IMWRITE_JPEG_QUALITY, 70])
                res.update(layout=lay, pos_xy=pos, clock_xy=clk and clk[:2], clock=clk and clk[2], frame_s=sec)
                if lay != 'other':
                    break
        except Exception as ex:  # noqa: BLE001
            res['layout'] = f'error {ex!r}'[:80]
        w.writerow(res)
        fh.flush()
        print(f"[{k + 1}/{len(rows)}] {r['video_id']} {res['layout']}", flush=True)
    print('CENSUS DONE', flush=True)


if __name__ == '__main__':
    main(sys.argv[1])
