"""neyvia.video.* native tools: agent-usable HyperFrames editing, LAYA video judgement and the improve loop.

Written on track/laya-video (plan 28); since the 7 Oct reconciliation every judgement, the improve loop, contact
sheets and taste votes run on the one video adapter (laya_video, domain "video"); free-form editing stays in
video_hyperframes and pre-render checks in laya_video_edit (domain "video-edit")."""
from __future__ import annotations

from pathlib import Path

TEXT = {"type": "string", "maxLength": 16000}
NUM = {"type": "number"}
PROJECT = {"type": "string", "maxLength": 1000, "description": "Project folder (inside the workspace or D:/NeyviaRuns/video)"}
DEFINITIONS = [
    ("video.new", "Create a HyperFrames video project driven by an edit decision list (EDL).",
     {"project": PROJECT, "width": {"type": "integer"}, "height": {"type": "integer"}, "fps": {"type": "integer"}, "duration": NUM,
      "background": TEXT, "title": TEXT}, ["project"]),
    ("video.add", "Place an image, video, text, caption or audio clip on the timeline; the composition recompiles.",
     {"project": PROJECT, "kind": {"enum": ["image", "video", "text", "caption", "audio"]}, "start": NUM, "duration": NUM, "src": TEXT,
      "text": TEXT, "id": TEXT, "track": {"type": "integer"}, "fit": {"enum": ["card", "contain", "cover"]}, "volume": NUM,
      "mediaStart": NUM, "fadeIn": NUM, "fadeOut": NUM, "tags": {"type": "array", "items": TEXT}, "intent": TEXT},
     ["project", "kind", "start", "duration"]),
    ("video.trim", "Trim a clip: new start, duration and/or source offset.",
     {"project": PROJECT, "id": TEXT, "start": NUM, "duration": NUM, "mediaStart": NUM}, ["project", "id"]),
    ("video.split", "Split a clip at an absolute time; the second half keeps the right source offset.",
     {"project": PROJECT, "id": TEXT, "at": NUM}, ["project", "id", "at"]),
    ("video.transition", "Set a clip entrance or exit: fade, crossfade, slide, rise, zoom or none.",
     {"project": PROJECT, "id": TEXT, "kind": {"enum": ["none", "fade", "crossfade", "slide", "rise", "zoom"]}, "seconds": NUM,
      "edge": {"enum": ["in", "out"]}}, ["project", "id", "kind", "seconds"]),
    ("video.caption", "Add a plain caption for a time range.",
     {"project": PROJECT, "text": TEXT, "start": NUM, "duration": NUM, "id": TEXT}, ["project", "text", "start", "duration"]),
    ("video.keyframe", "Keyframe scale, x, y or opacity on a clip (time relative to the clip).",
     {"project": PROJECT, "id": TEXT, "property": {"enum": ["scale", "x", "y", "opacity"]}, "at": NUM, "value": NUM,
      "ease": {"enum": ["none", "power1.inOut", "power2.out", "power2.inOut", "power3.out", "sine.inOut", "expo.out"]}},
     ["project", "id", "property", "at", "value"]),
    ("video.remove", "Remove a clip from the timeline.", {"project": PROJECT, "id": TEXT}, ["project", "id"]),
    ("video.timeline", "Observe the composition and timeline as a CL Scene (EDL, HyperFrames timeline and lint) and judge it before rendering.",
     {"project": PROJECT, "brief": {"type": ["object", "string"]}}, ["project"]),
    ("video.render", "Render the project to MP4 headless with HyperFrames.",
     {"project": PROJECT, "output": TEXT, "quality": {"enum": ["draft", "looks", "delivery"]}, "workers": {"type": "integer", "minimum": 1, "maximum": 8}},
     ["project"]),
    ("video.transcribe", "Transcribe a rendered video into a CL Scene: shots, cuts, black/frozen runs, loudness, true peak, beats, Whisper words with timings, keyframe OCR, caption boxes from the composition DOM, LAYA glance and source audit of every screen.",
     {"video": TEXT, "project": PROJECT, "brief": {"type": ["object", "string"]}, "speech": {"enum": ["auto", "off"]}}, ["video"]),
    ("video.judge", "Judge a rendered video against the CL video predicates (and a brief); findings name their fixes.",
     {"video": TEXT, "project": PROJECT, "brief": {"type": ["object", "string"]}}, ["video"]),
    ("video.contracts", "Fast outcome contracts for a render: ok, duration and frame count, no black or frozen frames, no clipping, captions in safe areas.",
     {"video": TEXT, "project": PROJECT, "brief": {"type": ["object", "string"]}}, ["video"]),
    ("video.contracts_proof", "Render (or reuse) a 3 s fixture with one clean and several defective sections and show each contract catches its defect.", {}, []),
    ("video.improve", "LAYA edits by itself from a CL brief file: first draft from real captures -> preview render -> judge -> one named EDL fix per round, kept only on a strict finding reduction with exact rollback otherwise -> master render; every outcome is an episode.",
     {"brief": TEXT, "out": TEXT, "maxRounds": {"type": "integer", "minimum": 0, "maximum": 24},
      "master": {"type": "boolean"}}, ["brief", "out"]),
    ("video.studio", "Serve HyperFrames Studio for a project headless (no window) on an explicit port 49165-49167, or stop it.",
     {"project": PROJECT, "port": {"type": "integer", "minimum": 49165, "maximum": 49167}, "stop": {"type": "boolean"}}, ["project", "port"]),
    ("video.contact_sheet", "Write a contact sheet of evenly spaced frames of a video.",
     {"video": TEXT, "out": TEXT, "count": {"type": "integer", "minimum": 4, "maximum": 60}}, ["video", "out"]),
    ("video.vote", "Record Paul's A/B preference between two judged cuts (two video Scenes) as personal taste episodes.",
     {"a": {"type": "object"}, "b": {"type": "object"}, "winner": {"enum": ["a", "b"]}, "reason": TEXT, "user": TEXT},
     ["a", "b", "winner", "reason", "user"]),
]
READ = {"video.timeline", "video.transcribe", "video.judge", "video.contracts", "video.contracts_proof"}
EXTERNAL = {"video.render", "video.improve", "video.studio"}


