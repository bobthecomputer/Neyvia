"""LAYA video adapter on the shared Scene core (plan 28).

brief (CL spec) -> edit decision list (edl.json) -> HyperFrames composition -> headless
render -> transcribe the rendered file -> shared judge -> named EDL fixes -> keep only
strict improvements (scene_core.improve) -> episodes.

Every fact is measured from the rendered MP4 (decoded frames and PCM), the composition's
own DOM (caption boxes, fonts) read in the admitted headless Obscura engine, local OCR of
keyframes, local Whisper speech-to-text and the LAYA screenshot glance of each source
capture. The EDL supplies only stable node ids and declared intent (planned cut times,
designed holds); a predicate never fires on the plan alone.

One video stack (reconciled 7 Oct from track/video and track/laya-video): this module is the
only ``video`` adapter and judge. ``video_hyperframes`` (free-form EDL editing behind the
``neyvia.video.*`` tools), ``laya_video_edit`` (pre-render ``video-edit`` checks) and
``video_contracts`` (fast outcome contracts) were written on track/laya-video and now render
with this module's toolchain and judge with this module's vocabulary. Whisper word timings
(start and end per word) follow track/laya-video's speech reader.
"""
from __future__ import annotations

import copy
import glob
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time

import numpy as np

from . import laya_video_audio as audio

ROOT = Path(__file__).resolve().parents[2]
MANUAL = ROOT / 'manuals/cl/laya-video.cl'
DESIGN_W, DESIGN_H = 1920, 1080
TOOLS_DIR = Path(os.environ.get('NEYVIA_VIDEO_TOOLS', 'D:/NeyviaRuns/video/track-video'))
CACHE = Path(os.environ.get('NEYVIA_VIDEO_CACHE', str(TOOLS_DIR / 'cache')))
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
PREVIEW = {'scale': 1 / 3, 'fps': 12, 'quality': 'draft'}
MASTER = {'scale': 1.0, 'fps': int(os.environ.get('NEYVIA_VIDEO_MASTER_FPS', '60')), 'quality': 'standard'}
_LOCK = threading.Lock()
FROZEN_DIFF = 0.15  # mean |frame - run anchor| on 160x90 grey thumbnails, of 255
ANALYSIS_VERSION = 'video-facts-17'
SCREEN_KINDS = ('capture', 'layout')  # shots that put product imagery on screen
STOCK = ('seamless', 'unlock', 'ai-powered', 'streamline', 'supercharge', 'revolution', 'game-changer', 'game changer',
         'effortless', 'next-level', 'next level', 'cutting-edge', 'cutting edge', 'introducing', 'leverage')  # track/laya-video's list


# --------------------------------------------------------------------------- tools

def _first(*candidates):
    for c in candidates:
        if c and Path(c).is_file():
            return str(Path(c))
    return None


def tools():
    """Resolve the headless toolchain. All paths are overridable; nothing is downloaded."""
    shells = sorted(glob.glob(str(Path.home() / '.cache/puppeteer/chrome-headless-shell/*/chrome-headless-shell-win64/chrome-headless-shell.exe')))
    ffmpeg = _first(os.environ.get('NEYVIA_FFMPEG'), shutil.which('ffmpeg'),
                    'C:/Users/user/Documents/Codex/2026-08-10/openai-has-opened-multiple-positions-to/work/ffmpeg-portable/ffmpeg-8.1.1-essentials_build/bin/ffmpeg.exe')
    cli = _first(os.environ.get('NEYVIA_HYPERFRAMES_CLI'), TOOLS_DIR / 'hf-cli/node_modules/hyperframes/bin/hyperframes.mjs')
    gsap = _first(os.environ.get('NEYVIA_GSAP'), TOOLS_DIR / 'hf-cli/node_modules/gsap/dist/gsap.min.js',
                  ROOT / 'node_modules/gsap/dist/gsap.min.js')
    font = _first(os.environ.get('NEYVIA_VIDEO_FONT'), ROOT / 'node_modules/@fontsource-variable/inter/files/inter-latin-wght-normal.woff2')
    return {'ffmpeg': ffmpeg, 'ffprobe': ffmpeg and str(Path(ffmpeg).with_name('ffprobe' + Path(ffmpeg).suffix)),
            'hyperframes': cli, 'gsap': gsap, 'font': font,
            'headless': _first(os.environ.get('NEYVIA_HEADLESS_SHELL'), *(reversed(shells)))}


def _run(args, *, cwd=None, env=None, timeout=1800, binary=False):
    proc = subprocess.run(args, cwd=cwd, env=env, capture_output=True, timeout=timeout, creationflags=NO_WINDOW)
    if proc.returncode != 0:
        tail = (proc.stderr or b'')[-1500:].decode('utf-8', 'replace')
        raise RuntimeError(f'{Path(args[0]).name} failed ({proc.returncode}): {tail}')
    return proc.stdout if binary else proc.stdout.decode('utf-8', 'replace')


def sha_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


# --------------------------------------------------------------------------- brief

def read_brief(path):
    """A brief is a CL file: `S key <json>` spec lines and `C` must-hold checks on the scene."""
    text = Path(path).read_text(encoding='utf-8')
    spec, checks, name = {}, [], Path(path).stem
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith('L '):
            name = line[2:].split(' -- ')[0].split()[0]
        elif line.startswith('S '):
            key, _, body = line[2:].partition(' ')
            body = body.split(' -- ')[0].strip() if not body.strip().startswith(('{', '[', '"')) else body.strip()
            if body.startswith(('{', '[', '"')):
                # A JSON value may be followed by ' -- gloss'.
                decoder = json.JSONDecoder()
                value, _ = decoder.raw_decode(body)
            else:
                value = body
            spec[key] = value
        elif line.startswith('C '):
            checks.append(line)
    spec.setdefault('length', {'min': 30, 'max': 60, 'target': 40})
    spec.setdefault('aspect', {'width': 1920, 'height': 1080})
    spec.setdefault('music', {'bpm': 120, 'sync': True, 'lufs': -14})
    spec.setdefault('captions', {'maxWords': 6, 'safe': 0.9, 'minHeightFrac': 0.035, 'minContrast': 4.5})
    spec.setdefault('pacing', {'medianShotS': [1.5, 4.0]})
    spec.setdefault('brand', {'stage': '#0d1612', 'ink': '#e9eef0', 'accent': '#46b077', 'font': 'Inter'})
    return {'name': name, 'path': str(Path(path).resolve()), 'spec': spec, 'checks': checks,
            'sha256': hashlib.sha256(text.encode()).hexdigest()}


def brief_from(value, meta=None):
    """A brief from a CL path, a small dict (track/laya-video's contract briefs: duration, width/height or
    aspect "16:9", freezeMinS, safeArea, allowBlackHeadTail, maxCaptionWords, lufs) or nothing (a file
    judged on its own: no length, pacing, sync, brand or must-include expectations)."""
    if isinstance(value, (str, Path)) and str(value).strip():
        return read_brief(value)
    value = dict(value or {})
    fps = (meta or {}).get('fps') or 30
    spec = {'sources': [], 'story': [], 'must': [],
            'length': {'min': 0.0, 'max': 1e9}, 'pacing': {'medianShotS': [0.0, 1e9]},
            'music': {'bpm': 120, 'sync': False, 'tailS': 0.0, 'expectSound': bool(value.get('expectSound', False))},
            'captions': {'maxWords': int(value.get('maxCaptionWords', 99)), 'safe': round(1 - 2 * float(value.get('safeArea', 0.05)), 4),
                         'minHeightFrac': 0.0, 'minContrast': 4.5},
            'brand': {'stage': '#0d1612', 'ink': '#e9eef0', 'accent': '#46b077', 'font': 'Inter'},
            'freezeMinS': float(value.get('freezeMinS', 1.5)), 'allowBlackHeadTailS': float(value.get('allowBlackHeadTail', 0.0)),
            'brandChecks': False}
    if value.get('duration'):
        d = float(value['duration'])
        spec['length'] = {'min': d - 1.0 / fps, 'max': d + 1.0 / fps, 'target': d}
    if value.get('aspect') and ':' in str(value['aspect']):
        a, b = (int(v) for v in str(value['aspect']).split(':'))
        spec['aspect'] = {'width': a * 120, 'height': b * 120}
    else:
        spec['aspect'] = {'width': int(value.get('width', (meta or {}).get('width', 1920))),
                          'height': int(value.get('height', (meta or {}).get('height', 1080)))}
    if value.get('lufs') is not None:
        spec['music']['lufs'] = float(value['lufs'])
    return {'name': value.get('name', 'file'), 'path': None, 'spec': spec, 'checks': [],
            'sha256': hashlib.sha256(_canonical(value).encode()).hexdigest()}


# --------------------------------------------------------------------------- capture library

_INDEX = {}


def library_for(brief):
    """The brief's capture library, indexed once per process."""
    key = _canonical(brief['spec']['sources'])
    if key not in _INDEX:
        _INDEX[key] = capture_index(brief['spec']['sources'])
    return _INDEX[key]


def capture_index(sources):
    """Real app captures. A source is a glob string or {glob, surface}; the tour names files
    <surface>-<variant>.png, other folders declare their surface."""
    rows, seen = [], set()
    known = ('bubble-peek-isolated-phone', 'bubble-peek-isolated', 'bubble-peek-phone', 'bubble-peek', 'side-floating',
             'side-left', 'side-phone', 'bubble-phone', 'full-phone', 'main-phone', 'bubble', 'full', 'main', 'side', 'dragging')
    for source in sources:
        pattern, surface_override = (source, None) if isinstance(source, str) else (source['glob'], source.get('surface'))
        crop = None if isinstance(source, str) else source.get('crop')
        for p in sorted(glob.glob(pattern)):
            p = str(Path(p).resolve())
            if crop:
                p = derive_crop(p, crop)
            if p in seen:
                continue
            seen.add(p)
            stem = Path(p).stem
            if surface_override:
                surface, variant = surface_override, Path(p).parent.name + '/' + stem
            else:
                variant = next((v for v in known if stem.endswith('-' + v)), '')
                surface = stem[:-(len(variant) + 1)] if variant else stem
            rows.append({'path': p, 'surface': surface, 'variant': variant, 'sha256': sha_file(p)})
    return rows


