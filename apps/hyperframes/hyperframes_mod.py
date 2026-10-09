"""HyperFrames (HeyGen, Apache-2.0) for agents: HTML compositions rendered headless to video.

Adapted, not forked: every action runs the pinned upstream `hyperframes` CLI. Renders and
snapshots use the local chrome-headless-shell with a throwaway profile; telemetry, skill
installs and cloud describers are switched off; the Studio never opens a window.
"""
import json
import os
from pathlib import Path
import subprocess

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
STUDIO_PORT = 49165


def _tools():
    from grant_agent.laya_video import tools
    tl = tools()
    if not tl["hyperframes"] or not tl["headless"] or not tl["ffmpeg"]:
        raise ValueError("HyperFrames CLI, a headless shell and ffmpeg are required; set NEYVIA_HYPERFRAMES_CLI, "
                         "NEYVIA_HEADLESS_SHELL and NEYVIA_FFMPEG")
    return tl


def _env(tl):
    env = {k: v for k, v in os.environ.items() if k not in {"GEMINI_API_KEY", "HEYGEN_API_KEY", "OPENAI_API_KEY"}}
    temp = Path(os.environ.get("NEYVIA_VIDEO_TOOLS", "D:/NeyviaRuns/video/track-video")) / "tmp"
    temp.mkdir(parents=True, exist_ok=True)
    env.update({"TEMP": str(temp), "TMP": str(temp), "HYPERFRAMES_NO_TELEMETRY": "1", "HYPERFRAMES_SKIP_SKILLS": "1",
                "HYPERFRAMES_BROWSER_PATH": tl["headless"], "PRODUCER_HEADLESS_SHELL_PATH": tl["headless"],
                "PATH": env.get("PATH", "") + os.pathsep + str(Path(tl["ffmpeg"]).parent)})
    return env


def _project(args):
    project = Path(args["project"]).resolve()
    if not (project / "index.html").is_file():
        raise ValueError("A HyperFrames project folder with index.html is required")
    return project


def _cli(args_list, project, timeout=1800):
    tl = _tools()
    proc = subprocess.run(["node", tl["hyperframes"], *args_list], cwd=str(project), env=_env(tl), capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=timeout, creationflags=NO_WINDOW)
    return proc.returncode, proc.stdout, proc.stderr


def lint(args, *, root):
    project = _project(args)
    code, out, err = _cli(["lint", str(project), "--json"], project, timeout=120)
    try:
        report = json.loads(out[out.index("{"):])
    except ValueError:
        report = {"raw": (out + err)[-4000:]}
    return {"ok": code == 0, "project": str(project), "lint": report}


def timeline(args, *, root):
    """Observer: the composition's tracks and clips as a CL Scene (timeline nodes)."""
    project = _project(args)
    code, out, err = _cli(["timeline", "--json"], project, timeout=120)
    if code != 0:
        raise RuntimeError((err or out)[-2000:])
    data = json.loads(out[out.index("{"):])["timeline"]
    nodes = [{"id": "composition", "kind": "composition", "attributes": {}, "measurements": {"durationS": data.get("duration")}, "relations": {}}]
    for track in data.get("tracks", []):
        for row in track.get("rows", []):
            nodes.append({"id": "clip:" + str(row.get("id") or row.get("ref")), "kind": "clip",
                          "attributes": {k: row.get(k) for k in ("kind", "trackKind", "trackIndex", "src", "file", "role")},
                          "measurements": {k: row.get(k) for k in ("start", "duration", "end", "absStart", "absEnd", "volume", "playbackRate")},
                          "relations": {"children": [c.get("id") for c in row.get("children", []) if isinstance(c, dict)]}})
    return {"ok": True, "scene": {"surface": "hyperframes:" + project.name, "nodes": nodes}, "timeline": data}


EDITS = {"move", "trim", "split", "delete", "set", "duplicate"}


def edit(args, *, root):
    """One upstream timeline edit (move, trim, split, delete, set, duplicate) on a clip ref, then re-observe."""
    project = _project(args)
    if args["op"] not in EDITS:
        raise ValueError("Timeline edits: " + ", ".join(sorted(EDITS)))
    flags = [f"--{k}={v}" for k, v in (args.get("options") or {}).items() if k.isidentifier()]
    positional = [str(args["time"])] if args.get("time") is not None else []
    code, out, err = _cli(["timeline", args["op"], args["ref"], *positional, "--dir", str(project), *flags, "--json"], project, timeout=120)
    if code != 0:
        return {"ok": False, "error": (err or out)[-1500:]}
    return {"ok": True, "receipt": out[-3000:], "after": timeline({"project": str(project)}, root=root)["scene"]}


def render(args, *, root):
    """Render to MP4 (headless, throwaway profile) and check the outcome contracts on the file."""
    project = _project(args)
    out = Path(args.get("out") or project / "renders" / "out.mp4").resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    fps = int(args.get("fps", 30))
    code, stdout, stderr = _cli(["render", str(project), "-o", str(out), "--sdr", "--quality", args.get("quality", "standard"),
                                 "--fps", str(fps), "--workers", str(args.get("workers", 4)), "--no-browser-gpu", "--quiet"], project, 3600)
    if code != 0 or not out.is_file():
        return {"ok": False, "error": (stderr or stdout)[-2000:]}
    return {"ok": True, "out": str(out), "outcome": outcome(str(out), expected_s=args.get("expectedS"), fps=fps)}


