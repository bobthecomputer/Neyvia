"""PhotoCraft (ArtCraft/storytold, MIT OR Apache-2.0) for video frames through its headless CLI.

Adapted, not forked: every action runs the unmodified upstream `photocraft-cli` built from
source (headless, no window).
"""
import json
import os
from pathlib import Path
import subprocess

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _binary():
    path = os.environ.get("NEYVIA_PHOTOCRAFT_CLI") or "D:/NeyviaRuns/video/track-video/target/photocraft/release/photocraft-cli.exe"
    if not Path(path).is_file():
        raise ValueError("photocraft-cli is not built; set NEYVIA_PHOTOCRAFT_CLI (nothing is downloaded)")
    return path


def _cli(args, timeout=900):
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
    return {"ok": True, "commands": _json(_cli(["commands", "--json", *(["--filter", args["filter"]] if args.get("filter") else [])]))}


def info(args, *, root):
    doc = _json(_cli(["info", args["file"]]))
    layers = doc.get("layers", []) if isinstance(doc, dict) else []
    nodes = [{"id": "document", "kind": "document", "attributes": {k: doc.get(k) for k in ("mode", "depth") if k in doc},
              "measurements": {k: doc.get(k) for k in ("width", "height") if k in doc} | {"layers": len(layers)}, "relations": {}}]
    nodes += [{"id": f"layer:{i}", "kind": "layer", "attributes": {k: l.get(k) for k in ("name", "kind", "visible", "blendMode") if k in l},
               "measurements": {k: l.get(k) for k in ("opacity",) if k in l}, "relations": {}} for i, l in enumerate(layers)]
    return {"ok": True, "scene": {"surface": "photocraft:" + Path(args["file"]).name, "nodes": nodes}, "document": doc}


def run(args, *, root):
    cmd = ["run", args["file"]]
    for step in args["steps"]:
        cmd += ["--cmd", step["id"], "--params", json.dumps(step.get("params", {}))]
    out = _cli(cmd + ["--out", args["out"]])
    return {"ok": Path(args["out"]).is_file(), "out": args["out"], "output": out[-4000:]}


def convert(args, *, root):
    _cli(["convert", args["input"], args["out"]])
    return {"ok": Path(args["out"]).is_file(), "out": args["out"]}


def verify(args, *, root):
    """Real round trip on a Neyvia capture: inspect as a Scene, lossless convert, compare decoded pixels."""
    import time
    import numpy as np
    from PIL import Image
    try:
        _binary()
    except ValueError as error:
        return {"passed": False, "blocked": str(error)}
    base = Path(root) / ".agent_control" / "photocraft-verify" / str(time.time_ns())
    base.mkdir(parents=True)
    source = sorted(Path("D:/NeyviaRuns/tour/final-verified-theme/dark").glob("*-full.png"))[0]
    observed = info({"file": str(source)}, root=root)
    converted = convert({"input": str(source), "out": str(base / "frame.tif")}, root=root)
    a = np.asarray(Image.open(source).convert("RGB"), dtype=np.int16)
    b = np.asarray(Image.open(base / "frame.tif").convert("RGB"), dtype=np.int16)
    edited = run({"file": str(source), "steps": [{"id": "image.adjustments.desaturate"}], "out": str(base / "gray.png")}, root=root)
    g = np.asarray(Image.open(base / "gray.png").convert("RGB"), dtype=np.int16) if edited["ok"] else None
    doc = next(n for n in observed["scene"]["nodes"] if n["id"] == "document")
    checks = {"sizeObserved": doc["measurements"].get("width") == a.shape[1] and doc["measurements"].get("height") == a.shape[0],
              "converted": converted["ok"], "pixelsIdentical": a.shape == b.shape and int(np.abs(a - b).max()) == 0,
              "desaturated": g is not None and int(np.abs(g[..., 0] - g[..., 1]).max()) <= 1 and int(np.abs(g[..., 1] - g[..., 2]).max()) <= 1}
    return {"passed": all(checks.values()), "checks": checks, "document": doc}