def derive_crop(path, crop):
    """Crop a source to its objects with the PhotoCraft engine (headless CLI), cached by content.
    Falls back to Pillow only when PhotoCraft is not built; the sidecar JSON says which ran."""
    digest = hashlib.sha256((sha_file(path) + _canonical(crop)).encode()).hexdigest()[:20]
    out = CACHE / 'derived' / f'{Path(path).stem}-crop-{digest}.png'
    if out.is_file():
        return str(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    cli = os.environ.get('NEYVIA_PHOTOCRAFT_CLI') or str(TOOLS_DIR / 'target/photocraft/release/photocraft-cli.exe')
    rect = {k: int(crop[k]) for k in ('x', 'y', 'width', 'height')}
    if Path(cli).is_file():
        _run([cli, 'run', str(path), '--cmd', 'image.crop', '--params', json.dumps(rect), '--out', str(out)])
        engine = 'photocraft-cli image.crop'
    else:
        from PIL import Image
        with Image.open(path) as im:
            im.crop((rect['x'], rect['y'], rect['x'] + rect['width'], rect['y'] + rect['height'])).save(out)
        engine = 'pillow'
    out.with_suffix('.json').write_text(json.dumps({'source': str(path), 'crop': rect, 'engine': engine}), encoding='utf-8')
    return str(out)


def _ui_text_patterns():
    """The UI vocabulary's own text regexes (raw-error, encoded-path, internal-id) from laya-glance.cl."""
    found = {}

    def walk(node, kind):
        if isinstance(node, dict):
            if node.get('field') == 'text' and node.get('op') == 'matches':
                found.setdefault(kind, []).append(node['value'])
            for v in node.values():
                walk(v, kind)
        elif isinstance(node, list):
            for v in node:
                walk(v, kind)
    for line in (ROOT / 'manuals/cl/laya-glance.cl').read_text(encoding='utf-8').splitlines():
        if line.startswith('-- @bug '):
            row = json.loads(line[8:])
            if row['type'] in ('raw-error', 'encoded-path', 'internal-id'):
                walk(row['predicate'], row['type'])
    return found


ERROR_STATE = r"\b(?:is not running|failed to|unavailable|could not|cannot|can't|not found)\b"
EMPTY_STATE = (r"\bno \w+(?: \w+)? (?:yet|here|recorded)\b|\bnothing (?:here|yet|to show)\b|\bget started\b|\bis empty\b|"
               r"\bwhen an agent uses\b|\bhas been recorded yet\b|\bstart (?:a|your) first\b")
DEBUG_LABEL = r"[a-z]{2,}(?:[-\u2010-\u2015\u2022\u00b7\ufffd][a-z]{2,})+"  # any dash or dot OCR returns


def _audit_lines(png, scale=2):
    """Windows OCR on the capture upscaled 2x (small UI text), word boxes mapped back to source pixels."""
    from PIL import Image
    from .laya_glance_image import _recognize
    with Image.open(png) as im:
        rgba = im.convert('RGBA')
    big = rgba.resize((rgba.width * scale, rgba.height * scale), Image.LANCZOS)
    return rgba, [(text, [(w[0], w[1] / scale, w[2] / scale, w[3] / scale, w[4] / scale) for w in words])
                  for text, words in _recognize(big)]


def _unread_runs(gray, lines):
    """Text-like ink that continues a recognised line but that OCR did not read (paths, ids, code).

    Scans outward from a line's first and last recognised word along the line's band: ink columns
    joined by gaps under 1.2 line heights, with text-like texture (many ink/background transitions)."""
    runs = []
    H, W = gray.shape
    covered = np.zeros(gray.shape, dtype=bool)  # ink OCR did read, on any line, is not unread text
    for _, words in lines:
        for _, x, y, w, h in words:
            covered[int(max(0, y - 2)):int(min(H, y + h + 2)), int(max(0, x - 2)):int(min(W, x + w + 2))] = True
    for text, words in lines:
        if not any(len(t) >= 4 and t.isalpha() for t in text.split()):
            continue  # a stray OCR fragment is not a line of copy
        y0 = int(max(0, min(w[2] for w in words)))
        y1 = int(min(H, max(w[2] + w[4] for w in words)))
        h = max(y1 - y0, 4)
        band = gray[y0:y1]
        if band.size == 0:
            continue
        ink = (np.abs(band - np.median(band)) > 35) & ~covered[y0:y1]
        cols = ink.any(axis=0)
        x_left = int(min(w[1] for w in words))
        x_right = int(max(w[1] + w[3] for w in words))
        # Inside the line: a wide gap between two read words that holds text-like ink
        # (a path between an icon and a button label, for instance).
        ordered = sorted(words, key=lambda w: w[1])
        for a, b in zip(ordered, ordered[1:]):
            lo, hi = int(a[1] + a[3]) + 2, int(b[1]) - 2
            if hi - lo < max(6 * h, 120):
                continue
            seg = ink[:, lo:hi + 1]
            if not seg.any():
                continue
            filled = np.flatnonzero(seg.any(axis=0))
            width = int(filled[-1] - filled[0]) if len(filled) else 0
            transitions = np.abs(np.diff(seg.astype(int), axis=1)).sum() / max(seg.shape[0], 1)
            if width >= max(6 * h, 120) and transitions / max(width, 1) >= 0.12:
                runs.append({'line': text[:80], 'side': 'inside', 'widthPx': width, 'lineHeightPx': int(h)})
        for side, start, step in (('right', x_right + 1, 1), ('left', x_left - 1, -1)):
            x, last, end = start, start, start
            while 0 <= x < W and abs(x - last) <= 1.2 * h:
                if cols[x]:
                    last = end = x
                x += step
            lo, hi = sorted((start, end))
            width = hi - lo
            if width < max(6 * h, 120):  # paths and ids run long; icons and badges do not
                continue
            seg = ink[:, lo:hi + 1]
            transitions = np.abs(np.diff(seg.astype(int), axis=1)).sum() / max(seg.shape[0], 1)
            if transitions / max(width, 1) >= 0.12:
                runs.append({'line': text[:80], 'side': side, 'widthPx': int(width), 'lineHeightPx': int(h)})
    return runs


def unread_path_blocks(gray, lines):
    """Free-standing text OCR never read at all (a path in an input, a footer path): a line-shaped
    ink block 6-22 px tall and >= 100 px wide, untouched by any OCR word, with text-like texture
    and almost no word spaces (< 1.2 spaces per 100 px; sentences measure about 2)."""
    from scipy import ndimage
    H, W = gray.shape
    covered = np.zeros(gray.shape, dtype=bool)
    for _, words in lines:
        for _, x, y, w, h in words:
            covered[int(max(0, y - 3)):int(min(H, y + h + 3)), int(max(0, x - 3)):int(min(W, x + w + 3))] = True
    ink = np.abs(gray - ndimage.uniform_filter(gray, 25)) > 30
    labels, _ = ndimage.label(ndimage.binary_dilation(ink, structure=np.ones((1, 7))))
    blocks = []
    for sl in ndimage.find_objects(labels):
        hh, ww = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
        if not (6 <= hh <= 22 and ww >= 100) or covered[sl].mean() >= 0.1:
            continue
        cols = ink[sl].any(axis=0)
        fill = ink[sl].mean()
        texture = np.abs(np.diff(cols.astype(int))).sum() / ww
        gaps, run = 0, 0
        for c in cols:
            if not c:
                run += 1
            else:
                gaps += run >= max(3, 0.35 * hh)
                run = 0
        if 0.08 <= fill <= 0.55 and texture > 0.12 and gaps * 100 / ww < 1.2:
            blocks.append({'x': int(sl[1].start), 'y': int(sl[0].start), 'widthPx': int(ww), 'heightPx': int(hh),
                           'spacesPer100px': round(gaps * 100 / ww, 2)})
    return blocks


def largest_flat_rect(gray, b=24):
    """Fraction of the frame covered by the largest axis-aligned rectangle of flat 24px blocks:
    an undrawn page, an empty viewport or an empty terminal leave one big flat rectangle."""
    h, w = gray.shape
    flat = gray[:h // b * b, :w // b * b].reshape(h // b, b, w // b, b).std(axis=(1, 3)) < 2.0
    rows, cols = flat.shape
    best, heights = 0, np.zeros(cols, int)
    for r in range(rows):
        heights = np.where(flat[r], heights + 1, 0)
        stack = []
        for c in range(cols + 1):
            height = heights[c] if c < cols else 0
            start = c
            while stack and stack[-1][1] >= height:
                s0, h0 = stack.pop()
                best = max(best, h0 * (c - s0))
                start = s0
            stack.append((start, height))
    return round(best / max(rows * cols, 1), 4)


def source_audit(path):
    """Observed facts about a source capture beyond the UI glance: unread text runs, error and
    empty-state copy, debug labels and how much of the screen is blank. Cached by content."""
    digest = sha_file(path)
    cache = CACHE / 'audit' / (ANALYSIS_VERSION + '-' + digest + '.json')
    if cache.is_file():
        return json.loads(cache.read_text(encoding='utf-8'))
    rgba, lines = _audit_lines(path)
    gray = np.asarray(rgba.convert('L'), dtype=float)
    texts = [t for t, _ in lines]
    patterns = _ui_text_patterns()
    error = [t for t in texts if any(re.search(rx, t, re.I) for kind in ('raw-error', 'encoded-path') for rx in patterns.get(kind, []))
             or re.search(ERROR_STATE, t, re.I)]
    internal = [t for t in texts if any(re.search(rx, t, re.I) for rx in patterns.get('internal-id', []))]
    b = 32
    h, w = gray.shape
    blocks = gray[:h // b * b, :w // b * b].reshape(h // b, b, w // b, b)
    row = {'text': ' | '.join(texts)[:4000], 'errorCopy': error[:10], 'internalIds': internal[:10],
           'emptyStateCopy': [t for t in texts if re.search(EMPTY_STATE, t, re.I)][:10],
           'debugLabels': [t for t in texts if re.fullmatch(DEBUG_LABEL, t.strip())][:10],
           'unreadTextRuns': (_unread_runs(gray, lines) + unread_path_blocks(gray, lines))[:10],
           'blankFraction': round(float((blocks.std(axis=(1, 3)) < 2.5).mean()), 4),
           'largestFlatRect': largest_flat_rect(gray), 'ocrScale': 2}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(row), encoding='utf-8')
    return row


def capture_flags(path, brief):
    """Every observed reason a capture should not be in the film (glance, audit, banned text)."""
    g, a = glance_capture(path), source_audit(path)
    flags = list(g['trusted']) + list(g['advisory'])
    if a['errorCopy'] or a['internalIds']:
        flags.append('error-copy')
    if a['unreadTextRuns']:
        flags.append('unreadable-text')
    if len(set(a['debugLabels'])) >= 2:  # a contact sheet labels several rows; one id is not a sheet
        flags.append('debug-sheet')
    if (a['emptyStateCopy'] and a['blankFraction'] > 0.6) or a['blankFraction'] > 0.85 or a['largestFlatRect'] > 0.7:
        flags.append('empty-state')
    if re.search(brief['spec'].get('bans', '$^'), a['text'] + ' ' + source_text(path), re.I):
        flags.append('banned-text')
    return flags


def source_text(path):
    """Full-resolution OCR of a source capture (cached by content)."""
    digest = sha_file(path)
    cache = CACHE / 'ocr' / (digest + '.json')
    if cache.is_file():
        return json.loads(cache.read_text(encoding='utf-8'))['text']
    text = ' | '.join(l['text'] for l in ocr_lines(path))
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({'text': text}), encoding='utf-8')
    return text


def glance_capture(path):
    """LAYA screenshot glance of a source capture, cached by content (lenses apply inside glance)."""
    digest = sha_file(path)
    cache = CACHE / 'glance' / (digest + '.json')
    if cache.is_file():
        return json.loads(cache.read_text(encoding='utf-8'))
    from .laya_glance import glance, load_calibration, REPO
    started = time.perf_counter()
    result = glance(screenshot=str(path), record=False)
    calibration = load_calibration(REPO)
    trusted = sorted({b['type'] for b in result['bugs'] if calibration.get(b['type'], {}).get('precisionLower', 0) >= 0.95})
    fired = sorted({b['type'] for b in result['bugs']} | {f['predicate'] for f in result.get('advisory', [])})
    row = {'sha256': digest, 'trusted': trusted, 'advisory': sorted(set(fired) - set(trusted)),
           'admitted': bool(result.get('admitted')), 'ms': round((time.perf_counter() - started) * 1000, 1)}
    try:
        from .scene_core import lenses  # plan 24 registry (VISION); present once merged
        row['lenses'] = sorted(getattr(lenses, 'registered', lambda: [])())
    except Exception:
        row['lenses'] = []
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(row), encoding='utf-8')
    return row


# --------------------------------------------------------------------------- assembly (first draft)

