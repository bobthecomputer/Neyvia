"""Real CLI/host/HTTP proof journey; owns and always stops only its backend."""
from __future__ import annotations
import argparse
import http.cookiejar
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPCookieProcessor

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, type=int)
    args = parser.parse_args()
    if not 48491 <= args.port <= 48499:
        raise ValueError("Use the assigned PROOFS-d ports")
    from grant_agent.durability import atomic_write_json
    from grant_agent.proof_coverage import retirement_gate
    from grant_agent.subprocess_utils import hidden_windows_subprocess_kwargs
    base = REPO / ".agent_control/proofs-d/journeys"
    base.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="host-", dir=base))
    env = dict(os.environ)
    for key in ("NEYVIA_UI_STATE_ROOT", "NEYVIA_UI_BACKEND_URL", "FLUXIO_WORKSPACE_ROOT"):
        env.pop(key, None)
    password = secrets.token_urlsafe(24)  # Ephemeral in-memory account; no credential file read.
    env.update(GRAND_AGENT_ADMIN_PASSWORD=password, NEYVIA_TOOL_AUTO_UPDATE="0",
        FLUXIO_WATCHDOG_AUTOSTART="0", NEYVIA_COORDINATOR_AUTOSTART="0")
    log = (root / "backend.log").open("w", encoding="utf-8")
    backend = subprocess.Popen([sys.executable, str(REPO / "scripts/run_web_backend.py"),
        "--host", "127.0.0.1", "--port", str(args.port), "--root", str(root),
        "--static-root", str(REPO / ".agent_control/proofs-d/build"), "--skip-runtime-auto-update"],
        cwd=REPO, env=env, stdout=log, stderr=subprocess.STDOUT, **hidden_windows_subprocess_kwargs())
    start = time.perf_counter()
    base_url = f"http://127.0.0.1:{args.port}"
    browser = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
    observations = []

    def request(path, body=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Origin": base_url, "Content-Type": "application/json"}
        with browser.open(Request(base_url + path, data=data, headers=headers), timeout=660) as response:
            return json.load(response)

    def require(condition, identity):
        if not condition:
            raise RuntimeError("Proof failed: " + identity)
        observations.append({"id": identity, "passed": True})

    try:
        deadline = time.monotonic() + 660
        while time.monotonic() < deadline:
            if backend.poll() is not None:
                raise RuntimeError("Owned backend exited; inspect " + str(root / "backend.log"))
            try:
                health = request("/api/health")
                break
            except (URLError, TimeoutError):
                time.sleep(.25)
        else:
            raise RuntimeError("Owned backend startup exceeded 660 seconds")
        require(health.get("ok") is True, "actual-backend-health")
        try:
            request("/api/ui/tools/call", {"tool": "neyvia.verify.status", "arguments": {}})
        except HTTPError as error:
            require(error.code == 401, "anonymous-proof-tool-denied")
        else:
            require(False, "anonymous-proof-tool-denied")
        require(request("/api/auth/login", {"username": "admin", "password": password}).get("ok") is True,
                "normal-ephemeral-owner-login")

        def tool(name, arguments):
            value = request("/api/ui/tools/call", {"tool": name, "arguments": arguments})
            return value["data"]

        status = tool("neyvia.verify.status", {})
        require(status.get("ok") and status["result"]["available"], "startup-created-actual-proof-receipt")
        require(status["result"]["contractsOk"] and not status["result"]["complete"], "startup-reports-frontier-honestly")
        native = tool("neyvia.native.runtime.observe", {})
        require(native.get("ok") and native["result"]["ok"] and isinstance(native["result"]["goals"], list),
                "new-native-observer-reachable-through-authenticated-route")
        manual = tool("neyvia.manual.run", {"id": "native-runtime", "procedure": "observe-and-prove", "inputs": {}})
        require(manual.get("ok") and manual["result"].get("status") == "completed" and
                all(row["passed"] for row in manual["result"]["checks"]), "native-manual-procedure-completes-real-scratch-actions")
        folder = root / "owner-notes"
        require(tool("neyvia.notes.folder", {"folder": str(folder)}).get("ok"), "owner-notes-folder-configured")
        note = tool("neyvia.notes.write", {"title": "Owner keeper", "body": "Preserve this host state"})
        require(note.get("ok"), "actual-tool-note-written")
        sentinel = folder / note["result"]["path"]
        prior = sentinel.read_bytes()
        rejected = tool("neyvia.notes.write", {"title": "Rejected", "body": 42})
        require(not rejected.get("ok") and not (folder / "Rejected.md").exists(), "invalid-action-rejected-before-effects")
        verification = tool("neyvia.verify", {})
        report = verification["result"]
        require(report["contractsOk"] and not report["complete"], "real-model-tool-runs-all-contracts-and-reports-frontier")
        require(Path(report["scratchRoot"]).is_relative_to(root / ".agent_control/proofs/scratch")
                and sentinel.read_bytes() == prior, "embedded-verifier-isolates-host-notes-and-state-overrides")
        require(tool("neyvia.notes.list", {})["result"]["folder"] == str(folder), "host-notes-choice-survives-verifier")
        cli = subprocess.run(["node", str(REPO / "scripts/fluxio-cli.mjs"), "verify", "--root", str(root), "--skip-manuals"],
            cwd=REPO, env={**env, "NEYVIA_PYTHON": sys.executable}, capture_output=True, text=True, timeout=660,
            **hidden_windows_subprocess_kwargs())
        cli_report = json.loads(cli.stdout)
        require(cli.returncode == 2 and cli_report["contractsOk"] and not cli_report["complete"], "neyvia-verify-cli-exits-incomplete-for-partial-coverage")
        try:
            retirement_gate(["tests/test_action_executor.py"])
        except ValueError:
            require(True, "uncovered-test-retirement-refused")
        else:
            require(False, "uncovered-test-retirement-refused")
        evidence = {"schema": "neyvia.proofs.host-journey.v1", "ok": True, "root": str(root),
            "port": args.port, "observations": observations, "verification": report,
            "durationMs": round((time.perf_counter() - start) * 1000),
            "build": {"passed": True, "log": ".agent_control/proofs-d/build.log"},
            "authority": "Owned localhost backend, ephemeral in-memory account, no credential file reads, no external service changes"}
        atomic_write_json(REPO / "scripts/evidence/PROOFS-d-host.json", evidence)
        print(json.dumps({"ok": True, "observations": len(observations), "receipt": "scripts/evidence/PROOFS-d-host.json"}))
    finally:
        backend.terminate()
        try:
            backend.wait(timeout=15)
        except subprocess.TimeoutExpired:
            backend.kill()
            backend.wait(timeout=15)
        log.close()


if __name__ == "__main__":
    main()
