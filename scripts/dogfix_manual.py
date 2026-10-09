"""Add one checked procedure to the existing authored workspace manual."""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from grant_agent.cl.manuals import cl_to_manual, manual_to_cl

if __name__ == "__main__":
    bug = int(sys.argv[1])
    source = REPO / "manuals/cl/workspace.cl"
    data = cl_to_manual(source.read_text(encoding="utf-8"))
    chapter = data["chapters"]["terminal"]
    chapter["checks"][f"dogfix-{bug}"] = {"tool": "workspace.read", "args": {
        "path": f"scripts/evidence/DOGFIX-{bug}.json"}, "expect": {
        "op": "contains", "path": "content", "value": '"passed": true'}}
    chapter["procedures"][f"dogfix-{bug}"] = {"goal": sys.argv[2], "inputs": {
        "type": "object", "properties": {}, "additionalProperties": False}, "steps": [{
        "action": "terminal.exec", "args": {"shell": "python", "timeoutMs": 120000,
        "command": f"import runpy; print(runpy.run_path('scripts/dogfix_contracts.py')['run']({bug}))"},
        "check": f"dogfix-{bug}", "save": "receipt"}]}
    source.write_text(manual_to_cl(data), encoding="utf-8", newline="\n")