def assemble(brief, library, *, out_dir):
    """First draft straight from the brief: one shot per story beat, reading-time durations,
    captures as found, subtitles in a generic bottom position, the bed at unity gain.
    No judgement is applied here; the loop finds and fixes what is wrong."""
    spec = brief['spec']
    by_surface = {}
    for row in library:
        by_surface.setdefault(row['surface'], []).append(row)
    shots, captions, t = [], [], 0.0
    for i, beat in enumerate(spec['story']):
        if beat.get('layout'):
            # A designed composition of real media (a sheet beside its turntable render, phones in a
            # device frame); its layers are product imagery like a capture, judged layer by layer.
            words = len(beat.get('caption', '').split())
            duration = round(1.6 + 0.35 * words, 3)
            sid = f's{i + 1:02d}'
            shots.append({'id': sid, 'kind': 'layout', 'surface': beat['surface'], 'variant': beat['layout'].get('name', 'layout'),
                          'layers': beat['layout']['layers'], 'start': round(t, 3), 'duration': duration, 'motion': None,
                          'focus': [0.5, 0.5]})
            if beat.get('caption'):
                captions.append({'id': f'c{i + 1:02d}', 'shot': sid, 'text': beat['caption'], 'offset': 0.25,
                                 'duration': round(duration - 0.4, 3), 'x': 96, 'bottom': 40, 'size': 34,
                                 'weight': 600, 'color': '#ffffff', 'font': 'Segoe UI', 'scrim': False})
            t += duration
            continue
        options = by_surface.get(beat['surface'], [])
        if beat.get('variant'):
            options = [r for r in options if r['variant'] == beat['variant']] or options
        if not options:
            raise ValueError('No capture for story beat: ' + beat['surface'])
        cap = options[0]
        words = len(beat.get('caption', '').split())
        duration = round(1.6 + 0.35 * words, 3)
        sid = f's{i + 1:02d}'
        shots.append({'id': sid, 'kind': 'capture', 'capture': cap['path'], 'surface': cap['surface'],
                      'variant': cap['variant'], 'start': round(t, 3), 'duration': duration, 'motion': None,
                      'focus': beat.get('focus', [0.5, 0.45])})
        if beat.get('caption'):
            captions.append({'id': f'c{i + 1:02d}', 'shot': sid, 'text': beat['caption'], 'offset': 0.25,
                             'duration': round(duration - 0.4, 3), 'x': 96, 'bottom': 40, 'size': 34,
                             'weight': 600, 'color': '#ffffff', 'font': 'Segoe UI', 'scrim': False})
        t += duration
    end = spec.get('end', {})
    shots.append({'id': 'end', 'kind': 'card', 'start': round(t, 3), 'duration': 3.0, 'motion': None,
                  'surface': 'brand', 'line': end.get('line', ''), 'hold': True})
    t += 3.0
    aspect = spec['aspect']
    edl = {'schema': 'neyvia.video.cut.v1', 'brief': brief['path'], 'name': brief['name'],
           'size': {'width': aspect['width'], 'height': aspect['height']},
           'stage': spec['brand']['stage'], 'brand': spec['brand'], 'shots': shots, 'captions': captions,
           'music': {'bpm': spec['music']['bpm'], 'gainDb': 0.0, 'coverS': round(t, 3), 'seed': 7},
           'library': [{k: r[k] for k in ('path', 'surface', 'variant')} for r in library]}
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    (Path(out_dir) / 'edl.json').write_text(json.dumps(edl, indent=1), encoding='utf-8')
    return edl


def total_seconds(edl):
    return round(max(s['start'] + s['duration'] for s in edl['shots']), 4)


# --------------------------------------------------------------------------- compile to HyperFrames

def _caption_layout(c, size, edl):
    """Design-space (1920-wide) caption box: left/top from the caption's own declared intent."""
    H = DESIGN_W * edl['size']['height'] / edl['size']['width']
    line_h = round(c['size'] * 1.25)
    pad = round(c['size'] * 0.35) if c.get('scrim') else 0
    if 'top' in c:
        top = c['top']
    else:
        top = H - c['bottom'] - line_h - 2 * pad
    return {'left': c['x'], 'top': top, 'lineH': line_h, 'pad': pad, 'designH': H}


def compile_project(edl, project, *, scale, fps):
    """Write a deterministic HyperFrames project for this EDL. Returns the project file map."""
    tl = tools()
    project = Path(project)
    for sub in ('assets', 'fonts', 'vendor', 'audio'):
        (project / sub).mkdir(parents=True, exist_ok=True)
    width = int(round(edl['size']['width'] * scale / 2) * 2)
    height = int(round(edl['size']['height'] * scale / 2) * 2)
    k = width / DESIGN_W  # design (1920-wide) -> output pixels
    total = total_seconds(edl)
    shutil.copyfile(tl['gsap'], project / 'vendor/gsap.min.js')
    shutil.copyfile(tl['font'], project / 'fonts/inter.woff2')
    mark = ROOT / 'web/public/icons/neyvia-mark.svg'
    if mark.is_file():
        shutil.copyfile(mark, project / 'assets/mark.svg')
    for name in os.listdir(project / 'assets'):
        if name.startswith('cap-'):
            (project / 'assets' / name).unlink()
    music = edl['music']
    bed, _ = audio.synth_bed(music['bpm'], total, seed=music.get('seed', 7), gain_db=music.get('gainDb', 0.0),
                             cover_s=music.get('coverS', total))
    audio.write_wav(project / 'audio/bed.wav', bed)
    css, body, js, later = [], [], [], []
    brand = edl['brand']
    css.append('@font-face{font-family:"Inter";src:url("fonts/inter.woff2") format("woff2");font-weight:100 900;}')
    css.append(f'html,body{{margin:0;width:{width}px;height:{height}px;background:#000;overflow:hidden}}')
    css.append('#root{position:relative;width:100%;height:100%;overflow:hidden}')
    css.append('.clip{position:absolute;inset:0;overflow:hidden}')
    css.append(f'.stage{{position:absolute;inset:0;background:{edl["stage"]}}}')
    css.append('.shot>img{position:absolute;left:0;top:0;transform-origin:0 0}')
    css.append('.cap{position:absolute;white-space:nowrap;line-height:1.25;font-feature-settings:"tnum" 1}')
    for shot in edl['shots']:
        sid = shot['id']
        body.append(f'<div id="sh-{sid}" class="clip shot" data-start="{shot["start"]}" data-duration="{shot["duration"]}" data-track-index="0"><div class="stage"></div>')
        if shot['kind'] == 'capture':
            src = Path(shot['capture'])
            digest = sha_file(src)[:16]
            name = f'cap-{digest}{src.suffix.lower()}'
            if not (project / 'assets' / name).exists():
                try:
                    os.link(src, project / 'assets' / name)
                except OSError:
                    shutil.copyfile(src, project / 'assets' / name)
            from PIL import Image
            with Image.open(src) as im:
                iw, ih = im.size
            # Cover-fit the frame (UI fills the frame; cinetic: no small floating cards).
            fit = max(width / iw, height / ih)
            w, h = iw * fit, ih * fit
            x0, y0 = (width - w) / 2, (height - h) / 2
            body.append(f'<img id="im-{sid}" src="assets/{name}" style="width:{w:.2f}px;height:{h:.2f}px">')
            motion = shot.get('motion')
            fx, fy = shot.get('focus', [0.5, 0.5])
            if motion:
                s0, s1 = motion.get('from', 1.0), motion.get('to', 1.06)
                # Scale about the focus point so the meaningful part stays framed.
                px, py = x0 + fx * w, y0 + fy * h
                ax0, ay0 = px - (px - x0) * s0, py - (py - y0) * s0
                ax1, ay1 = px - (px - x0) * s1, py - (py - y0) * s1
                js.append(f'tl.fromTo("#im-{sid}",{{x:{ax0:.3f},y:{ay0:.3f},scale:{s0}}},{{x:{ax1:.3f},y:{ay1:.3f},scale:{s1},duration:{shot["duration"]},ease:"none"}},{shot["start"]});')
            else:
                js.append(f'tl.set("#im-{sid}",{{x:{x0:.3f},y:{y0:.3f},scale:1}},{shot["start"]});')
        elif shot['kind'] == 'layout':
            later.extend(_compile_layout(shot, project, k, width, height, body, js))
        elif shot['kind'] == 'card':
            size = round(150 * k)
            body.append(f'<div id="card-{sid}" style="position:absolute;left:0;top:0;width:{width}px;height:{height}px;display:flex;flex-direction:column;align-items:center;justify-content:center">'
                        f'<div style="display:flex;align-items:center;gap:{round(28 * k)}px"><img id="mk-{sid}" src="assets/mark.svg" style="width:{size}px;height:{size}px">'
                        f'<div id="wm-{sid}" class="brandtext" style="font-family:\'Inter\';font-weight:600;font-size:{round(118 * k)}px;letter-spacing:-0.03em;color:{brand["ink"]}">Neyvia</div></div>'
                        + (f'<div id="ln-{sid}" class="brandtext" style="margin-top:{round(30 * k)}px;font-family:\'Inter\';font-weight:450;font-size:{round(46 * k)}px;color:{brand["ink"]};opacity:.82">{shot.get("line", "")}</div>' if shot.get('line') else '')
                        + '</div>')
            js.append(f'tl.fromTo("#mk-{sid}",{{scale:0.86,opacity:0}},{{scale:1,opacity:1,duration:0.7,ease:"expo.out"}},{shot["start"] + 0.05});')
            js.append(f'tl.fromTo("#wm-{sid}",{{x:{round(-24 * k)},opacity:0}},{{x:0,opacity:1,duration:0.6,ease:"expo.out"}},{shot["start"] + 0.25});')
            if shot.get('line'):
                js.append(f'tl.fromTo("#ln-{sid}",{{y:{round(14 * k)},opacity:0}},{{y:0,opacity:0.82,duration:0.5,ease:"power3.out"}},{shot["start"] + 0.6});')
            js.append(f'tl.fromTo("#card-{sid}",{{scale:1}},{{scale:1.03,duration:{shot["duration"]},ease:"none"}},{shot["start"]});')
        body.append('</div>')
    body.extend(later)  # timed <video> layers sit at the root, above the shot they belong to
    shots = {s['id']: s for s in edl['shots']}
    for c in edl['captions']:
        shot = shots.get(c['shot'])
        if not shot:
            continue
        start = round(shot['start'] + c['offset'], 4)
        duration = round(min(c['duration'], shot['start'] + shot['duration'] - start), 4)
        lay = _caption_layout(c, None, edl)
        scrim = f'background:rgba(13,22,18,.78);padding:{round(lay["pad"] * k)}px {round(lay["pad"] * 1.5 * k)}px;border-radius:{round(10 * k)}px;' if c.get('scrim') else ''
        font = c.get('font', brand['font'])
        body.append(f'<div id="cp-{c["id"]}" class="clip" data-start="{start}" data-duration="{duration}" data-track-index="2">'
                    f'<div id="ct-{c["id"]}" class="cap" style="left:{c["x"] * k:.2f}px;top:{lay["top"] * k:.2f}px;font-family:\'{font}\';font-size:{c["size"] * k:.2f}px;font-weight:{c.get("weight", 600)};color:{c["color"]};{scrim}">{c["text"]}</div></div>')
        js.append(f'tl.fromTo("#ct-{c["id"]}",{{opacity:0,y:{round(12 * k)}}},{{opacity:1,y:0,duration:0.35,ease:"power3.out"}},{start});')
    body.append(f'<audio id="bed" src="audio/bed.wav" data-start="0" data-duration="{total}" data-track-index="4"></audio>')
    html = ('<!doctype html><html><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width={width}, height={height}">'
            '<style>' + '\n'.join(css) + '</style><script src="vendor/gsap.min.js"></script></head><body>'
            f'<div id="root" data-composition-id="main" data-start="0" data-duration="{total}" data-fps="{fps}" data-width="{width}" data-height="{height}">'
            + '\n'.join(body) + '</div>\n<script>\nwindow.__timelines=window.__timelines||{};\n'
            'const tl=gsap.timeline({paused:true});\n' + '\n'.join(js) + f'\ntl.set({{}},{{}},{total});\nwindow.__timelines["main"]=tl;\n</script></body></html>')
    (project / 'index.html').write_text(html, encoding='utf-8')
    (project / 'edl.json').write_text(json.dumps(edl, indent=1), encoding='utf-8')
    return {'width': width, 'height': height, 'fps': fps, 'total': total}


def _link_asset(project, src, prefix='cap'):
    src = Path(src)
    name = f'{prefix}-{sha_file(src)[:16]}{src.suffix.lower()}'
    target = Path(project) / 'assets' / name
    if not target.exists():
        try:
            os.link(src, target)
        except OSError:
            shutil.copyfile(src, target)
    return 'assets/' + name


