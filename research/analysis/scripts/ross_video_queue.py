"""One polite queue for all Ross video work, so YouTube does not block us again (it did on 2026-11-16).

Rules: one YouTube request at a time, at least GAP seconds between requests; on a bot check ("not a bot") wait
BACKOFF seconds and retry the same item. Work order:
  1. Lightspeed order-log test video (2018-07-02 recap)
  2. remaining 2022 live videos (ross_live_video_batch.process)
  3. 2017-2019 daily recaps (ross_lightspeed_log_reader.process)
  4. remaining rows of the missing-live-video layout census (one frame grab each)
Resumable: every step writes its own output (.csv / .skip / census row) and finished items are skipped.
Run with the OCR venv python:
  python -I ross_video_queue.py <work_dir>
"""
import csv
import glob
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
OUTD = os.path.abspath(os.path.join(HERE, '..', 'outputs', 'ross_imitation'))
EXTR = r'C:\Repositories\Stock-Picker\Ross Cameron Day Trading Videos\extractions'
GAP, BACKOFF = 90, 3600
_last = [0.0]


def log(*a):
    print(time.strftime('%m-%d %H:%M:%S'), *a, flush=True)


def yt(args, timeout=1800):
    """Run yt-dlp politely. Returns (ok, stdout). Blocks (sleeps) through bot checks."""
    while True:
        wait = _last[0] + GAP - time.time()
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        r = subprocess.run([sys.executable, '-m', 'yt_dlp', '--js-runtimes', 'node', '--no-progress', '-q',
                            '--no-warnings'] + args, capture_output=True, text=True, timeout=timeout)
        err = (r.stderr or '') + (r.stdout or '')
        if 'not a bot' in err or 'HTTP Error 429' in err:
            log(f'  YouTube bot check, backing off {BACKOFF // 60} min')
            time.sleep(BACKOFF)
            continue
        if 'getaddrinfo' in err or 'timed out' in err.lower():
            log('  network down, waiting 5 min')
            time.sleep(300)
            continue
        return r.returncode == 0, r.stdout


def download(vid, dl):
    mp4 = os.path.join(dl, f'{vid}.mp4')
    if os.path.exists(mp4):
        return mp4
    ok, _ = yt(['-f', 'bv*[height<=1080][ext=mp4]', '-o', mp4, f'https://www.youtube.com/watch?v={vid}'])
    return mp4 if os.path.exists(mp4) else None


def lightspeed_list():
    m = json.load(open(os.path.join(EXTR, 'file_video_id_map.json')))
    typ = {}
    for f in glob.glob(os.path.join(EXTR, 'TRANSCRIPT_SUMMARIES_*.md')):
        for h in re.finditer(r'FILE (\d{4}) \| TYPE: ([^\n]*)', open(f, encoding='utf-8').read()):
            typ[h.group(1)] = h.group(2)
    rows = [(str(v['upload_date']), v['video_id']) for k, v in m.items()
            if v and v.get('video_id') and str(v.get('upload_date', ''))[:4] in ('2017', '2018', '2019')
            and 'Recap' in typ.get(k, '')]
    return [vid for _, vid in sorted(set(rows))]


def main(work):
    from rapidocr_onnxruntime import RapidOCR
    import ross_live_video_batch as LB
    import ross_lightspeed_log_reader as LS
    import ross_live_layout_census as CE
    import cv2
    sys.stdout.reconfigure(encoding='utf-8')
    ocr = RapidOCR()
    dl = os.path.join(work, 'dl')
    os.makedirs(dl, exist_ok=True)
    os.makedirs(LS.OUT, exist_ok=True)

    def done(d, vid):
        return os.path.exists(os.path.join(d, f'{vid}.csv')) or os.path.exists(os.path.join(d, f'{vid}.skip'))

    # 1 + 3: Lightspeed recaps (test video first)
    ls = ['YFgjhbaE5f8'] + [v for v in lightspeed_list() if v != 'YFgjhbaE5f8']
    # 2: 2022 live videos
    live = [l.split(',')[1] for l in open(LB.LIST).read().split('\n')[1:] if l]
    jobs = [('ls', ls[0])] + [('live', v) for v in live] + [('ls', v) for v in ls[1:]]
    log(f'queue: {len(live)} live, {len(ls)} lightspeed')
    for kind, vid in jobs:
        d = LB.OUT if kind == 'live' else LS.OUT
        if done(d, vid):
            continue
        log(kind, vid)
        mp4 = download(vid, dl)
        if not mp4:
            log('  download failed (not a block), skipping for now')
            continue
        try:
            err = LB.process(vid, dl, ocr) if kind == 'live' else LS.process(ocr, vid, dl)
        except Exception as ex:  # noqa: BLE001
            err = f'error: {ex!r}'[:300]
        if err:
            log('  skip:', err)
            open(os.path.join(d, f'{vid}.skip'), 'w').write(err + '\n')
        for f in glob.glob(os.path.join(dl, '*')):
            os.remove(f)

    # 4: census
    doneids = {r['video_id'] for r in csv.DictReader(open(CE.OUT, encoding='utf-8'))} if os.path.exists(CE.OUT) else set()
    rows = [r for r in csv.DictReader(open(CE.SRC, encoding='utf-8', errors='replace'), delimiter='\t')
            if r.get('in_collection') == 'no' and r['video_id'] not in doneids]
    fdir = os.path.join(work, 'census_frames')
    os.makedirs(fdir, exist_ok=True)
    fh = open(CE.OUT, 'a', newline='', encoding='utf-8')
    w = csv.DictWriter(fh, CE.COLS)
    log(f'census: {len(rows)} left')
    for r in rows:
        try:
            dur = float(r.get('duration_s') or 0)
        except ValueError:
            dur = 0
        ok, out = yt(['-f', 'bv*[height<=1080][ext=mp4]/bv*[height<=1080]', '-g',
                      f"https://www.youtube.com/watch?v={r['video_id']}"], timeout=180)
        url = (out.strip().splitlines() or [''])[-1]
        res = dict(video_id=r['video_id'], upload_date=r.get('upload_date'), duration_s=int(dur), tab=r.get('tab'),
                   title=(r.get('title') or '')[:120], layout='no url')
        if url.startswith('http'):
            for q in (0.4, 0.7):
                sec = int(dur * q) if dur > 60 else 30
                path = os.path.join(fdir, f"{r['video_id']}_{sec}.jpg")
                subprocess.run(['ffmpeg', '-v', 'error', '-ss', str(sec), '-i', url, '-frames:v', '1', '-y', path],
                               capture_output=True, timeout=300)
                im = cv2.imread(path) if os.path.exists(path) else None
                if im is None:
                    res['layout'] = 'grab failed'
                    continue
                lay, pos, clk = CE.classify(ocr, im)
                cv2.imwrite(path, cv2.resize(im, (960, 540)), [cv2.IMWRITE_JPEG_QUALITY, 70])
                res.update(layout=lay, pos_xy=pos, clock_xy=clk and clk[:2], clock=clk and clk[2], frame_s=sec)
                if lay != 'other':
                    break
        if res['layout'] in ('grab failed', 'no url'):
            log('  census', r['video_id'], res['layout'], '(not saved, will retry next run)')
            continue
        w.writerow(res)
        fh.flush()
        log('  census', r['video_id'], res['layout'])
    log('QUEUE DONE')


if __name__ == '__main__':
    main(sys.argv[1])
