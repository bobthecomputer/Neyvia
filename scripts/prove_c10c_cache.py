"""Replay an actual native captured source through the production cache reader."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from grant_agent.research_hops import source_cached
from grant_agent.research_pipeline import ResearchPipeline
from grant_agent.transition_memory import atomic_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-proof", required=True)
    parser.add_argument("--obscura-port", type=int, required=True)
    parser.add_argument("--laya-port", type=int, required=True)
    args = parser.parse_args()
    if any(port not in range(48771, 48780) for port in (args.obscura_port, args.laya_port)):
        parser.error("Explicit assigned ports only")
    os.environ.update(NEYVIA_TOOL_AUTO_UPDATE="0", NEYVIA_COORDINATOR_AUTOSTART="0",
        FLUXIO_WATCHDOG_AUTOSTART="0", PYTHONDONTWRITEBYTECODE="1",
        NEYVIA_BROWSER_PROOF_PORTS=",".join(map(str, range(48771, 48780))),
        NEYVIA_OBSCURA_EXE=str(REPO / ".agent_control/T20/obscura-v0.2.3/bin/obscura.exe"),
        NEYVIA_LAYA_URL=f"http://127.0.0.1:{args.laya_port}")
    proof_path = (REPO / args.native_proof).resolve()
    if not proof_path.is_relative_to(REPO / "scripts/evidence"):
        parser.error("Owned evidence only")
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    receipt = json.loads(Path(proof["receiptPath"]).read_text(encoding="utf-8"))
    root = Path(proof["receiptPath"]).parents[2]
    source = next(s for s in receipt["sources"] if s["url"] == receipt["answer"]["citations"][0]["url"])
    original = Path(source["receiptPath"])
    destination = root / "cache-replayed-source.json"
    replay_receipt = {}
    pipeline = ResearchPipeline(root, obscura_port=args.obscura_port, timeout=60)
    try:
        replay = source_cached(pipeline, source["requestedUrl"], pipeline.slots.get(),
            receipt["question"], [receipt["plan"]["hops"][0]["query"]], destination,
            receipt["asOf"], replay_receipt)
    finally:
        pipeline.close()
    original_sha = hashlib.sha256(original.read_bytes()).hexdigest()
    replay_sha = hashlib.sha256(destination.read_bytes()).hexdigest()
    result = {"schema": "neyvia.C10c.cache.v1", "passed": bool(replay.get("cached") and
        replay_receipt.get("sourceCacheHits") and original_sha == replay_sha),
        "sourceBinding": pipeline.source_binding, "originalSource": str(original),
        "replayedSource": str(destination), "originalSha256": original_sha,
        "replayedSha256": replay_sha, "sourceCacheHits": replay_receipt.get("sourceCacheHits", []),
        "boundary": "Production ResearchPipeline and source_cached, existing captured public source; byte-identical replay with no source fetch or model call"}
    result_path = root / "cache-replay.json"
    atomic_json(result_path, result)
    if not result["passed"]:
        raise RuntimeError("Actual cached replay was not byte-identical")
    proof["cacheReplay"] = {"passed": True, "path": str(result_path),
        "sha256": hashlib.sha256(result_path.read_bytes()).hexdigest()}
    atomic_json(proof_path, proof)
    print(json.dumps({"passed": True, "cacheReplay": str(result_path.relative_to(REPO))}))


if __name__ == "__main__":
    main()
