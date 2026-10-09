"""Run one isolated direct verifier pass to expose the rendered-family worker error."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
from prove_C7d_browser import PrivateDesktopProcess

PORT = 48983
OUTPUT = REPO / "scripts/evidence/C7e-rendered-failure.json"
LOG = REPO / ".agent_control/C7e/compiled-families/c7d-rendered-diagnostic.log"


def main() -> int:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    for key in list(environment):
        if any(word in key.upper() for word in ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")):
            environment.pop(key, None)
    environment.update(
        NEYVIA_C7_PORT=str(PORT),
        PYTHONIOENCODING="utf-8",
        NEYVIA_TOOL_AUTO_UPDATE="0",
        FLUXIO_WATCHDOG_AUTOSTART="0",
        NEYVIA_COORDINATOR_AUTOSTART="0",
    )
    command = [
        str(sys.executable), str(REPO / "scripts/verify_c7_edges.py"),
        "--port", str(PORT), "--output", str(OUTPUT),
        "--semantic-fixtures", "--family", "c7d-rendered",
    ]
    wrapper = "\n".join((
        "import json, os, subprocess, sys, traceback",
        f"command = {command!r}",
        "try:",
        "    result = subprocess.run(command, cwd=os.getcwd(), env=dict(os.environ), capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=10800)",
        f"    open({str(LOG)!r}, 'w', encoding='utf-8').write('=== stdout ===\\n' + result.stdout + '\\n=== stderr ===\\n' + result.stderr)",
        "    raise SystemExit(result.returncode)",
        "except Exception:",
        f"    open({str(LOG)!r}, 'w', encoding='utf-8').write(traceback.format_exc())",
        "    raise",
    ))
    process = PrivateDesktopProcess(
        sys.executable,
        environment,
        ["-c", wrapper],
    )
    started = time.time()
    try:
        exit_code = process.wait(10830)
        remaining = process.pids()
        if remaining:
            process.terminate()
            process.wait(15)
        report = None
        if OUTPUT.is_file():
            report = json.loads(OUTPUT.read_text(encoding="utf-8"))
        result = report or {
            "schema": "neyvia.c7e-rendered-diagnostic.v1",
            "ok": False,
            "family": "c7d-rendered",
            "explicitPort": PORT,
            "error": "Direct verifier exited without writing its report; inspect the owned log",
        }
        result["diagnostic"] = {
            "privateDesktop": process.name,
            "pid": process.pid,
            "exitCode": exit_code,
            "durationSeconds": round(time.time() - started, 2),
            "remainingOwnedPids": process.pids(),
            "log": LOG.relative_to(REPO).as_posix() if LOG.is_file() else None,
            "sourceBindings": {
                "scripts/diagnose_C7e_rendered.py": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "scripts/verify_c7_edges.py": hashlib.sha256((REPO / "scripts/verify_c7_edges.py").read_bytes()).hexdigest(),
                "src/grant_agent/edge_fixture_c7d_rendered.py": hashlib.sha256((REPO / "src/grant_agent/edge_fixture_c7d_rendered.py").read_bytes()).hexdigest(),
            },
            "boundary": "One direct generated rendered-family verifier run on an owned private desktop; only its worker output and returned receipt support the diagnosis.",
        }
        result["ok"] = bool(exit_code == 0 and result.get("ok"))
        OUTPUT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        print(json.dumps({"ok": result["ok"], "exitCode": exit_code, "diagnostic": OUTPUT.as_posix(), "log": LOG.as_posix()}))
        return int(not result["ok"])
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(15)
        process.close()


if __name__ == "__main__":
    raise SystemExit(main())
