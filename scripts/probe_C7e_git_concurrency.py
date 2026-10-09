"""Measure the two existing concurrent Git adapter fixture rows in isolation."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sys
import time
import traceback
import uuid

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

PORT = 48947
SOURCE_PATHS = (
    "src/grant_agent/git_reference_adapter.py",
    "src/grant_agent/edge_fixture_c7d_adapters.py",
)
CASES = (
    ("adapters.git.objects", "c7d-adapters.adapters.git.objects.concurrency"),
    ("adapters.git.safety", "c7d-adapters.adapters.git.safety.concurrency"),
)


def main() -> int:
    output = REPO / "scripts/evidence/C7e-git-concurrency.json"
    root = REPO / ".agent_control/proofs/c7e-git-concurrency" / uuid.uuid4().hex
    git_path = shutil.which("git")
    if not git_path:
        raise RuntimeError("Installed Git executable was not found before fixture isolation")
    original_path = os.environ.get("PATH", "")

    from grant_agent.edge_fixture_c7d_local import _isolate
    from grant_agent.proof_credential_guard import install
    from grant_agent.proof_contracts import source_digest

    _isolate(root, PORT)
    install(root)
    # _isolate scopes home/state only. Preserve the installed Git selected before
    # isolation and refuse to proceed if a future helper change alters PATH.
    if os.environ.get("PATH", "") != original_path or shutil.which("git") != git_path:
        raise RuntimeError("Installed Git selection changed during fixture isolation")

    from grant_agent.edge_fixture_c7d_adapters import _git

    bindings = {name: source_digest(REPO / name) for name in SOURCE_PATHS}
    rows = []
    for index, (identity, case_id) in enumerate(CASES):
        case_root = root / str(index)
        case_root.mkdir(parents=True, exist_ok=False)
        started = time.monotonic()
        row = {
            "id": case_id,
            "contracts": [identity],
            "category": "concurrency",
            "status": "running",
            "boundary": "Exact existing c7d-adapters _git concurrency fixture using installed local Git; isolated local repository, no provider/network/publication behavior",
            "gitExecutable": git_path,
            "scratchRoot": str(case_root),
        }
        try:
            detail = _git(case_root, "concurrency", identity)
            row.update(status="passed", detail=detail)
        except Exception as error:
            row.update(
                status="failed",
                detail={
                    "type": type(error).__name__,
                    "error": str(error),
                    "traceback": traceback.format_exc()[-5000:],
                },
            )
        row["elapsedMs"] = round((time.monotonic() - started) * 1000, 2)
        rows.append(row)

    stable = bindings == {name: source_digest(REPO / name) for name in SOURCE_PATHS}
    report = {
        "schema": "neyvia.c7e-git-concurrency-probe.v1",
        "ok": stable and all(row["status"] == "passed" for row in rows),
        "sourceStable": stable,
        "sourceBindings": bindings,
        "explicitPort": PORT,
        "gitExecutable": git_path,
        "root": str(root),
        "rows": rows,
        "boundary": "Two exact existing generated C7 contract rows; source bindings cover only GitReferenceAdapter and its c7d-adapters builder. No campaign, timeout change, fixture weakening, external authority, or result substitution.",
    }
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "ok": report["ok"],
        "sourceStable": stable,
        "rows": [{"id": row["id"], "status": row["status"], "elapsedMs": row["elapsedMs"], "detail": row.get("detail")} for row in rows],
    }, ensure_ascii=False))
    return int(not report["ok"])


if __name__ == "__main__":
    raise SystemExit(main())
