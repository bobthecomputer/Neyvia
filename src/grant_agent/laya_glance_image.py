"""Pixel transcriber for the UI adapter: one screenshot -> Scene v1 nodes.

Vision here only DESCRIBES. Local OCR (Windows.Media.Ocr, no network, no model
download) reads visible text with boxes; numpy measures the pixels around each
text line. The shared CL vocabulary (manuals/cl/laya-glance.cl) then judges these
facts exactly like DOM facts. Nothing is labelled here and nothing is learned here.

Every node carries ``measurements.source='pixels'``. Pixel facts are measurements
of the painted image, so they are approximate with respect to the DOM: admission
of a pixel verdict is decided by per-predicate calibration (plan 21 episodes), not
by the predicate merely matching. See ``laya_glance.glance``.

Image node kinds:
  text  one OCR line. measurements: contrastRatio, ellipsisGap, spacedEllipsis,
        clippedText, crossesSurfaceEdge,
        overlap, viewportCut, offScreenControl.
  page  a page-shaped rectangle (portrait, fully visible). measurements:
        expectedContent, uniform, verticalDetail, textInside.
"""
from __future__ import annotations

import asyncio
from functools import lru_cache
import hashlib
from pathlib import Path
import re
import time

import numpy as np
from PIL import Image

OCR_IDENTITY = 'windows-media-ocr'


@lru_cache(maxsize=1)
def _ocr_language():
    from winrt.windows.media.ocr import OcrEngine
    tags = [lang.language_tag for lang in OcrEngine.available_recognizer_languages]
    for preferred in ('en-US', 'en-GB', 'en'):
        if preferred in tags:
            return preferred
    if not tags:
        raise RuntimeError('No Windows OCR language is installed')
    return tags[0]


def _recognize(image):
    """Windows.Media.Ocr on an RGBA PIL image -> [(text, [(word, x, y, w, h)])]."""
    from winrt.windows.globalization import Language
    from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage.streams import DataWriter
    writer = DataWriter()
    writer.write_bytes(image.tobytes())
    bitmap = SoftwareBitmap.create_copy_from_buffer(writer.detach_buffer(), BitmapPixelFormat.RGBA8, image.width, image.height)
    engine = OcrEngine.try_create_from_language(Language(_ocr_language()))

    async def run():
        return await engine.recognize_async(bitmap)
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        result = asyncio.run(run())
    else:
        # Called from a thread that already runs an event loop (e.g. Playwright's
        # sync API in the gate): recognise on a short-lived worker thread.
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(1) as worker:
            result = worker.submit(lambda: asyncio.run(run())).result(timeout=30)
    lines = []
    for line in result.lines:
        words = []
        for word in line.words:
            r = word.bounding_rect
            words.append((word.text, r.x, r.y, r.width, r.height))
        if words:
            lines.append((line.text, words))
    return lines


def _luminance(rgb):
    c = np.asarray(rgb, dtype=np.float64) / 255.0
    c = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    return c[..., 0] * 0.2126 + c[..., 1] * 0.7152 + c[..., 2] * 0.0722


def _contrast(a, b):
    la, lb = float(_luminance(a)), float(_luminance(b))
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


class _Pixels:
    def __init__(self, rgb):
        self.rgb = rgb.astype(np.int16)
        self.h, self.w = rgb.shape[:2]
        # Steps in gamma-encoded grey between neighbouring columns / rows. Linear
        # luminance compresses dark themes (panel borders differ by ~0.003).
        self.gray = self.rgb.mean(axis=2)
        self.vedge = np.zeros((self.h, self.w), dtype=bool)
        self.vedge[:, :-1] = np.abs(np.diff(self.gray, axis=1)) >= 4
        self.hedge = np.zeros((self.h, self.w), dtype=bool)
        self.hedge[:-1, :] = np.abs(np.diff(self.gray, axis=0)) >= 4

    def clamp_box(self, x0, y0, x1, y1):
        return max(0, int(x0)), max(0, int(y0)), min(self.w, int(np.ceil(x1))), min(self.h, int(np.ceil(y1)))

    def background(self, x0, y0, x1, y1, pad=3):
        """Median colour of a thin ring around a box."""
        X0, Y0, X1, Y1 = self.clamp_box(x0 - pad, y0 - pad, x1 + pad, y1 + pad)
        patch = self.rgb[Y0:Y1, X0:X1].reshape(-1, 3)
        inner = np.zeros((Y1 - Y0, X1 - X0), dtype=bool)
        ix0, iy0, ix1, iy1 = int(x0) - X0, int(y0) - Y0, int(np.ceil(x1)) - X0, int(np.ceil(y1)) - Y0
        inner[max(0, iy0):max(0, iy1), max(0, ix0):max(0, ix1)] = True
        ring = patch[~inner.reshape(-1)]
        if not len(ring):
            ring = patch
        return np.median(ring, axis=0)

    def distance(self, region, color):
        return np.abs(region - np.asarray(color)[None, None, :]).max(axis=2)


