"""Evidence script (plan 28 Build 4): the A/B taste mechanism, checked without casting Paul's vote.

Uses the launch proof's recorded before/after scenes in a scratch store and a clearly
synthetic user ("mechanism-check"): one vote writes two personal episodes immediately, an
exact replay of the preferred cut answers 'preferred' for that user only, another user gets
nothing, and forget(source) removes the vote. Paul's real votes go through
neyvia.mod.laya_video.vote with user='paul'. Writes scripts/evidence/VIDEO-taste.json.
"""
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from grant_agent import laya_video as V  # noqa: E402
from grant_agent.scene_core import episode_input  # noqa: E402
from grant_agent.laya_instant import store  # noqa: E402

RUN = Path("D:/NeyviaRuns/video/track-video/launch")


def main():
    before = json.loads((RUN / "scene-before.json").read_text(encoding="utf-8"))
    after = json.loads((RUN / "scene-after.json").read_text(encoding="utf-8"))
    root = Path("D:/NeyviaRuns/video/track-video/taste-ws") / str(time.time_ns())
    root.mkdir(parents=True)
    source = "vote:mechanism-check:before-vs-after"
    started = time.perf_counter()
    rows = V.vote(root, before, after, "b", user="mechanism-check", reason="Mechanism check, not a taste judgement", source=source)
    write_ms = (time.perf_counter() - started) * 1000
    memory = store(str(root))
    domain, data = episode_input(after)
    own = memory.query(domain, data, user="mechanism-check", labels=["preferred", "not-preferred"])
    other = memory.query(domain, data, user="someone-else", labels=["preferred", "not-preferred"])
    memory.forget(source + ":a")
    memory.forget(source + ":b")
    gone = memory.query(domain, data, user="mechanism-check", labels=["preferred", "not-preferred"])
    proof = {"episodesWritten": len(rows), "writeMs": round(write_ms, 1), "layer": "personal",
             "ownAnswer": own.get("answer"), "ownKind": own.get("confidenceKind"), "otherUserAnswer": other.get("answer"),
             "afterForget": gone.get("answer"), "training": False,
             "passed": len(rows) == 2 and own.get("answer") == "preferred" and other.get("answer") != "preferred" and gone.get("answer") != "preferred",
             "note": "Synthetic user; Paul has cast no vote. His votes use neyvia.mod.laya_video.vote(user='paul')."}
    (REPO / "scripts/evidence/VIDEO-taste.json").write_text(json.dumps(proof, indent=1), encoding="utf-8")
    print(json.dumps(proof, indent=1))


if __name__ == "__main__":
    main()
