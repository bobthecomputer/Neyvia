"""Compile changed implementation files and record their exact inspected bytes."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import py_compile
import subprocess

REPO = Path(__file__).resolve().parents[1]
BASE = "ea26c48809ffa590f5969ea8a7e55ccf3aca95a6"


def main() -> int:
    names = set(subprocess.check_output(
        ["git", "diff", "--name-only", BASE, "--", "src/grant_agent", "scripts", "plugins/neyvia/mcp"],
        cwd=REPO, text=True).splitlines())
    names.update(path.relative_to(REPO).as_posix() for path in (REPO / "scripts").glob("intcl_*.py"))
    names.add("tests/test_cl_product_completion.py")
    names.add("tests/test_cl_config_validation.py")
    names.add("tests/test_native_mcp_read_only.py")
    names.add("scripts/record_intcl_evidence.py")
    names = sorted(name for name in names if name.endswith(".py")
                   and not name.startswith("scripts/evidence/") and (REPO / name).is_file())
    rows, failures = [], []
    for name in names:
        path = REPO / name
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            failures.append({"path": name, "error": str(exc)})
        rows.append({"path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    result = {"schema": "neyvia.intcl.pycompile.v1", "exitCode": int(bool(failures)),
              "passed": not failures, "files": rows, "failures": failures}
    destination = REPO / "scripts/evidence/intcl/checks/pycompile.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"compiled": len(rows), "passed": result["passed"]}))
    return result["exitCode"]


if __name__ == "__main__":
    raise SystemExit(main())
