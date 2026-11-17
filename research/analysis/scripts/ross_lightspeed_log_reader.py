"""Read Ross's order log ("Executed or Cancelled Orders", Lightspeed, 2017-2019 recaps) off the video screen.

The window lists orders with Time (to the second), Symbol, Price, Quantity (filled / ordered) and Side. Rows stay
visible after the trade, so recaps recorded after the session still show the fills.
Method: download the video, find the window title by OCR on 12 sample frames (most common position wins), then every
2 s compare the log area with the last OCR'd one and OCR it when it changed. Rows are parsed and de-duplicated.
Output: outputs/ross_imitation/lightspeed_logs/<video_id>.csv (time, symbol, price, filled, ordered, side, first_seen_s)
or <video_id>.skip.
Run with the OCR venv python (yt-dlp, rapidocr-onnxruntime, opencv):
  python -I ross_lightspeed_log_reader.py <dl_dir> <video_id> [<video_id> ...]
"""
import csv
import os
import re
import subprocess
import sys
from collections import Counter

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.abspath(os.path.join(HERE, '..', 'outputs', 'ross_imitation', 'lightspeed_logs'))
TIME = re.compile(r'^([01]?\d):?([0-5]\d):?([0-5]\d)$')
QTY = re.compile(r'^(\d[\d,]*)\s*/\s*(\d[\d,]*)$')
SIDES = {'BOT', 'SLD', 'SS', 'SHRT', 'BUY', 'SELL', 'BTC', 'SL', 'B', 'S'}
W, H = 360, 140          # log body size below the title (1080p pixels)
STEP = 2                 # seconds between looks


def find_window(ocr, cap, n):
    pos = Counter()
    for q in np.linspace(0.05, 0.95, 12):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(n * q))
        ok, im = cap.read()
        if not ok:
            continue
        im = cv2.resize(im, (1920, 1080))
        r, _ = ocr(im, use_cls=False)
        for b, txt, _ in r or []:
            if 'xecuted' in txt or 'ancelled Orders' in txt:
                pos[(int(b[0][0]) // 20 * 20, int(b[0][1]) // 10 * 10)] += 1
    return pos.most_common(1)[0] if pos else (None, 0)


def parse(ocr, crop):
    r, _ = ocr(cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC), use_cls=False)
    rows = {}
    for b, txt, _ in r or []:
        rows.setdefault(int(round(b[0][1] / 3 / 14.0)), []).append((b[0][0] / 3, txt.strip()))
    out = []
    for toks in rows.values():
        toks.sort()
        d = {}
        for x, t in toks:
            t2 = t.replace(' ', '')
            if 'time' not in d and TIME.match(t2):
                d['time'] = ':'.join(f'{int(g):02d}' for g in TIME.match(t2).groups())
            elif 'qty' not in d and QTY.match(t2):
                d['qty'] = tuple(int(g.replace(',', '')) for g in QTY.match(t2).groups())
            elif t2.upper() in SIDES:
                d['side'] = t2.upper()
            elif 'sym' not in d and re.fullmatch(r'[A-Z]{1,5}', t2):
                d['sym'] = t2
            elif 'price' not in d and re.fullmatch(r'\d{1,4}\.\d{2,4}', t2):
                d['price'] = float(t2)
        if {'time', 'sym', 'price', 'qty'} <= d.keys():
            out.append((d['time'], d['sym'], d['price'], d['qty'][0], d['qty'][1], d.get('side', '')))
    return out


def process(ocr, vid, dl):
    mp4 = os.path.join(dl, f'{vid}.mp4')
    if not os.path.exists(mp4):
        subprocess.run([sys.executable, '-m', 'yt_dlp', '--no-progress', '-q', '--js-runtimes', 'node',
                        '-f', 'bv*[height<=1080][ext=mp4]', '-o', mp4, f'https://www.youtube.com/watch?v={vid}'],
                       capture_output=True, timeout=1800)
        if not os.path.exists(mp4):
            return 'download failed'
    try:
        cap = cv2.VideoCapture(mp4)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        (xy, hits) = find_window(ocr, cap, n)
        if not xy or hits < 2:
            cap.release()  # else Windows keeps the mp4 locked and the cleanup below raises PermissionError
            return f'no order log window ({hits}/12 frames)'
        x0, y0 = xy
        box = (slice(y0 + 12, min(1080, y0 + 12 + H)), slice(max(0, x0 - 10), min(1920, x0 - 10 + W)))
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        seen, prev, i, step = {}, None, 0, int(round(fps * STEP))
        while cap.grab():
            if i % step == 0:
                ok, im = cap.retrieve()
                if not ok:
                    break
                g = cv2.resize(im, (1920, 1080))[box]
                gg = cv2.cvtColor(g, cv2.COLOR_BGR2GRAY).astype(int)
                if prev is None or int((np.abs(gg - prev) > 40).sum()) >= 12:
                    for row in parse(ocr, g):
                        seen.setdefault(row, int(i / fps))
                prev = gg
            i += 1
        cap.release()
        rows = sorted(seen.items(), key=lambda kv: kv[0][0])
        with open(os.path.join(OUT, f'{vid}.csv'), 'w', newline='') as fh:
            w = csv.writer(fh)
            w.writerow(['time', 'symbol', 'price', 'filled', 'ordered', 'side', 'first_seen_s'])
            for (t, s, p, f, o, sd), fs in rows:
                w.writerow([t, s, p, f, o, sd, fs])
        print(f'  {vid}: window at {xy} ({hits}/12), rows {len(rows)}, filled {sum(1 for r, _ in rows if r[3] > 0)}',
              flush=True)
        return None
    finally:
        if os.path.exists(mp4):
            os.remove(mp4)


def main(dl, vids):
    from rapidocr_onnxruntime import RapidOCR
    sys.stdout.reconfigure(encoding='utf-8')
    ocr = RapidOCR()
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(dl, exist_ok=True)
    for vid in vids:
        if os.path.exists(os.path.join(OUT, f'{vid}.csv')) or os.path.exists(os.path.join(OUT, f'{vid}.skip')):
            continue
        print(vid, flush=True)
        err = process(ocr, vid, dl)
        if err:
            print('  skip:', err, flush=True)
            if err != 'download failed':
                open(os.path.join(OUT, f'{vid}.skip'), 'w').write(err + '\n')
    print('DONE', flush=True)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2:])