def outcome(mp4, *, expected_s=None, fps=None):
    """Fast outcome contracts on a rendered file: duration/frames, no black or frozen runs, no clipping."""
    import numpy as np
    from grant_agent import laya_video as V, laya_video_audio as A
    meta = V.probe(mp4)
    gray = V.decode_gray(mp4)
    diffs = np.abs(np.diff(gray, axis=0)).mean(axis=(1, 2)) if len(gray) > 1 else np.zeros(0)
    black = int(((gray.mean(axis=(1, 2)) < 12) & (gray.std(axis=(1, 2)) < 6)).sum())
    run = best = 0
    for d in diffs:
        run = run + 1 if d < 0.02 else 0
        best = max(best, run)
    pcm = V.decode_audio(mp4) if meta["hasAudio"] else None
    level = A.measure(pcm) if pcm is not None and len(pcm) else None
    return {"durationS": round(meta["durationS"], 3), "frames": len(gray), "fps": round(meta["fps"], 3),
            "durationOk": expected_s is None or abs(meta["durationS"] - expected_s) <= 1.5 / (fps or meta["fps"] or 30),
            "frameCountOk": fps is None or abs(len(gray) - round(meta["durationS"] * fps)) <= 1,
            "blackFrames": black, "frozenRunMaxS": round((best + 1) / meta["fps"], 3) if best else 0.0,
            "audio": level and {k: level[k] for k in ("integratedLufs", "truePeakDbtp", "clippedSamples")},
            "audioClipping": bool(level and (level["clippedSamples"] > 0 or level["truePeakDbtp"] > -1.0))}


def snapshot(args, *, root):
    project = _project(args)
    out = Path(args.get("out") or project / "snapshots").resolve()
    at = ",".join(str(float(t)) for t in args.get("at", [])) or None
    cmd = ["snapshot", str(project), "-o", str(out), "--no-browser-gpu"] + (["--at", at, "--no-end"] if at else ["--frames", str(args.get("frames", 5))])
    code, stdout, stderr = _cli(cmd, project, 600)
    return {"ok": code == 0, "frames": sorted(str(p) for p in out.glob("*.png")), "error": None if code == 0 else (stderr or stdout)[-1500:]}


def studio(args, *, root):
    """Start/stop/status of the HyperFrames Studio for one project: background, no browser window."""
    project = _project(args)
    verb = args.get("action", "status")
    flag = {"start": ["--background", "--no-open", "--port", str(STUDIO_PORT)], "stop": ["--stop"], "status": ["--status", "--json"]}[verb]
    code, stdout, stderr = _cli(["preview", str(project), *flag], project, 120)
    url = f"http://127.0.0.1:{STUDIO_PORT}/" if verb != "stop" else None
    if code == 0 and verb != "stop":
        # The Studio's own deep link to this project, read from its managed status.
        _, status, _ = _cli(["preview", str(project), "--status", "--json"], project, 60)
        try:
            result = json.loads(status[status.index("{"):]).get("result") or {}
            url = result.get("studioUrl") or (result.get("preview") or {}).get("studioUrl") or url
        except ValueError:
            pass
    return {"ok": code == 0, "action": verb, "url": url, "output": (stdout or stderr)[-1500:]}


def verify(args, *, root):
    """Real round trip on a two-clip composition: lint -> render -> outcome contracts."""
    import shutil
    import tempfile
    import numpy as np
    from grant_agent import laya_video as V, laya_video_audio as A
    tl = _tools()
    base = Path(root) / ".agent_control" / "hyperframes-verify"
    base.mkdir(parents=True, exist_ok=True)
    project = Path(tempfile.mkdtemp(prefix="hf-", dir=base))
    (project / "vendor").mkdir()
    shutil.copyfile(tl["gsap"], project / "vendor/gsap.min.js")
    bed, _ = A.synth_bed(120, 2.0, gain_db=-12)
    (project / "audio").mkdir()
    A.write_wav(project / "audio/bed.wav", bed)
    (project / "index.html").write_text(
        '<!doctype html><html><head><meta charset="utf-8"><style>html,body{margin:0;width:320px;height:180px;background:#000}'
        '.clip{position:absolute;inset:0}#a{background:#0d1612}#b{background:#46b077}</style><script src="vendor/gsap.min.js"></script></head><body>'
        '<div id="root" data-composition-id="main" data-start="0" data-duration="2" data-fps="24" data-width="320" data-height="180">'
        '<div id="a" class="clip" data-start="0" data-duration="1" data-track-index="0"><div id="m" style="position:absolute;width:40px;height:40px;background:#e9eef0"></div></div>'
        '<div id="b" class="clip" data-start="1" data-duration="1" data-track-index="0"></div>'
        '<audio id="bed" src="audio/bed.wav" data-start="0" data-duration="2"></audio></div>'
        '<script>window.__timelines=window.__timelines||{};const tl=gsap.timeline({paused:true});'
        'tl.fromTo("#m",{x:0},{x:280,duration:1,ease:"none"},0);tl.set({},{},2);window.__timelines["main"]=tl;</script></body></html>',
        encoding="utf-8")
    before = timeline({"project": str(project)}, root=root)["scene"]
    split = edit({"project": str(project), "op": "split", "ref": "#a", "time": 0.5}, root=root)
    after = split.get("after") or before
    result = render({"project": str(project), "out": str(project / "out.mp4"), "fps": 24, "quality": "draft", "expectedS": 2.0}, root=root)
    o = result.get("outcome") or {}
    passed = bool(result["ok"] and o.get("durationOk") and o.get("frameCountOk") and o.get("blackFrames") == 0
                  and o.get("frozenRunMaxS", 9) < 1.5 and not o.get("audioClipping"))
    clips = lambda scene: sum(n["kind"] == "clip" for n in scene["nodes"])
    split_ok = bool(split.get("ok")) and clips(after) == clips(before) + 1
    return {"passed": passed and split_ok, "render": result, "split": {"ok": split_ok, "clipsBefore": clips(before), "clipsAfter": clips(after),
            "error": split.get("error")}, "project": str(project)}
