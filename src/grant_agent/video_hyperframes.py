"""Edit decision lists compiled to HyperFrames compositions, driven headless.

HyperFrames (github.com/heygen-com/hyperframes, Apache-2.0, HeyGen) renders an
HTML composition (clips as elements with ``data-start``/``data-duration``,
seekable GSAP timelines) to MP4 with headless Chrome and FFmpeg. Neyvia adapts
it rather than forking it: an agent edits a small JSON edit decision list (EDL),
every edit recompiles the project's ``index.html`` in HyperFrames' own format,
and the HyperFrames CLI lints, reads the timeline back, renders and serves
Studio. Nothing here opens a window: renders use HyperFrames' headless shell,
Studio is started with ``--no-open`` on an explicit port.

Written on track/laya-video (plan 28) and kept as the free-form editing layer of the one video
stack: projects made here are rendered with the same HyperFrames install, headless shell and
Inter brand font as ``laya_video`` (``laya_video.tools()``), and judged by the one ``video`` adapter.
"""
from __future__ import annotations

import copy
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from .subprocess_utils import hidden_windows_subprocess_kwargs

SCHEMA = "neyvia.video.edl.v1"
RUNS = Path(os.environ.get("NEYVIA_VIDEO_RUNS", r"D:\NeyviaRuns\video"))
HF_HOME = Path(os.environ.get("NEYVIA_HYPERFRAMES_HOME", str(RUNS / "hf")))
KINDS = ("image", "video", "text", "caption", "audio")
TRANSITIONS = ("none", "fade", "crossfade", "slide", "rise", "zoom")
PROPERTIES = ("scale", "x", "y", "opacity")
EASES = ("none", "power1.inOut", "power2.out", "power2.inOut", "power3.out", "sine.inOut", "expo.out")
PORTS = range(49165, 49168)  # track VIDEO block (49161-49169); 49161-49164 are capture/DOM ports
DEFAULT_STYLE = {
    "font": {"family": "Inter", "file": None},
    "captionColor": "#f1ede3", "captionSize": 46, "captionWeight": 500,
    "captionPlate": None, "captionPosition": "bottom", "captionBand": 0,
    "titleColor": "#f1ede3", "titleSize": 96, "titleWeight": 560,
    "screenRadius": 14, "screenShadow": "0 30px 90px rgba(0,0,0,.35)", "screenMargin": 96,
    "safe": 0.05,
}


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def allowed_roots(root=None):
    roots = [RUNS.resolve()]
    if root:
        roots.append(Path(root).resolve())
    return roots


def confine(path, root=None):
    """Resolve a project or media path; it must stay under the workspace or the video runs folder."""
    target = Path(path).expanduser()
    if not target.is_absolute():
        target = (Path(root) if root else RUNS) / target
    target = target.resolve()
    for base in allowed_roots(root):
        if target == base or target.is_relative_to(base):
            return target
    raise ValueError("Video paths must stay inside the workspace or " + str(RUNS))


def media_path(path, root=None):
    """Source media may come from any readable local file (screenshots, renders); it is copied into the project."""
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise ValueError("Media file does not exist: " + str(target))
    for forbidden in (Path("C:/Users/user/Projects/Neyvia"), Path("C:/Users/user/Projects/Neyvia-next")):
        if target.is_relative_to(forbidden.resolve()):
            raise ValueError("Live Neyvia folders are outside the video scope")
    return target


# --- EDL ------------------------------------------------------------------

def edl_path(project):
    return Path(project) / "edl.json"


def load(project):
    return json.loads(edl_path(project).read_text(encoding="utf-8"))


def save(project, edl, *, compile_now=True):
    validate(edl)
    edl["updatedAt"] = _now()
    edl_path(project).write_text(json.dumps(edl, indent=1, ensure_ascii=False), encoding="utf-8")
    if compile_now:
        compile_project(project, edl)
    return edl


def new_project(project, *, width=1920, height=1080, fps=30, duration=None, background="#0a0f0c", style=None, title=""):
    project = Path(project)
    if edl_path(project).exists():
        raise ValueError("A video project already exists here")
    project.mkdir(parents=True, exist_ok=True)
    edl = {"schema": SCHEMA, "id": re.sub(r"[^a-z0-9-]+", "-", project.name.lower()).strip("-") or "video", "title": title,
           "width": int(width), "height": int(height), "fps": int(fps), "duration": duration, "background": background,
           "style": {**copy.deepcopy(DEFAULT_STYLE), **(style or {})}, "clips": [], "createdAt": _now(), "history": []}
    return save(project, edl)


