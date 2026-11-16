"""Batch: read Ross's fills off every 2022 live-trading video (eSignal layout with a Positions window).

For each video in the list (built from the extraction files: TYPE Live Trading, upload year 2022, has a YouTube id):
  1. download 1080p video only (yt-dlp, current version, node JS runtime)
  2. layout check: OCR the top-left corner of 5 sample frames for the "Positions" title; skip if absent
  3. decode at 1 fps straight from the mp4 (no frames on disk), keep the Positions + clock crops of seconds where the
     Price / day-Realized columns changed (see ross_live_video_fills.py), OCR those
  4. write outputs/ross_imitation/screen_fills/<video_id>.csv (or <video_id>.skip with the reason), delete the mp4
Resumable: videos with a .csv or .skip are not redone.
Run with a Python that has yt-dlp, rapidocr-onnxruntime, opencv, pandas (not the repo venv):
  python -I ross_live_video_batch.py list          # build the video list (any python)
  python -I ross_live_video_batch.py run <dl_dir>  # process
"""
import glob
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.abspath(os.path.join(HERE, '..', 'outputs', 'ross_imitation', 'screen_fills'))
LIST = os.path.join(OUT, 'videos_2022_live.csv')
EXTR = r'C:\Repositories\Stock-Picker\Ross Cameron Day Trading Videos\extractions'


def build_list():
    os.makedirs(OUT, exist_ok=True)
    m = json.load(open(os.path.join(EXTR, 'file_video_id_map.json')))
    seen, rows = set(), []
    for f in sorted(glob.glob(os.path.join(EXTR, 'TRANSCRIPT_SUMMARIES_*.md'))):
        for blk in re.split(r'(?=FILE \d{4} \|)', open(f, encoding='utf-8').read()):
            h = re.match(r'FILE (\d{4}) \| TYPE: (.*)', blk)
            if not h or 'Live' not in h.group(2):
                continue
            v = m.get(h.group(1)) or {}
            vid, up = v.get('video_id'), str(v.get('upload_date') or '')
            if not vid or not up.startswith('2022') or vid in seen:
                continue
            seen.add(vid)
            rows.append((h.group(1), vid, up))
    with open(LIST, 'w') as fh:
        fh.write('file,video_id,upload_date\n')
        for r in rows:
            fh.write(','.join(r) + '\n')
    print(f'{len(rows)} videos -> {LIST}')


CLOCK_RE = re.compile(r'([0-2]\d):?([0-5]\d):?([0-5]\d)')


def find_clock(cap, ocr, n):
    """Find the on-screen clock: OCR the bottom and top strips of a few frames, look for HH:MM:SS (04-16 h)."""
    import cv2
    for q in (0.2, 0.5, 0.8):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(n * q))
        ok, im = cap.read()
        if not ok:
            continue
        if im.shape[:2] != (1080, 1920):
            im = cv2.resize(im, (1920, 1080))
        for y0, y1 in ((1030, 1080), (0, 50)):
            r, _ = ocr(cv2.resize(im[y0:y1], None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC), use_cls=False)
            for b, txt, _ in r or []:
                m = CLOCK_RE.search(txt.replace(' ', ''))
                if m and 4 <= int(m.group(1)) <= 16:
                    xs = [pt[0] / 2 for pt in b]; ys = [pt[1] / 2 + y0 for pt in b]
                    return (slice(max(0, int(min(ys)) - 4), min(1080, int(max(ys)) + 4)),
                            slice(max(0, int(min(xs)) - 10), min(1920, int(max(xs)) + 10)))
    return None


def read_clk(ocr, c):
    import cv2
    if c is None:
        return None
    r, _ = ocr(cv2.resize(c, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC), use_cls=False)
    for x in r or []:
        m = CLOCK_RE.search(x[1].replace(' ', ''))
        if m:
            return ':'.join(m.groups())
    return None


# A = Jan-Sep 2022 eSignal "Positions" (narrow); B = late-2022 "Positions 2" (Strategy, Symbol, Cost Basis,
# P&L per Share, Realized P&L), clock usually hidden by a banner -> times fitted from ticks later.
LAYOUTS = {
    'A': dict(crop=(slice(0, 235), slice(0, 285)), rows=(28, 215), cols=[(55, 115), (185, 285)]),
    'B': dict(crop=(slice(0, 205), slice(0, 530)), rows=(28, 180), cols=[(190, 290), (400, 530)]),
}


def detect_layout(ocr, im):
    import cv2
    r, _ = ocr(cv2.resize(im[0:30, 0:560], None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC), use_cls=False)
    toks = [(x[1].replace(' ', ''), x[0][0][0] / 2) for x in (r or [])]
    if not any('osition' in s and x < 120 for s, x in toks):
        return None
    if any('ositions2' in s for s, _ in toks) or any(x > 380 for _, x in toks):
        return 'B'
    return 'A'


def read_positions_b(ocr, crop):
    import cv2
    r, _ = ocr(cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC), use_cls=False)
    rows = {}
    for box, txt, _ in r or []:
        x, y = box[0][0] / 3, box[0][1] / 3
        if y < 28 or y > 178:
            continue
        col = 'status' if x < 80 else 'sym' if x < 180 else 'cost' if x < 300 else 'pps' if x < 380 else 'realized'
        rows.setdefault(int(round(y / 14.0)), {})[col] = txt
    out = {}
    for d in rows.values():
        s = d.get('sym', '')
        if re.fullmatch(r'[A-Z]{1,5}', s) and s != 'All':
            out[s] = (d.get('cost'), d.get('pps'), d.get('realized'))
    return out


