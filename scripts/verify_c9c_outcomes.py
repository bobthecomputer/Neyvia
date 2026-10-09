"""Lead re-execution of retained actual outputs against frozen outcome recipes."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import uuid

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from grant_agent.durability import atomic_write_json, atomic_write_text
from grant_agent.lesson_replay import digest, relative
from grant_agent.subprocess_utils import hidden_windows_subprocess_kwargs

def main():
    evidence = json.loads((REPO / "scripts/evidence/C9c-lifecycle.json").read_text(encoding="utf-8"))
    source = evidence["sourceManifest"]
    regression = evidence["regressionSuite"]["manifests"][0]
    cases = [("source", source, evidence["source"]),
             ("promoted-next-run", source, evidence["promotedReplay"]),
             ("reverted-next-run", source, evidence["revertedReplay"])]
    for kind in ("beneficialTrial", "harmfulTrial"):
        trial = evidence[kind]["evolver"]
        cases += [(kind+"-source-before", source, trial["caseBefore"]), (kind+"-source-after", source, trial["caseAfter"]),
                  (kind+"-regression-before", regression, trial["suiteBefore"][0]),
                  (kind+"-regression-after", regression, trial["suiteAfter"][0])]
    root = REPO / "scripts/evidence/C9c-runs/lead-outcomes" / uuid.uuid4().hex
    records = []
    for name, manifest, output in cases:
        directory = root / name
        directory.mkdir(parents=True)
        if digest(manifest) != output["manifestSha256"]:
            raise ValueError("Frozen manifest does not match a retained real run")
        for filename, text in manifest["inputs"].items():
            atomic_write_text(directory / relative(filename), text)
        for filename, text in output["files"].items():
            atomic_write_text(directory / relative(filename), text)
        result = subprocess.run([sys.executable, manifest["validator"]], cwd=directory, capture_output=True,
            text=True, encoding="utf-8", timeout=40, **hidden_windows_subprocess_kwargs())
        observed = json.loads(result.stdout.splitlines()[-1])
        if result.returncode != 0 or observed["criteria"] != output["executableCriteria"]:
            raise ValueError("Independent execution disagrees with the recorded outcome: " + name)
        records.append({"name": name, "exitCode": result.returncode, "observed": observed,
                        "outputSha256": {f: hashlib.sha256((directory / f).read_bytes()).hexdigest() for f in output["files"]}})
    if evidence["beneficialTrial"]["state"] != "promoted" or evidence["harmfulTrial"]["state"] != "rejected":
        raise ValueError("Actual promotion/rejection states are wrong")
    receipt = {"schema": "neyvia.C9c-independent-outcomes.v1", "records": records,
               "sourceSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "passed": True}
    atomic_write_json(REPO / "scripts/evidence/C9c-independent-outcomes.json", receipt)
    print(json.dumps({"realRecipesReexecuted": len(records), "passed": True}))

if __name__ == "__main__": main()
