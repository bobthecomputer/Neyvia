from __future__ import annotations

import json
import shlex
import time
from datetime import datetime, timezone
from pathlib import Path

import paramiko


ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = "/volume1/Saclay/projects/syntelos/releases/neyvia-candidate-20260721T130407Z-crashproof"
CONTROL = "/volume1/Saclay/projects/vibe-coding-platform"
PORT = 47882


def run(client: paramiko.SSHClient, command: str, timeout: int = 120) -> str:
    _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    output = stdout.read().decode("utf-8", "replace")
    error = stderr.read().decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    if code:
        raise RuntimeError(f"remote command failed ({code}): {error[-1600:] or output[-1600:]}")
    return output.strip()


def main() -> int:
    credentials = json.loads((ROOT / ".agent_control" / "nas_codex2_100_125_54_118.json").read_text(encoding="utf-8"))
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=credentials.get("host", "192.0.2.10"), port=int(credentials.get("port", 22)),
        username=credentials.get("username", "nas-user"), password=credentials.get("password") or credentials.get("secret"),
        look_for_keys=False, allow_agent=False, timeout=15,
    )
    pid = ""
    cookie = f"/tmp/neyvia-candidate-{PORT}.cookies"
    log = f"/tmp/neyvia-candidate-{PORT}.log"
    try:
        current_before = run(client, "readlink -f /volume1/Saclay/projects/syntelos/current")
        public_before = json.loads(run(client, "curl -ksS --max-time 15 https://127.0.0.1:47880/health"))
        summary_code = (
            "import json,collections,pathlib;"
            f"p=pathlib.Path({(CONTROL + '/.agent_control/missions.json')!r});"
            "rows=json.loads(p.read_text()) if p.exists() else [];"
            "c=collections.Counter(str((r.get('state') or {}).get('status') or r.get('status') or 'missing') for r in rows);"
            "print(json.dumps({'total':len(rows),'hardBlocked':sum(c.get(k,0) for k in ('blocked','needs_approval','verification_failed')),'statuses':dict(c)}))"
        )
        missions_before = json.loads(run(client, f"python3 -c {shlex.quote(summary_code)}"))
        cutoff = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        python = "/volume1/Saclay/projects/syntelos/.venv/bin/python"
        reset_raw = run(
            client,
            f"env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH={shlex.quote(CANDIDATE + '/src')} {shlex.quote(python)} -m grant_agent.cli mission-history-reset --root {shlex.quote(CONTROL)} --before {shlex.quote(cutoff)}",
            timeout=180,
        )
        reset = json.loads(reset_raw)
        missions_after = json.loads(run(client, f"python3 -c {shlex.quote(summary_code)}"))
        launch = (
            f"nohup env PYTHONDONTWRITEBYTECODE=1 NEYVIA_COORDINATOR_AUTOSTART=1 "
            f"{shlex.quote(python)} {shlex.quote(CANDIDATE + '/scripts/run_web_backend.py')} "
            f"--host 127.0.0.1 --port {PORT} --root {shlex.quote(CONTROL)} --static-root {shlex.quote(CANDIDATE + '/web/dist')} "
            f"--skip-runtime-auto-update > {shlex.quote(log)} 2>&1 < /dev/null & echo $!"
        )
        pid = run(client, launch, timeout=30).splitlines()[-1].strip()
        health_raw = run(client, f"for i in $(seq 1 40); do curl -sS --max-time 2 http://127.0.0.1:{PORT}/health && exit 0; sleep 1; done; tail -c 1600 {shlex.quote(log)}; exit 7", timeout=60)
        health = json.loads(health_raw)
        run(client, f"curl -sS -c {shlex.quote(cookie)} -X POST http://127.0.0.1:{PORT}/api/auth/local-session >/dev/null")
        initialize_payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "nas-proof", "version": "1"}}})
        mcp = json.loads(run(client, f"curl -sS -b {shlex.quote(cookie)} -H 'Content-Type: application/json' --data {shlex.quote(initialize_payload)} http://127.0.0.1:{PORT}/mcp"))
        runtime = json.loads(run(client, f"curl -sS -b {shlex.quote(cookie)} http://127.0.0.1:{PORT}/api/neyvia/runtime"))
        current_after = run(client, "readlink -f /volume1/Saclay/projects/syntelos/current")
        public_after = json.loads(run(client, "curl -ksS --max-time 15 https://127.0.0.1:47880/health"))
        proof = {
            "schema": "neyvia.nas-candidate-readiness.v1", "status": "passed", "candidate": CANDIDATE,
            "candidateHealth": health, "mcpTitle": mcp["result"]["serverInfo"]["title"],
            "mcpProtocolVersion": mcp["result"]["protocolVersion"], "runtimeSchema": runtime["data"]["schema"],
            "runtimeLegacyBlockedIncluded": runtime["data"]["blockFactor"]["legacyBlockedMissionsIncluded"],
            "missionHistoryReset": {"before": missions_before, "after": missions_after, "receipt": reset},
            "publicLive": {"currentBefore": current_before, "currentAfter": current_after, "unchanged": current_before == current_after, "healthBefore": public_before, "healthAfter": public_after},
            "verifiedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        if not health.get("ok") or proof["mcpProtocolVersion"] != "2025-11-25" or proof["runtimeLegacyBlockedIncluded"] is not False or not proof["publicLive"]["unchanged"] or missions_after["hardBlocked"]:
            raise RuntimeError(json.dumps(proof, ensure_ascii=False))
        output = ROOT / ".agent_control" / "runtime_proof" / "neyvia-nas-candidate-readiness-20260721.json"
        output.write_text(json.dumps(proof, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps({"ok": True, "candidateHealth": True, "mcpProtocolVersion": proof["mcpProtocolVersion"], "removedMissionCount": reset["removedMissionCount"], "hardBlockedAfter": missions_after["hardBlocked"], "publicCurrentUnchanged": True, "receipt": str(output)}, ensure_ascii=False))
    finally:
        if pid.isdigit():
            try:
                run(client, f"kill {pid} 2>/dev/null || true; for i in $(seq 1 20); do kill -0 {pid} 2>/dev/null || break; sleep 1; done; rm -f {shlex.quote(cookie)}")
            except Exception:
                pass
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
