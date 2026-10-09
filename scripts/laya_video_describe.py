"""Evidence script (plan 29 VID): LAYA describes a rendered video in words, so a model can correct the
scene from text instead of looking at frames itself.

Works on any MP4 (fframes, HyperFrames, Remotion). Every sentence comes from a measurement on decoded
frames: per-second motion, static spans, where content sits and how much of the frame it covers, empty
regions, and the text Windows OCR reads at a few keyframes. No model call, so the description costs
zero tokens to make; the model only reads a few hundred words.

    python scripts/laya_video_describe.py D:/NeyviaRuns/29-VID/fframes-test/test.mp4 [--json out.json]
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from grant_agent import laya_video as V  # noqa: E402

W, H = 160, 90          # analysis grid (area-scaled gray frames)
CHANGE = 6.0            # a grid cell changed when its gray level moves by more than this
STATIC = 0.0005         # share of changed cells under which a frame counts as still
INK = 18.0              # pixel above the frame's background level by this much counts as content


def _background(frame):
    return float(np.median(frame))  # the dominant level: dark UI or a white page alike


def _content_mask(frame):
    return np.abs(frame - _background(frame)) > INK  # dark text on a light page counts as content too


def _region_name(cx, cy):
    col = "left" if cx < 1 / 3 else "right" if cx > 2 / 3 else "centre"
    row = "top" if cy < 1 / 3 else "bottom" if cy > 2 / 3 else "middle"
    return "centre" if (row, col) == ("middle", "centre") else f"{row} {col}" if col != "centre" else f"{row} centre"


def describe(mp4, keyframes=None, scratch=None):
    started = time.perf_counter()
    meta = V.probe(mp4)
    fps = meta["fps"] or 30.0
    gray = V.decode_gray(mp4, W, H)
    n = len(gray)
    diffs = np.concatenate([[0.0], (np.abs(np.diff(gray, axis=0)) > CHANGE).mean(axis=(1, 2))])
    seconds = int(np.ceil(n / fps))
    motion = [round(float(diffs[int(s * fps):int((s + 1) * fps)].mean()) * 100, 2) for s in range(seconds)]  # % of frame changing

    lag = max(1, int(round(fps)))  # slow ambient motion (a drifting canopy) changes too little per frame; compare 1 s apart
    slow = np.concatenate([np.zeros(lag), (np.abs(gray[lag:] - gray[:-lag]) > CHANGE).mean(axis=(1, 2))]) if n > lag else np.zeros(n)
    slow_motion = [round(float(slow[int(s * fps):int((s + 1) * fps)].mean()) * 100, 2) for s in range(seconds)]
    still = (diffs < STATIC) & (np.concatenate([slow[lag:], slow[-lag:] if n > lag else slow]) < STATIC)
    spans, start = [], None
    for i, s in enumerate(list(still) + [False]):
        if s and start is None:
            start = i
        elif not s and start is not None:
            if (i - start) / fps >= 1.0:
                spans.append((round(start / fps, 2), round(i / fps, 2)))
            start = None

    blank = [i for i in range(n) if not _content_mask(gray[i]).any()]
    occupancy = []
    for i in range(0, n, max(1, int(fps / 2))):
        mask = _content_mask(gray[i])
        if not mask.any():
            occupancy.append((i / fps, 0.0, None, 0.0))
            continue
        ys, xs = np.nonzero(mask)
        box = (xs.min() / W, ys.min() / H, (xs.max() + 1) / W, (ys.max() + 1) / H)
        cover = float(mask.mean())
        empty_bottom = float(1 - (ys.max() + 1) / H)
        occupancy.append((i / fps, cover, box, empty_bottom))

    keyframes = keyframes or max(4, int(meta["durationS"] // 4))  # one read every ~4 s, so each beat of a long film is read
    times = [meta["durationS"] * (k + 1) / (keyframes + 1) for k in range(keyframes)]
    scratch = Path(scratch or (Path(mp4).parent / f"laya-describe-{Path(mp4).stem}"))  # per video: keyframes are cached by time
    texts = []
    for t, png in zip(times, V.frames_at(mp4, times, scratch)):
        try:
            lines = V.ocr_lines(png)
        except Exception as error:  # noqa: BLE001 - OCR is optional on machines without Windows OCR
            lines = [{"text": f"(OCR unavailable: {type(error).__name__})", "box": [0, 0, 0, 0]}]
        rows = [{"text": l["text"], "heightPx": l["box"][3], "box": l["box"]} for l in lines]
        clashes = []
        from PIL import Image
        with Image.open(png) as im:
            g = np.asarray(im.convert("L"), dtype=np.float32)
        floor = float(np.median(g))
        for big in rows:
            if big["heightPx"] < 48:
                continue
            bx, by, bw, bh = (int(v) for v in big["box"])
            band = g[by:by + bh, bx + bw + 2:bx + bw + 40]  # the 38 px just right of the line
            if band.size and float((np.abs(band - floor) > INK).mean()) > 0.08:
                clashes.append({"big": big["text"], "small": "content right next to it", "gapPx": 0})
        fw = meta["width"]
        cut = [r["text"] for r in rows if r["heightPx"] >= 14 and (r["box"][0] <= 3 or r["box"][0] + r["box"][2] >= fw - 3)]  # a line touching the frame edge is cut by the crop
        texts.append({"t": round(t, 2), "lines": [{k: r[k] for k in ("text", "heightPx")} for r in rows[:8]], "clashes": clashes[:3], "cutAtEdge": cut[:4]})

    facts = {"file": str(mp4), "width": meta["width"], "height": meta["height"], "fps": round(fps, 2),
             "durationS": round(meta["durationS"], 2), "motionPerSecond": motion, "slowMotionPerSecond": slow_motion, "stillSpans": spans,
             "blankFrames": len(blank), "keyframeText": texts,
             "occupancy": [{"t": round(t, 2), "cover": round(c, 3), "box": [round(v, 3) for v in b] if b else None,
                            "emptyBottom": round(e, 3)} for t, c, b, e in occupancy]}
    facts["text"] = narrate(facts)
    facts["describeSeconds"] = round(time.perf_counter() - started, 1)
    return facts


def narrate(f):
    out = [f"{f['durationS']} s at {f['width']}x{f['height']} {f['fps']} fps."]
    lit = [o for o in f["occupancy"] if o["box"]]
    if lit and lit[0]["t"] > 0.4:
        out.append(f"The first {lit[0]['t']:.1f} s show only the background.")
    for a, b in f["stillSpans"]:
        out.append(f"Nothing moves from {a:.1f} s to {b:.1f} s ({b - a:.1f} s of still frame).")
    peak = max(range(len(f["motionPerSecond"])), key=lambda s: f["motionPerSecond"][s])
    out.append(f"Most motion is in second {peak}-{peak + 1}; share of the frame changing per second (%): {f['motionPerSecond']}.")
    slow = f.get("slowMotionPerSecond") or []
    if slow and max(f["motionPerSecond"]) < 0.05 and max(slow) >= 0.05:
        out.append(f"Frame to frame nothing changes, but compared 1 s apart the picture drifts (% changed: {slow}): slow ambient motion, calm rather than still.")
    if lit:
        mid = lit[len(lit) // 2]
        x0, y0, x1, y1 = mid["box"]
        out.append(f"At {mid['t']:.1f} s content spans x {x0:.0%}-{x1:.0%}, y {y0:.0%}-{y1:.0%} "
                   f"(centre {_region_name((x0 + x1) / 2, (y0 + y1) / 2)}), lit pixels {mid['cover']:.0%} of the frame; "
                   f"the bottom {mid['emptyBottom']:.0%} is empty.")
    for k in f["keyframeText"]:
        words = "; ".join(f"\"{l['text']}\" ({l['heightPx']:.0f} px)" for l in k["lines"]) or "no readable text"
        out.append(f"Text read at {k['t']:.1f} s: {words}.")
    for k in f["keyframeText"]:
        for c in k.get("clashes", []):
            out.append(f"At {k['t']:.1f} s the large text \"{c['big']}\" touches other content on its right (under 40 px of space): give the title its own space or move the content.")
            break
    cut = [(k["t"], c) for k in f["keyframeText"] for c in k.get("cutAtEdge", [])]
    if cut:
        out.append("Text is cut by the frame edge (the crop slices it): " + "; ".join(f"\"{c}\" at {t:.1f} s" for t, c in cut[:6]) + ". Frame wider or move the content in.")
    small = sorted({round(l["heightPx"]) for k in f["keyframeText"] for l in k["lines"] if 0 < l["heightPx"] < 16})
    if small:
        out.append(f"Some text is only {small[0]}-{small[-1]} px tall at {f['height']}p, too small to read; enlarge what must be read or let it go.")
    if f["blankFrames"]:
        out.append(f"{f['blankFrames']} frames are blank.")
    return " ".join(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    facts = describe(args.video)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(facts, indent=2), encoding="utf-8")
    print(facts["text"])
    print(f"(described in {facts['describeSeconds']} s, 0 model tokens; {len(facts['text'].split())} words for the model)")


if __name__ == "__main__":
    main()
