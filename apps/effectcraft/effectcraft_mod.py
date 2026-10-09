"""EffectCraft (ArtCraft/storytold, MIT OR Apache-2.0) for agents through its headless CLI.

Adapted, not forked: every action runs the unmodified upstream `effectcraft-cli` built from
source (headless, no window). Projects are observed as a CL Scene of comps and layers.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _binary():
    path = os.environ.get("NEYVIA_EFFECTCRAFT_CLI") or "D:/NeyviaRuns/video/track-video/target/effectcraft/release/effectcraft-cli.exe"
    if not Path(path).is_file():
        raise ValueError("effectcraft-cli is not built; set NEYVIA_EFFECTCRAFT_CLI (nothing is downloaded)")
    return path


def _project(args):
    return ["--project", args["project"]] if args.get("project") else ["--demo"]


def _cli(args, timeout=1800):
    proc = subprocess.run([_binary(), *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, creationflags=NO_WINDOW)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout)[-2000:])
    return proc.stdout


def _json(text):
    text = text.strip()
    start = min([i for i in (text.find("{"), text.find("[")) if i >= 0], default=-1)
    return json.loads(text[start:]) if start >= 0 else {"text": text}


def commands(args, *, root):
    return {"ok": True, "commands": _json(_cli(["commands", *(["--filter", args["filter"]] if args.get("filter") else []), "--json"]))}


def scene_of(info, layer_props=None):
    """CL Scene of an `effectcraft-cli info --json` document: every comp in the project, the active
    comp's layers (in/out, type), and, when given, each layer's effects and keyframed properties."""
    project = info.get("project") or {}
    active = info.get("activeComp") or {}
    nodes = []
    for item in project.get("items", []):
        if item.get("type") != "Composition":
            continue
        size = item.get("size") or [None, None]
        nodes.append({"id": f"comp:{item['id']}", "kind": "comp", "attributes": {"name": item.get("name"), "active": item["id"] == active.get("id")},
                      "measurements": {"width": size[0], "height": size[1], "fps": item.get("frameRate"),
                                       "duration": item.get("duration"), "layers": item.get("layers")}, "relations": {}})
    for layer in active.get("layers", []):
        props = (layer_props or {}).get(layer["id"], [])
        effects = sorted({p["path"].split("/")[1] for p in props if p["path"].startswith("effects/#")})
        keyed = [p["path"] for p in props if p.get("keys")]
        nodes.append({"id": f"layer:{active['id']}:{layer['id']}", "kind": "layer",
                      "attributes": {"name": layer.get("name"), "type": layer.get("type"), "index": layer.get("index")},
                      "measurements": {"in": layer.get("in"), "out": layer.get("out"), "effects": len(effects), "keyframed": keyed},
                      "relations": {"comp": f"comp:{active['id']}", "parent": layer.get("parent")}})
    return {"surface": "effectcraft", "nodes": nodes}


def _layer_props(args, data):
    out = {}
    for layer in (data.get("activeComp") or {}).get("layers", []):
        tree = _json(_cli([*_project(args), "props", "-", str(layer["id"]), "--flat", "--json"]))
        out[layer["id"]] = tree.get("properties", []) if isinstance(tree, dict) else []
    return out


def info(args, *, root):
    data = _json(_cli([*_project(args), "info", "--json"]))
    data = data if isinstance(data, dict) else {}
    return {"ok": True, "scene": scene_of(data, _layer_props(args, data)), "info": data}


def run(args, *, root):
    pairs = []
    for step in args["steps"]:
        pairs += [step["id"], json.dumps(step.get("params", {}))]
    out = _cli([*_project(args), "--save-as", args["saveAs"], "run", *pairs, "--json"])
    return {"ok": True, "saved": args["saveAs"], "results": _json(out)}


def frame(args, *, root):
    _cli([*_project(args), "render-frame", *(["--comp", args["comp"]] if args.get("comp") else []),
          "--time", str(args.get("time", 0)), "--out", args["out"]])
    return {"ok": Path(args["out"]).is_file(), "out": args["out"]}


def render(args, *, root):
    extra = []
    for key in ("comp", "format", "start", "end"):
        if args.get(key) is not None:
            extra += ["--" + key, str(args[key])]
    _cli([*_project(args), "render", "--out", args["out"], *extra], timeout=3600)
    from grant_agent.laya_video import probe
    meta = probe(args["out"]) if Path(args["out"]).suffix.lower() in {".mp4", ".mov", ".webm"} else {}
    return {"ok": Path(args["out"]).is_file(), "out": args["out"], "outcome": meta}


def _steps(project, steps, *, first=False):
    pairs = []
    for command, params in steps:
        pairs += [command, json.dumps(params)]
    head = ["--empty", "--save-as", project] if first else ["--project", project, "--save"]
    return _json(_cli([*head, "run", *pairs, "--json"]))["result"]


def verify(args, *, root):
    """Real round trip on a real Neyvia capture: new comp, import, place, keyframed push-in, a title
    with an effect and a keyframed fade, observe as a Scene, one frame, a render, then the outcome
    contracts on the decoded file."""
    import time
    import numpy as np
    from grant_agent import laya_video as V
    try:
        _binary()
    except ValueError as error:
        return {"passed": False, "blocked": str(error)}
    captures = [p for p in (Path("D:/NeyviaRuns/video/track-video/recapture/dark/laya-full.png"),
                            *sorted(Path("D:/NeyviaRuns/tour/final-verified-theme/dark").glob("*-full.png"))) if p.is_file()]
    if not captures:
        raise ValueError("A real Neyvia capture is needed for the round trip")
    base = Path(root) / ".agent_control" / "effectcraft-verify" / str(time.time_ns())
    base.mkdir(parents=True)
    project = str(base / "verify.ecproj")
    made = _steps(project, [("comp.new", {"name": "Verify", "width": 1280, "height": 720, "frameRate": 30, "duration": 3}),
                            ("file.import", {"paths": [str(captures[0])]})], first=True)
    item = made[1]["result"]["items"][0]
    edits = _steps(project, [
        ("layer.addItem", {"item": item, "time": 0, "duration": 3}),
        ("prop.addKey", {"layer": "#1", "path": "transform/scale", "time": 0, "value": [80, 80, 100]}),
        ("prop.addKey", {"layer": "#1", "path": "transform/scale", "time": 3, "value": [88, 88, 100]}),
        ("layer.newText", {"text": "Checked by LAYA", "name": "Title", "size": 72, "fill": "#ffffff", "position": [640, 620]}),
        ("effect.apply", {"effect": "Drop Shadow", "layers": ["Title"]}),
        ("prop.addKey", {"layer": "Title", "path": "transform/opacity", "time": 0, "value": 0}),
        ("prop.addKey", {"layer": "Title", "path": "transform/opacity", "time": 0.8, "value": 100})])
    observed = info({"project": project}, root=root)
    layers = {n["attributes"]["name"]: n for n in observed["scene"]["nodes"] if n["kind"] == "layer"}
    still = frame({"project": project, "out": str(base / "frame.png"), "time": 1.5}, root=root)
    started = time.perf_counter()
    clip = render({"project": project, "out": str(base / "clip.mp4"), "format": "h264"}, root=root)
    seconds = time.perf_counter() - started
    meta = clip.get("outcome") or {}
    gray = V.decode_gray(clip["out"])
    diffs = np.abs(np.diff(gray, axis=0)).mean(axis=(1, 2))
    black = int(((gray.mean(axis=(1, 2)) < 12) & (gray.std(axis=(1, 2)) < 6)).sum())
    run_, best = 0, 0
    for d in diffs:
        run_ = run_ + 1 if d < 0.02 else 0
        best = max(best, run_)
    title = layers.get("Title", {}).get("measurements", {})
    shot = next((n for n in layers.values() if n["attributes"]["type"] == "Footage"), {}).get("measurements", {})
    outcome = {"durationS": round(meta.get("durationS", 0), 3), "frames": len(gray), "expectedFrames": 90, "blackFrames": black,
               "frozenRunMaxS": round((best + 1) / meta["fps"], 3) if best and meta.get("fps") else 0.0,
               "renderSeconds": round(seconds, 2), "width": meta.get("width"), "height": meta.get("height"),
               "fadeInLuma": [round(float(gray[0].mean()), 1), round(float(gray[45].mean()), 1)] if len(gray) > 45 else None,
               "capture": str(captures[0])}
    checks = {"edited": all(not isinstance(r.get("result"), dict) or "error" not in r["result"] for r in edits),
              "sceneHasComp": any(n["kind"] == "comp" and n["attributes"]["name"] == "Verify" for n in observed["scene"]["nodes"]),
              "sceneHasLayers": bool(title) and bool(shot),
              "effectApplied": title.get("effects") == 1,
              "keyframed": "transform/opacity" in title.get("keyframed", []) and "transform/scale" in shot.get("keyframed", []),
              "frame": still["ok"], "rendered": clip["ok"], "size": (meta.get("width"), meta.get("height")) == (1280, 720),
              "frameCount": abs(outcome["frames"] - 90) <= 1, "duration": abs(outcome["durationS"] - 3.0) <= 0.1,
              "noBlack": black == 0, "notFrozen": outcome["frozenRunMaxS"] < 1.5,
              "titleFadesIn": bool(outcome["fadeInLuma"]) and outcome["fadeInLuma"][1] > outcome["fadeInLuma"][0] + 1}
    return {"passed": all(checks.values()), "checks": checks, "outcome": outcome, "scene": observed["scene"],
            "project": project, "frame": still["out"], "out": clip["out"]}
