#!/usr/bin/env python3
"""Non-interactive NAS backup + managed CLI install attempt for Phase A.

Uses .agent_control/nas_codex2_100_125_54_118.json (same pattern as pull_nas_tree.py).
Uploads via SSH+base64 because Synology SFTP cannot open /volume1 paths for this account.
Does not perform interactive device-auth logins; writes a receipt documenting
remaining operator steps.
"""

from __future__ import annotations

import base64
import json
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import paramiko


ROOT = Path(__file__).resolve().parents[1]
CREDENTIALS_PATH = ROOT / ".agent_control" / "nas_codex2_100_125_54_118.json"
RECEIPT_DIR = ROOT / ".agent_control" / "nas_transfers"
DEFAULT_REMOTE_ROOT = "/volume1/Saclay/projects"
DEFAULT_RUNTIME_ROOT = "/volume1/Saclay/runtime"
DEFAULT_PROJECT = "vibe-coding-platform"


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _load_credentials() -> dict:
    payload = json.loads(CREDENTIALS_PATH.read_text(encoding="utf-8"))
    return {
        "host": payload.get("host", "192.0.2.10"),
        "port": int(payload.get("port", 22)),
        "username": payload.get("username") or payload.get("user") or "nas-user",
        "password": payload.get("password") or payload.get("secret") or "",
        "remoteRoot": payload.get("remoteRoot") or DEFAULT_REMOTE_ROOT,
    }


def _connect(credentials: dict) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=credentials["host"],
        port=credentials["port"],
        username=credentials["username"],
        password=credentials["password"],
        look_for_keys=False,
        allow_agent=False,
        timeout=20,
    )
    return client


def _run(client: paramiko.SSHClient, command: str, *, timeout: int = 600) -> dict:
    started = time.time()
    _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    return {
        "command": command,
        "exitCode": code,
        "stdout": out[-12000:],
        "stderr": err[-4000:],
        "elapsedSec": round(time.time() - started, 2),
    }


def _upload_via_ssh(client: paramiko.SSHClient, local_path: Path, remote_path: str) -> dict:
    remote_dir = str(PurePosixPath(remote_path).parent)
    mkdir = _run(client, f"mkdir -p '{remote_dir}'", timeout=30)
    if mkdir["exitCode"] != 0:
        return {"ok": False, "stage": "mkdir", **mkdir}
    payload = base64.b64encode(local_path.read_bytes()).decode("ascii")
    # Keep the command under typical SSH arg limits by using a here-doc style stdin write.
    command = (
        f"python3 - <<'PY'\n"
        f"import base64, pathlib\n"
        f"path = pathlib.Path({remote_path!r})\n"
        f"path.parent.mkdir(parents=True, exist_ok=True)\n"
        f"path.write_bytes(base64.b64decode({payload!r}))\n"
        f"print('uploaded', path, path.stat().st_size)\n"
        f"PY"
    )
    result = _run(client, command, timeout=120)
    return {"ok": result["exitCode"] == 0, "stage": "write", **result}