def _box(words):
    x0 = min(w[1] for w in words); y0 = min(w[2] for w in words)
    x1 = max(w[1] + w[3] for w in words); y1 = max(w[2] + w[4] for w in words)
    return x0, y0, x1, y1


def _ellipsis_after(px, bg, x1, y0, y1):
    """Find three baseline dots after a text box; return the gap in px or None."""
    X0, Y0, X1, Y1 = px.clamp_box(x1, y0, x1 + 28, y1 + 1)
    if X1 - X0 < 6 or Y1 - Y0 < 4:
        return None
    ink = px.distance(px.rgb[Y0:Y1, X0:X1], bg) > 45
    cols = ink.any(axis=0)
    # Column runs of ink are blob candidates.
    runs, start = [], None
    for i, v in enumerate(list(cols) + [False]):
        if v and start is None:
            start = i
        elif not v and start is not None:
            runs.append((start, i)); start = None
    dots = []
    for a, b in runs:
        rows = np.where(ink[:, a:b].any(axis=1))[0]
        if b - a <= 3 and 1 <= len(rows) <= 3 and rows.min() >= (Y1 - Y0) * 0.5:
            dots.append((a, b, rows.mean()))
        elif dots:
            break
        elif a > 14:
            break
    if len(dots) >= 3:
        gaps = [dots[i + 1][0] - dots[i][1] for i in range(2)]
        if all(1 <= g <= 4 for g in gaps) and abs(dots[0][2] - dots[2][2]) <= 1.5:
            return int(dots[0][0])
    return None


def _runs(mask, min_len):
    """Runs of True along axis 1 of a 2-D mask -> (index, start, end), vectorised."""
    padded = np.zeros((mask.shape[0], mask.shape[1] + 2), dtype=np.int8)
    padded[:, 1:-1] = mask
    d = np.diff(padded, axis=1)
    starts, ends = np.argwhere(d == 1), np.argwhere(d == -1)
    keep = (ends[:, 1] - starts[:, 1]) >= min_len
    return [(int(i), int(a), int(b)) for (i, a), (_, b) in zip(starts[keep], ends[keep])]


def _vertical_edge_runs(px, min_len):
    """Long vertical boundaries as (x, y_start, y_end); x is the left pixel."""
    return _runs(px.vedge.T, min_len)


def _horizontal_edge_runs(px, min_len):
    return _runs(px.hedge, min_len)


def _surface_edges(px, runs, axis):
    """Keep surface boundaries: a fill change, or an isolated border line.

    Rejects 1-px texture stripes (parallel neighbours every few pixels) and
    boundaries that are only text edges. Medians over the run keep text painted
    across the edge from averaging the boundary away.
    """
    g = px.gray if axis == 'x' else px.gray.T
    limit = g.shape[1]
    kept = []
    for at, a, b in runs:
        if at < 4 or at > limit - 6:
            continue
        rows = g[a:b]
        step = float(np.median(np.abs(rows[:, at - 2:at + 1].mean(axis=1) - rows[:, at + 1:at + 4].mean(axis=1))))
        line = float(np.median(np.abs(rows[:, at + 1] - (rows[:, at - 1] + rows[:, at + 3]) / 2)))
        neighbours = sum(1 for o, c, d in runs if 2 <= abs(o - at) <= 8 and min(b, d) - max(a, c) > 0.5 * (b - a))
        if step >= 3 or (line >= 15 and neighbours < 2):
            kept.append((at, a, b))
    return kept


def _merge_runs(runs, tol=2, gap=2):
    """Collapse neighbouring parallel runs (anti-aliased borders are 1-2 px)."""
    runs = sorted(runs)
    merged = []
    for r in runs:
        if merged and abs(r[0] - merged[-1][0]) <= tol and r[1] <= merged[-1][2] + gap and r[2] >= merged[-1][1] - gap:
            m = merged[-1]
            merged[-1] = (m[0], min(m[1], r[1]), max(m[2], r[2]))
        else:
            merged.append(r)
    return merged


def _side_step(px, x0, y0, x1, y1):
    """Mean grey difference between 3 px just inside and just outside each side."""
    g = px.gray
    if x0 < 4 or y0 < 4 or x1 > px.w - 4 or y1 > px.h - 4:
        return None
    ys, xs = slice(y0 + 6, y1 - 6), slice(x0 + 6, x1 - 6)
    steps = [abs(g[ys, x0 + 1:x0 + 4].mean() - g[ys, x0 - 4:x0 - 1].mean()),
             abs(g[ys, x1 - 4:x1 - 1].mean() - g[ys, x1 + 1:x1 + 4].mean()),
             abs(g[y0 + 1:y0 + 4, xs].mean() - g[y0 - 4:y0 - 1, xs].mean()),
             abs(g[y1 - 4:y1 - 1, xs].mean() - g[y1 + 1:y1 + 4, xs].mean())]
    return min(steps)