def _compile_layout(shot, project, k, width, height, body, js):
    """Layers in design (1920-wide) pixels: images (optionally inside a drawn phone frame) in the shot's
    own clip, timed <video> layers returned for the root. Optional push on the whole layout; the first image is there at the cut, later layers rise in."""
    sid, start, dur = shot['id'], shot['start'], shot['duration']
    motion = shot.get('motion') or {}
    s0, s1 = motion.get('from', 1.0), motion.get('to', 1.0)
    cx, cy = width / 2, height / 2
    later = []
    body.append(f'<div id="ly-{sid}" style="position:absolute;left:0;top:0;width:{width}px;height:{height}px;transform-origin:50% 50%">')
    for j, layer in enumerate(shot['layers']):
        x, y, w, h = (v * k for v in layer['box'])
        radius = round(layer.get('radius', 18) * k)
        lid = f'{sid}-{j}'
        if layer.get('kind', 'image') == 'video':
            rel = _link_asset(project, layer['src'], 'clip')
            media = f' data-media-start="{layer["mediaStart"]}"' if layer.get('mediaStart') else ''
            later.append(f'<video id="vd-{lid}" class="clip layer" src="{rel}" data-start="{start}" data-duration="{dur}" data-track-index="1"{media} muted playsinline '
                         f'style="position:absolute;left:{x:.2f}px;top:{y:.2f}px;width:{w:.2f}px;height:{h:.2f}px;object-fit:cover;border-radius:{radius}px;'
                         f'box-shadow:0 {round(30 * k)}px {round(90 * k)}px rgba(0,0,0,.45);transform-origin:{cx - x:.2f}px {cy - y:.2f}px"></video>')
            # A designed entrance (fade and rise) instead of a pop: a timed <video> shows its first frame a
            # frame or two after the cut, which read as a second, late cut.
            js.append(f'tl.fromTo("#vd-{lid}",{{opacity:0,y:{round(36 * k)}}},{{opacity:1,y:0,duration:0.6,ease:"expo.out"}},{round(start + 0.08 + 0.14 * j, 4)});')
            if s0 != s1:
                js.append(f'tl.fromTo("#vd-{lid}",{{scale:{s0}}},{{scale:{s1},duration:{dur},ease:"none"}},{start});')
            continue
        rel = _link_asset(project, layer['src'])
        if layer.get('frame') == 'phone':
            bez, rad = round(13 * k), round(56 * k)
            island_w, island_h = round(104 * k), round(30 * k)
            # The capture has no status bar: a strip in the app's own top colour sits under the island,
            # so the island never covers the app's header.
            from PIL import Image
            with Image.open(layer['src']) as im:
                top = '#%02x%02x%02x' % im.convert('RGB').getpixel((4, 4))
            strip = round(40 * k)
            body.append(f'<div id="lr-{lid}" style="position:absolute;left:{x - bez:.2f}px;top:{y - bez:.2f}px;width:{w + 2 * bez:.2f}px;height:{h + 2 * bez:.2f}px;'
                        f'border-radius:{rad}px;background:#040605;box-shadow:0 0 0 {max(1, round(2 * k))}px #33413a,0 {round(40 * k)}px {round(110 * k)}px rgba(0,0,0,.6)">'
                        f'<div style="position:absolute;left:{bez}px;top:{bez}px;width:{w:.2f}px;height:{h:.2f}px;border-radius:{rad - bez}px;overflow:hidden;background:{top}">'
                        f'<img src="{rel}" style="position:absolute;left:0;top:{strip}px;display:block;width:100%;height:{h - strip:.2f}px;object-fit:cover;object-position:top"></div>'
                        f'<div style="position:absolute;top:{bez + round(9 * k)}px;left:50%;margin-left:{-island_w / 2:.1f}px;width:{island_w}px;height:{island_h}px;border-radius:{island_h}px;background:#000"></div></div>')
        else:
            fit = layer.get('fit', 'cover')
            body.append(f'<div id="lr-{lid}" style="position:absolute;left:{x:.2f}px;top:{y:.2f}px;width:{w:.2f}px;height:{h:.2f}px;border-radius:{radius}px;overflow:hidden;'
                        f'background:{layer.get("background", "#101b16")};box-shadow:0 {round(30 * k)}px {round(90 * k)}px rgba(0,0,0,.45)">'
                        f'<img src="{rel}" style="display:block;width:100%;height:100%;object-fit:{fit};object-position:{layer.get("position", "center")}"></div>')
        # The first image layer is on screen at the cut, so the cut itself lands on the beat; later layers
        # rise in after it. When every layer rose in, a layout cut from a dark screen measured 177 ms late
        # (the biggest change came with the layers, not the cut).
        if layer.get('enter', 'cut' if j == 0 else 'rise') == 'rise':
            js.append(f'tl.fromTo("#lr-{lid}",{{y:{round(36 * k)},opacity:0}},{{y:0,opacity:1,duration:0.6,ease:"expo.out"}},{round(start + 0.08 + 0.14 * j, 4)});')
    body.append('</div>')
    if s0 != s1:
        js.append(f'tl.fromTo("#ly-{sid}",{{scale:{s0}}},{{scale:{s1},duration:{dur},ease:"none"}},{start});')
    return later


def project_hash(project, params):
    h = hashlib.sha256(_canonical(params).encode())
    for path in sorted(Path(project).rglob('*')):
        if path.is_file() and 'renders' not in path.parts and path.name != 'edl.json':
            h.update(path.relative_to(project).as_posix().encode())
            h.update(sha_file(path).encode())
    return h.hexdigest()


def render(project, *, fps, quality, workers=4):
    """Headless HyperFrames render (own throwaway browser profile, no window), cached by content."""
    tl = tools()
    params = {'fps': fps, 'quality': quality, 'engine': 'hyperframes'}
    key = project_hash(project, params)
    out = CACHE / 'renders' / (key + '.mp4')
    if out.is_file():
        return out, {'cached': True, 'seconds': 0.0, 'key': key}
    out.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = TOOLS_DIR / 'tmp'  # renders write large temp files; keep them off the system drive
    temp_dir.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, 'TEMP': str(temp_dir), 'TMP': str(temp_dir), 'HYPERFRAMES_NO_TELEMETRY': '1', 'HYPERFRAMES_SKIP_SKILLS': '1',
           'HYPERFRAMES_BROWSER_PATH': tl['headless'], 'PRODUCER_HEADLESS_SHELL_PATH': tl['headless'],
           'PATH': os.environ.get('PATH', '') + os.pathsep + str(Path(tl['ffmpeg']).parent)}
    temp = Path(project) / 'renders' / (key + '.mp4')
    temp.parent.mkdir(exist_ok=True)
    started = time.perf_counter()
    _run(['node', tl['hyperframes'], 'render', str(project), '-o', str(temp), '--sdr', '--quality', quality,
          '--fps', str(fps), '--workers', str(workers), '--no-browser-gpu', '--quiet',
          '--frames-cache-dir', str(CACHE / 'frames'), '--video-frame-format', 'png'], cwd=str(project), env=env, timeout=3600)
    shutil.move(str(temp), out)
    return out, {'cached': False, 'seconds': round(time.perf_counter() - started, 2), 'key': key}


# --------------------------------------------------------------------------- measurement

