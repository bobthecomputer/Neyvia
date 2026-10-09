"""LAYA pre-render check of a HyperFrames video project (domain ``video-edit``).

The composition and timeline as a CL Scene before anything renders: the EDL clips that
``neyvia.video.*`` edits (``video_hyperframes``), HyperFrames' own ``timeline --json`` rows and
``lint --json``. Vocabulary: the ``video-edit`` ``-- @bug`` lines in ``manuals/cl/video.cl``.

Rendered cuts are judged by the one video adapter, ``laya_video`` (domain ``video``, vocabulary
``manuals/cl/laya-video.cl``). This module was written on track/laya-video (plan 28, 7 Oct) and
kept when the two video stacks were reconciled into one on track/video.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MANUAL = REPO / "manuals/cl/video.cl"
STOCK = ("seamless", "unlock", "ai-powered", "streamline", "supercharge", "revolution", "game-changer", "game changer",
         "effortless", "next-level", "next level", "cutting-edge", "cutting edge", "introducing", "leverage")


def _load_brief(brief):
    """A brief is a dict ({duration, aspect "16:9", maxCaptionWords}) or a CL brief file read by laya_video."""
    if not brief:
        return {}
    if isinstance(brief, dict):
        return brief
    from .laya_video import read_brief
    spec = read_brief(brief)["spec"]
    w, h = spec["aspect"]["width"], spec["aspect"]["height"]
    g = math.gcd(w, h)
    return {"duration": spec["length"].get("target"), "aspect": f"{w // g}:{h // g}",
            "maxCaptionWords": spec["captions"].get("maxWords", 99)}


def transcribe_edit(source):
    """The composition and timeline as a Scene, before any render: EDL clips, HyperFrames' own timeline rows and lint."""
    from . import video_hyperframes as hf
    started = time.perf_counter()
    project = Path(source["project"])
    edl = hf.load(project)
    brief = _load_brief(source.get("brief"))
    total = hf.duration_of(edl)
    expected = float(brief.get("duration") or total)
    nodes = []
    vis = sorted((c for c in edl["clips"] if c["kind"] in ("image", "video", "text")), key=lambda c: c["start"])
    gaps, t = [], 0.0
    for c in vis:
        if c["start"] - t > 1 / edl["fps"]:
            gaps.append([round(t, 3), round(c["start"], 3)])
        t = max(t, c["start"] + c["duration"])
    if total - t > 1 / edl["fps"]:
        gaps.append([round(t, 3), round(total, 3)])
    head_tail = float(brief.get("allowBlackHeadTail", 1.2))
    unintended = [g for g in gaps if not (g[0] <= 0.001 and g[1] <= head_tail) and not (g[0] >= total - head_tail)]
    max_words = int(brief.get("maxCaptionWords", 99))
    caps = sorted((c for c in edl["clips"] if c["kind"] == "caption"), key=lambda c: c["start"])
    for c in edl["clips"]:
        m = {"start": c["start"], "end": round(c["start"] + c["duration"], 4), "durationS": c["duration"], "track": c["track"],
             "overrunS": round(max(0.0, c["start"] + c["duration"] - total), 4), "intent": c.get("intent")}
        if c["kind"] in ("caption", "text"):
            words = len(c["text"].split())
            clash = [o["id"] for o in caps if o is not c and c["kind"] == "caption" and o["start"] < c["start"] + c["duration"] and c["start"] < o["start"] + o["duration"]]
            m.update(words=words, maxWords=max_words if c["kind"] == "caption" else 99,
                     wordsOver=max(0, words - max_words) if c["kind"] == "caption" else 0, charsPerSecond=round(len(c["text"]) / c["duration"], 2),
                     stockPhrase=any(s in c["text"].lower() for s in STOCK), collidesWith=clash)
        nodes.append({"id": "clip-" + c["id"], "kind": "clip-" + c["kind"], "attributes": {"text": c.get("text"), "src": Path(c["src"]).name if c.get("src") else None,
                      "tags": c.get("tags", [])}, "measurements": m, "relations": {"edl": c["id"]}, "certainty": "observed"})
    lint_row = hf.lint(project)
    try:
        tl = hf.timeline(project)
        rows = [row for track in tl.get("tracks", []) for row in track.get("rows", [])]
    except RuntimeError as exc:
        tl, rows = {"duration": None, "error": str(exc)[:300]}, []
    for row in rows:
        nodes.append({"id": "tl-" + str(row["id"]), "kind": "timeline-clip", "attributes": {"element": row.get("kind"), "src": row.get("src")},
                      "measurements": {"start": row.get("absStart"), "end": row.get("absEnd"), "track": row.get("trackIndex"),
                                       "overrunS": round(max(0.0, (row.get("absEnd") or 0) - (tl.get("duration") or 0)), 3),
                                       "warnings": row.get("warnings", [])}, "relations": {"edl": str(row["id"]).removeprefix("c-")}, "certainty": "observed"})
    nodes.append({"id": "lint", "kind": "lint", "attributes": {"codes": sorted({f.get("code") for f in lint_row.get("findings", [])})},
                  "measurements": {"errors": lint_row.get("errors"), "warnings": lint_row.get("warnings")}, "relations": {}, "certainty": "observed"})
    W, H = edl["width"], edl["height"]
    g = math.gcd(W, H)
    nodes.insert(0, {"id": "composition", "kind": "composition", "attributes": {"title": edl.get("title"), "edl": str(hf.edl_path(project))},
                     "measurements": {"durationS": total, "timelineDurationS": tl.get("duration"), "expectedDurationS": expected,
                                      "durationErrorS": round(abs(total - expected), 3), "aspect": f"{W // g}:{H // g}",
                                      "aspectOk": (f"{W // g}:{H // g}" == brief["aspect"]) if brief.get("aspect") else True,
                                      "gaps": unintended, "clips": len(edl["clips"]), "captions": len(caps)},
                     "relations": {}, "certainty": "observed"})
    return {"surface": project.name, "layer": "timeline", "nodes": nodes, "truncated": False, "measured": "exact",
            "provenance": {"project": str(project), "edlSha256": hashlib.sha256(hf.edl_path(project).read_bytes()).hexdigest(),
                           "hyperframes": "timeline --json + lint --json"},
            "metrics": {"totalMs": round((time.perf_counter() - started) * 1000), "durationErrorS": round(abs(total - expected), 3)}}



def read_predicates(domain="video-edit"):
    rules = []
    for line in MANUAL.read_text(encoding="utf-8").splitlines():
        if line.startswith("-- @bug "):
            r = json.loads(line.removeprefix("-- @bug "))
            if r.get("domain", "video") != domain:
                continue
            condition = {"all": [{"field": "kind", "op": "eq", "value": r["node"]}, r["predicate"]]}
            rules.append({"id": r["type"], "condition": condition, "severity": r.get("severity", "error"), "means": r.get("means", ""),
                          "evidence": ["attributes", "measurements"],
                          "fix": {"action": r["fix"], "arguments": r.get("arguments", {}), "instruction": r.get("instruction", "")}})
    return rules


def edit_adapter():
    from .scene_core import Adapter
    return Adapter(transcribe=transcribe_edit, vocabulary=lambda: read_predicates("video-edit"))