def _detached_ellipses(px):
    """Three baseline dots separated from the glyphs before them by >=5 px.

    A browser draws text-overflow's ellipsis right after the last visible glyph;
    a gap means the label was offset inside its clip (first glyphs cut too).
    Works without OCR, so one-letter fragments ("I …") are still seen.
    Returns [(x_text_start, x_text_end, x_dots, y0, y1)].
    """
    from scipy import ndimage
    g = px.gray
    ink = np.abs(g - ndimage.uniform_filter(g, size=9)) > 25
    labels, count = ndimage.label(ink, structure=np.ones((3, 3)))
    if not count:
        return []
    sl = ndimage.find_objects(labels)
    box = np.array([(s[0].start, s[0].stop, s[1].start, s[1].stop) for s in sl], dtype=np.int32)
    h, w = box[:, 1] - box[:, 0], box[:, 3] - box[:, 2]
    dots = box[(h <= 3) & (w <= 3)]
    glyphs = box[(h >= 4) & (h <= 40) & (w <= 60)]
    if len(dots) < 3 or not len(glyphs):
        return []
    dots = dots[np.lexsort((dots[:, 2], dots[:, 0]))]
    same = np.abs(np.diff(dots[:, 0])) <= 1
    gap = dots[1:, 2] - dots[:-1, 3]
    step = dots[1:, 2] - dots[:-1, 2]
    pair = same & (gap > 0) & (gap <= 4) & (step <= 6)
    starts = np.where(pair[:-1] & pair[1:])[0]
    out = []
    for i in starts:
        x_dots, base = int(dots[i, 2]), int(dots[i, 1])
        near = glyphs[(glyphs[:, 3] <= x_dots) & (x_dots - glyphs[:, 3] <= 30) & (np.abs(glyphs[:, 1] - base) <= 3)]
        if not len(near):
            continue
        nearest = near[np.argmax(near[:, 3])]
        if x_dots - int(nearest[3]) < 4:
            continue  # ellipsis attached to the last glyph: ordinary end truncation
        line = glyphs[(np.abs(glyphs[:, 1] - base) <= 3) & (glyphs[:, 3] <= nearest[3]) & (nearest[2] - glyphs[:, 3] <= 60)]
        start = int(line[:, 2].min()) if len(line) else int(nearest[2])
        top = int(min(line[:, 0].min() if len(line) else nearest[0], nearest[0]))
        out.append((start, int(nearest[3]), x_dots, top, base))
    return out


def _edge_cuts(px):
    """Content sliced by the left/right viewport edge: short ink runs in the
    outermost columns that continue inward (window borders are full-height)."""
    cuts = []
    # Row background = median of a wide band beside the edge (ink is a minority).
    for side, cols, ref in (('right', slice(px.w - 3, px.w), slice(px.w - 60, px.w - 6)),
                            ('left', slice(0, 3), slice(6, 60))):
        background = np.median(px.rgb[:, ref], axis=1)
        differs = (np.abs(px.rgb[:, cols] - background[:, None, :]).max(axis=2) > 40).all(axis=1)
        for _, a, b in _runs(differs[None, :], 3):
            block = px.gray[max(0, a - 2):b + 2, cols]
            # Glyph or icon strokes vary inside the cut; solid fills (buttons,
            # fields, panels flush with the edge) do not.
            if b - a <= 24 and block.std() > 18:
                cuts.append((side, a, b))
    return cuts


def _local_step(px, axis, at, lo, hi, run=None):
    """The boundary separates different fills just outside the text on both ends."""
    g = px.gray
    lo, hi = int(lo), int(np.ceil(hi))
    first, last = run if run else (0, px.h if axis == 'x' else px.w)
    windows = [(max(first, lo - 24), max(first, lo - 2)), (min(last, hi + 2), min(last, hi + 24))]
    for a, b in windows:
        if b - a < 6:
            return False
        # Compare fills 2-4 px away on each side: a 1-px rule line has the same
        # fill on both sides, a surface boundary does not.
        if axis == 'x':
            step = abs(g[a:b, max(0, at - 4):at - 1].mean() - g[a:b, at + 2:at + 5].mean())
            # A bordered panel side may have the same fill on both sides; its
            # 1-px border line is then the boundary (vertical rules through
            # text do not occur in this UI, horizontal ruled paper does).
            line = abs(g[a:b, at + 1].mean() - (g[a:b, at - 1].mean() + g[a:b, at + 3].mean()) / 2)
            if step < 3 and line < 15:
                return False
        else:
            step = abs(g[max(0, at - 4):at - 1, a:b].mean() - g[at + 2:at + 5, a:b].mean())
            if step < 3:
                return False
    return True


