"""Probe: do Ross's daily recap videos show execution lists with second-level times (e.g. Tradervue)?

For each sample video: download (1080p, video only), decode one frame every 10 s, OCR the full frame, and flag frames
with >= 3 HH:MM:SS times (an execution table) or the words Tradervue / Executions. Flagged frames are saved as jpg
for a human/LLM look; the mp4 is deleted. No transcript reading.
Run with the OCR venv python (yt-dlp, rapidocr-onnxruntime, opencv):
  python -I ross_recap_tradervue_probe.py <out_dir> <video_id> [<video_id> ...]
"""
import json
import os
import re
import subprocess
import sys

import cv2

TIME = re.compile(r'\b([01]?\d|2[0-3]):[0-5]\d:[0-5]\d\b')
WORDS = re.compile(r'tradervue|execution', re.I)


def main(out, vids):
    from rapidocr_onnxruntime import RapidOCR
    sys.stdout.reconfigure(encoding='utf-8')
    ocr = RapidOCR()
    os.makedirs(out, exist_ok=True)
    summary = []
    for vid in vids:
        mp4 = os.path.join(out, f'{vid}.mp4')
        subprocess.run([sys.executable, '-m', 'yt_dlp', '--no-progress', '-q', '--js-runtimes', 'node',
                        '-f', 'bv*[height<=1080][ext=mp4]', '-o', mp4, f'https://www.youtube.com/watch?v={vid}'],
                       capture_output=True, timeout=1800)
        if not os.path.exists(mp4):
            summary.append(dict(video_id=vid, error='download failed')); print(summary[-1], flush=True); continue
        cap = cv2.VideoCapture(mp4)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        flagged, words_hit, best = 0, 0, []
        for f in range(0, n, int(fps * 10)):
            cap.set(cv2.CAP_PROP_POS_FRAMES, f)
            ok, im = cap.read()
            if not ok:
                break
            r, _ = ocr(cv2.resize(im, (1920, 1080)), use_cls=False)
            txt = ' '.join(x[1] for x in (r or []))
            nt, w = len(TIME.findall(txt)), bool(WORDS.search(txt))
            if nt >= 3 or w:
                flagged += 1
                words_hit += w
                best.append((nt + 5 * w, int(f / fps)))
                cv2.imwrite(os.path.join(out, f'{vid}_{int(f / fps):05d}_t{nt}{"_w" if w else ""}.jpg'), im)
        cap.release()
        os.remove(mp4)
        best.sort(reverse=True)
        summary.append(dict(video_id=vid, dur_s=int(n / fps), frames=int(n / fps / 10), flagged=flagged,
                            with_words=words_hit, top=best[:3]))
        print(summary[-1], flush=True)
    json.dump(summary, open(os.path.join(out, 'summary.json'), 'w'), indent=1)
    print('DONE', flush=True)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2:])
