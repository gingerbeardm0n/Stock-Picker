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
        try:
            r = subprocess.run([sys.executable, '-m', 'yt_dlp', '--js-runtimes', 'node', '--no-progress', '-q',
                                '--no-warnings'] + args, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:  # internet dropped mid-request (crashed the queue 2026-11-19)
            log(f'  yt-dlp timed out after {timeout}s, waiting 5 min')
            time.sleep(300)
            continue
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
    ok, out = yt(['-f', 'bv*[height<=1080][ext=mp4]', '--print', 'after_move:UPLOAD %(upload_date)s', '-o', mp4,
                  f'https://www.youtube.com/watch?v={vid}'])
    # census-added videos have no reliable date in the list (channel listing dates are approximate): keep the real one
    m = re.search(r'UPLOAD (\d{8})', out or '')
    if m:
        with open(os.path.join(OUTD, 'screen_fills', 'upload_dates.csv'), 'a') as fh:
            fh.write(f'{vid},{m.group(1)}\n')
    return mp4 if os.path.exists(mp4) else None


MEDIA_PAD, MEDIA_FPS, WATCH_EVERY, MIN_FREE_GB = 20, 2, 10, 15


def media_extras(vid, mp4, work):
    """While the mp4 is on disk (live videos), keep what a re-download would otherwise be needed for:
    - clips/<a>_<b>.mp4: full-res clip at 2 fps from 20 s before to 20 s after every positions-window change
      (overlapping windows merged; a, b = video seconds) -> his L2, time & sales and chart around each fill
    - watch_10s.mp4: whole screen every 10 s (scanner / watchlist / which chart he is on)
    Stored outside the repo in <work>/../media/<vid>/. Skipped when the disk has < MIN_FREE_GB free."""
    import shutil
    if shutil.disk_usage(work).free / 1e9 < MIN_FREE_GB:
        log(f'  media extras skipped: < {MIN_FREE_GB} GB free')
        return
    out = os.path.join(os.path.dirname(work), 'media', vid)
    os.makedirs(os.path.join(out, 'clips'), exist_ok=True)
    enc = ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '26', '-pix_fmt', 'yuv420p', '-an', '-y']
    fills = os.path.join(OUTD, 'screen_fills', f'{vid}.csv')
    wins = []
    if os.path.exists(fills):
        for r in csv.DictReader(open(fills)):
            s = int(float(r['video_sec']))
            a, b = max(0, s - MEDIA_PAD), s + MEDIA_PAD
            if wins and a <= wins[-1][1]:
                wins[-1][1] = max(wins[-1][1], b)
            else:
                wins.append([a, b])
    for a, b in wins:
        subprocess.run(['ffmpeg', '-v', 'error', '-ss', str(a), '-i', mp4, '-t', str(b - a), '-vf', f'fps={MEDIA_FPS}']
                       + enc + [os.path.join(out, 'clips', f'{a}_{b}.mp4')], capture_output=True, timeout=600)
    subprocess.run(['ffmpeg', '-v', 'error', '-i', mp4, '-vf', f'fps=1/{WATCH_EVERY}'] + enc
                   + [os.path.join(out, 'watch_10s.mp4')], capture_output=True, timeout=7200)
    mb = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(out) for f in fs) / 1e6
    log(f'  media extras: {len(wins)} clips + watchlist time-lapse, {mb:.0f} MB')


def captions(vid, work):
    """Timed auto-captions (what he says, with timestamps). One small extra request, throttled like the rest."""
    out = os.path.join(os.path.dirname(work), 'media', vid)
    os.makedirs(out, exist_ok=True)
    ok, _ = yt(['--skip-download', '--write-auto-subs', '--write-subs', '--sub-langs', 'en.*,en', '--sub-format', 'vtt',
                '-o', os.path.join(out, 'captions'), f'https://www.youtube.com/watch?v={vid}'], timeout=300)
    got = glob.glob(os.path.join(out, 'captions*.vtt'))
    log(f'  captions: {"saved" if got else "none"}')


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
        # A video the watchdog killed mid-run gets retried forever (YuNvqwJftVY, 1.2 GB, looped Nov 21-23):
        # count attempts and skip after 2.
        att = os.path.join(work, 'attempts', f'{vid}.n')
        os.makedirs(os.path.dirname(att), exist_ok=True)
        n = int(open(att).read() or 0) if os.path.exists(att) else 0
        if n >= 2:
            log(kind, vid, f'- skipped, {n} earlier attempts never finished')
            open(os.path.join(d, f'{vid}.skip'), 'w').write(f'never finished in {n} attempts (killed by watchdog)\n')
            continue
        open(att, 'w').write(str(n + 1))
        log(kind, vid)
        mp4 = download(vid, dl)
        if not mp4:
            log('  download failed (not a block), skipping for now')
            continue
        log(f'  downloaded {os.path.getsize(mp4) / 1e6:.0f} MB, processing')
        try:
            err = LB.process(vid, dl, ocr, keep=True) if kind == 'live' else LS.process(ocr, vid, dl)
            if kind == 'live' and not err:
                media_extras(vid, mp4, work)
                captions(vid, work)
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
                g = subprocess.run(['ffmpeg', '-v', 'error', '-ss', str(sec), '-i', url, '-frames:v', '1', '-y', path],
                                   capture_output=True, text=True, timeout=300)
                im = cv2.imread(path) if os.path.exists(path) else None
                if im is None:
                    # raw stream URL refused (seen on ~60% of videos 2026-11-18): let yt-dlp fetch a 2 s clip instead,
                    # it sends the headers the URL wants
                    log('  ffmpeg grab failed:', (g.stderr or '').strip()[-160:])
                    clip = os.path.join(fdir, f"{r['video_id']}_{sec}.mp4")
                    yt(['-f', 'bv*[height<=1080][ext=mp4]/bv*[height<=1080]', '--download-sections', f'*{sec}-{sec + 2}',
                        '-o', clip, f"https://www.youtube.com/watch?v={r['video_id']}"], timeout=300)
                    if os.path.exists(clip):
                        c = cv2.VideoCapture(clip)
                        ok, im = c.read()
                        c.release()
                        os.remove(clip)
                        im = im if ok else None
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
