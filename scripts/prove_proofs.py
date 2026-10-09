"""Real CLI/host/HTTP proof journey; owns and always stops only its backend."""
from __future__ import annotations
import argparse
import hashlib
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


def main(*, port_range=((48361, 48369), (48461, 48469), (48481, 48489), (48501, 48509)), evidence_path="scripts/evidence/PROOFS-host.json",
         build_root=".agent_control/proofs/build", build_log=".agent_control/proofs/build.log"):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--output", type=Path, default=REPO / evidence_path)
    parser.add_argument("--pending-test", default="tests/test_action_executor.py")
    parser.add_argument("--build-log", default=build_log)
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("--builder-browser", action="store_true", help="Also observe the actual classic Builder; retain failed/unmeasured claims as frontier")
    parser.add_argument("--static-root", type=Path, default=REPO / build_root)
    parser.add_argument("--mobile-journey", action="store_true")
    parser.add_argument("--track", choices=("proofs", "proofs-e"), default="proofs")
    parser.add_argument("--receipt", type=Path, help="Alias for the host receipt output")
    parser.add_argument("--startup-timeout-seconds", type=float)
    args = parser.parse_args()
    if args.timeout <= 0 or (args.startup_timeout_seconds is not None and args.startup_timeout_seconds <= 0):
        parser.error("Proof timeouts must be positive")
    if args.receipt is not None:
        args.output = args.receipt
    ranges = (port_range,) if len(port_range) == 2 and all(isinstance(value, int) for value in port_range) else port_range
    if not any(first <= args.port <= last for first, last in ranges):
        raise ValueError("Use the assigned PROOFS ports")
    from grant_agent.proof_credential_guard import install
    install(REPO)
    build_path = (REPO / args.static_root).resolve()
    build_path.relative_to(REPO)
    build_log_path = (REPO / args.build_log).resolve()
    build_log_path.relative_to(REPO)
    if not (build_path / "index.html").is_file() or "built in" not in build_log_path.read_text(encoding="utf-8", errors="replace"):
        raise RuntimeError("Build the owned frontend and retain its successful log before the host journey")
    entry = json.loads((build_path / "desktop-entry.json").read_text(encoding="utf-8"))
    artifacts = {}
    for name in ["index.html", "desktop-entry.json", entry["js"], *entry.get("css", [])]:
        path = (build_path / name).resolve()
        path.relative_to(build_path)
        artifacts[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    from grant_agent.durability import atomic_write_json
    from grant_agent.proof_coverage import retirement_gate
    from grant_agent.subprocess_utils import hidden_windows_subprocess_kwargs
    base = REPO / ".agent_control/proofs/journeys"
    base.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="host-", dir=base))
    from grant_agent.proof_credential_guard import prepare_broker_fixture
    prepare_broker_fixture(root)
    env = dict(os.environ)
    for key in ("NEYVIA_UI_STATE_ROOT", "NEYVIA_UI_BACKEND_URL", "FLUXIO_WORKSPACE_ROOT"):
        env.pop(key, None)
    password = secrets.token_urlsafe(24)  # Ephemeral in-memory account; no credential file read.
    env.update(GRAND_AGENT_ADMIN_PASSWORD=password, NEYVIA_TOOL_AUTO_UPDATE="0",
        FLUXIO_WATCHDOG_AUTOSTART="0", NEYVIA_COORDINATOR_AUTOSTART="0", NEYVIA_PROOF_CREDENTIAL_GUARD="1")
    # The actual product broker may inspect provider configuration/history.
    # Select empty owned profiles as well as guarding all saved provider data.
    for key, directory in (("CODEX_HOME", "codex"), ("CLAUDE_CONFIG_DIR", "claude"),
                           ("OPENCLAW_STATE_DIR", "openclaw")):
        profile = root / "empty-profiles" / directory
        profile.mkdir(parents=True)
        env[key] = str(profile)
    log = (root / "backend.log").open("w", encoding="utf-8")
    backend = subprocess.Popen([sys.executable, str(REPO / "scripts/run_web_backend.py"),
        "--host", "127.0.0.1", "--port", str(args.port), "--root", str(root),
        "--static-root", str(build_path), "--skip-runtime-auto-update"],
        cwd=REPO, env=env, stdout=log, stderr=subprocess.STDOUT, **hidden_windows_subprocess_kwargs())
    start = time.perf_counter()
    base_url = f"http://127.0.0.1:{args.port}"
    browser = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
    observations = []

    def request(path, body=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Origin": base_url, "Content-Type": "application/json"}
        with browser.open(Request(base_url + path, data=data, headers=headers), timeout=args.timeout) as response:
            return json.load(response)

    def require(condition, identity):
        if not condition:
            raise RuntimeError("Proof failed: " + identity)
        observations.append({"id": identity, "passed": True})

    try:
        deadline = time.monotonic() + (args.startup_timeout_seconds or args.timeout)
        while time.monotonic() < deadline:
            if backend.poll() is not None:
                raise RuntimeError("Owned backend exited; inspect " + str(root / "backend.log"))
            try:
                health = request("/api/health")
                break
            except (URLError, TimeoutError):
                time.sleep(.25)
        else:
            raise RuntimeError("Owned backend startup exceeded its explicit proof deadline")
        require(health.get("ok") is True, "actual-backend-health")
        try:
            request("/api/ui/tools/call", {"tool": "neyvia.verify.status", "arguments": {}})
        except HTTPError as error:
            require(error.code == 401, "anonymous-proof-tool-denied")
        else:
            require(False, "anonymous-proof-tool-denied")
        require(request("/api/auth/login", {"username": "admin", "password": password}).get("ok") is True,
                "normal-ephemeral-owner-login")
        for name, expected_hash in artifacts.items():
            with browser.open(Request(base_url + "/" + name.lstrip("./")), timeout=900) as response:
                served_hash = hashlib.sha256(response.read()).hexdigest()
            require(served_hash == expected_hash, "actual-served-build-bytes:" + name)

        if args.mobile_journey:
            def command(name, payload):
                return request("/api/backend", {"command": name, "payload": payload})["data"]

            created = command("create_ios_app_command", {"root": str(root), "name": "HTTP Contract Journey",
                "directory": "apps/http-journey", "bundleIdentifier": "com.neyvia.httpjourney", "installDependencies": False})
            project = Path(created["projectRoot"])
            observed = command("get_ios_studio_status_command", {"root": str(project)})
            require(created["created"] and observed["project"]["recognized"]
                    and observed["project"]["bundleIdentifier"] == "com.neyvia.httpjourney",
                    "migrated-mobile-create-and-observe-through-real-http")
            saved = command("save_windows_ios_config_command", {"root": str(project), "distro": "default", "minimumIos": "17.2"})
            require(saved["minimumIos"] == "17.2" and command("get_ios_studio_status_command", {"root": str(project)})["project"]["recognized"],
                    "migrated-mobile-config-command-and-fresh-status")
            keeper = (project / "package.json").read_bytes()
            try:
                command("create_ios_app_command", {"root": str(root), "name": "Rejected", "directory": "../escape",
                    "bundleIdentifier": "com.neyvia.rejected", "installDependencies": False})
            except HTTPError as error:
                require(error.code in {400, 500} and (project / "package.json").read_bytes() == keeper,
                        "migrated-mobile-http-scope-rejection-preserves-project")
            else:
                require(False, "migrated-mobile-http-scope-rejection-preserves-project")

        def tool(name, arguments):
            value = request("/api/ui/tools/call", {"tool": name, "arguments": arguments})
            return value["data"]

        status = tool("neyvia.verify.status", {})
        require(status.get("ok") and status["result"]["available"], "startup-created-actual-proof-receipt")
        require(status["result"]["contractsOk"] and not status["result"]["complete"], "startup-reports-frontier-honestly")
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
        builder_browser = None
        if args.builder_browser:
            import importlib.util
            spec = importlib.util.spec_from_file_location("owned_builder_verifier", REPO / "scripts/verify_authenticated_live_control.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            browser_args = argparse.Namespace(url=base_url + "/control?ui=classic", username="admin", password=password,
                password_file="", report_path=str(root / "builder-report.json"),
                screenshot_path=str(root / "builder.png"), timeout=5, with_browser=True,
                browser_channel="", browser_path="", headed=False, allowed_origin=base_url)
            builder_browser = module.build_report(browser_args)
            atomic_write_json(root / "builder-report.json", builder_browser)
            require(any(row["checkId"] == "browser-account-login" and row["passed"] is True
                        for row in builder_browser["checks"]), "actual-browser-owner-login")
        cli_command = ["node", str(REPO / "scripts/fluxio-cli.mjs"), "verify", "--root", str(root), "--skip-manuals"]
        # Reobserve the unchanged earlier track's areas without rewriting its
        # coverage rows. The owned areas already have current-source mappings.
        for area in ("awareness", "dictation", "frontend", "frontend-models", "notes-files", "settings"):
            cli_command += ["--area", area]
        cli = subprocess.run(cli_command,
            cwd=REPO, env={**env, "NEYVIA_PYTHON": sys.executable}, capture_output=True, text=True, timeout=args.timeout,
            **hidden_windows_subprocess_kwargs())
        cli_report = json.loads(cli.stdout)
        require(cli.returncode == 2 and cli_report["contractsOk"] and not cli_report["complete"], "neyvia-verify-cli-exits-incomplete-for-partial-coverage")
        try:
            retirement_gate([args.pending_test])
        except ValueError:
            require(True, "uncovered-test-retirement-refused")
        else:
            require(False, "uncovered-test-retirement-refused")
        evidence = {"schema": "neyvia.proofs.host-journey.v1", "ok": True, "root": str(root),
            "port": args.port, "observations": observations, "verification": report,
            "builderBrowser": builder_browser,
            "durationMs": round((time.perf_counter() - start) * 1000),
            "build": {"passed": True, "log": args.build_log, "root": str(build_path.relative_to(REPO)), "artifacts": artifacts},
            "authority": "Owned localhost backend and ephemeral in-memory account; Python saved-credential opens and unscoped provider launches rejected by the proof guard; no external service changes"}
        atomic_write_json(args.output, evidence)
        print(json.dumps({"ok": True, "observations": len(observations), "receipt": str(args.output)}))
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