def _blurred_vertical_edges(px, k=5):
    """Vertical boundaries of a 5x5 box-blurred grey image (fine textures vanish)."""
    g = px.gray
    c = np.cumsum(np.cumsum(np.pad(g, ((1, 0), (1, 0))), axis=0), axis=1)
    b = (c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]) / (k * k)
    edge = np.zeros_like(g, dtype=bool)
    off = k // 2
    step = np.abs(b[:, 4:] - b[:, :-4]) >= 6
    edge[off:off + step.shape[0], off + 2:off + 2 + step.shape[1]] = step
    # Thin each boundary to its centre column so parallel runs merge cleanly.
    return _merge_runs(_runs(edge.T, 120), tol=5)


def _pages(px, lines, vruns=None):
    """Portrait page-like rectangles, all four borders inside the viewport.

    A page is bounded by two long vertical boundaries of matching extent whose
    fill differs from the surround on all four sides (texture stripes do not).
    """
    vruns = _blurred_vertical_edges(px)
    out = []
    area = px.w * px.h
    for i, (xa, ya0, ya1) in enumerate(vruns):
        for xb, yb0, yb1 in vruns[i + 1:]:
            w = xb - xa
            if w < 90 or abs(ya0 - yb0) > 8 or abs(ya1 - yb1) > 8:
                continue
            top, bottom = max(ya0, yb0) + 2, min(ya1, yb1) - 2
            h = bottom - top
            if h < 120 or not 1.15 <= h / w <= 1.65 or not 0.015 <= (w * h) / area <= 0.6:
                continue
            x0, y0, x1, y1 = xa + 3, top, xb + 3, bottom
            step = _side_step(px, x0, y0, x1, y1)
            if step is None or step < 6:
                continue
            if any(abs(x0 - o[0]) < 8 and abs(y0 - o[1]) < 8 for o in out):
                continue
            inner = px.gray[y0 + 3:y1 - 3, x0 + 3:x1 - 3]
            # Share of pixels with real vertical structure (text, image detail).
            vertical = float((np.abs(np.diff(inner, axis=0)) > 6).mean()) if inner.size else 1.0
            inside = [k for k, (_, b) in enumerate(lines) if b[0] >= x0 - 2 and b[2] <= x1 + 2 and b[1] >= y0 - 2 and b[3] <= y1 + 2]
            out.append((x0, y0, x1, y1, vertical, inside, step))
    # Keep outermost rectangles: inner stripes of a skeleton are not separate pages.
    out.sort(key=lambda o: -(o[2] - o[0]) * (o[3] - o[1]))
    kept = []
    for o in out:
        if not any(o[0] >= k[0] - 4 and o[1] >= k[1] - 4 and o[2] <= k[2] + 4 and o[3] <= k[3] + 4 for k in kept):
            kept.append(o)
    return kept


_ELLIPSIS = re.compile(r'(?:…|\.\.\.|\. \. \.)\s*$')
# OCR reads a detached ellipsis as '...', '.', '_' or '…' after a space.
_SPACED_ELLIPSIS = re.compile(r'\S\s+(?:…|\.{1,3}|_)\s*$')


SECOND_PASS = {'scale': 3, 'maxCrops': 10, 'minRunPx': 24}
# On by default since VISION2 (plan 27 §7, 7 Oct), decided by the rule fixed in scripts/vision2_ocr_decision.py on a
# NEW blind-labelled held-out split (163 captures): encoded-path recall .931 -> .966, overlap .271 -> .300,
# no type loses precision (internal-id stays 1.0; the first version's 1.0 -> .20 collapse is fixed), added time
# median 138 ms / p95 1.16 s cold. Evidence scripts/evidence/VISION2-ocr-decision.json. Opt out with
# NEYVIA_LAYA_OCR_SECOND_PASS=0 (history: scripts/evidence/VISION-ocr-second-pass.json).
SECOND_PASS_ENABLED = __import__('os').environ.get('NEYVIA_LAYA_OCR_SECOND_PASS', '1') != '0'


def _text_runs(rgb):
    """Text-like ink runs: horizontal-gradient strokes joined along a line, 7-40 px tall, wide."""
    from scipy import ndimage
    # Same values as rgb.astype(int16).mean(axis=2) (exact integer sum, one float division) and the same
    # mask as binary_dilation with a 3x9 box (separable max filters, zero border), at a fraction of the
    # cost: this function was ~70% of the second pass's time (VISION2 latency probe).
    total = rgb[..., 0].astype(np.int16)
    total += rgb[..., 1]
    total += rgb[..., 2]
    gray = total / 3.0
    edges = np.zeros(gray.shape, bool)
    edges[:, 1:] = np.abs(gray[:, 1:] - gray[:, :-1]) > 28
    joined = ndimage.maximum_filter1d(edges.view(np.uint8), 9, axis=1, mode='constant')
    joined = ndimage.maximum_filter1d(joined, 3, axis=0, mode='constant').astype(bool)
    labels, _ = ndimage.label(joined)
    runs = []
    for sl in ndimage.find_objects(labels):
        if sl is None:
            continue
        h, w = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
        if 7 <= h <= 40 and w >= 24 and w >= 2.5 * h and edges[sl].mean() >= 0.06:
            runs.append((sl[1].start, sl[0].start, sl[1].stop, sl[0].stop))
    return runs


