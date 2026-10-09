"""Exercise the existing CL runner/compiler with the greeting mod contract."""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from neyvia_sdk import NeyviaClient


def main():
    rows = []
    def execute(step, procedure):
        client = NeyviaClient("http://127.0.0.1:48911", timeout=180)
        client.sign_in()
        result = client.cl('G: mod.hello.greet(name="Paul").greeting == "Hello, Paul!"\nrun ' + procedure + '\ndone()')
        row = {"step": step, "ok": result.get("ok"), "status": result.get("status"),
               "checks": [check for item in result.get("results", []) for check in item.get("checks", [])]}
        rows.append(row)
        print(json.dumps(row), flush=True)
        if not result.get("ok"):
            raise RuntimeError(result.get("text", str(result))[-2000:])
        return client
    try:
        ordinary = 'manuals-next.verified-run(id="hello-module",procedure="verify-greeting",inputs={},chapter="overview",runId="",decisions={},scopeTools=["neyvia.mod.hello.greet"])'
        execute("ordinary-1", ordinary)
        execute("ordinary-2", ordinary)
        client = execute("compile", 'manuals-next.verified-compile(id="hello-module",chapter="overview",procedure="verify-greeting",inputs={},minRuns=2)')
        catalog = client.tool("neyvia.manual.compiled", {"id": "hello-module"})
        scripts = catalog.get("scripts", catalog.get("result", {}).get("scripts", []))
        script = next(row for row in scripts if row.get("procedure") == "verify-greeting")
        rows.append({"step": "retained-script", "script": script})
        execute("compiled-run", 'manuals-next.verified-script-run(scriptId=' + json.dumps(script["scriptId"]) + ',inputs={},runId="",decisions={},scopeTools=["neyvia.mod.hello.greet"])')
    finally:
        (REPO / "scripts/evidence/MOD-compiled.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
