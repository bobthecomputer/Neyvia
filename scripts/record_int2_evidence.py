"""Record INT2 acceptance gates from real receipts, with missing gates explicit."""
from __future__ import annotations
import hashlib
import json
import re
from pathlib import Path
import shutil
import subprocess
import time

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "scripts/evidence/int2"


def read(name: str) -> dict:
    path = OUT / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def main() -> int:
    sealed = OUT / "merge-checks"
    sealed.mkdir(exist_ok=True)
    for name in ("merge-cl-vite.log", "merge-follow-vite.log", "related-cl.outcomes.json",
                 "related-cl-rerun.outcomes.json", "related-follow.outcomes.json",
                 "related-cl.pytest.log", "related-cl-rerun.pytest.log", "related-follow.pytest.log"):
        source = REPO / ".agent_control/int2" / name
        if source.exists():
            shutil.copy2(source, sealed / name)
    node = read("pytest/node-comparison.json")
    python = read("pytest/comparison.json")
    smoke = read("luna-b-transport-repair/comparison.json")
    manual = read("manuals/final-grounded-check.json")
    compiled = read("final-pycompile.json")
    compile_current = compiled.get("passed") is True and bool(compiled.get("files")) and all(
        (REPO / row["path"]).is_file() and hashlib.sha256((REPO / row["path"]).read_bytes()).hexdigest() == row["sha256"]
        for row in compiled["files"])
    smoke_inputs = read("luna-b-transport-repair/manifest.json").get("inputs", {})
    smoke_current = bool(smoke_inputs) and all((REPO / name).is_file() and
        hashlib.sha256((REPO / name).read_bytes()).hexdigest() == digest for name, digest in smoke_inputs.items())
    remote = read("follow-remote.json")
    remote_current = remote.get("configSha256") == hashlib.sha256((REPO / "config/neyvia_remote.json").read_bytes()).hexdigest()
    gates = {
        "both_merges_pycompile": all(read(name).get("passed") is True for name in ("merge-cl-pycompile.json", "merge-follow-pycompile.json")),
        "current_pycompile": compile_current,
        "both_merges_Vite": all(re.search(r"built in \d+(?:\.\d+)?s", (sealed / name).read_text(encoding="utf-8", errors="replace")) for name in ("merge-cl-vite.log", "merge-follow-vite.log")),
        "related_pytest": all(json.loads((sealed / name).read_text(encoding="utf-8")).get("exitstatus") == 0 for name in ("related-cl-rerun.outcomes.json", "related-follow.outcomes.json")),
        "manuals": manual.get("manuals") == 37 and all(manual.get(key) == 0 for key in
            ("groundedValidationExitCode", "clCompileCheckExitCode", "pluginSkillsCheckExitCode", "renderCheckExitCode")),
        "CL_real_calls": read("http.json").get("allPassed") is True,
        "followup_real_calls": read("follow-routes.json").get("passed") is True,
        "remote_real_calls": remote_current and remote.get("passed") is True,
        "sidebar_900": read("sidebar.json").get("passed") is True,
        "dispatch_calls": read("dispatch-returns.json").get("checked", 0) > 0 and read("dispatch-returns.json").get("missing") == [],
        "lost_lines_review": read("lost-lines-review.json").get("passed") is True,
        "six_Luna_b": smoke_current and smoke.get("complete") is True and smoke.get("allCurrentSuccessful") is True,
        "Node_no_new_failures": node.get("noNewFailures") is True,
        "full_pytest_no_new_failures": python.get("noNewFailures") is True,
        "owned_proof_cleanup": read("cleanup.json").get("backendStopped") is True and read("cleanup.json").get("assignedListenersAfter") == [],
    }
    artifacts = []
    durable_paths = subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard", "--", "scripts/evidence/int2"], cwd=REPO, text=True)
    for name in sorted(set(durable_paths.splitlines())):
        path = REPO / name
        if path.is_file() and path.is_relative_to(OUT):
            artifacts.append({"path": path.relative_to(REPO).as_posix(), "bytes": path.stat().st_size,
                              "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    source_hashes = {}
    changed = subprocess.check_output(["git", "diff", "--name-only", "8b9d17d9", "--", "src", "web", "config", "manuals", "plugins"], cwd=REPO, text=True)
    for name in changed.splitlines():
        path = REPO / name
        if path.is_file():
            source_hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    receipt = {
        "schema": "neyvia.INT2.integration.v1", "recordedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "sourceHeadBeforeReceiptCommit": head, "branch": "track/integrate-2",
        "baseline": "8b9d17d9b4ec0815c61739d92bcd94ad36df5fe3",
        "mergeOrder": [
            {"branch": "track/integrate-cl", "tip": "496b6fb69f7d801a265e0b55f293dd6463a0a196", "merge": "c0e388c72605e9b9c97c3de62787f8fad7c6ffed"},
            {"branch": "track/followups", "tip": "25394a9665f37a48fb25efef73d64f365212643f", "merge": "16d5cc64beb0966b831c1ea3b5bf61d7aaa094ef"}],
        "gates": gates, "complete": all(gates.values()),
        "pendingOrFailedGates": [name for name, passed in gates.items() if not passed],
        "manualSourceAuthority": "manuals/cl/*.cl; generated JSON, docs and plugin skills checked against compiled CL",
        "addedRuntimeCoverage": {
            "CL": {"tools": ["neyvia.cl", "neyvia.cl.describe"], "receipt": "scripts/evidence/int2/http.json"},
            "followups": {"tools": ["neyvia.gamedev.state", "neyvia.gamedev.receipts"],
                "commands": ["gamedev_state_command", "gamedev_receipts_command", "get_control_room_workspace_action_receipt_command"],
                "receipt": "scripts/evidence/int2/follow-routes.json"},
            "remote": {"routes": ["/api/ui/remote/frame"], "commands": ["remote_frame_command"],
                "receipts": ["scripts/evidence/int2/follow-remote.json", "scripts/evidence/int2/remote-missing-connection.json"]}},
        "nativeRefTransportRepair": "Generic proposal transport now states that observation results are unavailable until the proposal returns, and refreshed references replace earlier ones. Primer, authored goals, scoring, seeds, models and budgets unchanged. Earlier failed runs retained; new cohort is integration smoke, not benchmark improvement evidence.",
        "sidebar": {key: read("sidebar.json").get("checks", [{}])[0].get(key) for key in ("coldMs", "warmMs")},
        "remoteConfigRepair": "Restored the complete previous night proof-port authorization ranges 48271-48279 and 48351-48359 in the explicit whitelist, retaining followup and INT2 ports. Actual network calls remain restricted to INT2 ports; matched old/current remote tests and the native field/frame journey were replayed.",
        "incident": {"mergeCommit": "16d5cc64", "message": "x", "cause": "A baseline test invoked Git commit from an uninitialized fixture inside the worktree; Git found the ancestor repository and committed the staged second merge.",
                     "response": "Preserved the commit and interrupted trial; isolated corrected matched full runs with contained Git fixtures. No amend, push or merge-out. Incident trial excluded from acceptance."},
        "boundaries": ["Explicit proof ports 48601-48609 only; no credential/NAS access or public service operations.",
                       "Owned loopback HTTP/plugin/desktop forwarding and native disposable fixture proof; no second PC, installed-editor execution or microphone claim.",
                       "Chrome plugin has no available browser; no rendered frontend user-journey claim.",
                       "Native remote cold input is not consistently below 500 ms: a separate capture-speed attempt measured 974.41 ms and failed its budget; the failure is retained alongside complete functional and timed runs. Sidebar first load measured 9.26 seconds.",
                       "Node auth-restart file excluded from both sides because it requests an unassigned random port and reads a generated password file; inherited two failures retained.",
                       "Raw full pytest runs share a frozen guard; corrected paired reruns must use matched frozen guards with the parsing correction and unchanged authority boundaries recorded. Denials are actual failed operations, not simulated successes.",
                       "Task-local pytest TEMP initially hid the public tokenizer cache. Raw failures are retained; hash-verified cache restoration and actual affected-case replacements must be shown by the Python comparison.",
                       "Pinned official CUA driver downloaded to workspace only: 30,882,682 bytes, below 200 MB; hashes retained."],
        "sourceHashes": source_hashes, "artifacts": artifacts,
    }
    (REPO / "scripts/evidence/INT2.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"complete": receipt["complete"], "pendingOrFailedGates": receipt["pendingOrFailedGates"], "artifacts": len(artifacts)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