def _erase_underscores(crop):
    """Windows OCR drops tokens joined by underscores ('install_cua_driver.py' reads as nothing).
    Paint isolated baseline strokes (an underscore: a thin horizontal ink run with no ink just above it)
    in the crop's background colour; return (clean crop, erased x-ranges in crop pixels)."""
    a = np.asarray(crop.convert('RGB')).astype(np.int16)
    if a.shape[0] < 6 or a.shape[1] < 6:
        return crop, []
    border = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])
    bg = np.median(border, axis=0)
    ink = np.abs(a - bg).max(axis=2) > 40
    out = a.copy()
    spans = []
    hh = a.shape[0]
    # An underscore is about one character wide: never longer than the glyph height (crops carry 4 px
    # padding above and below). Longer baseline strokes are chip borders, underlines or the edge of
    # a panel showing through, and erasing them joined real words ('Window_Browser'; VISION2).
    longest = max(6, hh - 8)
    for y in range(hh // 2, hh - 1):
        row = ink[y]
        above = ink[max(0, y - 3):y - 1].any(axis=0) if y >= 3 else np.zeros_like(row)
        below = ink[y + 3:y + 5].any(axis=0) if y + 3 < hh else np.zeros_like(row)
        x = 0
        while x < row.size:
            if row[x]:
                x1 = x
                while x1 < row.size and row[x1]:
                    x1 += 1
                if (max(4, hh // 4) <= x1 - x <= longest and above[x:x1].mean() < 0.25
                        and below[x:x1].mean() < 0.25):  # a thin stroke, not the top of a glyph or a box
                    out[y:y + 2, x:x1] = bg
                    spans.append((x, x1))
                x = x1
            else:
                x += 1
    if not spans:
        return crop, []
    return Image.fromarray(out.astype(np.uint8)), spans


def _join_text(words, erased):
    """Rebuild a line from words in reading order: '_' where an erased underscore sat in the gap,
    nothing after a path separator or across a gap under a quarter of the text height."""
    text = ''
    for k, (t, x, y, ww, hh) in enumerate(words):
        if k:
            px1 = words[k - 1][1] + words[k - 1][3]
            gap = x - px1
            tol = 0.35 * max(hh, 1)
            # The erased stroke must sit IN the gap (an underscore joins the two words); a stroke under a
            # word's own letters is something else (VISION2: 'server_keeps' from a see-through mash).
            if any(px1 - tol <= a and b <= x + tol and a < x and b > px1 for a, b in erased):
                text += '_'
            elif not (text.endswith(('/', chr(92))) or gap < 0.25 * max(hh, 1)):
                text += ' '
        text += t
    return text


def _second_pass(image, rgb, lines, memo_dir=None):
    """Second OCR pass (plan 24 observer lens 'ocr-second-pass'): Windows OCR drops some words,
    notably path-like and error-like runs ('... missing:' then nothing). Find text-like ink runs the
    first pass left unread (no OCR box over at least half of a >= 24 px stretch), OCR each stretch
    again on a 3x upscaled crop, and either extend the OCR line it continues or add a new line.
    Bounded: at most 10 crops, largest unread stretches first. Returns (lines, metrics)."""
    h, w = rgb.shape[:2]
    started = time.perf_counter()
    covered = np.zeros((h, w), bool)
    # Coverage by WORD boxes: OCR often keeps a line box across a dropped middle word
    # ('scripts/ - -source' with the path between them unread).
    for _, _, words in lines:
        for _, wx, wy, ww, wh in words:
            covered[max(0, int(wy) - 2):int(wy + wh) + 2, max(0, int(wx) - 3):int(wx + ww) + 3] = True
    stretches = []
    for x0, y0, x1, y1 in _text_runs(rgb):
        cols = covered[y0:y1, x0:x1].mean(axis=0) < 0.5
        best, start = (0, 0, 0), None
        for i, free in enumerate(list(cols) + [False]):
            if free and start is None:
                start = i
            elif not free and start is not None:
                if i - start > best[0]:
                    best = (i - start, start, i)
                start = None
        if best[0] >= SECOND_PASS['minRunPx']:
            stretches.append((best[0], x0 + best[1], y0, x0 + best[2], y1))
    # Low character density: a word box far wider than its letters ('scripts/' over the whole
    # 'scripts/install_cua_driver.py') means OCR kept the box but dropped characters.
    for _, _, words in lines:
        for t, wx, wy, ww, wh in words:
            chars = len(t.strip())
            if chars and ww >= SECOND_PASS['minRunPx'] and ww / chars > 1.15 * max(wh, 6):
                stretches.append((ww, int(wx), int(wy), int(wx + ww), int(wy + wh)))
    stretches.sort(reverse=True)
    stretches = stretches[:SECOND_PASS['maxCrops']]
    lines = list(lines)
    added = extended = 0
    all_erased = []
    s = SECOND_PASS['scale']
    for _, x0, y0, x1, y1 in stretches:
        X0, Y0, X1, Y1 = max(0, x0 - 6), max(0, y0 - 4), min(w, x1 + 6), min(h, y1 + 4)
        clean, spans = _erase_underscores(image.crop((X0, Y0, X1, Y1)))
        erased = [(X0 + a, X0 + b) for a, b in spans]
        crop = clean.resize(((X1 - X0) * s, (Y1 - Y0) * s), Image.BICUBIC).convert('RGBA')
        memo = None
        if memo_dir:
            import json
            memo = Path(memo_dir) / ('p2-' + hashlib.sha256(crop.tobytes()).hexdigest()[:24] + '.json')
            if memo.exists():
                found = json.loads(memo.read_text(encoding='utf-8'))
            else:
                found = _recognize(crop)
                memo.parent.mkdir(parents=True, exist_ok=True)
                memo.write_text(json.dumps(found), encoding='utf-8')
        else:
            found = _recognize(crop)
        words = [(t, X0 + x / s, Y0 + y / s, ww / s, hh / s) for text, ws in found for t, x, y, ww, hh in ws]
        words = [wd for wd in words if re.search(r'[A-Za-z0-9]{2}', wd[0])]
        # Never re-read into another line's words (that would invent overlapping text).
        others = [ow for k_, (_, _, lw) in enumerate(lines) for ow in lw]
        def clash(wd):
            for _, ox, oy, ow_, oh in others:
                ix = min(wd[1] + wd[3], ox + ow_) - max(wd[1], ox); iy = min(wd[2] + wd[4], oy + oh) - max(wd[2], oy)
                if ix > 0 and iy > 0 and ix * iy > 0.2 * min(wd[3] * wd[4], ow_ * oh) and not (x0 - 2 <= ox + ow_ / 2 <= x1 + 2):
                    return True
            return False
        words = sorted((wd for wd in words if not clash(wd)), key=lambda wd: wd[1])
        if not words:
            continue
        bx0, by0, bx1, by1 = _box(words)
        text = _join_text(words, erased)
        # Overlapping or just after an OCR line on the same row: put the words into that line in reading
        # order. (VISION2: a re-read starting left of a line used to become a second, overlapping line.)
        def vshare(a0, a1, b0, b1):
            return min(a1, b1) - max(a0, b0) >= 0.5 * max(1e-6, min(a1 - a0, b1 - b0))
        row = [k for k, (_, (lx0, ly0, lx1, ly1), _) in enumerate(lines)
               if vshare(ly0, ly1, by0, by1) and bx0 <= lx1 + 18 and bx1 >= lx0 - 18]
        if not row:
            lines.append((text, (bx0, by0, bx1, by1), words))
            added += 1
            continue
        host = row[0]
        _, (lx0, ly0, lx1, ly1), _ = lines[host]
        # Only words on the host's own row join it (a crop can reach into the next row; merging those
        # grew the line box over two rows and broke its surface-edge facts; VISION2).
        words = [wd for wd in words if vshare(ly0, ly1, wd[2], wd[2] + wd[4]) and wd[4] <= 1.5 * (ly1 - ly0)]
        # A re-read word replaces the first-pass words under it (in ANY line of this row) only when it
        # reads MORE characters ('scripts/' -> 'scripts/install_cua_driver.'); otherwise the first reading
        # stays ('could' re-read as ':ould' broke the raw-error wording; 'Browser' re-read next to the
        # first-pass 'Browser' line drew a false overlap; VISION2).
        def under(wd, ow):
            return wd[1] - 2 <= ow[1] + ow[3] / 2 <= wd[1] + wd[3] + 2 and vshare(ow[2], ow[2] + ow[4], wd[2], wd[2] + wd[4])
        alnum = lambda t: len(re.sub(r'[^A-Za-z0-9]', '', t))
        gone, new = set(), []
        for wd in words:
            old = [(k, j) for k in row for j, ow in enumerate(lines[k][2]) if (k, j) not in gone and under(wd, ow)]
            if not old or alnum(wd[0]) > sum(alnum(lines[k][2][j][0]) for k, j in old):
                gone.update(old)
                new.append(wd)
        if not new:
            continue
        all_erased.extend(erased)
        rebuilt = []
        for k, line in enumerate(lines):
            if k == host:
                merged = sorted([ow for j, ow in enumerate(line[2]) if (k, j) not in gone] + new, key=lambda wd: wd[1])
                rebuilt.append((_join_text(merged, all_erased), _box(merged), merged))
            elif any(g[0] == k for g in gone):
                rest = [ow for j, ow in enumerate(line[2]) if (k, j) not in gone]
                if rest:
                    rebuilt.append((_join_text(rest, all_erased), _box(rest), rest))
            else:
                rebuilt.append(line)
        lines = rebuilt
        extended += 1
    return lines, {'secondPassCrops': len(stretches), 'secondPassAdded': added, 'secondPassExtended': extended,
                   'secondPassMs': round((time.perf_counter() - started) * 1000, 2)}


def transcribe_image(path, *, scale=None, ocr_cache=None):
    """Return a raw UI Scene (dict) for one screenshot. Pure observation.

    ``ocr_cache`` (a directory) memoises the OCR reading per image bytes, so
    re-measuring pixel facts over a corpus does not re-run OCR.
    """
    from PIL import Image
    started = time.perf_counter()
    path = Path(path)
    raw = path.read_bytes()
    image = Image.open(path).convert('RGB')
    rgb = np.asarray(image)
    h, w = rgb.shape[:2]
    scale = scale or (2.0 if w < 800 else 1.5)
    big = image.resize((int(w * scale), int(h * scale)), Image.BICUBIC).convert('RGBA')
    t0 = time.perf_counter()
    memo = Path(ocr_cache) / (hashlib.sha256(raw).hexdigest()[:24] + f'-{scale}.json') if ocr_cache else None
    if memo and memo.exists():
        import json
        cached = json.loads(memo.read_text(encoding='utf-8'))
        ocr, ocr_error, ocr_ms = cached['lines'], None, cached['ms']
    else:
        try:
            ocr = _recognize(big)
            ocr_error = None
        except Exception as exc:  # OCR unavailable: keep pixel facts, mark text unknown.
            ocr, ocr_error = [], type(exc).__name__ + ': ' + str(exc)
        ocr_ms = (time.perf_counter() - t0) * 1000
        if memo and not ocr_error:
            import json
            memo.parent.mkdir(parents=True, exist_ok=True)
            memo.write_text(json.dumps({'lines': ocr, 'ms': ocr_ms}), encoding='utf-8')
    t1 = time.perf_counter()
    px = _Pixels(rgb)
    lines = []
    for text, words in ocr:
        words = [(t, x / scale, y / scale, ww / scale, hh / scale) for t, x, y, ww, hh in words]
        lines.append((text, _box(words), words))
    second = {}
    if not ocr_error and SECOND_PASS_ENABLED:
        lines, second = _second_pass(image, rgb, lines, Path(ocr_cache) if ocr_cache else None)
    # A panel side interrupted by a widget drawn across it is still one side.
    vlong = _merge_runs(_surface_edges(px, _merge_runs(_vertical_edge_runs(px, 60)), 'x'), gap=24)
    hlong = _surface_edges(px, _merge_runs(_horizontal_edge_runs(px, 120)), 'y')
    nodes = []
    boxes = []
    for i, (text, (x0, y0, x1, y1), words) in enumerate(lines):
        bg = px.background(x0, y0, x1, y1)
        X0, Y0, X1, Y1 = px.clamp_box(x0, y0, x1, y1)
        region = px.rgb[Y0:Y1, X0:X1]
        contrast = None
        if region.size:
            dist = px.distance(region, bg).reshape(-1)
            flat = region.reshape(-1, 3)
            if len(dist) >= 8 and dist.max() > 0:
                cut = np.quantile(dist, 0.9)
                fg = flat[dist >= cut].mean(axis=0)
                contrast = round(_contrast(fg, bg), 2)
        ellipsis_x = _ellipsis_after(px, bg, x1, y0, y1)
        gap = None if ellipsis_x is None else ellipsis_x
        textual_spaced = bool(_SPACED_ELLIPSIS.search(text))
        spaced = textual_spaced or (gap is not None and gap >= 5)
        # Glyph ink cut by the viewport edge (control or label off-screen).
        viewport_cut = bool((x1 >= w - 1.5 and (px.distance(px.rgb[Y0:Y1, w - 1:w], bg) > 45).any())
                            or (x0 <= 0.5 and (px.distance(px.rgb[Y0:Y1, 0:1], bg) > 45).any()))
        # Text continuing across a long surface boundary: a panel edge runs through it.
        crosses = []
        # A surface side is tall (>=35% of the viewport); a surface top/bottom
        # edge runs past the text on both ends. Text straddling either is paint
        # from another layer showing through that surface.
        for ex, es, ee in vlong:
            if (x0 + 6 < ex < x1 - 6 and ee - es >= 0.35 * h and es <= y0 - 9 and ee >= y1 + 9
                    and _local_step(px, 'x', ex, y0, y1, (es, ee))):
                crosses.append({'axis': 'x', 'at': ex, 'from': es, 'to': ee})
        for ey, es, ee in hlong:
            if (y0 + 2 < ey < y1 - 2 and es <= x0 - 6 and ee >= x1 + 6
                    and _local_step(px, 'y', ey, x0, x1, (es, ee))):
                crosses.append({'axis': 'y', 'at': ey, 'from': es, 'to': ee})
        if len(crosses) > 2:  # many parallel lines through one label: texture, not a surface edge
            crosses = []
        facts = {
            'source': 'pixels',
            'contrastRatio': contrast,
            'ellipsisGap': gap,
            'spacedEllipsis': spaced,
            'clippedText': bool(spaced),
            'crossesSurfaceEdge': crosses,
            'overlap': [],
            'viewportCut': viewport_cut,
            'offScreenControl': viewport_cut,
        }
        boxes.append((x0, y0, x1, y1))
        nodes.append({'id': f't{i}', 'kind': 'text',
                      'attributes': {'text': text, 'bounds': {'x': round(x0, 1), 'y': round(y0, 1), 'w': round(x1 - x0, 1), 'h': round(y1 - y0, 1)},
                                     'words': [t for t, *_ in words]},
                      'measurements': facts, 'relations': {}, 'certainty': 'observed'})
    for i, a in enumerate(boxes):
        for j in range(i + 1, len(boxes)):
            b = boxes[j]
            ix = min(a[2], b[2]) - max(a[0], b[0]); iy = min(a[3], b[3]) - max(a[1], b[1])
            if ix <= 2 or iy <= 2:
                continue
            smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
            if ix * iy >= 0.25 * smaller:
                nodes[i]['measurements']['overlap'].append(nodes[j]['id'])
                nodes[j]['measurements']['overlap'].append(nodes[i]['id'])
    for k, (x0, y0, x1, y1, vertical, inside, step) in enumerate(_pages(px, [(t, b) for t, b, _ in lines], vlong)):
        nodes.append({'id': f'g{k}', 'kind': 'page',
                      'attributes': {'text': '', 'bounds': {'x': x0, 'y': y0, 'w': x1 - x0, 'h': y1 - y0}},
                      'measurements': {'source': 'pixels', 'expectedContent': True, 'verticalDetail': round(vertical, 5),
                                       'borderStep': round(float(step), 1), 'textInside': len(inside),
                                       'uniform': bool(vertical < 0.05 and not inside)},
                      'relations': {'text': [f't{i}' for i in inside]}, 'certainty': 'observed'})
    for k, (tx0, tx1, xd, ty0, ty1) in enumerate(_detached_ellipses(px)):
        near = [n['id'] for n, bx in zip(nodes, boxes) if bx[0] - 4 <= tx1 and bx[2] + 4 >= tx0 and bx[1] - 4 <= ty1 and bx[3] + 4 >= ty0]
        if any(nodes[int(i[1:])]['measurements']['spacedEllipsis'] for i in near):
            continue  # already measured on the OCR line
        nodes.append({'id': f'd{k}', 'kind': 'text',
                      'attributes': {'text': ' '.join(nodes[int(i[1:])]['attributes']['text'] for i in near)[:200],
                                     'bounds': {'x': tx0, 'y': ty0, 'w': xd + 9 - tx0, 'h': ty1 - ty0}, 'words': []},
                      'measurements': {'source': 'pixels', 'spacedEllipsis': True, 'ellipsisGap': xd - tx1, 'contrastRatio': None,
                                       'clippedText': True, 'crossesSurfaceEdge': [], 'overlap': [],
                                       'viewportCut': False, 'offScreenControl': False, 'unread': not near},
                      'relations': {'ocr': near}, 'certainty': 'observed'})
    for k, (side, a, b) in enumerate(_edge_cuts(px)):
        near = [n['id'] for n, bx in zip(nodes, boxes) if bx[1] - 4 <= b and bx[3] + 4 >= a and
                ((side == 'right' and bx[2] >= w - 60) or (side == 'left' and bx[0] <= 60))]
        if not near:
            continue  # a cut must sit in a row of controls/labels next to the edge
        nodes.append({'id': f'e{k}', 'kind': 'viewport-edge',
                      'attributes': {'text': ' '.join(nodes[int(i[1:])]['attributes']['text'] for i in near)[:200],
                                     'bounds': {'x': w - 3 if side == 'right' else 0, 'y': a, 'w': 3, 'h': b - a}},
                      'measurements': {'source': 'pixels', 'offScreenControl': True, 'side': side},
                      'relations': {'nearText': near}, 'certainty': 'observed'})
    pixel_ms = (time.perf_counter() - t1) * 1000
    return {'surface': path.stem, 'layer': 'image', 'nodes': nodes,
            'viewport': {'width': w, 'height': h}, 'truncated': False, 'modelTranscription': False,
            'measured': 'approximate',
            'provenance': {'screenshotPath': str(path.resolve()), 'screenshotSha256': hashlib.sha256(raw).hexdigest(),
                           'ocr': OCR_IDENTITY + ':' + (_ocr_language() if not ocr_error else 'unavailable'),
                           'ocrScale': scale, 'ocrError': ocr_error},
            'metrics': {'ocrMs': round(ocr_ms, 2), 'pixelMs': round(pixel_ms, 2),
                        'totalMs': round((time.perf_counter() - started) * 1000, 2), 'lines': len(lines), **second}}
