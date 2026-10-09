"""Real paired Evolver execution for LAYA binding, using a bounded CPU fixture.

This proves architecture storage, executable evaluations and promotion gates.
It does not train a LAYA model or demonstrate general model improvement.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
CHILD = r'''
import ctypes,json,sys,time
architecture,item=json.load(sys.stdin)
mix=architecture['execution_genes']['lexical_mix']
started=time.perf_counter()
text=item['text'].casefold() if mix == 1 else item['text']
answer=text.split().count('alpha')
latency=(time.perf_counter()-started)*1000
class Memory(ctypes.Structure):
 _fields_=[('cb',ctypes.c_ulong),('faults',ctypes.c_ulong),('peak',ctypes.c_size_t),('working',ctypes.c_size_t),('poolPeak',ctypes.c_size_t),('pool',ctypes.c_size_t),('nonPoolPeak',ctypes.c_size_t),('nonPool',ctypes.c_size_t),('page',ctypes.c_size_t),('peakPage',ctypes.c_size_t)]
memory=Memory();memory.cb=ctypes.sizeof(memory)
ctypes.windll.kernel32.GetCurrentProcess.restype=ctypes.c_void_p
ctypes.windll.psapi.GetProcessMemoryInfo.argtypes=[ctypes.c_void_p,ctypes.POINTER(Memory),ctypes.c_ulong]
if not ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(),ctypes.byref(memory),memory.cb): raise RuntimeError('OS memory measurement failed')
print(json.dumps({'answer':answer,'correct':answer==item['expected'],'cpu_ms':latency,'peak_memory_mib':memory.peak/(1024*1024)}))
'''


def evaluate(genome, item, seed):
    from grant_agent.evolver_laya import decode_architecture, HARD_GATES
    architecture = decode_architecture(genome)
    completed = subprocess.run([sys.executable, "-I", "-c", CHILD], input=json.dumps([architecture, item]),
                               capture_output=True, text=True, encoding="utf-8", timeout=15)
    if completed.returncode:
        raise RuntimeError("Owned CPU evaluator failed: " + completed.stderr[-500:])
    measured = json.loads(completed.stdout)
    gates = {"cpu_only": True, "cpu_p95_le_50_ms": measured["cpu_ms"] <= 50,
             "peak_memory_le_100_mib": measured["peak_memory_mib"] <= 100,
             "train_only_fit": item["split"] == "train", "typed_valid": type(measured["answer"]) is int}
    assert set(gates) == set(HARD_GATES)
    return {"objectives": {"train_correct": int(measured["correct"])}, "hard_gates": gates,
            "measurement": {**measured, "seed": seed, "processExitCode": completed.returncode,
                            "boundary": "Real stdlib CPU token counter; no learned model or fitting"}}


def run(root):
    from grant_agent import evolver_laya as laya
    from grant_agent.evolver_core import EvolutionError
    root = Path(root).resolve()
    if not root.is_relative_to(REPO / ".agent_control/int3"):
        raise ValueError("LAYA proof root must be task-owned")
    architecture = {"schema": "laya.architecture_genome.v1",
                    "graph": [{"id": name} for name in ("lexical", "shared_state", "head")],
                    "genes": {"lexical_mix": {"value": 0, "allowed": [0, 1]}}, "execution_genes": {"lexical_mix": 0}}
    path = root / "architecture/r3-genome.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(architecture, sort_keys=True)
    if path.exists() and path.read_text(encoding="utf-8") != encoded:
        raise ValueError("Existing scratch architecture differs; use a fresh owned runtime root")
    path.write_text(encoded, encoding="utf-8")
    panels = [{"id": "int3-panel-" + str(panel), "role": "discovery" if panel == 0 else "held_out",
               "items": [{"id": f"int3-{panel}-{case}", "text": "Alpha " * (case + 1),
                          "expected": case + 1, "split": "train"} for case in range(8)]} for panel in range(4)]
    established = laya.establish(root, panels, [Path(__file__)], architecture, max_trials=1, min_pairs=8, max_seconds=300)
    engine, seed = established["engine"], established["registration"]
    candidate = deepcopy(architecture)
    candidate["genes"]["lexical_mix"]["value"] = 1
    candidate["execution_genes"]["lexical_mix"] = 1
    registration = laya.register(engine, candidate, seed["id"], "lexical_mutation", {"generation": 1, "fit_split": "original_train"})
    receipt = laya.trial(engine, registration["id"], evaluate)
    assert receipt["state"] == "accepted" and receipt["promoted"] and len(receipt["stages"]) == 3, receipt
    assert all(stage["sample_count"] == 8 and stage["eligible"] for stage in receipt["stages"])
    repeated = laya.trial(engine, registration["id"], evaluate)
    assert repeated["deduplicated"] is True and repeated["id"] == receipt["id"]
    guards = []
    def rejected(name, action):
        try:
            action()
        except (EvolutionError, ValueError) as error:
            guards.append({"name": name, "errorType": type(error).__name__, "error": str(error)})
        else:
            raise AssertionError("Failure guard did not refuse: " + name)
    rejected("invalid architecture", lambda: laya.architecture_genome({"schema": "wrong"}))
    rejected("unknown operator", lambda: laya.register(engine, candidate, seed["id"], "unknown", {"generation": 1}))
    rejected("fourth generation", lambda: laya.register(engine, candidate, seed["id"], "lexical_mutation", {"generation": 4}))
    rejected("teacher fit on held out", lambda: laya.register(engine, candidate, seed["id"], "teacher_typed_distillation", {"generation": 1, "fit_split": "held_out"}))
    rejected("direct incumbent replacement", lambda: engine.set_incumbent(laya.DOMAIN, seed["id"]))
    path.write_text(encoded + " ", encoding="utf-8")
    try:
        rejected("frozen architecture tamper", lambda: engine._verify_frozen(laya.DOMAIN))
    finally:
        path.write_text(encoded, encoding="utf-8")
    assert laya.decode_architecture(engine._genome(laya.DOMAIN, registration["id"])) == candidate
    report = {"ok": True, "domain": laya.DOMAIN, "seed": seed["id"], "candidate": registration["id"],
              "trial": receipt, "guards": guards, "deduplicated": True, "store": str(laya.store_path(root)),
              "sourceSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "boundary": "Real Rust canonical validation, SQLite architecture binding and 48 CPU executable paired observations across three disjoint train-side panels. CPU model training absent; held-out role here is Evolver reconfirmation over disposable train fixtures, not LAYA public benchmark."}
    output = REPO / "scripts/evidence/int3/runtime/laya-binding.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args()
    value = run(args.root)
    print(json.dumps({"ok": value["ok"], "trial": value["trial"]["id"], "guards": len(value["guards"])}))
