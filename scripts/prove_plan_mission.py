"""Real Claude builds and Codex verification through the saved mission scheduler."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--codex-model", help="Explicit supported model; omitted uses the account's configured default")
    parser.add_argument("--builder-model", default="haiku")
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    root.relative_to(REPO)
    root.mkdir(parents=True, exist_ok=True)
    origin = root / "origin"
    if origin.exists():
        raise ValueError("Use a fresh proof folder to preserve earlier evidence")
    origin.mkdir()
    def git(*parts, cwd=origin):
        subprocess.run(["git", *parts], cwd=cwd, check=True, capture_output=True, text=True)
    git("init")
    (origin / "README.md").write_text("Disposable two-track mission proof.\n", encoding="utf-8")
    git("add", "README.md")
    git("-c", "user.name=Codex Proof", "-c", "user.email=proof@localhost", "commit", "-m", "Initialize disposable proof")
    for track in ("alpha", "beta"):
        git("worktree", "add", "-b", "proof/" + track, str(root / track))
    plan = root / "plan.md"
    plan.write_text("""# Two-track mission proof
## §0 Shared rules
Work only in your assigned scratch worktree. Never access other project trees, global settings or services. No commits, push or merge. Use local Node only. Keep work small.
| Track | Worktree | Backend |
|---|---|---|
| alpha | alpha | 48184 |
| beta | beta | 48185 |
## §1 alpha: sum utility
Create sum.cjs exporting a sum(a,b) function with module.exports=sum. Verify with Node that sum(2,3) equals 5 and sum(-2,2) equals 0. Keep any local check scripts in .cjs because the parent package uses ESM. Run the commands and quote actual outputs.
## §2 beta: reverse utility
Create reverse.cjs exporting reverse(text) with module.exports=reverse. Verify with Node that reverse('abc') equals 'cba' and reverse('') equals ''. Keep any local check scripts in .cjs because the parent package uses ESM. Run the commands and quote actual outputs.
""", encoding="utf-8")
    from grant_agent.web_backend import FluxioWebBackend
    from grant_agent.neyvia_workspace_tools import workspace_for
    from grant_agent.nightshift import nightshift_for
    from grant_agent.neyvia_missions import call, records, summary
    backend = FluxioWebBackend(root, REPO / "web" / "dist")
    service = nightshift_for(root, backend)
    workspace = workspace_for(root, backend)
    receipt = {"root": str(root), "models": {"builder": args.builder_model, "verifier": args.codex_model}}
    try:
        created = workspace.call("mission.from_plan", {"id": "two-track-proof", "planPath": str(plan), "folder": str(root),
                "acceptanceChecks": ["Both actual artifacts pass Node assertions", "Codex independently reruns each builder's acceptance"],
                "builder": {"model": args.builder_model, "permissionMode": "full-access"},
                "verifier": {"model": args.codex_model, "effort": "low", "permissionMode": "read-only"},
                "budget": {"maxTaskSeconds": args.timeout}, "holdAtPlanPercent": 70})
        receipt["created"] = created
        tasks = service.tasks()
        assert len(tasks) == 3 and all(task["status"] == "waiting" and not task["armed"] for task in tasks)
        assert next(task for task in tasks if task["id"].endswith(":verify-all"))["needs"] == ["two-track-proof:alpha-build", "two-track-proof:beta-build"]
        for bad in (plan.read_text().replace("| beta | beta | 48185 |", "| beta | alpha | 48185 |"), plan.read_text().replace("| beta | beta | 48185 |", "| beta | beta | 48184 |")):
            from grant_agent.neyvia_mission_plan import compile_plan
            try:
                compile_plan(bad, folder=str(root))
                raise AssertionError("Invalid allocation accepted")
            except ValueError:
                pass
        receipt["allocationFailuresRejected"] = True
        started = call(service, "mission.control", {"id": "two-track-proof", "action": "start"})
        assert started["status"] == "approval_required"
        workspace.approve(started["approvalId"])
        receipt["start"] = call(service, "mission.control", {"id": "two-track-proof", "action": "start"})
        deadline = time.monotonic() + args.timeout
        previous = None
        while time.monotonic() < deadline:
            tasks = service.tasks()
            statuses = [(task["id"], task["status"], task.get("reason")) for task in tasks]
            verify = next(task for task in tasks if task["id"].endswith(":verify-all"))
            if any(task["status"] != "done" for task in tasks if task["id"].endswith("-build")):
                assert verify["status"] == "waiting", "Verifier started before all builds completed"
            if statuses != previous:
                receipt.setdefault("stateHistory", []).append({"tasks": statuses, "at": time.time()})
                print(json.dumps(statuses), flush=True)
                previous = statuses
            if all(task["status"] in {"done", "blocked"} for task in tasks) or any(task["status"] == "blocked" for task in tasks):
                break
            time.sleep(1)
        receipt["missions"], receipt["summary"], receipt["tasks"] = records(service), summary(service), service.tasks()
        receipt["runs"] = [service.broker.get_run(task["runId"]) for task in service.tasks() if task.get("runId")]
        receipt["transcripts"] = {run["sessionId"]: service.broker.read(run["sessionId"], limit=200)
                                  for run in receipt["runs"] if run.get("sessionId")}
        if not all(task["status"] == "done" for task in service.tasks()):
            receipt["status"] = "blocked"
            return 1
        for track, command in (("alpha", "const assert=require('node:assert/strict'), mod=require('./sum.cjs'), sum=typeof mod==='function'?mod:mod.sum; assert.equal(sum(2,3),5); assert.equal(sum(-2,2),0); console.log('SUM PASS')"),
                               ("beta", "const assert=require('node:assert/strict'), mod=require('./reverse.cjs'), reverse=typeof mod==='function'?mod:mod.reverse; assert.equal(reverse('abc'),'cba'); assert.equal(reverse(''),''); console.log('REVERSE PASS')")):
            output = subprocess.run(["node", "-e", command], cwd=root / track, capture_output=True, text=True, check=True)
            receipt.setdefault("independentChecks", []).append({"track": track, "exitCode": output.returncode, "output": output.stdout})
        receipt["status"] = "passed"
        return 0
    finally:
        for task in service.tasks():
            if task["status"] == "running":
                service.stop(task["id"], "Proof runner ended")
        (root / "receipt.json").write_text(json.dumps(receipt, indent=2, ensure_ascii=False), encoding="utf-8")
        print(str(root / "receipt.json"), flush=True)
        service.close()
        service.broker.close()
        workspace.close()


if __name__ == "__main__":
    raise SystemExit(main())
