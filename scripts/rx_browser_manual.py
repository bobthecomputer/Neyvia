"""Author the admitted-engine contract in the browser CL manual (release browser gate).

Adds checks that the running agent engine is the admitted C2h Obscura build (exact sha256
from scripts/evidence/C2h-engine-admission.json) with stealth off, and a procedure that
observes both. Then compile: python scripts/cl_compile_manuals.py --source-file manuals/cl/browser.cl
"""
import json
from copy import deepcopy
from pathlib import Path

from rel_agent_manual import load, save

REPO = Path(__file__).resolve().parents[1]
admission = json.loads((REPO / "scripts/evidence/C2h-engine-admission.json").read_text(encoding="utf-8"))
engine_sha = admission["engineBinary"]["sha256"]

path, data = load("browser")
section = data["chapters"]["goal-cascade"]
section["checks"]["admitted-engine"] = {"tool": "neyvia.browser.state", "args": {},
                                        "expect": {"path": "headless.binarySha256", "op": "eq", "value": engine_sha}}
section["checks"]["engine-connected"] = {"tool": "neyvia.browser.state", "args": {},
                                         "expect": {"path": "headless.connected", "op": "eq", "value": True}}
section["checks"]["engine-without-stealth"] = {"tool": "neyvia.browser.state", "args": {},
                                               "expect": {"path": "headless.stealth", "op": "eq", "value": False}}
section["procedures"]["verify-admitted-engine"] = {
    "goal": "Observe that the connected agent browser engine is the source-admitted C2h Obscura build with stealth off.",
    "inputs": {"type": "object", "properties": {}},
    "steps": [{"action": "browser.state", "args": {}, "save": "connected", "check": "engine-connected"},
              {"action": "browser.state", "args": {}, "save": "identity", "check": "admitted-engine"},
              {"action": "browser.state", "args": {}, "save": "policy", "check": "engine-without-stealth"}]}
note = ("The admitted engine lives in " + admission["home"] + " (C2h source fork rebuilt from v0.2.4 plus the recorded patches); "
        "managed_executable() resolves it from scripts/evidence/C2h-engine-admission.json. Run verify-admitted-engine after headless.start; "
        "a different binary, a disconnected engine or stealth on fails the contract.")
section["guidance"] = [text for text in section["guidance"] if not text.startswith("The admitted engine lives in ")] + [note]
save(path, deepcopy(data))
print(json.dumps({"manual": str(path), "engineSha256": engine_sha}))
