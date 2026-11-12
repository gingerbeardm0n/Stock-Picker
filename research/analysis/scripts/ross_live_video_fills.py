"""Pilot: read Ross's fills off the screen of a live-trading video (2022 eSignal layout).

Input: a folder of 1-fps frames (ffmpeg -vf fps=1) from one video.
Method:
  1. Each second, compare the Positions window's Price and day-Realized columns with the previous second
     (pixel difference). Only changed seconds are OCR'd, which keeps it fast.
  2. OCR (rapidocr, local, free) the Positions window and the eSignal clock (bottom right, "HH:MM:SS GMT-5")
     on the changed second and the second before.
  3. A fill happened between those two clock readings. Entry = new symbol row or avg Price change;
     exit = day Realized change.
Needs a Python with rapidocr-onnxruntime and opencv (not the repo venv):
  python ross_live_video_fills.py <frames_dir> <out_csv>
Layout coordinates are for 1920x1080 frames of the Jan-Feb 2022 layout. Other layouts need new boxes.
"""
import os
import re
import sys

import cv2
import numpy as np
import pandas as pd

POS = (slice(28, 215), slice(0, 285))          # Positions rows (header excluded)
COLS = [(55, 115), (185, 285)]                  # Price, day Realized (x ranges inside POS)
CLOCK = (slice(1052, 1076), slice(1640, 1740))  # eSignal clock
PIX = 12                                        # changed pixels (|diff| > 40) that count as a change


def col_diff(a, b):
    return max(int((np.abs(a[:, x0:x1].astype(int) - b[:, x0:x1].astype(int)) > 40).sum()) for x0, x1 in COLS)


def read_clock(ocr, im):
    c = cv2.resize(im[CLOCK], None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    r, _ = ocr(c, use_cls=False)
    for x in r or []:
        m = re.search(r'(\d{2}):?(\d{2}):?(\d{2})', x[1].replace(' ', ''))
        if m:
            return ':'.join(m.groups())
    return None


def read_positions(ocr, im):
    p = cv2.resize(im[0:235, 0:285], None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    r, _ = ocr(p, use_cls=False)
    rows = {}
    for box, txt, _ in r or []:
        x, y = box[0][0] / 2, box[0][1] / 2
        if y < 28 or y > 212:
            continue
        key = int(round(y / 13.0))
        col = 'sym' if x < 50 else 'price' if x < 120 else 'pnl_ps' if x < 190 else 'realized'
        rows.setdefault(key, {})[col] = txt
    out = {}
    for d in rows.values():
        s = d.get('sym', '')
        if re.fullmatch(r'[A-Z]{1,5}', s):
            out[s] = (d.get('price'), d.get('pnl_ps'), d.get('realized'))
    return out


def main(frames, out_csv):
    from rapidocr_onnxruntime import RapidOCR
    sys.stdout.reconfigure(encoding='utf-8')
    ocr = RapidOCR()
    files = sorted(f for f in os.listdir(frames) if f.endswith('.jpg'))
    prev, changed = None, []
    for i, f in enumerate(files):
        g = cv2.cvtColor(cv2.imread(os.path.join(frames, f)), cv2.COLOR_BGR2GRAY)[POS]
        if prev is not None and col_diff(g, prev) >= PIX:
            changed.append(i)
        prev = g
    print(f'frames {len(files)} | changed seconds {len(changed)}', flush=True)
    ev = []
    for i in changed:
        a = cv2.imread(os.path.join(frames, files[i - 1]))
        b = cv2.imread(os.path.join(frames, files[i]))
        pa, pb = read_positions(ocr, a), read_positions(ocr, b)
        if pa == pb:
            continue
        ev.append(dict(video_sec=i, clock_before=read_clock(ocr, a), clock_after=read_clock(ocr, b),
                       before=pa, after=pb))
        print(ev[-1], flush=True)
    pd.DataFrame(ev).to_csv(out_csv, index=False)
    print('DONE', len(ev))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