def mutability(name):
    return "read" if name in READ else "external_action" if name in EXTERNAL else "artifact_write"


def call(workspace, name, args):
    from . import video_hyperframes as hf
    root = Path(getattr(getattr(workspace, "bus", None), "root", None) or Path.cwd()) if workspace is not None else None
    if name == "video.new":
        project = hf.confine(args["project"], root)
        edl = hf.new_project(project, width=args.get("width", 1920), height=args.get("height", 1080), fps=args.get("fps", 30),
                             duration=args.get("duration"), background=args.get("background", "#0a0f0c"), title=args.get("title", ""))
        return {"ok": True, "project": str(project), "edl": edl}
    if name in {"video.add", "video.caption", "video.trim", "video.split", "video.transition", "video.keyframe", "video.remove"}:
        project = hf.confine(args["project"], root)
        edl = hf.load(project)
        if name in {"video.add", "video.caption"}:
            kind = "caption" if name == "video.caption" else args["kind"]
            result = hf.add_clip(edl, kind, start=args["start"], duration=args["duration"], src=args.get("src"), text=args.get("text"),
                                 id=args.get("id"), track=args.get("track"), fit=args.get("fit"), volume=args.get("volume"),
                                 media_start=args.get("mediaStart"), fade_in=args.get("fadeIn"), fade_out=args.get("fadeOut"),
                                 tags=args.get("tags"), intent=args.get("intent"), root=root)
        elif name == "video.trim":
            result = hf.trim(edl, args["id"], start=args.get("start"), duration=args.get("duration"), media_start=args.get("mediaStart"))
        elif name == "video.split":
            result = hf.split(edl, args["id"], args["at"])
        elif name == "video.transition":
            result = hf.transition(edl, args["id"], args["kind"], args["seconds"], args.get("edge", "in"))
        elif name == "video.keyframe":
            result = hf.keyframe(edl, args["id"], args["property"], args["at"], args["value"], args.get("ease", "power2.inOut"))
        else:
            result = hf.remove(edl, args["id"])
        hf.save(project, edl)
        return {"ok": True, "clip": result, "duration": hf.duration_of(edl), "clips": len(edl["clips"])}
    if name == "video.timeline":
        from .scene_core import judge, transcribe
        project = hf.confine(args["project"], root)
        scene = transcribe("video-edit", {"project": str(project), "brief": args.get("brief")})
        return {"scene": scene, "verdict": judge(scene, record=False)}
    if name == "video.render":
        project = hf.confine(args["project"], root)
        output = hf.confine(args.get("output") or str(project / "renders" / "out.mp4"), root)
        return hf.render(project, output, quality=args.get("quality", "draft"), workers=args.get("workers", 4))
    if name in {"video.transcribe", "video.judge", "video.contracts"}:
        from .scene_core import judge, transcribe
        source = {"video": str(hf.confine(args["video"], root)), "brief": args.get("brief"), "speech": args.get("speech", "auto")}
        if args.get("project"):
            source["project"] = str(hf.confine(args["project"], root))
        if name == "video.contracts":
            from .video_contracts import outcome
            return outcome(source)
        scene = transcribe("video", source)
        return scene if name == "video.transcribe" else {"verdict": judge(scene, record=False),
                                                        "sceneSha256": scene["sha256"], "metrics": scene.get("metrics")}
    if name == "video.contracts_proof":
        from .video_contracts import proof
        return proof()
    if name == "video.improve":
        import json as _json
        from . import laya_video as V
        from .scene_core import judge, transcribe
        brief = V.read_brief(hf.confine(args["brief"], root) if not Path(args["brief"]).is_absolute() else args["brief"])
        out = hf.confine(args["out"], root)
        project = out / "project"
        if not (project / "edl.json").is_file():
            V.assemble(brief, V.capture_index(brief["spec"]["sources"]), out_dir=project)
        state_path = out / "improve-state.json"
        state = _json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {}
        save = lambda s: state_path.write_text(_json.dumps(s, indent=1, default=str), encoding="utf-8")
        V.improve_cut(project, str(out / "episodes"), state, save=save, max_rounds=args.get("maxRounds", 12), log=lambda *a: None)
        result = {"rounds": [{k: r[k] for k in ("round", "action", "predicate", "status", "findingsBefore", "findingsAfter", "seconds")}
                             for r in state["rounds"]], "project": str(project)}
        if args.get("master"):
            source = {"project": str(project), "quality": "master"}
            verdict = judge(transcribe("video", source), record=False)
            result["master"] = {"mp4": source["_latest"]["mp4"], "findings": len(verdict["findings"])}
        save(state)
        return result
    if name == "video.studio":
        return hf.studio(hf.confine(args["project"], root), args["port"], stop=args.get("stop", False))
    if name == "video.contact_sheet":
        from .laya_video import contact_sheet
        return {"ok": True, "sheet": contact_sheet(hf.confine(args["video"], root), hf.confine(args["out"], root), count=args.get("count", 24))}
    if name == "video.vote":
        from .laya_video import vote
        return {"episodes": vote(str(root), args["a"], args["b"], args["winner"], user=args["user"], reason=args["reason"], source="neyvia.video.vote")}
    raise KeyError(name)