def probe(mp4):
    tl = tools()
    data = json.loads(_run([tl['ffprobe'], '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(mp4)]))
    video = next(s for s in data['streams'] if s['codec_type'] == 'video')
    num, den = (int(v) for v in video['avg_frame_rate'].split('/'))
    return {'width': int(video['width']), 'height': int(video['height']), 'fps': num / den if den else 0.0,
            'durationS': float(data['format']['duration']), 'frames': int(video.get('nb_frames') or 0),
            'hasAudio': any(s['codec_type'] == 'audio' for s in data['streams']),
            'pixFmt': video.get('pix_fmt'), 'codec': video.get('codec_name')}


def decode_gray(mp4, w=160, h=90):
    tl = tools()
    raw = _run([tl['ffmpeg'], '-v', 'error', '-i', str(mp4), '-vf', f'scale={w}:{h}:flags=area,format=gray',
                '-f', 'rawvideo', '-'], binary=True)
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w).astype(np.float32)


def decode_audio(mp4):
    tl = tools()
    raw = _run([tl['ffmpeg'], '-v', 'error', '-i', str(mp4), '-vn', '-ac', '2', '-ar', str(audio.SR), '-f', 'f32le', '-'], binary=True)
    return np.frombuffer(raw, np.float32).reshape(-1, 2).astype(np.float64)


def frames_at(mp4, times, out_dir):
    """Exact decoded frames (PNG) at the given times; one decode pass."""
    tl = tools()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, t in enumerate(times):
        path = out_dir / f'f{i:03d}-{t:.3f}.png'
        if not path.is_file():
            _run([tl['ffmpeg'], '-v', 'error', '-ss', f'{t:.4f}', '-i', str(mp4), '-frames:v', '1', '-y', str(path)])
        paths.append(path)
    return paths


def _ncc(a, b):
    """Layout similarity of two frames. A flat frame (black, a fade) has no layout to repeat,
    so it never makes a jump cut; black frames have their own predicate."""
    if a.std() < 2 or b.std() < 2:
        return 0.0
    # Compare the coarse layout (5x5 block means of the 160x90 thumbnails): a re-framed copy of
    # the same screen (a 7% push) stays similar, fine UI detail does not decide it.
    h, w = a.shape
    a = a[:h // 5 * 5, :w // 5 * 5].reshape(h // 5, 5, w // 5, 5).mean(axis=(1, 3))
    b = b[:h // 5 * 5, :w // 5 * 5].reshape(h // 5, 5, w // 5, 5).mean(axis=(1, 3))
    a = a - a.mean()
    b = b - b.mean()
    d = np.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / d)


def speech(pcm):
    """Local Whisper (base, CPU) with word timestamps, cached by audio content. Words carry start and
    end (track/laya-video's reader); segments Whisper marks as non-speech are dropped. The model must
    already be cached locally: nothing is downloaded."""
    digest = hashlib.sha256(pcm.astype(np.float32).tobytes()).hexdigest()
    cache = CACHE / 'speech' / ('v2-' + digest + '.json')
    if cache.is_file():
        return json.loads(cache.read_text(encoding='utf-8'))
    try:
        import whisper
    except ImportError:
        return {'available': False, 'reason': 'openai-whisper is not installed', 'segments': [], 'words': [], 'model': None}
    if not (Path.home() / '.cache/whisper/base.pt').is_file():
        return {'available': False, 'reason': 'local Whisper base model is not cached (no download attempted)',
                'segments': [], 'words': [], 'model': None}
    started = time.perf_counter()
    from scipy import signal as sig
    mono = sig.resample_poly(pcm.mean(axis=1), 1, 3).astype(np.float32)  # 48k -> 16k
    model = whisper.load_model('base', device='cpu')
    result = model.transcribe(mono, word_timestamps=True, fp16=False, condition_on_previous_text=False, language='en')
    segments = [{'start': round(s['start'], 2), 'end': round(s['end'], 2), 'text': s['text'].strip(),
                 'noSpeechProb': round(s.get('no_speech_prob', 0), 3), 'avgLogprob': round(s.get('avg_logprob', 0), 3),
                 'words': [{'word': w['word'].strip(), 'start': round(w['start'], 2), 'end': round(w['end'], 2)} for w in s.get('words', [])]}
                for s in result.get('segments', [])]
    # Instrumental music makes Whisper invent text; keep only segments it believes are speech.
    kept = [s for s in segments if s['noSpeechProb'] < 0.5 and s['avgLogprob'] > -1.0]
    row = {'available': True, 'model': 'whisper-base-local', 'segments': kept, 'rejected': len(segments) - len(kept),
           'words': [w for s in kept for w in s['words']], 'text': ' '.join(s['text'] for s in kept),
           'seconds': round(time.perf_counter() - started, 2)}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(row), encoding='utf-8')
    return row


def ocr_lines(png):
    from PIL import Image
    from .laya_glance_image import _recognize
    with Image.open(png) as im:
        lines = _recognize(im.convert('RGBA'))
    out = []
    for text, words in lines:
        x0 = min(w[1] for w in words); y0 = min(w[2] for w in words)
        x1 = max(w[1] + w[3] for w in words); y1 = max(w[2] + w[4] for w in words)
        out.append({'text': text, 'box': [round(x0, 1), round(y0, 1), round(x1 - x0, 1), round(y1 - y0, 1)]})
    return out


def _serve(directory, port):
    import functools
    import http.server
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a, **k):
            pass
    handler = functools.partial(Quiet, directory=str(directory))
    server = http.server.ThreadingHTTPServer(('127.0.0.1', port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


DOM_PROBE = r"""async ({ids, times, prefix}) => {
 try { await document.fonts.load('600 40px "Inter"'); } catch (e) {}
 const tl = window.__timelines && window.__timelines.main;
 const out = {};
 for (let i = 0; i < ids.length; i++) {
   if (tl) tl.seek(times[i], false);
   const el = document.getElementById((prefix || 'ct-') + ids[i]);
   if (!el) { out[ids[i]] = null; continue; }
   const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
   out[ids[i]] = {x: r.left, y: r.top, w: r.width, h: r.height, color: cs.color, background: cs.backgroundColor,
                  fontFamily: cs.fontFamily, fontSize: parseFloat(cs.fontSize),
                  fontLoaded: document.fonts.check(cs.fontWeight + ' ' + cs.fontSize + ' ' + cs.fontFamily)};
 }
 const fams = new Set();
 document.querySelectorAll('.cap,.brandtext,.caption,.text').forEach(e => fams.add(getComputedStyle(e).fontFamily));
 return {captions: out, families: [...fams], viewport: [innerWidth, innerHeight]};
}"""


from contextlib import contextmanager


@contextmanager
def _obscura_fixture(port):
    """The admitted headless Obscura engine with the owner's loopback-fixture grant
    (--allow-private-network, as browser_obscura does for fixtures on assigned ports)."""
    import secrets
    import urllib.request
    from playwright.sync_api import sync_playwright
    from .laya_glance_gate import _admitted_engine
    exe, _ = _admitted_engine()
    import socket
    from .proof_ports import PORT_ENV, proof_port
    candidates = [proof_port(48462)] if PORT_ENV in os.environ else [port] + [p for p in (49168, 49169, 49162, 49161) if p != port]
    for candidate in candidates:
        try:
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', candidate))
            port = candidate
            break
        except OSError:
            continue
    token = secrets.token_urlsafe(24)
    process = subprocess.Popen([str(exe), 'serve', '--host', '127.0.0.1', '--port', str(port), '--max-connections', '4',
                                '--allow-private-network'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=NO_WINDOW, env={**os.environ, 'OBSCURA_CDP_TOKEN': token, 'OBSCURA_ROTATE_PROFILE': '0'})
    try:
        deadline = time.monotonic() + 30
        while True:
            try:
                req = urllib.request.Request(f'http://127.0.0.1:{port}/json/version', headers={'Authorization': 'Bearer ' + token})
                urllib.request.urlopen(req, timeout=2).read()
                break
            except Exception:
                if time.monotonic() > deadline or process.poll() is not None:
                    raise RuntimeError('Obscura did not start on port %d' % port)
                time.sleep(0.25)
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(f'http://127.0.0.1:{port}', headers={'Authorization': 'Bearer ' + token}, timeout=20000)
            try:
                yield browser
            finally:
                browser.close()
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except Exception:
            process.kill()


def dom_facts(project, captions, times, port=None, prefix='ct-'):
    """Caption boxes and fonts from the composition DOM in headless Obscura (fixture server on
    VIDEO's assigned ports 49163/49164; nothing else is reachable)."""
    from .proof_ports import PORT_ENV, proof_port
    port = proof_port(48461) if PORT_ENV in os.environ else port or int(os.environ.get('NEYVIA_VIDEO_DOM_PORT', '49163'))
    server = _serve(project, port)
    try:
        last = None
        for attempt in range(2):  # one retry: Obscura start-up and loads are slow on a saturated machine
            try:
                with _obscura_fixture(port + 1) as browser:
                    page = browser.new_context().new_page()
                    page.goto(f'http://127.0.0.1:{port}/index.html', wait_until='domcontentloaded', timeout=90000)
                    # Obscura runs no animation frames, so poll from here rather than wait_for_function (rAF).
                    deadline = time.monotonic() + 90
                    while not page.evaluate('() => !!(window.__timelines && window.__timelines.main)'):
                        if time.monotonic() > deadline:
                            raise TimeoutError('Composition timeline never registered in Obscura')
                        time.sleep(0.25)
                    return page.evaluate(DOM_PROBE, {'ids': [c['id'] for c in captions], 'times': times, 'prefix': prefix})
            except Exception as exc:
                last = exc
        raise last
    finally:
        server.shutdown()
        server.server_close()


def _rgb(css):
    m = re.findall(r'[\d.]+', css or '')
    return tuple(float(v) for v in m[:3]) if len(m) >= 3 else None


def _hex(value):
    value = value.lstrip('#')
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _lab(rgb):
    c = np.array(rgb, dtype=float) / 255
    c = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    m = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    x, y, z = (m @ c) / np.array([0.95047, 1.0, 1.08883])
    f = lambda v: np.cbrt(v) if v > 0.008856 else 7.787 * v + 16 / 116
    return (116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z)))


def delta_e(a, b):
    return float(np.linalg.norm(np.array(_lab(a)) - np.array(_lab(b))))


def _lum(rgb):
    c = np.array(rgb, dtype=float) / 255
    c = np.where(c <= 0.03928, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    return float(c @ [0.2126, 0.7152, 0.0722])


def pixel_text_colours(png, box):
    """Measured (text, background) colours inside a caption box: the background is the box's
    dominant colour, the text the pixels farthest from it."""
    from PIL import Image
    with Image.open(png) as im:
        rgb = np.asarray(im.convert('RGB'), dtype=float)
    x0, y0 = max(0, int(box['x'])), max(0, int(box['y']))
    x1, y1 = min(rgb.shape[1], int(box['x'] + box['w'])), min(rgb.shape[0], int(box['y'] + box['h']))
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    patch = rgb[y0:y1, x0:x1].reshape(-1, 3)
    bg = np.median(patch, axis=0)
    dist = np.linalg.norm(patch - bg, axis=1)
    cut = np.percentile(dist, 92)
    text = patch[dist >= cut].mean(axis=0) if cut > 8 else bg
    contrast = (max(_lum(text), _lum(bg)) + 0.05) / (min(_lum(text), _lum(bg)) + 0.05)
    return {'text': [round(v) for v in text], 'background': [round(v) for v in bg], 'contrast': round(contrast, 2)}


def _layer_frame(path, t, out_dir):
    """One decoded frame of a video layer's own source file (what the layer shows mid-shot)."""
    out = Path(out_dir) / f'{sha_file(path)[:16]}-{t:.2f}.png'
    if not out.is_file():
        out.parent.mkdir(parents=True, exist_ok=True)
        _run([tools()['ffmpeg'], '-v', 'error', '-y', '-ss', f'{t:.3f}', '-i', str(path), '-frames:v', '1', str(out)])
    return out


def _empty_audit():
    return {'errorCopy': [], 'internalIds': [], 'emptyStateCopy': [], 'debugLabels': [], 'unreadTextRuns': [], 'blankFraction': 0.0,
            'largestFlatRect': 0.0}


def _shot_audit(shot, keyframe):
    """Source audit of what a shot puts on screen. A capture is its source file; a layout is each layer
    (a video layer through one of its own frames); a free file's segment is its rendered keyframe.
    Placeholder measures (blank, flat rectangle) apply to UI imagery only: a turntable render or a sketch
    sheet on a plain backdrop is not an empty screen. Text measures apply to every layer."""
    if shot['kind'] == 'capture':
        return source_audit(shot['capture'])
    if shot['kind'] in ('frame', 'clip'):
        return source_audit(keyframe)
    if shot['kind'] != 'layout':
        return _empty_audit()
    out = _empty_audit()
    for layer in shot['layers']:
        src = layer['src']
        if layer.get('kind', 'image') == 'video':
            src = _layer_frame(src, float(layer.get('auditAt', 1.0)), CACHE / 'layer-frames')
        a = source_audit(src)
        for key in ('errorCopy', 'internalIds', 'emptyStateCopy', 'debugLabels', 'unreadTextRuns'):
            out[key] = out[key] + a[key]
        if layer.get('ui', True):
            out['blankFraction'] = max(out['blankFraction'], a['blankFraction'])
            out['largestFlatRect'] = max(out['largestFlatRect'], a['largestFlatRect'])
    return out


def _shot_glance(shot, keyframe):
    """LAYA glance of each UI image a shot shows (non-UI art such as sheets and renders is not glanced)."""
    if shot['kind'] == 'capture':
        return glance_capture(shot['capture'])
    srcs = [keyframe] if shot['kind'] in ('frame', 'clip') else \
        [l['src'] for l in shot.get('layers', []) if l.get('kind', 'image') == 'image' and l.get('ui', True)]
    rows = [glance_capture(s) for s in srcs if s]
    return {'trusted': sorted({x for r in rows for x in r['trusted']}), 'advisory': sorted({x for r in rows for x in r['advisory']})}


def analyse(mp4, edl, brief, project, *, fast=False):
    """All measured facts for one rendered cut (cached by render + EDL content). fast=True (outcome
    contracts) skips speech, keyframe OCR, glance and source audit; everything else is measured."""
    key = hashlib.sha256((ANALYSIS_VERSION + ('fast' if fast else '') + sha_file(mp4) + _canonical(edl) + brief['sha256']).encode()).hexdigest()
    cache = CACHE / 'facts' / (key + '.json')
    if cache.is_file():
        return json.loads(cache.read_text(encoding='utf-8'))
    started = time.perf_counter()
    timing = {}
    spec = brief['spec']
    meta = probe(mp4)
    fps = meta['fps']
    t0 = time.perf_counter()
    gray = decode_gray(mp4)
    timing['frames'] = time.perf_counter() - t0
    n = len(gray)
    diffs = np.concatenate([[255.0], np.abs(np.diff(gray, axis=0)).mean(axis=(1, 2))])
    means = gray.mean(axis=(1, 2))
    stds = gray.std(axis=(1, 2))
    black = (means < 12) & (stds < 6)
    t0 = time.perf_counter()
    pcm = decode_audio(mp4) if meta['hasAudio'] else np.zeros((int(meta['durationS'] * audio.SR), 2))
    level = audio.measure(pcm)
    measured_beats = audio.beats(pcm)
    timing['audio'] = time.perf_counter() - t0
    t0 = time.perf_counter()
    stt = speech(pcm) if meta['hasAudio'] and not fast else {'segments': [], 'words': [], 'model': None, 'available': False,
                                                             'reason': 'fast contracts' if fast else 'no audio stream'}
    timing['speech'] = time.perf_counter() - t0
    duration = meta['durationS']
    beats_s = np.array(measured_beats['beatTimes']) if measured_beats['beatTimes'] else np.array([])
    shots = sorted(edl['shots'], key=lambda s: s['start'])
    shot_facts, cut_facts = {}, {}
    planned = [round(s['start'] * fps) for s in shots[1:]]
    # Measured cut frames: large frame-to-frame change against the local median.
    local = np.array([np.median(diffs[max(1, i - 12):i + 12]) for i in range(n)])
    measured_cuts = [i for i in range(1, n) if diffs[i] > max(6.0, 4 * local[i])]
    allow = spec.get('allowBlackHeadTailS', 0.0)
    counted_black = black.copy()
    if allow:
        head, tail = int(round(allow * fps)), int(round((duration - allow) * fps))
        counted_black[:head] = False
        counted_black[tail:] = False
    for idx, shot in enumerate(shots):
        a = int(round(shot['start'] * fps))
        b = int(round((shots[idx + 1]['start'] if idx + 1 < len(shots) else duration) * fps))
        window = range(max(a, 0), min(b, n))
        # A freeze is a run of frames that stay within FROZEN_DIFF of the run's first frame. Comparing with
        # the anchor (not the previous frame) makes a slow push at 60 fps, which moves sub-pixel per frame,
        # leave the run within ~0.1 s, while encoder settling on a held frame (< 0.1 of 255) stays inside it.
        # Black frames have their own predicate and never count as a freeze.
        frozen, frozen_at, anchor = 0, None, None
        for i in window:
            if black[i]:
                anchor = None
                continue
            if anchor is None or np.abs(gray[i] - gray[anchor]).mean() >= FROZEN_DIFF:
                anchor = i
            if i - anchor + 1 > frozen:
                frozen, frozen_at = i - anchor + 1, anchor
        bl = [i for i in window if counted_black[i]]
        shot_facts[shot['id']] = {
            'startS': round(a / fps, 3), 'endS': round(b / fps, 3), 'durationS': round((b - a) / fps, 3),
            'blackFrames': len(bl), 'blackStartS': round(bl[0] / fps, 3) if bl else None,
            'frozenRunMaxS': round(frozen / fps, 3) if frozen > 1 else 0.0,
            'frozenStartS': round(frozen_at / fps, 3) if frozen else None,
            'motionMean': round(float(diffs[a + 1:b].mean()) if b - a > 1 else 0.0, 3)}
    for idx in range(1, len(shots)):
        before, after = shots[idx - 1], shots[idx]
        f = planned[idx - 1]
        near = [c for c in measured_cuts if abs(c - f) <= 2]
        cut_frame = max(near, key=lambda c: diffs[c]) if near else f
        cut_time = cut_frame / fps
        sim = _ncc(gray[max(cut_frame - 1, 0)], gray[min(cut_frame, n - 1)]) if n else 0.0
        off = float(np.min(np.abs(beats_s - cut_time)) * 1000) if len(beats_s) else None
        cut_facts[f'{before["id"]}>{after["id"]}'] = {
            'timeS': round(cut_time, 3), 'measured': bool(near), 'similarity': round(sim, 3),
            'changeMean': round(float(diffs[min(cut_frame, n - 1)]), 2), 'offBeatMs': round(off, 1) if off is not None else None,
            'sameSurface': before.get('surface') == after.get('surface')}
    # Keyframes: one exact frame per shot (mid), OCR for on-screen text.
    t0 = time.perf_counter()
    mids = [((sf['startS'] + sf['endS']) / 2) for sf in shot_facts.values()]
    frame_dir = CACHE / 'keyframes' / key[:16]
    keyframes = frames_at(mp4, mids, frame_dir)
    for (sid, sf), png in zip(shot_facts.items(), keyframes):
        if fast:
            sf['onScreenText'], sf['framePathText'] = None, None
            continue
        try:
            sf['onScreenText'] = ' | '.join(l['text'] for l in ocr_lines(png))[:400]
            patterns = _ui_text_patterns().get('encoded-path', [])
            sf['framePathText'] = [t for t in sf['onScreenText'].split(' | ') if any(re.search(rx, t, re.I) for rx in patterns)][:5]
        except Exception as exc:  # OCR unavailable is unknown text, not empty text.
            sf['onScreenText'] = None
            sf['framePathText'] = None
            sf['ocrError'] = type(exc).__name__
    timing['keyframes'] = time.perf_counter() - t0
    t0 = time.perf_counter()
    keyframe_of = {sid: str(png) for sid, png in zip(shot_facts, keyframes)}
    glances = {} if fast else {s['id']: _shot_glance(s, keyframe_of[s['id']]) for s in shots if s['kind'] in SCREEN_KINDS + ('frame', 'clip')}
    for s in shots:
        if fast:
            shot_facts[s['id']].update({'sourceText': None, 'errorCopy': [], 'emptyStateCopy': [], 'debugLabels': [], 'unreadTextRuns': 0,
                                        'blankFraction': 0.0, 'largestFlatRect': 0.0, 'audited': False})
            continue
        # A card has no source capture: its source text is observed to be empty.
        texts = [s['capture']] if s['kind'] == 'capture' else [l['src'] for l in s.get('layers', []) if l.get('kind', 'image') == 'image'] \
            if s['kind'] == 'layout' else [keyframe_of[s['id']]] if s['kind'] in ('frame', 'clip') else []
        shot_facts[s['id']]['sourceText'] = ' | '.join(source_text(x) for x in texts)[:2000]
        audit = _shot_audit(s, keyframe_of[s['id']])
        shot_facts[s['id']].update({'errorCopy': audit['errorCopy'] + audit['internalIds'], 'emptyStateCopy': audit['emptyStateCopy'],
                                    'debugLabels': audit['debugLabels'] if len(set(audit['debugLabels'])) >= 2 else [],
                                    'unreadTextRuns': len(audit['unreadTextRuns']),
                                    'blankFraction': audit['blankFraction'], 'largestFlatRect': audit['largestFlatRect']})
    timing['glance'] = time.perf_counter() - t0
    # Captions: exact DOM boxes, measured pixel colour/contrast at the caption's mid frame.
    caps = edl['captions']
    by_shot = {s['id']: s for s in shots}
    cap_times = []
    for c in caps:
        s = by_shot[c['shot']]
        start = s['start'] + c['offset']
        end = min(start + c['duration'], s['start'] + s['duration'])
        cap_times.append((start, end))
    t0 = time.perf_counter()
    dom = dom_facts(project, caps, [min(e - 0.05, s + 0.6) for s, e in cap_times], prefix=edl.get('domPrefix', 'ct-')) \
        if caps and project else {'captions': {}, 'families': []}
    timing['dom'] = time.perf_counter() - t0
    cap_frames = frames_at(mp4, [min(e - 0.05, s + 0.6) for s, e in cap_times], frame_dir / 'cap') if caps else []
    W, H = meta['width'], meta['height']
    safe = spec['captions'].get('safe', 0.9)
    mx, my = W * (1 - safe) / 2, H * (1 - safe) / 2
    brand = spec['brand']
    palette = [_hex(brand['ink']), _hex(brand['accent'])]
    cap_facts = {}
    for c, (start, end), png in zip(caps, cap_times, cap_frames):
        box = (dom.get('captions') or {}).get(c['id'])
        words = len(c['text'].split())
        path_rx = _ui_text_patterns().get('encoded-path', []) + _ui_text_patterns().get('internal-id', [])
        fact = {'startS': round(start, 3), 'holdS': round(end - start, 3), 'words': words,
                'pathText': bool(any(re.search(rx, c['text'], re.I) for rx in path_rx)),
                'minHoldS': round(0.6 + 0.1 * words, 2), 'maxWords': spec['captions'].get('maxWords', 99),
                'stockPhrase': sorted(s for s in STOCK if s in c['text'].lower()),
                'notRendered': bool(project) and (not box or not box.get('w') or not box.get('h'))}
        if box:
            colours = pixel_text_colours(png, box)
            fact.update({'box': {k: round(box[k], 1) for k in ('x', 'y', 'w', 'h')},
                         'heightFrac': round(box['h'] / H, 4) if box['h'] else 0.0,
                         'outsideSafe': bool(box['x'] < mx - 0.5 or box['y'] < my - 0.5 or box['x'] + box['w'] > W - mx + 0.5 or box['y'] + box['h'] > H - my + 0.5),
                         'fontFamily': box['fontFamily'], 'fontLoaded': box['fontLoaded'],
                         'contrastRatio': colours['contrast'] if colours else None,
                         'textColour': colours['text'] if colours else None,
                         'brandDeltaE': round(min(delta_e(colours['text'], p) for p in palette), 1) if colours else None})
        cap_facts[c['id']] = fact
    ids = list(cap_facts)
    for i, a_id in enumerate(ids):
        overlaps = []
        for b_id in ids:
            if a_id == b_id:
                continue
            a, b = cap_facts[a_id], cap_facts[b_id]
            if 'box' not in a or 'box' not in b:
                continue
            same_time = a['startS'] < b['startS'] + b['holdS'] and b['startS'] < a['startS'] + a['holdS']
            ba, bb = a['box'], b['box']
            inter = ba['x'] < bb['x'] + bb['w'] and bb['x'] < ba['x'] + ba['w'] and ba['y'] < bb['y'] + bb['h'] and bb['y'] < ba['y'] + ba['h']
            if same_time and inter:
                overlaps.append(b_id)
        cap_facts[a_id]['overlaps'] = overlaps
    # Video-level facts.
    lengths = sorted(sf['durationS'] for sid, sf in shot_facts.items() if by_shot[sid]['kind'] in SCREEN_KINDS + ('frame', 'clip'))
    median_shot = float(np.median(lengths)) if lengths else 0.0
    length = spec['length']
    pace = spec['pacing']['medianShotS']
    tail = spec['music'].get('tailS', 2.0)
    # Dead air only where the brief expects sound (a brief-less file or a silent fixture expects none).
    dead = [e - s for s, e in level['silentRuns'] if s < duration - tail] if spec['music'].get('expectSound', True) else []
    must = spec.get('must', [])
    covered = {s.get('surface') for s in shots if s['kind'] in SCREEN_KINDS and shot_facts[s['id']]['durationS'] >= 1.0}
    missing = [m for m in must if m not in covered]
    families = [f.split(',')[0].strip().strip('"\'') for f in dom.get('families', [])]
    off_brand = sorted({f for f in families if f.lower() != brand['font'].lower()}) if spec.get('brandChecks', True) else []
    expected_frames = int(round(duration * fps))
    target_lufs = spec['music'].get('lufs')
    aspect_target = spec['aspect']['width'] / spec['aspect']['height']
    video = {'durationS': round(duration, 3), 'width': W, 'height': H, 'fps': round(fps, 3), 'frames': n,
             'aspectError': round(abs(W / H - aspect_target) / aspect_target, 4),
             'durationOutsideBrief': not (length['min'] <= duration <= length['max']),
             'medianShotS': round(median_shot, 3), 'pacingOutsideBrief': not (pace[0] <= median_shot <= pace[1]),
             'integratedLufs': level['integratedLufs'], 'truePeakDbtp': level['truePeakDbtp'],
             'clippedSamples': level['clippedSamples'], 'deadAirMaxS': round(max(dead), 2) if dead else 0.0,
             'tempoBpm': measured_beats['tempoBpm'], 'beatsMeasured': len(measured_beats['beatTimes']),
             'syncRequested': bool(spec['music'].get('sync')), 'missingMustInclude': missing,
             'fontFamiliesOffBrand': off_brand, 'speechSegments': len(stt['segments']),
             'speechWords': sum(len(s['words']) for s in stt['segments']), 'blackFramesTotal': int(black.sum()),
             'measuredCuts': len(measured_cuts), 'plannedCuts': len(planned),
             'expectedFrames': expected_frames, 'frameCountOff': abs(n - expected_frames) > 1,
             'targetLufs': target_lufs, 'loudnessOff': bool(target_lufs is not None and level['integratedLufs'] is not None
                                                             and meta['hasAudio'] and abs(level['integratedLufs'] - target_lufs) > 2.0),
             'freezeMinS': spec.get('freezeMinS', 1.5), 'speechAvailable': bool(stt.get('available', bool(stt.get('model'))))}
    facts = {'meta': meta, 'video': video, 'shots': shot_facts, 'cuts': cut_facts, 'captions': cap_facts,
             'glance': glances, 'speech': stt, 'beats': measured_beats, 'level': {k: v for k, v in level.items() if k != 'silentRuns'},
             'silentRuns': level['silentRuns'], 'domFamilies': dom.get('families', []),
             'timing': {k: round(v, 2) for k, v in timing.items()}, 'analysisSeconds': round(time.perf_counter() - started, 2),
             'keyframes': [str(p) for p in keyframes]}
    facts = json.loads(json.dumps(facts))  # one representation, fresh or cached
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(facts), encoding='utf-8')
    return facts


# --------------------------------------------------------------------------- Scene

def scene_from(facts, edl, brief):
    spec = brief['spec']
    nodes = [{'id': 'video', 'kind': 'video', 'attributes': {'brief': brief['name'], 'engine': 'hyperframes'},
              'measurements': facts['video'], 'relations': {'shots': [s['id'] for s in edl['shots']]}}]
    by_shot = {s['id']: s for s in edl['shots']}
    for sid, sf in facts['shots'].items():
        shot = by_shot[sid]
        g = facts['glance'].get(sid) or {'trusted': [], 'advisory': []}
        nodes.append({'id': 'shot:' + sid, 'kind': 'shot',
                      'attributes': {'surface': shot.get('surface'), 'variant': shot.get('variant'), 'designedHold': bool(shot.get('hold')),
                                     'motion': bool(shot.get('motion')), 'sourceKind': shot['kind']},
                      'measurements': {**{k: v for k, v in sf.items() if k != 'ocrError'},
                                       'frozenOverLimit': sf['frozenRunMaxS'] > spec.get('freezeMinS', 1.5),
                                       'screenDefects': g['trusted'], 'screenAdvisory': g['advisory']},
                      'relations': {}})
    for cid, cf in facts['cuts'].items():
        incoming = by_shot.get(cid.split('>')[1], {})
        nodes.append({'id': 'cut:' + cid, 'kind': 'cut', 'attributes': {'syncRequested': bool(spec['music'].get('sync')),
                                                                     'transition': incoming.get('transitionIn', 'none')},
                      'measurements': cf, 'relations': {'between': cid.split('>')}})
    for cid, cf in facts['captions'].items():
        caption = next(c for c in edl['captions'] if c['id'] == cid)
        minimum = spec['captions']
        nodes.append({'id': 'caption:' + cid, 'kind': 'caption', 'attributes': {'text': caption['text']},
                      'measurements': {**cf, 'minHeightFrac': minimum.get('minHeightFrac', 0.035),
                                       'tooSmall': cf.get('heightFrac') is not None and cf['heightFrac'] < minimum.get('minHeightFrac', 0.035),
                                       'lowContrast': cf.get('contrastRatio') is not None and cf['contrastRatio'] < minimum.get('minContrast', 4.5),
                                       'tooBrief': cf['holdS'] < cf['minHoldS'], 'tooLong': cf['words'] > cf.get('maxWords', 99)},
                      'relations': {'shot': caption['shot']}})
    covered = 1 - len(facts['video']['missingMustInclude']) / max(len(spec.get('must', [])), 1)
    return {'surface': 'video:' + brief['name'], 'nodes': nodes,
            'metrics': {'mustIncludeCoverage': round(covered, 4), 'captionCount': len(facts['captions']),
                        'shotCount': len(facts['shots']),
                        # Captions per capture shot: a fix may ripple-delete a shot with its caption,
                        # but may not shed captions to escape a caption finding.
                        'captionCoverage': round(len(facts['captions']) / max(sum(s['kind'] in SCREEN_KINDS for s in edl['shots']), 1), 4)},
            'provenance': {'engine': 'hyperframes 0.8.138 headless', 'observers': ['ffmpeg decode', 'BS.1770', 'onset beats',
                           'whisper-base local', 'Windows OCR', 'Obscura DOM', 'LAYA glance'],
                           'renderSha256': facts.get('renderSha256'), 'briefSha256': brief['sha256']}}


def vocabulary():
    return [json.loads(line[14:]) for line in MANUAL.read_text(encoding='utf-8').splitlines() if line.startswith('-- @predicate ')]


def load_edl(project):
    return json.loads((Path(project) / 'edl.json').read_text(encoding='utf-8'))


def save_edl(project, edl):
    (Path(project) / 'edl.json').write_text(json.dumps(edl, indent=1), encoding='utf-8')


def _cut_view_of_clips(clip_edl, project):
    """track/laya-video's free-form EDL (neyvia.video.edl.v1, edited by neyvia.video.*) seen as a cut:
    visual clips are shots (images are captures, videos clips, titles cards), caption clips are captions
    (caption DOM ids 'ct-<id>' inside the timed row 'c-<id>'). Planned intent only: every fact is still measured from the rendered file."""
    vis = sorted((c for c in clip_edl['clips'] if c['kind'] in ('image', 'video', 'text')), key=lambda c: (c['start'], c['track']))
    shots = []
    for c in vis:
        if shots and c['start'] < shots[-1]['start'] + 1e-3:
            continue  # stacked on the same start: one shot window
        if shots and c.get('src') and c.get('src') == shots[-1].get('src') and c['id'].startswith(shots[-1]['id']):
            continue  # the second half of a split continues the same shot (motion carries across the split)
        kind = {'image': 'capture', 'video': 'clip', 'text': 'card'}[c['kind']]
        shot = {'id': c['id'], 'kind': kind, 'start': c['start'], 'duration': c['duration'], 'surface': (c.get('tags') or [None])[0],
                'variant': c.get('intent'), 'motion': bool(c.get('keyframes')) or None, 'hold': bool(c.get('hold')),
                'transitionIn': (c.get('transitionIn') or {}).get('kind', 'none'), 'src': c.get('src')}
        if kind == 'capture':
            shot['capture'] = c['src']
        shots.append(shot)
    captions = []
    for c in sorted((c for c in clip_edl['clips'] if c['kind'] == 'caption'), key=lambda c: c['start']):
        owner = max((s for s in shots if s['start'] <= c['start'] + 1e-3), key=lambda s: s['start'], default=shots[0] if shots else None)
        if owner is None:
            continue
        captions.append({'id': c['id'], 'shot': owner['id'], 'text': c['text'], 'offset': round(c['start'] - owner['start'], 4),
                         'duration': c['duration']})
    return {'schema': 'neyvia.video.cut.view', 'shots': shots, 'captions': captions, 'domPrefix': 'ct-',
            'size': {'width': clip_edl['width'], 'height': clip_edl['height']}}


def _cut_view_of_file(mp4, meta):
    """A file with no project: shots are the measured scene cuts, each judged on its rendered keyframe."""
    gray = decode_gray(mp4)
    n = len(gray)
    diffs = np.concatenate([[255.0], np.abs(np.diff(gray, axis=0)).mean(axis=(1, 2))]) if n else np.array([])
    local = np.array([np.median(diffs[max(1, i - 12):i + 12]) for i in range(n)])
    cuts = [0] + [i for i in range(1, n) if diffs[i] > max(6.0, 4 * local[i])]
    fps = meta['fps'] or 30
    shots = [{'id': f'seg{j + 1:02d}', 'kind': 'frame', 'start': round(a / fps, 4),
              'duration': round(((cuts[j + 1] if j + 1 < len(cuts) else n) - a) / fps, 4), 'surface': None, 'motion': None}
             for j, a in enumerate(cuts)]
    return {'schema': 'neyvia.video.cut.view', 'shots': shots, 'captions': [], 'size': {'width': meta['width'], 'height': meta['height']}}


def observe_file(source):
    """source = {video, project?, brief?, fast?}: judge a rendered file with the same observers.
    The project (either EDL schema) only supplies node ids, planned shot windows and caption DOM."""
    mp4 = Path(source['video'])
    meta = probe(mp4)
    project = Path(source['project']) if source.get('project') else None
    edl_file = project / 'edl.json' if project else None
    dom_project = None
    if edl_file and edl_file.is_file():
        raw = json.loads(edl_file.read_text(encoding='utf-8'))
        if raw.get('clips') is not None:
            edl = _cut_view_of_clips(raw, project)
            dom_project = project if (project / 'index.html').is_file() else None
        else:
            edl = raw
            build = project / 'build-preview'
            dom_project = build if (build / 'index.html').is_file() else None
        brief = brief_from(source.get('brief') or raw.get('brief'), meta)
    else:
        edl = _cut_view_of_file(mp4, meta)
        brief = brief_from(source.get('brief'), meta)
    edl.setdefault('size', {'width': meta['width'], 'height': meta['height']})
    facts = analyse(mp4, edl, brief, dom_project, fast=bool(source.get('fast')))
    facts['renderSha256'] = sha_file(mp4)
    source['_latest'] = {'mp4': str(mp4), 'facts': facts}
    return scene_from(facts, edl, brief)


def observe(source):
    """source = {project, quality:'preview'|'master'}; the EDL in project/edl.json is the editable state.
    A source with 'video' judges that rendered file instead (observe_file)."""
    if source.get('video'):
        return observe_file(source)
    with _LOCK:
        project = Path(source['project'])
        edl = load_edl(project)
        brief = read_brief(edl['brief'])
        mode = MASTER if source.get('quality') == 'master' else PREVIEW
        build = project / ('build-' + source.get('quality', 'preview'))
        compile_project(edl, build, scale=mode['scale'], fps=mode['fps'])
        mp4, info = render(build, fps=mode['fps'], quality=mode['quality'], workers=source.get('workers', 4))
        facts = analyse(mp4, edl, brief, build)
        facts['renderSha256'] = sha_file(mp4)
        source.setdefault('_renders', []).append({'mp4': str(mp4), **info, 'analysisSeconds': facts['analysisSeconds']})
        source['_latest'] = {'mp4': str(mp4), 'facts': facts}
        return scene_from(facts, edl, brief)


# --------------------------------------------------------------------------- fixes (each edits only edl.json)

def _beat(edl):
    return 60.0 / edl['music']['bpm']


def _relayout(edl):
    t = 0.0
    for shot in sorted(edl['shots'], key=lambda s: s['start']):
        shot['start'] = round(t, 4)
        t += shot['duration']
    edl['music']['coverS'] = round(max(edl['music'].get('coverS', 0), 0), 4)


def fix_snap_cuts(edl, finding, brief):
    beat = _beat(edl)
    for shot in edl['shots']:
        beats = max(2, round(shot['duration'] / beat))
        shot['duration'] = round(beats * beat, 4)
    _relayout(edl)
    edl['music']['coverS'] = total_seconds(edl)
    _fit_captions(edl)


def _fit_captions(edl):
    shots = {s['id']: s for s in edl['shots']}
    for c in edl['captions']:
        s = shots[c['shot']]
        c['duration'] = round(max(0.5, min(c['duration'], s['duration'] - c['offset'] - 0.05)), 4)


def fix_add_motion(edl, finding, brief):
    for shot in edl['shots']:
        if shot['kind'] in SCREEN_KINDS and not shot.get('motion') and not shot.get('hold'):
            shot['motion'] = {'kind': 'push', 'from': 1.0, 'to': 1.07 if shot['kind'] == 'capture' else 1.04}


def fix_card_motion(edl, finding, brief):
    for shot in edl['shots']:
        if shot['kind'] == 'card':
            shot['hold'] = True


def _clean_captures(rows, brief):
    return [r for r in rows if not capture_flags(r['path'], brief)]


def _swap_one(edl, shot, brief):
    """Replace one shot's capture with a clean capture of its surface, else of a brief alternate."""
    used = {s.get('capture') for s in edl['shots']}
    library = library_for(brief)
    usable = lambda rows: sorted([r for r in rows if r['path'] not in used and not r['variant'].endswith('phone')],
                                 key=lambda r: (r['variant'] != shot.get('variant'), r['variant'] != 'full', r['path']))
    choice = (_clean_captures(usable([r for r in library if r['surface'] == shot['surface']]), brief) or [None])[0]
    if choice is None:
        for surface in brief['spec'].get('alternates', {}).get(shot['surface'], []):
            rows = usable([r for r in library if r['surface'] == surface])
            choice = (_clean_captures(rows, brief) or [None])[0]
            if choice:
                break
    if choice is None:
        return False
    shot.update(capture=choice['path'], surface=choice['surface'], variant=choice['variant'])
    return True


def fix_swap_capture(edl, finding, brief):
    """House rule: every shot whose source capture LAYA flags (or shows banned text) gets a clean
    capture of the same surface, else of a brief alternate. Shots without one are left as found."""
    swapped, dropped = [], []
    must = set(brief['spec'].get('must', []))
    for shot in sorted(edl['shots'], key=lambda s: s['start']):
        if shot['kind'] != 'capture':
            continue
        if not capture_flags(shot['capture'], brief):
            continue
        if _swap_one(edl, shot, brief):
            swapped.append(shot['id'])
        elif shot.get('surface') not in must:
            # No clean capture and the brief does not require this surface: ripple-delete the shot.
            dropped.append(shot['id'])
    if dropped:
        edl['shots'] = [s for s in edl['shots'] if s['id'] not in dropped]
        edl['captions'] = [c for c in edl['captions'] if c['shot'] not in dropped]
        _relayout(edl)
        edl['music']['coverS'] = total_seconds(edl)
    if swapped or dropped:  # with neither, the re-observed cut is unchanged and the core reverts the step
        edl.setdefault('notes', []).append({'fix': 'edl.swap_capture', 'swapped': swapped, 'dropped': dropped})


def fix_separate(edl, finding, brief):
    a, b = finding['node'].split(':', 1)[1].split('>')
    order = sorted(edl['shots'], key=lambda s: s['start'])
    ids = [s['id'] for s in order]
    j = ids.index(b)
    if j + 1 < len(order) and order[j + 1]['kind'] in SCREEN_KINDS:
        order[j], order[j + 1] = order[j + 1], order[j]
    else:
        fix_swap_capture(edl, {'node': 'shot:' + b}, brief)
        return
    t = 0.0
    for s in order:
        s['start'] = round(t, 4)
        t += s['duration']


def fix_close_gap(edl, finding, brief):
    _relayout(edl)


def fix_retime(edl, finding, brief):
    spec = brief['spec']
    beat = _beat(edl)
    caps = [s for s in edl['shots'] if s['kind'] in SCREEN_KINDS]
    fixed = sum(s['duration'] for s in edl['shots'] if s['kind'] not in SCREEN_KINDS)
    target = spec['length'].get('target', (spec['length']['min'] + spec['length']['max']) / 2)
    lo, hi = spec['pacing']['medianShotS']
    per = min(max((target - fixed) / max(len(caps), 1), lo), hi)
    for s in caps:
        s['duration'] = round(max(2, round(per / beat)) * beat, 4)
    _relayout(edl)
    edl['music']['coverS'] = total_seconds(edl)
    _fit_captions(edl)


def fix_insert_shot(edl, finding, brief):
    missing = finding['evidence'].get('measurements.missingMustInclude') or []
    beat = _beat(edl)
    end = [s for s in edl['shots'] if s['kind'] == 'card']
    for surface in missing:
        row = next((r for r in edl['library'] if r['surface'] == surface), None)
        if not row:
            continue
        sid = 'm-' + surface
        insert_at = min((s['start'] for s in end), default=total_seconds(edl))
        for s in edl['shots']:
            if s['start'] >= insert_at:
                s['start'] = round(s['start'] + 4 * beat, 4)
        edl['shots'].append({'id': sid, 'kind': 'capture', 'capture': row['path'], 'surface': surface, 'variant': row['variant'],
                             'start': round(insert_at, 4), 'duration': round(4 * beat, 4),
                             'motion': {'kind': 'push', 'from': 1.0, 'to': 1.07}, 'focus': [0.5, 0.45]})
        # The brief's own line for this surface comes back with it, in the cut's caption style.
        line = next((b.get('caption') for b in brief['spec'].get('story', []) if b.get('surface') == surface and b.get('caption')), None)
        if line and edl['captions']:
            style = {k: v for k, v in edl['captions'][0].items() if k not in {'id', 'shot', 'text', 'offset', 'duration'}}
            edl['captions'].append({**style, 'id': 'c-' + surface, 'shot': sid, 'text': line, 'offset': 0.25,
                                    'duration': round(4 * beat - 0.4, 4)})
    edl['music']['coverS'] = total_seconds(edl)


def fix_normalize(edl, finding, brief):
    ev = finding['evidence']
    target = brief['spec']['music'].get('lufs', -14)
    lufs, peak = ev.get('measurements.integratedLufs'), ev.get('measurements.truePeakDbtp')
    gain = edl['music'].get('gainDb', 0.0)
    delta = min(target - lufs if lufs is not None else -6.0, -1.5 - peak if peak is not None else -6.0)
    edl['music']['gainDb'] = round(gain + delta, 2)


def fix_extend_bed(edl, finding, brief):
    edl['music']['coverS'] = total_seconds(edl)


def fix_move_into_safe(edl, finding, brief):
    safe = brief['spec']['captions'].get('safe', 0.9)
    H = DESIGN_H
    for c in edl['captions']:
        margin_y = H * (1 - safe) / 2 + 24
        margin_x = DESIGN_W * (1 - safe) / 2 + 24
        c['bottom'] = max(c.get('bottom', 0), round(margin_y))
        c['x'] = max(c['x'], round(margin_x))
        c.pop('top', None)


def fix_restyle(edl, finding, brief):
    minimum = brief['spec']['captions'].get('minHeightFrac', 0.035)
    size = int(np.ceil(minimum * DESIGN_H / 1.25 * 1.12))
    ink = brief['spec']['brand']['ink']
    for c in edl['captions']:
        c['size'] = max(c['size'], size)
        c['scrim'] = True
        # Legible on the dark scrim: a caption darker than the brand ink takes the ink.
        if _lum(_hex(c['color'])) < _lum(_hex(ink)) * 0.5:
            c['color'] = ink


def fix_restack(edl, finding, brief):
    cid = finding['node'].split(':', 1)[1]
    c = next(x for x in edl['captions'] if x['id'] == cid)
    others = finding['evidence'].get('measurements.overlaps') or []
    for other in edl['captions']:
        if other['id'] in others and other['id'] > cid:
            other['bottom'] = other.get('bottom', 40) + round(other['size'] * 1.6 + 24)


def fix_extend_caption(edl, finding, brief):
    shots = {s['id']: s for s in edl['shots']}
    for c in edl['captions']:
        need = 0.6 + 0.1 * len(c['text'].split())
        s = shots[c['shot']]
        room = s['duration'] - c['offset'] - 0.05
        if c['duration'] < need:
            c['duration'] = round(min(need + 0.2, room), 4)
            if c['duration'] < need:
                c['offset'] = round(max(0.05, s['duration'] - need - 0.1), 4)
                c['duration'] = round(need + 0.05, 4)


def fix_brand(edl, finding, brief):
    brand = brief['spec']['brand']
    edl['brand'] = brand
    for c in edl['captions']:
        c['font'] = brand['font']
        c['color'] = brand['ink']


def fix_aspect(edl, finding, brief):
    aspect = brief['spec']['aspect']
    edl['size'] = {'width': aspect['width'], 'height': aspect['height']}


FIXES = {'edl.snap_cuts': fix_snap_cuts, 'edl.add_motion': fix_add_motion, 'edl.swap_capture': fix_swap_capture,
         'edl.separate': fix_separate, 'edl.close_gap': fix_close_gap, 'edl.retime': fix_retime,
         'edl.insert_shot': fix_insert_shot, 'audio.normalize': fix_normalize, 'audio.extend_bed': fix_extend_bed,
         'caption.move_into_safe': fix_move_into_safe, 'caption.restyle': fix_restyle, 'caption.restack': fix_restack,
         'caption.extend': fix_extend_caption, 'brand.apply_tokens': fix_brand, 'render.set_aspect': fix_aspect,
         'edl.hold_card': fix_card_motion}


def apply_fix(source, finding):
    project = Path(source['project'])
    edl = load_edl(project)
    brief = read_brief(edl['brief'])
    FIXES[finding['fix']['action']](edl, finding, brief)
    save_edl(project, edl)
    source.setdefault('_fixes', []).append({'action': finding['fix']['action'], 'node': finding['node']})
    return {'action': finding['fix']['action'], 'node': finding['node']}


def checkpoint(source):
    return (Path(source['project']) / 'edl.json').read_bytes()


def restore(source, snapshot):
    path = Path(source['project']) / 'edl.json'
    path.write_bytes(snapshot)
    if path.read_bytes() != snapshot:
        raise RuntimeError('EDL restore did not reproduce the checkpoint')


def episode_input(scene):
    """Frozen representation for episodes: the measured facts per node kind, no ids or paths."""
    rows = []
    for n in scene['nodes']:
        m = {k: v for k, v in n.get('measurements', {}).items() if isinstance(v, (int, float, bool))}
        rows.append({'kind': n['kind'], 'measurements': m})
    return 'scene:video', {'nodes': rows}


def make_adapter():
    from .scene_core import Adapter
    return Adapter(transcribe=observe, vocabulary=vocabulary, fixes={k: apply_fix for k in FIXES},
                   checkpoint=checkpoint, restore=restore, episode_input=episode_input)


# --------------------------------------------------------------------------- the improve loop

GUARDS = {'mustIncludeCoverage': 'min', 'captionCoverage': 'min'}


def improve_cut(project, root, state, *, save=lambda state: None, max_rounds=24, max_seconds=300, log=print):
    """Rounds of scene_core.improve (one named EDL fix, kept only on a strict finding reduction with no
    guarded metric regression, else edl.json and the re-observed Scene are restored exactly) until no
    fix applies. A round over the core's time budget is retried once from the render cache; an action
    that fails twice is retired for this cut. state['rounds'] records every round with its receipt."""
    from . import scene_core
    project = Path(project)
    # A rejected action is retired only for the cut it failed on (keyed by the EDL's hash): once another
    # fix is kept, the cut has changed and the action may be tried again. Retiring it for the whole run
    # left v3 at 27.5 s (under the brief's 30 s) because edl.retime had failed on the 36-finding draft.
    raw = state.get('excluded', {})
    excluded = raw if isinstance(raw, dict) else {a: 'legacy' for a in raw}
    edl_sha = lambda: hashlib.sha256((project / 'edl.json').read_bytes()).hexdigest()
    state.setdefault('rounds', [])
    while len(state['rounds']) < max_rounds:
        source = {'project': str(project)}
        scene = scene_core.transcribe('video', source)
        verdict = scene_core.judge(scene, record=False)
        current = edl_sha()
        allowed = sorted({f['fix']['action'] for f in verdict['findings']} - {a for a, sha in excluded.items() if sha == current} - {'review'})
        if not allowed:
            break
        started = time.perf_counter()
        before_bytes = (project / 'edl.json').read_bytes()
        source = {'project': str(project)}
        try:
            result = scene_core.improve('video', source, {'max_steps': 1, 'max_seconds': max_seconds, 'allowed_fixes': allowed,
                                                          'guards': GUARDS}, root=root)
        except Exception as exc:  # the core restored edl.json before re-raising; record and retry once
            failures = state.setdefault('failures', [])
            failures.append({'error': type(exc).__name__ + ': ' + str(exc)[:300], 'edlRestoredExact': (project / 'edl.json').read_bytes() == before_bytes,
                             'seconds': round(time.perf_counter() - started, 1)})
            save(state)
            log('round failed', failures[-1])
            if len(failures) > 3:
                break
            continue
        seconds = time.perf_counter() - started
        if not result['steps']:
            break
        step = result['steps'][0]
        row = {'round': len(state['rounds']) + 1, 'action': step['finding']['fix']['action'], 'predicate': step['finding']['predicate'],
               'node': step['finding']['node'], 'status': step['status'], 'seconds': round(seconds, 1),
               'findingsBefore': len(verdict['findings']), 'findingsAfter': len(result['verdict']['findings']),
               'sceneBefore': step.get('before'), 'sceneAfter': step.get('after'),
               'renders': source.get('_renders', []), 'receipt': result['receipt'], 'analysis': ANALYSIS_VERSION}
        if step['status'] != 'kept':
            # The core already re-observed the restored cut and compared its Scene sha256 with the one
            # before the fix (it raises otherwise); the EDL bytes are checked here as well.
            row['edlRestoredExact'] = (project / 'edl.json').read_bytes() == before_bytes
            row['sceneRestoredExact'] = step['status'] == 'reverted'
            retried = state.setdefault('retried', [])
            key = row['action'] + '@' + current
            if seconds > max_seconds and key not in retried:
                retried.append(key)
                row['retry'] = 'over budget; one retry with the cached render'
            else:
                excluded[row['action']] = current
        state['rounds'].append(row)
        state['excluded'] = excluded
        save(state)
        log('round', row['round'], row['action'], row['status'], row['findingsBefore'], '->', row['findingsAfter'], row['seconds'], 's')
    return state


def contact_sheet(video, out, *, count=24, cols=6, width=320, label=''):
    """Evenly spaced decoded frames of a video in one PNG (track/laya-video's sheet, on this toolchain)."""
    from PIL import Image, ImageDraw
    meta = probe(video)
    times = [meta['durationS'] * (i + 0.5) / count for i in range(count)]
    frames = frames_at(video, times, CACHE / 'sheets' / sha_file(video)[:16])
    height = int(round(width * meta['height'] / meta['width']))
    rows = (count + cols - 1) // cols
    sheet = Image.new('RGB', (cols * width, rows * (height + 18)), (10, 15, 12))
    draw = ImageDraw.Draw(sheet)
    for i, (t, png) in enumerate(zip(times, frames)):
        with Image.open(png) as im:
            sheet.paste(im.convert('RGB').resize((width, height)), ((i % cols) * width, (i // cols) * (height + 18)))
        draw.text(((i % cols) * width + 4, (i // cols) * (height + 18) + height + 2), f'{t:.2f}s {label}', fill=(200, 210, 200))
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return str(out)


# --------------------------------------------------------------------------- taste (plan 28 Build 4)

def vote(root, scene_a, scene_b, winner, *, user, reason, source):
    """A/B vote on two cuts -> two personal episodes (winner 'preferred', loser 'not-preferred').

    Personal labels need a user (plan 21). The episode input is the measured cut facts,
    so the next similar edit retrieves the preference locally."""
    if winner not in ('a', 'b') or not user:
        raise ValueError('A vote needs winner a|b and the voting user')
    from .scene_core import episode
    out = []
    for side, scene in (('a', scene_a), ('b', scene_b)):
        label = 'preferred' if side == winner else 'not-preferred'
        out.append(episode(root, scene, label, reason, f'{source}:{side}', user=user, layer='personal'))
    return out
