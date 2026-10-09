"""Validate retained real-call receipts and seal FIX2 without hiding release failures."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import py_compile
import re
import socket
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
EVIDENCE = REPO / "scripts/evidence"
BASE = "199a54500634f4a87b3e8d266bc5bf4feed8565a"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args):
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, check=True).stdout.decode().strip()


def main():
    names = ["browser", "driver", "sdk", "search", "laya", "laya-fallback", "http", "verifier", "verifier-scoped"]
    receipts = {name: json.loads((EVIDENCE / ("fix2-" + name + ".json")).read_text(encoding="utf-8")) for name in names}
    for name in names[:-2]:
        assert receipts[name].get("ok", receipts[name].get("passed")), name
    browser, driver, sdk, search, laya = (receipts[name] for name in ("browser", "driver", "sdk", "search", "laya"))
    assert len(browser["invalidContractsRefused"]) == 4
    assert driver["stateCall"]["result"]["driver"]["available"] and len(driver["discoveredTools"]) == 22
    assert all(row["passed"] for row in sdk["checks"])
    assert search["searchNetworkOrChildEvents"] == [] and len(search["refusals"]) == 2
    accepted = laya["acceptedCascade"]
    assert accepted["route"] == "system1" and accepted["answer"] == "French" and not accepted["modelCalls"]
    confidence = next(row["providerDecision"]["confidence"] for row in accepted["trace"] if row["stage"] == "system1")
    assert confidence >= .95 and not laya["browserDownService"]["available"]
    hashes_checked = []
    for name in ("sdk", "laya"):
        for raw, expected in receipts[name]["sourceHashes"].items():
            path = REPO / raw.replace("\\", "/")
            assert sha(path) == expected, raw
            hashes_checked.append(str(path.relative_to(REPO)).replace("\\", "/"))
    for name in ("fix2-sdk-light.png", "fix2-sdk-dark.png"):
        assert (EVIDENCE / name).is_file()
    paths = git("diff", BASE, "--name-only").splitlines()
    paths += ["scripts/seal_fix2.py", "scripts/verify_fix2_http.py"]
    python_paths = sorted({path for path in paths if path.endswith(".py") and (REPO / path).is_file()})
    for path in python_paths:
        py_compile.compile(str(REPO / path), doraise=True)
    node_log = (REPO / ".agent_control/FIX2/node-tests.log").read_text(encoding="utf-8")
    passed = int(re.search(r"pass (\d+)", node_log).group(1))
    failed = int(re.search(r"fail (\d+)", node_log).group(1))
    assert passed == 55 and failed == 0
    build_log = (REPO / ".agent_control/FIX2/build.log").read_text(encoding="utf-8")
    assert "built in" in build_log
    compile_run = subprocess.run([sys.executable, "-B", "scripts/cl_compile_manuals.py", "--check"], cwd=REPO, capture_output=True, text=True, check=True)
    manuals = json.loads(compile_run.stdout)
    full, scoped = receipts["verifier"], receipts["verifier-scoped"]
    listening = []
    for port in range(48681, 48690):
        with socket.socket() as stream:
            stream.settimeout(.2)
            if stream.connect_ex(("127.0.0.1", port)) == 0:
                listening.append(port)
    assert not listening, "Stop owned proof listeners before sealing: " + str(listening)
    report = {
        "schema": "neyvia.FIX2.v1", "at": datetime.now(timezone.utc).isoformat(),
        "worktree": str(REPO), "branch": git("branch", "--show-current"), "base": BASE,
        "implementationHead": git("rev-parse", "HEAD"), "requestedBlockersProven": True, "releaseReady": False,
        "blockers": [
            {"item": 2, "commit": "adb4d87e", "works": "Integer workspace revision and string page revision have distinct authoritative CL contracts", "proof": "fix2-browser.json", "realNativeCalls": len(browser["calls"]), "refusals": 4},
            {"item": 3, "commit": "dff01ef8", "followup": "ebfcaddb", "works": "Shipped fresh-DOM browser provider and default cascade System1; service-down abstention before capture", "proof": ["fix2-laya.json", "fix2-laya-fallback.json"], "acceptedAnswer": accepted["answer"], "confidence": confidence, "generativeModelCalls": 0},
            {"item": 6, "commit": "d6031e43", "works": "All four generated kinds bundle A2 assets and credit; rendered web/PWA controls use them", "proof": "fix2-sdk.json", "checks": len(sdk["checks"])},
            {"item": 9, "commit": "fde99cb6", "works": "Both local pinned MIT executables verified; real stdio tools and native call; clear missing/corrupt setup error", "proof": "fix2-driver.json", "tools": 22, "downloaded": False},
            {"item": 12, "commit": "b8c3ef88", "works": "Local-only bounded in-process search selected before child/network operations", "proof": "fix2-search.json", "searchNetworkOrChildEvents": 0}
        ],
        "verification": {
            "pyCompile": {"ok": True, "files": python_paths}, "clArtifacts": manuals,
            "viteBuild": {"ok": True, "log": ".agent_control/FIX2/build.log", "sha256": sha(REPO / ".agent_control/FIX2/build.log")},
            "nodeTests": {"ok": True, "passed": passed, "failed": failed, "log": ".agent_control/FIX2/node-tests.log", "sha256": sha(REPO / ".agent_control/FIX2/node-tests.log")},
            "authenticatedHttp": {"ok": True, "calls": len(receipts["http"]["calls"]), "port": 48689},
            "fullNeyviaVerify": {"ok": full["ok"], "contractsOk": full["contractsOk"], "exitCode": 1, "areasPassed": sum(bool(a["ok"]) for a in full["areas"]), "areas": len(full["areas"]), "failures": full["failures"], "blockedManualEntries": full["blocked"], "sourceStableDuringRun": full["sourceStable"], "durationMs": full["durationMs"], "boundary": "Retained full run before the final service-down early-return repair; four affected areas and real LAYA were rerun afterward"},
            "affectedNeyviaVerify": {"ok": scoped["ok"], "contractsOk": scoped["contractsOk"], "exitCode": 1, "areas": [{"area": a["area"], "ok": a["ok"]} for a in scoped["areas"]], "failures": scoped["failures"], "coverageGatePassed": False}
        },
        "limits": ["Full neyvia verify remains blocked: missing Pillow/tokenizer cache/Syncthing, unassigned internal socket allocations, remote fixture port admission, native-runtime procedure and incomplete coverage", "Browser completion judgement is 1/2 with escalation; no general model improvement claimed", "Native Expo/desktop surfaces retain native UI; their web assets contain the DOM details kit", "Chrome plugin unavailable; rendered SDK proof used production AppBrowser and installed isolated Chromium", "Installed desktop, physical takeover, second-PC control and public promotion remain outside this proof"],
        "setup": {"laya": "docs/LAYA_SETUP.md: existing compatible CPU service and explicit NEYVIA_LAYA_URL", "driver": "tools/cua-driver-win/README.md: hash-verified local source or pinned 31MB setup", "node": "docs/FIX2.md: checkout-local venv from supplied Python, without downloads"},
        "authority": {"ports": list(range(48681, 48690)), "noDownloads": True, "noNasOrSavedCredentialReads": True, "noPushOrMerge": True, "ownedServicesStopped": not listening, "listeningAssignedPorts": listening},
        "sourceHashBindingsChecked": sorted(set(hashes_checked)),
        "artifacts": {"scripts/evidence/" + path.name: {"sha256": sha(path), "bytes": path.stat().st_size} for path in sorted(EVIDENCE.glob("fix2-*")) if path.is_file()}
    }
    (EVIDENCE / "FIX2.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"requestedBlockersProven": True, "releaseReady": False, "pythonFiles": len(python_paths), "nodePassed": passed, "fullVerifierFailures": full["failures"], "blocked": full["blocked"]}))


if __name__ == "__main__":
    main()