def main() -> int:
    RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = _utc_stamp()
    receipt_path = RECEIPT_DIR / f"nas_managed_cli_install_{stamp}.json"
    doctor_path = RECEIPT_DIR / f"nas_runtime_doctor_{stamp}.json"
    receipt: dict = {
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "phase": "A",
        "goal": "NAS backup + non-interactive managed CLI install",
        "steps": [],
        "doctor": None,
        "remainingOperatorAuth": [],
        "status": "started",
    }

    if not CREDENTIALS_PATH.exists():
        receipt["status"] = "blocked"
        receipt["error"] = f"Missing credentials file: {CREDENTIALS_PATH}"
        receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        print(json.dumps(receipt, indent=2))
        return 2

    try:
        credentials = _load_credentials()
    except Exception as exc:  # noqa: BLE001
        receipt["status"] = "blocked"
        receipt["error"] = f"Unable to load credentials: {exc}"
        receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        print(json.dumps(receipt, indent=2))
        return 2

    if not credentials["password"]:
        receipt["status"] = "blocked"
        receipt["error"] = "Credentials file has no password/secret for non-interactive SSH."
        receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        print(json.dumps(receipt, indent=2))
        return 2

    remote_root = credentials["remoteRoot"].rstrip("/")
    project_root = f"{remote_root}/{DEFAULT_PROJECT}"
    runtime_root = DEFAULT_RUNTIME_ROOT
    backup_root = f"{remote_root}/backups/neyvia-phase-a-{stamp}"

    try:
        client = _connect(credentials)
    except Exception as exc:  # noqa: BLE001
        receipt["status"] = "blocked"
        receipt["error"] = f"SSH connect failed: {type(exc).__name__}: {exc}"
        receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        print(json.dumps(receipt, indent=2))
        return 3

    try:
        probe = _run(client, "uname -a && pwd && id && which python3 || which python || true", timeout=30)
        receipt["steps"].append({"name": "ssh_probe", **probe})
        if probe["exitCode"] != 0:
            receipt["status"] = "blocked"
            receipt["error"] = "Remote probe failed"
            receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
            print(json.dumps(receipt, indent=2))
            return 3

        backup = _run(
            client,
            (
                f"mkdir -p '{backup_root}' && "
                f"tar -C '{project_root}' -czf '{backup_root}/grant_agent_runtimes_scripts.tgz' "
                f"src/grant_agent/runtimes scripts/install_nas_runtime_stack.py "
                f"scripts/nas_runtime_doctor.py 2>&1; "
                f"ls -la '{backup_root}'"
            ),
            timeout=180,
        )
        receipt["steps"].append({"name": "backup", "backupRoot": backup_root, **backup})

        upload_map = {
            "scripts/install_nas_runtime_stack.py": ROOT / "scripts" / "install_nas_runtime_stack.py",
            "scripts/nas_runtime_doctor.py": ROOT / "scripts" / "nas_runtime_doctor.py",
            "scripts/nas_managed_cli_phase_a_install.py": ROOT / "scripts" / "nas_managed_cli_phase_a_install.py",
            "src/grant_agent/runtimes/managed_cli.py": ROOT / "src" / "grant_agent" / "runtimes" / "managed_cli.py",
            "src/grant_agent/runtimes/__init__.py": ROOT / "src" / "grant_agent" / "runtimes" / "__init__.py",
            "src/grant_agent/external_cli_bridge.py": ROOT / "src" / "grant_agent" / "external_cli_bridge.py",
            "docs/GROK_BUILD_OPEN_SURFACES.md": ROOT / "docs" / "GROK_BUILD_OPEN_SURFACES.md",
            "web/src/neyvia/providerModelCatalog.js": ROOT / "web" / "src" / "neyvia" / "providerModelCatalog.js",
        }
        uploaded: list[str] = []
        upload_errors: list[dict] = []
        for relative, local_path in upload_map.items():
            if not local_path.exists():
                upload_errors.append({"path": relative, "error": "local_missing"})
                continue
            remote_path = f"{project_root}/{relative}"
            result = _upload_via_ssh(client, local_path, remote_path)
            if result.get("ok"):
                uploaded.append(relative)
            else:
                upload_errors.append({"path": relative, "error": result.get("stderr") or result.get("stdout") or "upload_failed"})
        receipt["steps"].append(
            {
                "name": "upload_phase_a_files",
                "uploaded": uploaded,
                "errors": upload_errors,
                "projectRoot": project_root,
            }
        )

        install_script = f"{project_root}/scripts/install_nas_runtime_stack.py"
        doctor_script = f"{project_root}/scripts/nas_runtime_doctor.py"
        install = _run(
            client,
            (
                f"python3 '{install_script}' "
                f"--runtime-root '{runtime_root}' "
                f"--install-kimi-code --install-claude-code --install-grok-build --json"
            ),
            timeout=1800,
        )
        receipt["steps"].append({"name": "install_managed_clis", **install})

        doctor = _run(
            client,
            f"python3 '{doctor_script}' --extra-bin-dir '{runtime_root}/bin' --json",
            timeout=120,
        )
        receipt["steps"].append({"name": "doctor", **doctor})
        doctor_payload = None
        try:
            doctor_payload = json.loads(doctor["stdout"] or "{}")
        except json.JSONDecodeError:
            doctor_payload = {"rawStdout": doctor["stdout"], "parseError": True}
        receipt["doctor"] = doctor_payload
        doctor_path.write_text(json.dumps(doctor_payload, indent=2), encoding="utf-8")

        managed = (doctor_payload or {}).get("managedCliDetected") or {}
        auth = (doctor_payload or {}).get("managedCliAuthentication") or {}
        remaining = []
        if not managed.get("claude-code"):
            remaining.append(
                "Install Claude Code on NAS: "
                f"python3 {install_script} --runtime-root {runtime_root} --install-claude-code"
            )
        else:
            remaining.append(
                "Authenticate Claude Code interactively on NAS as nas-user: `claude auth login` "
                "(or configure an approved Anthropic credential under the runtime HOME)."
            )
        if not managed.get("grok-build"):
            remaining.append(
                "Install Grok Build on NAS: "
                f"python3 {install_script} --runtime-root {runtime_root} --install-grok-build"
            )
        else:
            remaining.append(
                "Authenticate Grok Build: `grok login --device-auth` (browser/device flow) "
                "or export XAI_API_KEY for the runtime environment. "
                "Note: ~/.grok may already exist from a prior partial install."
            )
        if not managed.get("kimi-code"):
            remaining.append(
                "Install Kimi Code on NAS: "
                f"python3 {install_script} --runtime-root {runtime_root} --install-kimi-code"
            )
        else:
            remaining.append("Authenticate Kimi Code: `kimi login` (or `/login` inside Kimi Code).")
        if not managed.get("codex"):
            remaining.append(
                "Optional: install Codex with --install-codex / --install-openclaw, then authenticate Codex."
            )
        for key, state in auth.items():
            if state == "not_probed":
                remaining.append(
                    f"{key}: CLI detected but auth not probed non-interactively "
                    f"(doctor reports '{state}'). Complete provider login before live Chat proofs."
                )
        receipt["remainingOperatorAuth"] = remaining
        receipt["status"] = (
            "install_attempted"
            if install["exitCode"] == 0
            else "install_failed_or_partial"
        )
        receipt["artifacts"] = {
            "receipt": str(receipt_path),
            "doctorJson": str(doctor_path),
            "backupRoot": backup_root,
            "runtimeRoot": runtime_root,
            "installExitCode": install["exitCode"],
        }
    finally:
        client.close()

    # Avoid dumping huge step stdout in console; keep compact summary + write full receipt.
    receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    summary = {
        "status": receipt["status"],
        "artifacts": receipt.get("artifacts"),
        "doctorManagedCliDetected": (receipt.get("doctor") or {}).get("managedCliDetected"),
        "doctorManagedCliAuthentication": (receipt.get("doctor") or {}).get("managedCliAuthentication"),
        "remainingOperatorAuth": receipt.get("remainingOperatorAuth"),
        "upload": next((s for s in receipt["steps"] if s.get("name") == "upload_phase_a_files"), None),
        "installExitCode": next(
            (s.get("exitCode") for s in receipt["steps"] if s.get("name") == "install_managed_clis"),
            None,
        ),
        "installStdoutTail": next(
            ((s.get("stdout") or "")[-1500:] for s in receipt["steps"] if s.get("name") == "install_managed_clis"),
            "",
        ),
        "installStderrTail": next(
            ((s.get("stderr") or "")[-800:] for s in receipt["steps"] if s.get("name") == "install_managed_clis"),
            "",
        ),
    }
    print(json.dumps(summary, indent=2))
    return 0 if receipt["status"] == "install_attempted" else 1


if __name__ == "__main__":
    raise SystemExit(main())
