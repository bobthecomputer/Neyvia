"""Run the checked-in runtime doctor on the NAS and preserve its JSON proof."""

from __future__ import annotations

import argparse
import json
import shlex
import uuid
from pathlib import Path

import paramiko


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CREDENTIALS = ROOT / ".agent_control" / "nas_codex2_100_125_54_118.json"
DEFAULT_OUTPUT = ROOT / ".agent_control" / "runtime_proof" / "runtime-stack-nas-doctor-final.json"
DOCTOR = ROOT / "scripts" / "nas_runtime_doctor.py"
CORE_RUNTIME_ROOT = "/volume1/Saclay/projects/syntelos/runtime"
PROXY_RUNTIME_ROOT = "/volume1/Saclay/runtime"


def _credentials(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        "host": payload.get("host", "192.0.2.10"),
        "port": int(payload.get("port", 22)),
        "username": payload.get("username", "nas-user"),
        "password": payload.get("password") or payload.get("secret"),
    }


def _run(
    client: paramiko.SSHClient,
    command: str,
    timeout: int = 120,
    *,
    allow_nonzero: bool = False,
) -> str:
    _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    output = stdout.read().decode("utf-8", "replace")
    error = stderr.read().decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    if code and not allow_nonzero:
        raise RuntimeError(f"NAS doctor failed ({code}): {error[-1600:] or output[-1600:]}")
    return output


def _upload(client: paramiko.SSHClient, remote_path: str, data: bytes) -> None:
    stdin, stdout, stderr = client.exec_command(
        f"umask 077; cat > {shlex.quote(remote_path)}",
        timeout=120,
    )
    stdin.write(data)
    stdin.flush()
    stdin.channel.shutdown_write()
    error = stderr.read().decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    if code:
        raise RuntimeError(f"doctor upload failed ({code}): {error[-1600:]}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the current Neyvia runtime doctor on the configured NAS.",
    )
    parser.add_argument("--credentials", default=str(DEFAULT_CREDENTIALS))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    credential_path = Path(args.credentials).resolve(strict=True)
    output_path = Path(args.output).resolve()
    credentials = _credentials(credential_path)
    remote_path = f"/tmp/neyvia-runtime-doctor-{uuid.uuid4().hex}.py"

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=str(credentials["host"]),
        port=int(credentials["port"]),
        username=str(credentials["username"]),
        password=str(credentials["password"]),
        look_for_keys=False,
        allow_agent=False,
        timeout=20,
    )
    try:
        _upload(client, remote_path, DOCTOR.read_bytes())
        environment = {
            "SYNTELOS_RUNTIME_ROOT": CORE_RUNTIME_ROOT,
            "FLUXIO_RUNTIME_ROOT": CORE_RUNTIME_ROOT,
            "SYNTELOS_PROXY_RUNTIME_ROOT": PROXY_RUNTIME_ROOT,
            "FLUXIO_PROXY_RUNTIME_ROOT": PROXY_RUNTIME_ROOT,
        }
        exports = " ".join(
            f"{key}={shlex.quote(value)}" for key, value in environment.items()
        )
        command = (
            f"{exports} python3 {shlex.quote(remote_path)} "
            f"--extra-bin-dir {shlex.quote(CORE_RUNTIME_ROOT + '/bin')} "
            f"--extra-bin-dir {shlex.quote(PROXY_RUNTIME_ROOT + '/bin')} --json"
        )
        payload = json.loads(
            _run(client, command, timeout=180, allow_nonzero=True)
        )
    finally:
        try:
            _run(client, f"rm -f {shlex.quote(remote_path)}")
        finally:
            client.close()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "ok": bool(payload.get("ready")),
                "output": str(output_path),
                "runtimeRoots": [CORE_RUNTIME_ROOT, PROXY_RUNTIME_ROOT],
            },
            ensure_ascii=False,
        )
    )
    return 0 if payload.get("ready") else 1


if __name__ == "__main__":
    raise SystemExit(main())