def end_of(edl):
    return max((c["start"] + c["duration"] for c in edl["clips"]), default=0.0)


def duration_of(edl):
    return float(edl["duration"]) if edl.get("duration") else round(end_of(edl), 3)


def _number(value, name, low=0.0, high=3600.0):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
        raise ValueError(f"{name} must be a number in [{low}, {high}]")
    return round(float(value), 4)


def validate(edl):
    if edl.get("schema") != SCHEMA:
        raise ValueError("Expected a neyvia.video.edl.v1 document")
    for key, low, high in (("width", 16, 7680), ("height", 16, 7680), ("fps", 1, 240)):
        if not isinstance(edl.get(key), int) or not low <= edl[key] <= high:
            raise ValueError(f"{key} must be an integer in [{low}, {high}]")
    ids = [c["id"] for c in edl["clips"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Clip ids must be unique")
    for c in edl["clips"]:
        if c["kind"] not in KINDS or not re.fullmatch(r"[a-z][a-z0-9-]{0,47}", c["id"]):
            raise ValueError("Clip needs a known kind and a lowercase id")
        _number(c["start"], "start")
        _number(c["duration"], "duration", 0.04)
        for edge in ("transitionIn", "transitionOut"):
            t = c.get(edge)
            if t and (t.get("kind") not in TRANSITIONS or not 0 <= t.get("seconds", 0) <= 5):
                raise ValueError("Unknown transition or length outside 0..5 s")
        for k in c.get("keyframes", []):
            if k["property"] not in PROPERTIES or k.get("ease", "power2.inOut") not in EASES:
                raise ValueError("Keyframes animate scale, x, y or opacity with a known ease")
            _number(k["at"], "keyframe time", 0, c["duration"] + 1e-6)
    return True


def _record(edl, op, **details):
    edl.setdefault("history", []).append({"op": op, "at": _now(), **details})
    edl["history"] = edl["history"][-400:]


def _clip(edl, clip_id):
    for c in edl["clips"]:
        if c["id"] == clip_id:
            return c
    raise ValueError("No clip with id " + str(clip_id))


def _next_id(edl, kind):
    prefix = {"image": "shot", "video": "vid", "text": "title", "caption": "cap", "audio": "aud"}[kind]
    n = 1
    taken = {c["id"] for c in edl["clips"]}
    while f"{prefix}-{n}" in taken:
        n += 1
    return f"{prefix}-{n}"


def add_clip(edl, kind, *, start, duration, src=None, text=None, id=None, track=None, fit=None, volume=None,
             media_start=None, fade_in=None, fade_out=None, tags=None, intent=None, box=None, scale=None, hold=False, root=None):
    if kind not in KINDS:
        raise ValueError("Clip kind is image, video, text, caption or audio")
    clip = {"id": id or _next_id(edl, kind), "kind": kind, "start": _number(start, "start"),
            "duration": _number(duration, "duration", 0.04),
            "track": int(track if track is not None else {"image": 0, "video": 0, "text": 2, "caption": 3, "audio": 5}[kind])}
    if kind in ("image", "video", "audio"):
        if not src:
            raise ValueError(kind + " clips need a source file")
        clip["src"] = str(media_path(src, root))
    if kind in ("text", "caption"):
        if not isinstance(text, str) or not text.strip() or len(text) > 240:
            raise ValueError("Text and captions need 1..240 characters")
        clip["text"] = text.strip()
    if kind in ("image", "video"):
        clip["fit"] = fit or "card"
        if box:
            clip["box"] = {k: float(box[k]) for k in ("x", "y", "w", "h")}
        if scale:
            clip["scale"] = float(scale)
    if kind in ("video", "audio"):
        if media_start is not None:
            clip["mediaStart"] = _number(media_start, "mediaStart")
        if volume is not None:
            clip["volume"] = _number(volume, "volume", 0, 3.98)
        if fade_in is not None:
            clip["fadeIn"] = _number(fade_in, "fadeIn", 0, 30)
        if fade_out is not None:
            clip["fadeOut"] = _number(fade_out, "fadeOut", 0, 30)
    if tags:
        clip["tags"] = [str(t) for t in tags][:12]
    if intent:
        clip["intent"] = str(intent)
    if hold:
        clip["hold"] = True
    edl["clips"].append(clip)
    _record(edl, "add", id=clip["id"], kind=kind)
    return clip


def trim(edl, clip_id, *, start=None, duration=None, media_start=None):
    c = _clip(edl, clip_id)
    if start is not None:
        delta = _number(start, "start") - c["start"]
        c["start"] = _number(start, "start")
        if c["kind"] in ("video", "audio") and media_start is None:
            c["mediaStart"] = round(max(0.0, c.get("mediaStart", 0) + delta), 4)
    if duration is not None:
        c["duration"] = _number(duration, "duration", 0.04)
        c["keyframes"] = [k for k in c.get("keyframes", []) if k["at"] <= c["duration"]]
    if media_start is not None:
        c["mediaStart"] = _number(media_start, "mediaStart")
    _record(edl, "trim", id=clip_id)
    return c


def split(edl, clip_id, at):
    """Split at an absolute time; the second half gets id '<id>-b' and the matching source offset."""
    c = _clip(edl, clip_id)
    at = _number(at, "at")
    if not c["start"] + 0.04 <= at <= c["start"] + c["duration"] - 0.04:
        raise ValueError("Split point must fall inside the clip")
    second = copy.deepcopy(c)
    first_len = round(at - c["start"], 4)
    second["id"] = c["id"] + "-b"
    while any(x["id"] == second["id"] for x in edl["clips"]):
        second["id"] += "b"
    second["start"] = at
    second["duration"] = round(c["duration"] - first_len, 4)
    if c["kind"] in ("video", "audio"):
        second["mediaStart"] = round(c.get("mediaStart", 0) + first_len, 4)
    # Motion continues across the split: both halves get the (linearly interpolated) value at the split point.
    keys = c.get("keyframes", [])
    edge = []
    for prop in sorted({k["property"] for k in keys}):
        rows = sorted((k for k in keys if k["property"] == prop), key=lambda k: k["at"])
        lo = [k for k in rows if k["at"] <= first_len]
        hi = [k for k in rows if k["at"] >= first_len]
        if lo and hi and hi[0]["at"] > lo[-1]["at"]:
            a, b = lo[-1], hi[0]
            value = a["value"] + (b["value"] - a["value"]) * (first_len - a["at"]) / (b["at"] - a["at"])
            edge.append({"property": prop, "value": round(value, 5), "ease": "none"})
            b["ease"] = "none"  # an eased segment cut in two would stall at the cut; both halves move linearly
    second["keyframes"] = [{**k, "at": round(k["at"] - first_len, 4)} for k in keys if k["at"] >= first_len] + \
                          [{**e, "at": 0.0} for e in edge]
    c["keyframes"] = [k for k in keys if k["at"] <= first_len] + [{**e, "at": first_len} for e in edge]
    for clip in (c, second):
        clip["keyframes"] = sorted(clip["keyframes"], key=lambda k: (k["property"], k["at"]))
    c["duration"] = first_len
    c.pop("transitionOut", None)
    second.pop("transitionIn", None)
    edl["clips"].insert(edl["clips"].index(c) + 1, second)
    _record(edl, "split", id=clip_id, at=at, second=second["id"])
    return second


def visual(edl):
    return sorted((c for c in edl["clips"] if c["kind"] in ("image", "video", "text")), key=lambda c: (c["start"], c["track"]))


def previous_visual(edl, clip):
    before = [c for c in visual(edl) if c is not clip and c["start"] < clip["start"] and c["kind"] != "text"]
    return max(before, key=lambda c: c["start"] + c["duration"], default=None)


def transition(edl, clip_id, kind, seconds, edge="in"):
    """Set an entrance or exit. A crossfade entrance makes the previous shot overlap this one."""
    c = _clip(edl, clip_id)
    if kind not in TRANSITIONS or edge not in ("in", "out"):
        raise ValueError("Unknown transition or edge")
    seconds = _number(seconds, "seconds", 0, 5)
    c["transitionIn" if edge == "in" else "transitionOut"] = {"kind": kind, "seconds": seconds}
    if kind == "crossfade" and edge == "in":
        prev = previous_visual(edl, c)
        if prev:
            prev["duration"] = round(max(prev["duration"], c["start"] + seconds - prev["start"]), 4)
    _record(edl, "transition", id=clip_id, kind=kind, seconds=seconds, edge=edge)
    return c


def keyframe(edl, clip_id, prop, at, value, ease="power2.inOut"):
    c = _clip(edl, clip_id)
    if prop not in PROPERTIES or ease not in EASES:
        raise ValueError("Keyframes animate scale, x, y or opacity with a known ease")
    at = _number(at, "at", 0, c["duration"])
    rows = [k for k in c.get("keyframes", []) if not (k["property"] == prop and abs(k["at"] - at) < 1e-4)]
    rows.append({"property": prop, "at": at, "value": float(value), "ease": ease})
    c["keyframes"] = sorted(rows, key=lambda k: (k["property"], k["at"]))
    _record(edl, "keyframe", id=clip_id, property=prop, at=at)
    return c


def remove(edl, clip_id):
    c = _clip(edl, clip_id)
    edl["clips"].remove(c)
    _record(edl, "remove", id=clip_id)
    return c


# --- compile to HyperFrames ------------------------------------------------

def _asset(project, src, cache):
    if src in cache:
        return cache[src]
    data = Path(src).read_bytes()
    stem = re.sub(r"[^a-z0-9.]+", "-", Path(src).stem.lower()).strip("-")[:40] or "asset"
    name = stem + "-" + hashlib.sha256(data).hexdigest()[:12] + Path(src).suffix.lower()
    target = Path(project) / "assets" / name
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    cache[src] = "assets/" + name
    return cache[src]


def _image_size(path):
    from PIL import Image
    with Image.open(path) as image:
        return image.size


def _font_source(style):
    name = style.get("font", {}).get("file")
    if not name:
        from .laya_video import tools
        font = tools().get("font")
        return Path(font) if font and style.get("font", {}).get("family") == "Inter" else None
    candidate = Path(name)
    if not candidate.is_absolute():
        candidate = HF_HOME / "node_modules/@fontsource-variable/geist/files" / name
    return candidate if candidate.is_file() else None


def layout_box(edl, clip):
    """The pixel rectangle a screen is fitted into: the clip's own box, else the frame minus margins and caption band."""
    W, H, style = edl["width"], edl["height"], edl["style"]
    if clip.get("box"):
        b = clip["box"]
        return b["x"], b["y"], b["w"], b["h"]
    if clip.get("fit") in ("contain", "cover"):
        return 0.0, 0.0, float(W), float(H)
    margin = float(style.get("screenMargin", 96))
    band = float(style.get("captionBand", 0) or 0)
    top = margin * 0.6
    return margin, top, W - 2 * margin, H - top - max(margin * 0.6, band)


def placement(edl, clip):
    """Displayed rectangle of an image screen (object-fit maths done here so radius and shadow hug the pixels)."""
    x, y, w, h = layout_box(edl, clip)
    iw, ih = _image_size(clip["src"])
    fit = clip.get("fit", "card")
    s = max(w / iw, h / ih) if fit == "cover" else min(w / iw, h / ih)
    s *= float(clip.get("scale", 1.0))
    dw, dh = iw * s, ih * s
    return {"x": round(x + (w - dw) / 2, 1), "y": round(y + (h - dh) / 2, 1), "w": round(dw, 1), "h": round(dh, 1),
            "sourceW": iw, "sourceH": ih}


def caption_css(edl, *, title=False):
    style, W, H = edl["style"], edl["width"], edl["height"]
    family = style.get("font", {}).get("family", "Geist")
    size = style["titleSize" if title else "captionSize"]
    weight = style["titleWeight" if title else "captionWeight"]
    colour = style["titleColor" if title else "captionColor"]
    css = [f"font-family:'{family}',system-ui,sans-serif", f"font-size:{size}px", f"font-weight:{weight}", f"color:{colour}",
           "line-height:1.18", "letter-spacing:-0.01em", "text-align:center", "white-space:normal"]
    if title:
        css += ["position:absolute", "inset:0", "display:flex", "align-items:center", "justify-content:center",
                f"padding:0 {int(W * .12)}px"]
        return ";".join(css)
    band = float(style.get("captionBand", 0) or 0)
    safe = float(style.get("safe", 0.05))
    if band:
        bottom = max(H * safe, (band - size * 1.2) / 2)
    else:
        bottom = H * (0.085 if style.get("captionPosition") == "bottom" else 0.2)
    # The timed row spans the frame and centres an inline-block caption (text-align), so every engine that
    # reads the composition DOM (Chrome for renders, Obscura for caption boxes) lays it out the same way.
    row = ["position:absolute", "left:0", "right:0", "text-align:center", f"bottom:{round(bottom)}px"]
    css += ["display:inline-block", f"max-width:{int(W * 0.8)}px"]
    plate = style.get("captionPlate")
    if plate:
        css += [f"background:{plate}", "padding:14px 30px", "border-radius:14px"]
    return ";".join(row), ";".join(css)


def compile_project(project, edl=None):
    """Write index.html in the HyperFrames composition format from the EDL."""
    project = Path(project)
    edl = edl or load(project)
    validate(edl)
    W, H, style = edl["width"], edl["height"], edl["style"]
    cache = {}
    from .laya_video import tools
    gsap = Path(tools()["gsap"] or HF_HOME / "node_modules/gsap/dist/gsap.min.js")
    if not gsap.is_file():
        raise RuntimeError("GSAP is missing next to the HyperFrames install")
    gsap_rel = _asset(project, str(gsap), cache)
    font = _font_source(style)
    font_face = ""
    if font:
        font_face = (f"@font-face{{font-family:'{style['font']['family']}';src:url({_asset(project, str(font), cache)}) format('woff2');"
                     "font-weight:100 900;font-style:normal;font-display:block}")
    total = duration_of(edl)
    body, script = [], []
    order = sorted(edl["clips"], key=lambda c: (c["track"], c["start"]))
    for z, c in enumerate(order, 1):
        cid = "c-" + c["id"]
        timing = f'data-start="{c["start"]}" data-duration="{c["duration"]}" data-track-index="{c["track"]}"'
        if c["kind"] == "image":
            p = placement(edl, c)
            radius = 0 if c.get("fit") in ("cover", "contain") else style.get("screenRadius", 14)
            shadow = "none" if c.get("fit") in ("cover", "contain") else style.get("screenShadow")
            css = (f"position:absolute;left:{p['x']}px;top:{p['y']}px;width:{p['w']}px;height:{p['h']}px;"
                   f"border-radius:{radius}px;box-shadow:{shadow};z-index:{c['track'] * 100 + z};transform-origin:50% 50%")
            body.append(f'<img id="{cid}" class="clip shot" src="{_asset(project, c["src"], cache)}" {timing} style="{css}" alt="">')
        elif c["kind"] == "video":
            p = placement(edl, c) if c["src"].lower().endswith((".png", ".jpg")) else None
            css = f"position:absolute;inset:0;width:100%;height:100%;object-fit:{'cover' if c.get('fit') == 'cover' else 'contain'};z-index:{c['track'] * 100 + z}"
            sound = ' data-has-audio="true"' if c.get("volume", 0) > 0 else " muted"
            media = f' data-media-start="{c["mediaStart"]}"' if c.get("mediaStart") else ""
            body.append(f'<video id="{cid}" src="{_asset(project, c["src"], cache)}" {timing}{media}{sound} playsinline style="{css}"></video>')
        elif c["kind"] == "text":
            css = caption_css(edl, title=True) + f";z-index:{c['track'] * 100 + z}"
            body.append(f'<div id="{cid}" class="clip text" {timing} style="{css}">{html.escape(c["text"])}</div>')
        elif c["kind"] == "caption":
            row, css = caption_css(edl)
            row += f";z-index:{c['track'] * 100 + z}"
            if c.get("place"):  # explicit placement overrides the style's caption position
                row = f"position:absolute;left:{float(c['place']['left'])}px;top:{float(c['place']['top'])}px;z-index:{c['track'] * 100 + z}"
            body.append(f'<div id="{cid}" class="clip caption-row" {timing} style="{row}"><div id="ct-{c["id"]}" class="caption" style="{css}">'
                        f'{html.escape(c["text"])}</div></div>')
        elif c["kind"] == "audio":
            attrs = "".join(f' data-{name}="{c[key]}"' for key, name in (("volume", "volume"), ("fadeIn", "fade-in"),
                                                                        ("fadeOut", "fade-out"), ("mediaStart", "media-start")) if key in c)
            body.append(f'<audio id="{cid}" src="{_asset(project, c["src"], cache)}" {timing}{attrs}></audio>')
        if c["kind"] == "audio":
            continue
        sel = json.dumps("#" + cid)
        t_in, t_out = c.get("transitionIn") or {}, c.get("transitionOut") or {}
        has_scale = any(k["property"] == "scale" for k in c.get("keyframes", []))
        if t_in.get("kind", "none") != "none" and t_in.get("seconds", 0) > 0:
            s, d = c["start"], t_in["seconds"]
            frm, to = {"opacity": 0}, {"opacity": 1}
            if t_in["kind"] == "slide":
                frm["x"], to["x"] = round(W * 0.05), 0
            if t_in["kind"] == "rise":
                frm["y"], to["y"] = 36, 0
            if t_in["kind"] == "zoom" and not has_scale:
                frm["scale"], to["scale"] = 1.04, 1
            to.update(duration=d, ease="power2.out")
            script.append(f"tl.fromTo({sel},{json.dumps(frm)},{json.dumps(to)},{s});")
        for prop in PROPERTIES:
            keys = sorted((k for k in c.get("keyframes", []) if k["property"] == prop), key=lambda k: k["at"])
            if not keys:
                continue
            script.append(f"tl.set({sel},{{{prop}:{keys[0]['value']}}},{c['start'] + keys[0]['at']});")
            for a, b in zip(keys, keys[1:]):
                script.append(f"tl.to({sel},{{{prop}:{b['value']},duration:{round(b['at'] - a['at'], 4)},ease:{json.dumps(b.get('ease', 'power2.inOut'))}}},{round(c['start'] + a['at'], 4)});")
        if t_out.get("kind", "none") != "none" and t_out.get("seconds", 0) > 0:
            d = t_out["seconds"]
            script.append(f"tl.to({sel},{{opacity:0,duration:{d},ease:'power2.in'}},{round(c['start'] + c['duration'] - d, 4)});")
    page = f"""<!doctype html>
<!-- Generated by Neyvia from edl.json ({SCHEMA}); edit the EDL through neyvia.video.* or HyperFrames Studio. -->
<html lang="en"><head><meta charset="UTF-8"/><meta name="viewport" content="width={W}, height={H}"/>
<title>{html.escape(edl.get('title') or edl['id'])}</title>
<script src="{gsap_rel}"></script>
<style>{font_face}
html,body{{margin:0;width:{W}px;height:{H}px;overflow:hidden;background:{edl['background']}}}
#root{{position:relative;width:100%;height:100%;overflow:hidden;background:{edl['background']}}}
.caption,.text{{-webkit-font-smoothing:antialiased}}
</style></head>
<body><div id="root" data-composition-id="main" data-start="0" data-duration="{total}" data-width="{W}" data-height="{H}" data-fps="{edl['fps']}">
{chr(10).join(body)}
</div>
<script>
const tl=gsap.timeline({{paused:true}});
{chr(10).join(script)}
tl.set({{}},{{}},{total});
window.__timelines=window.__timelines||{{}};
window.__timelines.main=tl;
</script></body></html>
"""
    (project / "index.html").write_text(page, encoding="utf-8")
    (project / "hyperframes.json").write_text(json.dumps({"name": edl["id"], "neyvia": {"edl": "edl.json", "schema": SCHEMA}}, indent=1), encoding="utf-8")
    return {"index": str(project / "index.html"), "duration": total, "clips": len(edl["clips"])}


# --- HyperFrames CLI --------------------------------------------------------

def cli():
    """The one HyperFrames install (laya_video.tools(): NEYVIA_HYPERFRAMES_CLI, else the pinned 0.8.138 on D:), run by node."""
    from .laya_video import tools
    script = tools()["hyperframes"]
    if not script:
        raise RuntimeError("HyperFrames CLI is not installed (nothing is downloaded); set NEYVIA_HYPERFRAMES_CLI")
    return ["node", script]


def _env():
    env = dict(os.environ)
    env.update(DO_NOT_TRACK="1", HYPERFRAMES_NO_TELEMETRY="1", HYPERFRAMES_NO_UPDATE_CHECK="1", HYPERFRAMES_NO_AUTO_INSTALL="1",
               HYPERFRAMES_SKIP_SKILLS="1", HYPERFRAMES_EXTRACT_CACHE_DIR=str(RUNS / "cache"), NO_COLOR="1", CI="1")
    from .laya_video import tools
    tl = tools()
    if tl.get("headless"):  # the local chrome-headless-shell, throwaway profile, never a visible browser
        env.update(HYPERFRAMES_BROWSER_PATH=tl["headless"], PRODUCER_HEADLESS_SHELL_PATH=tl["headless"])
    if tl.get("ffmpeg"):
        env["PATH"] = env.get("PATH", "") + os.pathsep + str(Path(tl["ffmpeg"]).parent)
    # Render scratch (frames, Chrome profiles) goes to the large media drive, not the system temp folder.
    scratch = RUNS / "tmp"
    scratch.mkdir(parents=True, exist_ok=True)
    env.update(TEMP=str(scratch), TMP=str(scratch), TMPDIR=str(scratch))
    return env


def run_cli(args, project, *, timeout=900):
    started = time.perf_counter()
    done = subprocess.run([*cli(), *args], cwd=str(project), capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout, env=_env(), check=False, **hidden_windows_subprocess_kwargs())
    return {"code": done.returncode, "stdout": done.stdout, "stderr": done.stderr, "seconds": round(time.perf_counter() - started, 2)}


def _json_out(text):
    start = text.find("{")
    return json.loads(text[start:]) if start >= 0 else None


def lint(project):
    out = run_cli(["lint", "--json", "."], project, timeout=180)
    data = _json_out(out["stdout"]) or {}
    return {"ok": out["code"] == 0 and data.get("errorCount", 1) == 0, "errors": data.get("errorCount"),
            "warnings": data.get("warningCount"), "findings": data.get("findings", [])[:40], "seconds": out["seconds"]}


def timeline(project):
    out = run_cli(["timeline", "--json"], project, timeout=180)  # takes no directory argument; runs in cwd
    data = _json_out(out["stdout"])
    if out["code"] != 0 or not data:
        raise RuntimeError("HyperFrames timeline failed: " + (out["stderr"] or out["stdout"])[-800:])
    return data["timeline"]


def render(project, output, *, quality="draft", workers=4, fps=None, timeout=1800):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    args = ["render", ".", "--output", str(output), "--quality", quality, "--workers", str(int(workers)), "--quiet", "--sdr", "--no-browser-gpu"]
    if fps:
        args += ["--fps", str(fps)]
    out = run_cli(args, project, timeout=timeout)
    summary = [line.strip() for line in (out["stdout"] + "\n" + out["stderr"]).splitlines() if line.strip()][-6:]
    return {"ok": out["code"] == 0 and output.is_file() and output.stat().st_size > 0, "output": str(output),
            "seconds": out["seconds"], "summary": summary, "code": out["code"]}


_STUDIOS = {}


def studio(project, port, *, stop=False):
    """Serve HyperFrames Studio for a project, headless: --no-open, an explicit port in 49121-49129."""
    import urllib.request
    port = int(port)
    if port not in PORTS:
        raise ValueError("Studio uses an explicit port in 49165-49167")
    project = Path(project)
    state = project / ".neyvia-studio.json"
    if stop:
        if not state.is_file():
            return {"ok": True, "stopped": False, "reason": "not running"}
        pid = json.loads(state.read_text(encoding="utf-8"))["pid"]
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False, **hidden_windows_subprocess_kwargs())
        _STUDIOS.pop(port, None)
        state.unlink()
        return {"ok": True, "stopped": True, "pid": pid}
    # Studio binds 127.0.0.1 (``localhost`` may resolve to ::1 and hang).
    url = f"http://127.0.0.1:{port}/"
    log = open(project / ".neyvia-studio.log", "ab")
    env = _env()
    env.pop("CI", None)  # under CI=1 the preview server never starts listening
    # Our own hidden child in --foreground mode; HyperFrames' --background launcher does not survive a hidden parent.
    # stdin stays an open pipe: at EOF the foreground preview stops serving. The host process keeps the handle.
    proc = subprocess.Popen([*cli(), "preview", ".", "--foreground", "--no-open", "--port", str(port)], cwd=str(project),
                            stdout=log, stderr=log, stdin=subprocess.PIPE, env=env, **hidden_windows_subprocess_kwargs(new_process_group=True))
    _STUDIOS[port] = proc
    state.write_text(json.dumps({"pid": proc.pid, "port": port, "url": url}), encoding="utf-8")
    deadline = time.time() + 90
    while time.time() < deadline:
        if proc.poll() is not None:
            return {"ok": False, "url": url, "reason": "studio exited", "code": proc.returncode}
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                if response.status == 200:
                    return {"ok": True, "url": url, "studio": url + "#project/" + project.name, "pid": proc.pid,
                            "bytes": len(response.read())}
        except OSError:
            time.sleep(1)
    return {"ok": False, "url": url, "reason": "studio did not answer within 90 s", "pid": proc.pid}
