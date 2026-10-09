"""FilmCraft (ArtCraft/storytold, MIT OR Apache-2.0) for agents through its headless CLI.

Adapted, not forked: every action runs the unmodified upstream `filmcraft-cli` built from
source (headless engine session, no window, no bridge). The sequence is observed as a CL
Scene; exports are checked with the same outcome contracts as HyperFrames renders.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
TICKS = 254016000000


def _binary():
    path = os.environ.get("NEYVIA_FILMCRAFT_CLI") or "D:/NeyviaRuns/video/track-video/target/filmcraft/release/filmcraft-cli.exe"
    if not Path(path).is_file():
        raise ValueError("filmcraft-cli is not built; set NEYVIA_FILMCRAFT_CLI (nothing is downloaded)")
    return path


def _cli(args, timeout=900, data_dir=None):
    data = data_dir or str(Path(tempfile.gettempdir()) / "neyvia-filmcraft-data")
    Path(data).mkdir(parents=True, exist_ok=True)
    proc = subprocess.run([_binary(), "--data-dir", data, "--compact", *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout, creationflags=NO_WINDOW)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout)[-2000:])
    return proc.stdout


def _json_lines(text):
    out = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith(("{", "[")):
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def commands(args, *, root):
    rows = _json_lines(_cli(["commands", *([args["filter"]] if args.get("filter") else []), "--json"]))
    items = rows[0] if rows and isinstance(rows[0], list) else rows
    return {"ok": True, "commands": items}


def scene_of(seq):
    """Observer: the active sequence as a CL Scene (tracks, clips with in/out, effects, transitions, markers)."""
    nodes = [{"id": "sequence", "kind": "sequence", "attributes": {"name": seq.get("name")},
              "measurements": {"durationS": round(seq.get("duration", 0) / TICKS, 4), "frames": seq.get("durationFrames"),
                               "width": (seq.get("settings") or {}).get("width"), "height": (seq.get("settings") or {}).get("height")},
              "relations": {}}]
    for kind in ("video", "audio"):
        for track in seq.get(kind, []):
            tid = str(track.get("id"))
            nodes.append({"id": "track:" + tid, "kind": kind + "-track", "attributes": {k: track.get(k) for k in ("name", "muted", "locked", "enabled") if k in track},
                          "measurements": {"clips": len(track.get("items", [])), "transitions": len(track.get("transitions", []))}, "relations": {}})
            for clip in track.get("items", []):
                effects = [e.get("effect") for e in clip.get("effects", [])]
                animated = sorted({f"{e.get('effect')}.{name}" for e in clip.get("effects", []) for name, p in (e.get("params") or {}).items()
                                   if isinstance(p, dict) and p.get("keyframes")})
                nodes.append({"id": "clip:" + str(clip.get("clip")), "kind": kind + "-clip",
                              "attributes": {"name": clip.get("name"), "item": clip.get("item"), "effects": effects, "animated": animated},
                              "measurements": {"startS": round(clip.get("start", 0) / TICKS, 4), "endS": round(clip.get("end", 0) / TICKS, 4),
                                               "inS": round(clip.get("sourceIn", 0) / TICKS, 4), "outS": round(clip.get("sourceOut", 0) / TICKS, 4),
                                               "speed": clip.get("speed"), "gainDb": clip.get("gainDb")},
                              "relations": {"track": tid}})
    for marker in seq.get("markers", []):
        nodes.append({"id": "marker:" + str(marker.get("id")), "kind": "marker", "attributes": {"name": marker.get("name"), "comment": marker.get("comment")},
                      "measurements": {"startS": round(marker.get("start", 0) / TICKS, 4)}, "relations": {}})
    return {"surface": "filmcraft:" + str(seq.get("name", "sequence")), "nodes": nodes}


def inspect(args, *, root):
    data = _json_lines(_cli(["--project", args["project"], "inspect", "sequence"]))
    sequence = data[-1] if data else {}
    return {"ok": True, "scene": scene_of(sequence), "sequence": sequence}


def run(args, *, root):
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "steps.jsonl"
        script.write_text("\n".join(json.dumps({"id": s["id"], "params": s.get("params", {})}) for s in args["steps"]), encoding="utf-8")
        out = _cli([*(["--project", args["project"]] if args.get("project") else []), "--save-as", args["saveAs"], "run", str(script)])
    return {"ok": True, "saved": args["saveAs"], "results": _json_lines(out)}


def _outcome(path):
    from grant_agent.laya_video import probe
    import importlib.util
    meta = probe(path)
    return {"durationS": round(meta["durationS"], 3), "frames": meta["frames"], "fps": round(meta["fps"], 3),
            "width": meta["width"], "height": meta["height"], "hasAudio": meta["hasAudio"]}


def export(args, *, root):
    _cli(["--project", args["project"], "export", args["out"], *(["--format", args["format"]] if args.get("format") else [])], timeout=3600)
    return {"ok": Path(args["out"]).is_file(), "out": args["out"], "outcome": _outcome(args["out"])}


def frame(args, *, root):
    _cli(["--project", args["project"], "render", "--seconds", str(args["seconds"]), "--out", args["out"]])
    return {"ok": Path(args["out"]).is_file(), "out": args["out"]}


def verify(args, *, root):
    """Real round trip on real Neyvia captures: new sequence, import, place, animate, title, marker,
    inspect as a Scene, export, then the outcome contracts on the decoded file."""
    import time
    from grant_agent import laya_video as V
    import numpy as np
    base = Path(root) / ".agent_control" / "filmcraft-verify" / str(time.time_ns())
    base.mkdir(parents=True)
    project, data = str(base / "verify.fcproj"), str(base / "data")
    captures = sorted(Path("D:/NeyviaRuns/tour/final-verified-theme/dark").glob("*-full.png"))[:2]
    if len(captures) < 2:
        raise ValueError("Two real Neyvia captures are needed for the round trip")
    _cli(["--save-as", project, "exec", "file.newSequence", "name=Verify", "width=1280", "height=720", "fps=30"], data_dir=data)
    items = _json_lines(_cli(["--project", project, "--save", "import", *map(str, captures)], data_dir=data))[-1]["items"]
    steps = [{"id": "timeline.place", "params": {"item": items[0], "track": "V1", "seconds": 0}},
             {"id": "timeline.place", "params": {"item": items[1], "track": "V1", "seconds": 5}},
             {"id": "graphics.newText", "params": {"text": "Checked by LAYA", "size": 56, "seconds": 3, "time": TICKS, "newClip": True}},
             {"id": "markers.add", "params": {"time": 5 * TICKS, "name": "second shot"}}]
    script = base / "steps.jsonl"
    script.write_text(chr(10).join(json.dumps(s) for s in steps), encoding="utf-8")
    placed = _json_lines(_cli(["--project", project, "--save", "run", str(script)], data_dir=data))
    clips = [c for r in placed if r.get("id") == "timeline.place" for c in r["result"]["clips"]]
    animate = [{"id": "effects.toggleAnimation", "params": {"clip": c, "effect": "motion", "param": "scale"}} for c in clips]
    animate += [{"id": "effects.setParam", "params": {"clip": c, "effect": "motion", "param": "scale", "value": v, "time": t}}
               for i, c in enumerate(clips) for t, v in ((i * 5 * TICKS, 100.0), ((i + 1) * 5 * TICKS - 1, 108.0))]
    script.write_text(chr(10).join(json.dumps(s) for s in animate), encoding="utf-8")
    animated = _json_lines(_cli(["--project", project, "--save", "--keep-going", "run", str(script)], data_dir=data))
    sequence = _json_lines(_cli(["--project", project, "inspect", "sequence"], data_dir=data))[-1]
    scene = scene_of(sequence)
    out = base / "verify.mp4"
    started = time.perf_counter()
    _cli(["--project", project, "export", str(out)], timeout=1800, data_dir=data)
    seconds = time.perf_counter() - started
    meta = V.probe(out)
    gray = V.decode_gray(out)
    diffs = np.abs(np.diff(gray, axis=0)).mean(axis=(1, 2))
    black = int(((gray.mean(axis=(1, 2)) < 12) & (gray.std(axis=(1, 2)) < 6)).sum())
    run = best = 0
    for d in diffs:
        run = run + 1 if d < 0.02 else 0
        best = max(best, run)
    outcome = {"durationS": round(meta["durationS"], 3), "frames": len(gray), "expectedFrames": sequence.get("durationFrames"),
               "blackFrames": black, "frozenRunMaxS": round((best + 1) / meta["fps"], 3) if best else 0.0,
               "exportSeconds": round(seconds, 2), "width": meta["width"], "height": meta["height"]}
    kinds = {n["kind"] for n in scene["nodes"]}
    checks = {"exported": out.is_file(), "frameCount": abs(outcome["frames"] - (outcome["expectedFrames"] or -9)) <= 1,
              "noBlack": black == 0, "notFrozen": outcome["frozenRunMaxS"] < 1.5,
              "sceneHasTimeline": {"sequence", "video-clip", "marker"} <= kinds,
              "animated": all(r.get("ok") for r in animated)}
    return {"passed": all(checks.values()), "checks": checks, "outcome": outcome, "scene": scene, "project": project, "out": str(out)}
