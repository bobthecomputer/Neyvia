"""Fast outcome contracts for rendered video (plan 22 style), plus a fixture that proves each one bites.

Written on track/laya-video; since the reconciliation the contracts read the one video judge
(laya_video, vocabulary manuals/cl/laya-video.cl) in its fast mode.

``outcome(source)`` observes a render (no OCR of shots, no speech, no timeline) and answers:
render ok, duration and frame count, no unintended black or frozen frames, no clipping,
captions rendered and inside the safe area. ``proof()`` renders (once, then reuses) a
3-second fixture whose first 1.4 s are clean and whose rest carries a black gap, a frozen
hold, a clipped tone and a caption outside the safe area, and checks every contract
catches its own defect and stays quiet on the clean part.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import numpy as np

CONTRACTS = {
    "render-ok": ("render-failed",),
    "duration-and-frames": ("pacing-off-brief", "frame-count-off"),
    "no-black-frames": ("black-frames",),
    "no-frozen-frames": ("frozen-frames",),
    "audio-not-clipping": ("audio-clipping",),
    "captions-safe": ("caption-unsafe", "caption-not-rendered"),
}


def outcome(source):
    from .scene_core import judge, transcribe
    from .laya_video import probe, vocabulary
    started = time.perf_counter()
    try:
        meta = probe(source["video"])
        rendered = meta["frames"] > 0 or meta["durationS"] > 0
    except Exception as exc:  # no file, no stream: the render failed and nothing else can be observed
        return {"passed": False, "contracts": {"render-ok": {"passed": False, "findings": [{"predicate": "render-failed", "node": "video",
                "evidence": {"error": type(exc).__name__ + ": " + str(exc)[:200]}}], "unknown": []}}, "ms": round((time.perf_counter() - started) * 1000)}
    scene = transcribe("video", {**source, "fast": True})
    wanted = {p for ids in CONTRACTS.values() for p in ids}
    rules = [r for r in vocabulary() if r["id"] in wanted]
    verdict = judge(scene, rules, record=False)
    results = {}
    for name, predicates in CONTRACTS.items():
        hits = [f for f in verdict["findings"] if f["predicate"] in predicates]
        unknown = sorted(set(verdict["unknown"]) & set(predicates))
        passed = (rendered if name == "render-ok" else True) and not hits and not unknown
        results[name] = {"passed": passed, "findings": [{"predicate": f["predicate"], "node": f["node"],
                         "evidence": f["evidence"]} for f in hits][:6], "unknown": unknown}
    return {"passed": all(r["passed"] for r in results.values()), "contracts": results, "sceneSha256": scene["sha256"],
            "ms": round((time.perf_counter() - started) * 1000), "scene": scene}


def _scene_value(result, node, key):
    for n in result.get("scene", {}).get("nodes", []):
        if n["id"] == node:
            return n["measurements"].get(key)
    return None


def _fixture_media(folder):
    from PIL import Image, ImageDraw
    import soundfile
    folder.mkdir(parents=True, exist_ok=True)
    screen = folder / "screen.png"
    if not screen.exists():
        im = Image.new("RGB", (1280, 800), (14, 22, 17))
        d = ImageDraw.Draw(im)
        d.rectangle((0, 0, 220, 800), fill=(20, 32, 24))
        for i in range(8):
            d.rounded_rectangle((260, 60 + i * 88, 1220, 120 + i * 88), 10, fill=(28 + i * 4, 52, 38))
        im.save(screen)
    still = folder / "still.png"
    if not still.exists():
        im = Image.new("RGB", (1280, 800), (232, 226, 210))
        d = ImageDraw.Draw(im)
        for i in range(6):
            d.rounded_rectangle((120, 80 + i * 110, 1160, 150 + i * 110), 12, fill=(60 + i * 20, 110, 80))
        im.save(still)
    tone = folder / "tone.wav"
    if not tone.exists():
        sr = 48000
        t = np.arange(int(3.0 * sr)) / sr
        sig = 0.1 * np.sin(2 * np.pi * 440 * t)
        hot = t >= 1.5
        sig[hot] = np.clip(1.6 * np.sin(2 * np.pi * 220 * t[hot]), -1, 1)  # hard-clipped square-ish tone
        soundfile.write(str(tone), np.stack([sig, sig], axis=1).astype(np.float32), sr, subtype="FLOAT")
    return screen, still, tone


FIXTURE_BRIEF = {"duration": 3.0, "width": 640, "height": 360, "aspect": "16:9", "allowBlackHeadTail": 0.2, "freezeMinS": 0.5,
                 "safeArea": 0.05, "loudness": {"maxTruePeakDbtp": -1.0}}


def proof(folder=None):
    from . import video_hyperframes as hf
    started = time.perf_counter()
    folder = Path(folder or hf.RUNS / "contracts-fixture")
    screen, still, tone = _fixture_media(folder / "media")
    project = folder / "project"
    edl = {"schema": hf.SCHEMA, "id": "contracts-fixture", "title": "Video contracts fixture", "width": 640, "height": 360, "fps": 15,
           "duration": 3.0, "background": "#0a0f0c", "style": {**hf.DEFAULT_STYLE, "captionSize": 22, "screenMargin": 40},
           "clips": [
               {"id": "clean", "kind": "image", "start": 0.0, "duration": 1.4, "track": 0, "src": str(screen), "fit": "card",
                "keyframes": [{"property": "scale", "at": 0, "value": 1.0, "ease": "none"}, {"property": "scale", "at": 1.4, "value": 1.06, "ease": "none"}]},
               {"id": "held", "kind": "image", "start": 2.0, "duration": 1.0, "track": 0, "src": str(still), "fit": "card"},
               {"id": "cap-safe", "kind": "caption", "start": 0.2, "duration": 1.0, "track": 3, "text": "Inside the safe area"},
               {"id": "cap-edge", "kind": "caption", "start": 2.1, "duration": 0.8, "track": 3, "text": "Off the edge text",
                "place": {"left": 300, "top": 2}},
               {"id": "tone", "kind": "audio", "start": 0.0, "duration": 3.0, "track": 5, "src": str(tone), "volume": 1.0}]}
    digest = hashlib.sha256(json.dumps(edl, sort_keys=True).encode()).hexdigest()[:16]
    video = folder / f"fixture-{digest}.mp4"
    rendered = None
    if not video.is_file():
        project.mkdir(parents=True, exist_ok=True)
        hf.save(project, edl)
        rendered = hf.render(project, video, quality="draft", workers=2)
        if not rendered["ok"]:
            return {"passed": False, "reason": "fixture render failed", "render": rendered}
    elif not hf.edl_path(project).is_file():
        project.mkdir(parents=True, exist_ok=True)
        hf.save(project, edl)
    # HyperFrames' own mixer limits peaks (about -1.3 dBFS), so its render cannot carry a clipped mix. The clipping
    # case therefore muxes the raw clipped tone over the same HyperFrames picture.
    clipped = folder / f"fixture-{digest}-raw-audio.mp4"
    if not clipped.is_file():
        from .laya_video import tools, _run
        _run([tools()["ffmpeg"], "-v", "error", "-y", "-i", str(video), "-i", str(tone), "-map", "0:v", "-map", "1:a", "-c:v", "copy",
              "-c:a", "aac", "-b:a", "256k", "-shortest", str(clipped)], timeout=120)
    hf_mix = outcome({"video": str(video), "project": str(project), "brief": FIXTURE_BRIEF, "workdir": str(folder / "laya")})
    result = outcome({"video": str(clipped), "project": str(project), "brief": FIXTURE_BRIEF, "workdir": str(folder / "laya-raw")})
    c = result["contracts"]
    def nodes(name, predicate):
        return [f for f in c[name]["findings"] if f["predicate"] == predicate]
    black = nodes("no-black-frames", "black-frames")
    frozen = nodes("no-frozen-frames", "frozen-frames")
    edge = nodes("captions-safe", "caption-unsafe")
    at = lambda f, key: (f["evidence"].get("measurements." + key) if f["evidence"].get("measurements." + key) is not None
                         else (_scene_value(result, f["node"], key)))
    expectations = {
        "render-ok": c["render-ok"]["passed"],
        "duration-and-frames": c["duration-and-frames"]["passed"],
        "black gap caught at 1.4-2.0 s": any(1.2 <= (at(f, "blackStartS") or -1) <= 1.6 for f in black),
        "frozen hold caught after 2.0 s": any((at(f, "frozenStartS") or -1) >= 1.9 for f in frozen),
        "clean section has no black or frozen finding before 1.2 s": not any((at(f, "blackStartS") or 9) < 1.2 for f in black)
                                                                    and not any((at(f, "frozenStartS") or 9) < 1.2 for f in frozen),
        "raw clipped tone caught": not c["audio-not-clipping"]["passed"],
        "HyperFrames mix of the same tone passes (its limiter)": hf_mix["contracts"]["audio-not-clipping"]["passed"],
        "edge caption caught, safe caption passes": len(edge) == 1 and edge[0]["node"] == "caption:cap-edge",
    }
    return {"passed": all(expectations.values()), "expectations": expectations, "video": str(video), "reusedRender": rendered is None,
            "render": rendered and {"seconds": rendered["seconds"]}, "outcome": {k: v for k, v in result.items() if k != "scene"}, "hyperframesMixOutcome": {k: v for k, v in hf_mix.items() if k != "scene"},
            "ms": round((time.perf_counter() - started) * 1000)}
