"""LAYA video mod: brief -> first draft -> judge -> guarded improve -> master, plus A/B taste votes.

Thin wrappers over grant_agent.laya_video and the shared Scene core; no second judge.
"""
import json
from pathlib import Path


def _brief(path):
    from grant_agent import laya_video as V
    return V.read_brief(path)


def draft(args, *, root):
    from grant_agent import laya_video as V
    brief = _brief(args["brief"])
    edl = V.assemble(brief, V.capture_index(brief["spec"]["sources"]), out_dir=args["out"])
    return {"ok": True, "project": str(Path(args["out"]).resolve()), "shots": len(edl["shots"]),
            "captions": len(edl["captions"]), "seconds": V.total_seconds(edl)}


def inspect(args, *, root):
    from grant_agent import scene_core
    source = {"project": args["project"], "quality": args.get("quality", "preview")}
    scene = scene_core.transcribe("video", source)
    verdict = scene_core.judge(scene, record=False)
    return {"ok": True, "render": source["_latest"]["mp4"], "findings": verdict["findings"], "unknown": verdict["unknown"],
            "admitted": verdict["admitted"], "video": next(n for n in scene["nodes"] if n["id"] == "video")["measurements"],
            "sceneSha256": scene["sha256"]}


def improve(args, *, root):
    """One or more guarded rounds; each keeps a fix only on a strict finding reduction."""
    from grant_agent import scene_core
    rounds, excluded = [], set()
    for _ in range(int(args.get("rounds", 8))):
        source = {"project": args["project"]}
        scene = scene_core.transcribe("video", source)
        verdict = scene_core.judge(scene, record=False)
        allowed = sorted({f["fix"]["action"] for f in verdict["findings"]} - excluded - {"review"})
        allowed = [a for a in allowed if not args.get("allowedFixes") or a in args["allowedFixes"]]
        if not allowed:
            break
        result = scene_core.improve("video", source, {"max_steps": 1, "max_seconds": float(args.get("maxSeconds", 300)),
                                    "allowed_fixes": allowed, "guards": {"mustIncludeCoverage": "min", "captionCoverage": "min"}}, root=root)
        if not result["steps"]:
            break
        step = result["steps"][0]
        rounds.append({"action": step["finding"]["fix"]["action"], "status": step["status"], "receipt": result["receipt"],
                       "findings": len(result["verdict"]["findings"])})
        if step["status"] != "kept":
            excluded.add(step["finding"]["fix"]["action"])
    return {"ok": True, "rounds": rounds}


def vote(args, *, root):
    """Paul's A/B vote between two judged cuts becomes two personal episodes."""
    from grant_agent import laya_video as V, scene_core
    if not args.get("user"):
        raise ValueError("A taste vote needs the voting user")
    scenes = [scene_core.transcribe("video", {"project": args[k]}) for k in ("a", "b")]
    rows = V.vote(root, scenes[0], scenes[1], args["winner"], user=args["user"], reason=args.get("reason") or "A/B taste vote",
                  source="vote:" + args.get("voteId", scenes[0]["sha256"][:12] + "-" + scenes[1]["sha256"][:12]))
    return {"ok": True, "episodes": rows}


def verify(args, *, root):
    """Replay the recorded launch-cut proof against manuals/cl/laya-video.cl (no re-render)."""
    import grant_agent
    repo = Path(grant_agent.__file__).resolve().parents[2]
    evidence = repo / "scripts/evidence/VIDEO-proof.json"
    if not evidence.is_file():
        return {"passed": False, "reason": "No recorded proof; run scripts/laya_video_proof.py all"}
    proof = json.loads(evidence.read_text(encoding="utf-8"))
    from grant_agent.cl_skill import _parse_skill, _Expr
    skill = _parse_skill(repo / "manuals/cl/laya-video.cl")
    checks = [{"name": c.name, "passed": bool(_Expr(c.expr, {"proof": proof}, {}).run())} for c in skill.checks]
    return {"passed": all(c["passed"] for c in checks), "checks": checks, "replay": "recorded proof, not a new render"}
