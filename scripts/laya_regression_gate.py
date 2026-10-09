"""Regression gate: Neyvia's LAYA changes must not degrade LAYA's existing 2D-to-3D capability.

LAYA's 2D-to-3D work lives in the laya-improvement-kit (asset projects, shape operators, transition memory) and
its own System 1 service checkout; this repository's changes (hosting, new question set, seeded memory) must leave
all of it unchanged. Gates, each run for a "before" and an "after" phase and compared:

  G1 asset-project journey    the kit's real 11-step 2D-to-3D asset project journey on real saved GLBs
                               (scripts/verify_asset_project_journey.ps1, run from a scratch copy, read-only on the originals)
  G2 shape-operator routes    the committed reference-faithful shape memory route controls (read-only, same checks as
                               scripts/check_feasible_ray_memory_routes.py, nothing written)
  G3 System 1 on JevBench     the 231 public decisions through /ai/run (memory off) on the service in that phase;
                               "before" is the original service checkout and DB, "after" is the service Neyvia now hosts
  G4 memory isolation         the same decisions through /v1/decide with memory ON versus OFF on the seeded service:
                               every probability must be identical (the learned memory never leaks into other questions)

    python scripts/laya_regression_gate.py before      (original service on 48844)
    python scripts/laya_regression_gate.py after       (Neyvia-hosted service on 48845, seeded memory)
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
LAYA_PROJECT = Path(r"C:\Users\user\Documents\Codex\2026-09-30\the-ai-was-a-massive-improvement")
KIT = Path(r"C:\Users\user\Documents\Codex\2026-09-20\laya-c-est-l-alternative-open\outputs\laya-improvement-kit\capabilities")
HOME = Path.home()
WHISPER = HOME / "miniforge3/envs/whisper/python.exe"
MODEL = HOME / "Documents/Codex/2026-09-20/laya-c-est-l-alternative-open/work/models/laya-english"
SCRATCH = ROOT / ".agent_control/laya-visible/gate"
EVIDENCE = ROOT / "docs/evidence"
PORTS = {"before": 48844, "after": 48845}


def g1_journey():
    SCRATCH.mkdir(parents=True, exist_ok=True)
    source = (LAYA_PROJECT / "scripts/verify_asset_project_journey.ps1").read_text(encoding="utf-8")
    source = source.replace("Join-Path $PSScriptRoot ('..\\evidence\\asset-project-' + [guid]::NewGuid().ToString('N'))",
                            f"Join-Path '{SCRATCH}' ('asset-project-' + [guid]::NewGuid().ToString('N'))")
    source = source.replace("(Join-Path $PSScriptRoot '..\\evidence\\asset-project-journey.json')", f"'{SCRATCH / 'asset-project-journey.json'}'")
    assert "$PSScriptRoot" not in source, "journey script still writes beside the LAYA project"
    script = SCRATCH / "journey.ps1"
    script.write_text(source, encoding="utf-8")
    pwsh = str(Path.home() / "AppData/Local/Microsoft/WindowsApps/pwsh.exe")  # PowerShell 7: native stderr is not an error here
    started = time.time()
    done = subprocess.run([pwsh if Path(pwsh).is_file() else "powershell", "-NoProfile", "-File", str(script)], capture_output=True, text=True,
                          creationflags=subprocess.CREATE_NO_WINDOW, timeout=900)
    result = {"returncode": done.returncode, "seconds": round(time.time() - started, 1)}
    out = SCRATCH / "asset-project-journey.json"
    if done.returncode == 0 and out.is_file():
        value = json.loads(out.read_text(encoding="utf-8-sig"))
        result.update(passed=value.get("passed") is True, retainedSha256=value.get("retained_sha256"),
                      flags={k: value[k] for k in value if isinstance(value[k], bool)})
    else:
        result.update(passed=False, error=(done.stderr or done.stdout)[-400:])
    return result


def g2_routes():
    evidence = LAYA_PROJECT / "evidence/reference-shape-v10"
    sys.path.insert(0, str(KIT))
    from transition_memory import TransitionMemory, shape_scope
    from shape_operator_catalog import ShapeOperatorCatalog
    load = lambda p: json.loads(p.read_text(encoding="utf-8-sig"))
    request = load(evidence / "request.json")
    scope = shape_scope(request, load(evidence / "worker/correspondence.json"), load(evidence / "worker/protection.json"))
    memory = TransitionMemory(request["transition_memory_path"], read_only=True)
    try:
        catalog = ShapeOperatorCatalog()
        bound = catalog.select(memory, scope, allow_experimental=True)
        disabled = catalog.select(memory, scope, allow_experimental=True, memory_enabled=False)
        changed_source = catalog.select(memory, dict(scope, source_sha256="0" * 64), allow_experimental=True)
        recipe = catalog.select(memory, scope, allow_experimental=True, recipe_overrides={"assets.shape.feasible_ray.v1": "changed-recipe-control"})
        stored = load(evidence / "committed-memory-controls.json")
        return {"bound": bound["status"], "disabledOperator": disabled.get("operator_id"), "changedSourceOperator": changed_source.get("operator_id"),
                "changedRecipeOperator": recipe.get("operator_id"), "generation": bound["considered"][0]["memory"]["generation"],
                "matchesCommittedControls": bound["status"] == stored["bound"]["status"] and disabled.get("operator_id") == stored["disabled"].get("operator_id")
                and changed_source.get("operator_id") == stored["changed_source"].get("operator_id"),
                "passed": bound["status"] == "no_eligible_operator" and disabled.get("operator_id") == "assets.shape.cage.v1"}
    finally:
        memory.close()


def start_original(port):
    SCRATCH.mkdir(parents=True, exist_ok=True)
    env = {**__import__("os").environ, "PYTHONPATH": str(LAYA_PROJECT), "CUDA_VISIBLE_DEVICES": "", "LAYA_CUDA_GRAPHS": "0", "LAYA_WEIGHT_DTYPE": "float32",
           "USE_TF": "0", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "LAYA_CPU_THREADS": "4"}
    env.pop("LAYA_SOURCE", None)
    log = open(SCRATCH / "original-service.log", "ab")
    return subprocess.Popen([str(WHISPER), "-m", "laya_system1.service", "--model", str(MODEL), "--device", "cpu", "--port", str(port),
                             "--database", str(SCRATCH / "original.sqlite"), "--question-sets", str(LAYA_PROJECT / "question_sets"),
                             "--calibration", str(LAYA_PROJECT / "calibration/system1.json")], cwd=LAYA_PROJECT, env=env, stdout=log, stderr=log,
                            creationflags=subprocess.CREATE_NO_WINDOW)


def wait_ready(port, seconds=240):
    end = time.time() + seconds
    while time.time() < end:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/health", timeout=3) as response:
                if json.load(response).get("status") == "ready":
                    return True
        except Exception:
            time.sleep(2)
    return False


def g3_jevbench(port, name):
    output = LAYA_PROJECT / "evidence" / "jevbench" / f"regression-{name}.json"  # the runner requires this folder; new files only, moved out afterwards
    done = subprocess.run([sys.executable, str(LAYA_PROJECT / "scripts/run_jevbench.py"), "--endpoint", f"http://127.0.0.1:{port}/ai/run", "--name", name,
                           "--output", str(output), "--timeout", "180"], capture_output=True, text=True, cwd=LAYA_PROJECT,
                          creationflags=subprocess.CREATE_NO_WINDOW, timeout=3600)
    if not output.is_file():
        return {"passed": False, "error": (done.stderr or done.stdout)[-400:]}
    value = json.loads(output.read_text(encoding="utf-8"))
    for suffix in (".json", ".jsonl"):
        moved = output.with_suffix(suffix)
        if moved.is_file():
            shutil.move(str(moved), str(SCRATCH / moved.name))
    keys = ("correct", "total", "accuracy", "public_intelligence", "latency_p50_ms", "latency_p95_ms", "easy", "standard", "hard")
    summary = {k: value[k] for k in value if k in keys or "correct" in k or "accuracy" in k}
    return {"returncode": done.returncode, "summary": summary or {k: value[k] for k in list(value)[:8]}, "file": str(output)}


def g4_isolation(port):
    """Seeded memory must not change answers to any other question: identical probabilities with memory on and off."""
    def decide(body):
        request = urllib.request.Request(f"http://127.0.0.1:{port}/v1/decide", json.dumps(body).encode(), {"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.load(response)
    goals = ["Find the refund policy", "Rotate the mesh to face front", "Export the cleaned GLB", "Compare two candidate meshes", "Open the sprite sheet",
             "Preserve the silhouette while repairing floating parts", "Pick the detailed model over the faceted proxy", "Save the project"]
    differences, checked = [], 0
    for index, goal in enumerate(goals * 3):
        state = {"goal": goal, "options": ["search", "click", "type", "inspect", "done", "escalate"], "controls": [{"role": "button", "name": f"Action {index}"}],
                 "page": {"url": f"https://example.test/{index}", "title": goal}, "current": {"text": goal + f" (step {index})"}, "progress": f"{index} of 24",
                 "action_receipts": [], "previous": {"text": "before"}}
        for set_id, questions in (("neyvia.cl-state@1", ["next_action", "page_done", "relevance"]),):
            on = decide({"set": set_id, "questions": questions, "state": state, "scope": {"domain": "CL-State", "tabId": f"t{index % 3}"}, "memory": True})
            off = decide({"set": set_id, "questions": questions, "state": state, "scope": {"domain": "CL-State", "tabId": f"t{index % 3}"}, "memory": False})
            for q in questions:
                checked += 1
                if on["answers"][q]["p"] != off["answers"][q]["p"] or on["answers"][q]["source"] != "laya":
                    differences.append({"case": index, "question": q})
    return {"decisionsCompared": checked, "differences": differences, "passed": not differences}


if __name__ == "__main__":
    phase = sys.argv[1] if len(sys.argv) > 1 else "before"
    port = PORTS[phase]
    report = {"phase": phase, "port": port, "started": time.strftime("%Y-%m-%dT%H:%M:%S")}
    report["G1_asset_project_journey"] = g1_journey()
    print("G1", json.dumps(report["G1_asset_project_journey"])[:300], flush=True)
    report["G2_shape_operator_routes"] = g2_routes()
    print("G2", json.dumps(report["G2_shape_operator_routes"]), flush=True)
    process = None
    host = None
    try:
        if phase == "before":
            process = start_original(port)
        else:
            from grant_agent.laya_host import LayaHost, load_config
            SCRATCH.mkdir(parents=True, exist_ok=True)
            host = LayaHost(SCRATCH / "after-root", {**load_config(SCRATCH / "after-root"), "port": port}).start()
        report["serviceReady"] = wait_ready(port)
        if report["serviceReady"]:
            report["G3_jevbench"] = g3_jevbench(port, "after-hosted" if phase == "after" else "before-original")
            print("G3", json.dumps(report["G3_jevbench"])[:400], flush=True)
            if phase == "after":
                report["G4_memory_isolation"] = g4_isolation(port)
                print("G4", json.dumps(report["G4_memory_isolation"]), flush=True)
    finally:
        if process:
            process.terminate()
        if host:
            host.stop()
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (SCRATCH / f"gate-{phase}.json").write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print("done", phase)