def scan(path, ocr):
    import cv2
    import numpy as np
    from collections import Counter
    from ross_live_video_fills import PIX
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    secs = int(n / fps)
    want = {int(round(s * fps)) for s in range(secs)}
    votes = Counter()
    for q in (0.1, 0.3, 0.5, 0.7, 0.9):  # quick layout check by seeking, before the full decode
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(n * q))
        ok, im = cap.read()
        if ok:
            im = cv2.resize(im, (1920, 1080)) if im.shape[:2] != (1080, 1920) else im
            lay = detect_layout(ocr, im)
            if lay:
                votes[lay] += 1
    if not votes or votes.most_common(1)[0][1] < 2:
        cap.release()
        return secs, None, sum(votes.values()), [], None
    lay = votes.most_common(1)[0][0]
    L = LAYOUTS[lay]
    y0, y1 = L['rows']
    box = find_clock(cap, ocr, n)
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    prev, prev_small, kept, i, sec = None, None, [], 0, -1
    while True:
        if not cap.grab():
            break
        if i in want:
            sec += 1
            ok, im = cap.retrieve()
            if not ok:
                break
            if im.shape[:2] != (1080, 1920):
                im = cv2.resize(im, (1920, 1080))
            small = {'pos': im[L['crop']].copy(), 'clk': im[box].copy() if box else None}
            g = cv2.cvtColor(small['pos'], cv2.COLOR_BGR2GRAY)[y0:y1].astype(int)
            if prev is not None and max(int((np.abs(g[:, a:b] - prev[:, a:b]) > 40).sum()) for a, b in L['cols']) >= PIX:
                kept.append((sec, prev_small, small))
            prev, prev_small = g, small
        i += 1
    cap.release()
    return secs, lay, votes[lay], kept, box


def process(vid, dl, ocr):
    import pandas as pd
    from ross_live_video_fills import read_positions
    import numpy as np
    mp4 = os.path.join(dl, f'{vid}.mp4')
    if not os.path.exists(mp4):
        r = subprocess.run([sys.executable, '-m', 'yt_dlp', '--no-progress', '-q', '--js-runtimes', 'node',
                            '-f', 'bv*[height<=1080][ext=mp4]', '-o', mp4, f'https://www.youtube.com/watch?v={vid}'],
                           capture_output=True, text=True, timeout=1800)
        if not os.path.exists(mp4):
            return 'download failed: ' + (r.stderr or '')[-200:].replace('\n', ' ')
    try:
        secs, lay, hits, kept, box = scan(mp4, ocr)
        if lay is None:
            return f'no Positions window ({hits}/5 sample frames), {secs}s'

        def full(c):  # pad crops back into a 1080p canvas so the layout-A reader's coordinates hold
            im = np.zeros((1080, 1920, 3), np.uint8)
            im[0:235, 0:285] = c['pos']
            return im
        rd = (lambda c: read_positions(ocr, full(c))) if lay == 'A' else (lambda c: read_positions_b(ocr, c['pos']))
        ev = []
        for sec, a, b in kept:
            pa, pb = rd(a), rd(b)
            if pa != pb:
                ev.append(dict(video_sec=sec, clock_before=read_clk(ocr, a['clk']), clock_after=read_clk(ocr, b['clk']),
                               before=json.dumps(pa), after=json.dumps(pb), layout=lay))
        pd.DataFrame(ev, columns=['video_sec', 'clock_before', 'clock_after', 'before', 'after', 'layout']).to_csv(
            os.path.join(OUT, f'{vid}.csv'), index=False)
        print(f'  {vid}: layout {lay}, {secs}s, clock box {box and (box[0].start, box[1].start)}, changed {len(kept)}, events {len(ev)}', flush=True)
        return None
    finally:
        if os.path.exists(mp4):
            os.remove(mp4)


def net_ok():
    import socket
    try:
        socket.create_connection(('www.youtube.com', 443), timeout=10).close()
        return True
    except OSError:
        return False


def run(dl):
    sys.path.insert(0, HERE)
    sys.stdout.reconfigure(encoding='utf-8')
    from rapidocr_onnxruntime import RapidOCR
    ocr = RapidOCR()
    os.makedirs(dl, exist_ok=True)
    vids = [l.split(',') for l in open(LIST).read().split('\n')[1:] if l]
    for k, (f, vid, up) in enumerate(vids):
        if os.path.exists(os.path.join(OUT, f'{vid}.csv')) or os.path.exists(os.path.join(OUT, f'{vid}.skip')):
            continue
        t0 = time.time()
        print(f'[{k + 1}/{len(vids)}] {f} {vid} {up}', flush=True)
        tries = 0
        while True:
            try:
                err = process(vid, dl, ocr)
            except Exception as ex:  # noqa: BLE001
                err = f'error: {ex!r}'[:300]
            if not (err or '').startswith('download failed'):
                break
            if not net_ok():  # network down: wait, do not mark the video
                print('  network down, waiting', flush=True)
                time.sleep(60)
                continue
            tries += 1
            if tries >= 3:
                break
            time.sleep(30)
        if err:
            open(os.path.join(OUT, f'{vid}.skip'), 'w').write(err + '\n')
            print(f'  skip: {err}', flush=True)
        print(f'  {time.time() - t0:.0f}s', flush=True)
    print('BATCH DONE', flush=True)


if __name__ == '__main__':
    if sys.argv[1] == 'list':
        build_list()
    else:
        run(sys.argv[2])
