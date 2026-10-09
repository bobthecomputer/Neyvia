#!/usr/bin/env python3
"""Repair and verify the NAS OpenCode Go credential path without printing secrets.

The Neyvia web backend persists provider keys in the workspace-local,
gitignored provider_secrets.json file. Managed runtime adapters consume the
matching runtime-home .fluxio_provider_env file. This script reconciles the
OpenCode Go entry between those two stores, keeps a timestamped backup, and
can run bounded live CLI probes over SSH.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import time
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CREDENTIALS = ROOT / ".agent_control" / "nas_codex2_100_125_54_118.json"
DEFAULT_REPORT = (
    ROOT / ".agent_control" / "runtime_proof" / "nas-opencode-go-auth.json"
)
DEFAULT_WORKSPACE = "/volume1/Saclay/projects/vibe-coding-platform"
DEFAULT_RUNTIME_HOME = "/volume1/Saclay/projects/syntelos/runtime/home"
DEFAULT_RUNTIME_BIN = "/volume1/Saclay/projects/syntelos/runtime/bin"
DEFAULT_PROXY_BIN = "/volume1/Saclay/runtime/bin"
DEFAULT_WORKSPACE_MOUNT = Path("Y:/projects/vibe-coding-platform")
DEFAULT_RUNTIME_HOME_MOUNT = Path("Y:/projects/syntelos/runtime/home")
PROVIDER_ID = "opencode-go"
ENV_NAME = "OPENCODE_API_KEY"


def _credentials(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        "host": payload.get("host") or "192.0.2.10",
        "port": int(payload.get("port") or 22),
        "username": payload.get("username") or payload.get("user") or "nas-user",
        "password": payload.get("password") or payload.get("secret") or "",
    }


def _connect(credentials_path: Path) -> Any:
    import paramiko

    details = _credentials(credentials_path)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=str(details["host"]),
        port=int(details["port"]),
        username=str(details["username"]),
        password=str(details["password"]),
        look_for_keys=False,
        allow_agent=False,
        timeout=25,
    )
    return client


def _read_remote_text(sftp: Any, path: str) -> str:
    with sftp.open(path, "r") as handle:
        payload = handle.read()
    if isinstance(payload, bytes):
        return payload.decode("utf-8", "replace")
    return str(payload)


def _remote_exists(sftp: Any, path: str) -> bool:
    try:
        sftp.stat(path)
    except OSError:
        return False
    return True


def _shell_single_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def merge_provider_env(existing: str, secret: str) -> str:
    """Return the env file with exactly one current OpenCode Go export."""
    cleaned = secret.strip()
    if not cleaned:
        raise ValueError("The OpenCode Go credential is empty.")
    output: list[str] = []
    replaced = False
    for raw_line in existing.splitlines():
        stripped = raw_line.strip()
        assignment = stripped.removeprefix("export ").strip()
        if assignment.startswith(f"{ENV_NAME}="):
            if not replaced:
                output.append(f"export {ENV_NAME}={_shell_single_quote(cleaned)}")
                replaced = True
            continue
        output.append(raw_line)
    if not replaced:
        if output and output[-1].strip():
            output.append("")
        output.append(f"export {ENV_NAME}={_shell_single_quote(cleaned)}")
    result = "\n".join(output).rstrip() + "\n"
    check_provider_env_merge(existing, cleaned, result)
    return result


def check_provider_env_merge(existing: str, secret: str, result: str) -> None:
    """Manual contract: one safely quoted Go export, unrelated entries retained."""
    def assignment(line: str) -> bool:
        return line.strip().removeprefix("export ").strip().startswith(f"{ENV_NAME}=")
    entries = [line for line in result.splitlines() if assignment(line)]
    before = [line.rstrip() for line in existing.splitlines() if line.strip() and not assignment(line)]
    after = [line.rstrip() for line in result.splitlines() if line.strip() and not assignment(line)]
    if len(entries) != 1 or before != after or shlex.split(entries[0]) != ["export", f"{ENV_NAME}={secret.strip()}"]:
        raise ValueError("Contract d.runtime.go-env.merge: export binding or unrelated entries changed")


def _write_remote_private_atomic(
    sftp: Any,
    path: str,
    content: str,
) -> str | None:
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    target = PurePosixPath(path)
    backup = f"{path}.bak.{stamp}" if _remote_exists(sftp, path) else None
    temporary = f"{path}.tmp.{stamp}"
    if backup:
        with sftp.open(path, "rb") as source, sftp.open(backup, "wb") as sink:
            sink.write(source.read())
        sftp.chmod(backup, 0o600)
    with sftp.open(temporary, "wb") as handle:
        handle.write(content.encode("utf-8"))
    sftp.chmod(temporary, 0o600)
    try:
        sftp.posix_rename(temporary, str(target))
    except OSError:
        if _remote_exists(sftp, path):
            sftp.remove(path)
        sftp.rename(temporary, str(target))
    sftp.chmod(path, 0o600)
    return backup


def _write_local_private_atomic(path: Path, content: str) -> Path | None:
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    backup = path.with_name(f"{path.name}.bak.{stamp}") if path.exists() else None
    temporary = path.with_name(f"{path.name}.tmp.{stamp}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if backup:
        shutil.copy2(path, backup)
    temporary.write_text(content, encoding="utf-8")
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    temporary.replace(path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return backup


def _redact(value: str, secret: str) -> str:
    redacted = value.replace(secret, "[REDACTED]") if secret else value
    result = redacted[-8000:]
    if secret and secret in result:
        raise ValueError("Contract d.runtime.go-env.redact: secret leaked into bounded receipt")
    if len(result) > 8000:
        raise ValueError("Contract d.runtime.go-env.redact: receipt tail exceeded bound")
    return result


def _run_remote(
    client: Any,
    command: str,
    *,
    timeout: int,
    secret: str,
) -> dict[str, Any]:
    started = time.monotonic()
    _stdin, stdout, stderr = client.exec_command(command, timeout=timeout + 10)
    output = stdout.read().decode("utf-8", "replace")
    error = stderr.read().decode("utf-8", "replace")
    exit_code = stdout.channel.recv_exit_status()
    return {
        "exitCode": exit_code,
        "elapsedSeconds": round(time.monotonic() - started, 2),
        "stdoutTail": _redact(output, secret),
        "stderrTail": _redact(error, secret),
    }


def _probe_commands(
    client: Any,
    *,
    runtime_home: str,
    runtime_bin: str,
    proxy_bin: str,
    secret: str,
    live_smoke: bool,
) -> dict[str, Any]:
    prefix = (
        f"export HOME={shlex.quote(runtime_home)}; "
        f"export PATH={shlex.quote(runtime_bin)}:{shlex.quote(proxy_bin)}:/usr/local/bin:/usr/bin:/bin; "
        f"set -a; . {shlex.quote(runtime_home + '/.fluxio_provider_env')}; set +a; "
    )
    probes = {
        "hermesAuth": _run_remote(
            client,
            prefix + "timeout 30 hermes auth status opencode-go 2>&1",
            timeout=45,
            secret=secret,
        ),
        "modelCatalog": _run_remote(
            client,
            prefix + "timeout 60 opencode models opencode-go 2>&1",
            timeout=75,
            secret=secret,
        ),
    }
    catalog_text = (
        probes["modelCatalog"]["stdoutTail"]
        + "\n"
        + probes["modelCatalog"]["stderrTail"]
    ).lower()
    probes["modelCatalog"]["providerObserved"] = (
        probes["modelCatalog"]["exitCode"] == 0
        and "opencode-go/" in catalog_text
    )
    if live_smoke:
        probes["liveModel"] = _run_remote(
            client,
            prefix
            + "timeout 180 opencode run --format json "
            + "--model opencode-go/deepseek-v4-pro "
            + shlex.quote("Reply exactly NEYVIA_OPENCODE_GO_CONNECTED")
            + " < /dev/null 2>&1",
            timeout=195,
            secret=secret,
        )
        live_text = (
            probes["liveModel"]["stdoutTail"]
            + "\n"
            + probes["liveModel"]["stderrTail"]
        )
        probes["liveModel"]["markerObserved"] = (
            probes["liveModel"]["exitCode"] == 0
            and "NEYVIA_OPENCODE_GO_CONNECTED" in live_text
        )
    return probes


def repair_and_verify(
    *,
    credentials_path: Path,
    workspace: str,
    runtime_home: str,
    runtime_bin: str,
    proxy_bin: str,
    workspace_mount: Path | None,
    runtime_home_mount: Path | None,
    apply: bool,
    live_smoke: bool,
) -> dict[str, Any]:
    client = _connect(credentials_path)
    try:
        secrets_path = f"{workspace.rstrip('/')}/.agent_control/provider_secrets.json"
        env_path = f"{runtime_home.rstrip('/')}/.fluxio_provider_env"
        use_mount = bool(
            workspace_mount
            and runtime_home_mount
            and workspace_mount.exists()
            and runtime_home_mount.exists()
        )
        if use_mount:
            assert workspace_mount is not None
            assert runtime_home_mount is not None
            mounted_secrets = workspace_mount / ".agent_control" / "provider_secrets.json"
            mounted_env = runtime_home_mount / ".fluxio_provider_env"
            payload = json.loads(mounted_secrets.read_text(encoding="utf-8"))
            secret_payload = payload.get("secrets") if isinstance(payload.get("secrets"), dict) else payload
            secret = str(secret_payload.get(PROVIDER_ID) or "").strip()
            if not secret:
                raise RuntimeError(
                    "The NAS provider secret store has no OpenCode Go credential. "
                    "Save the existing key through Neyvia Settings before applying this repair."
                )
            existing = mounted_env.read_text(encoding="utf-8") if mounted_env.exists() else ""
            merged = merge_provider_env(existing, secret)
            changed = merged != existing
            backup = None
            if apply and changed:
                backup = _write_local_private_atomic(mounted_env, merged)
            transport = "nas-mapped-drive"
        else:
            sftp = client.open_sftp()
            try:
                payload = json.loads(_read_remote_text(sftp, secrets_path))
                secret_payload = payload.get("secrets") if isinstance(payload.get("secrets"), dict) else payload
                secret = str(secret_payload.get(PROVIDER_ID) or "").strip()
                if not secret:
                    raise RuntimeError(
                        "The NAS provider secret store has no OpenCode Go credential. "
                        "Save the existing key through Neyvia Settings before applying this repair."
                    )
                existing = _read_remote_text(sftp, env_path) if _remote_exists(sftp, env_path) else ""
                merged = merge_provider_env(existing, secret)
                changed = merged != existing
                backup = None
                if apply and changed:
                    backup = _write_remote_private_atomic(sftp, env_path, merged)
            finally:
                sftp.close()
            transport = "sftp"
        effective = merged if apply else existing
        env_ready = any(
            line.strip().removeprefix("export ").startswith(f"{ENV_NAME}=")
            for line in effective.splitlines()
        )
        probes = _probe_commands(
            client,
            runtime_home=runtime_home,
            runtime_bin=runtime_bin,
            proxy_bin=proxy_bin,
            secret=secret,
            live_smoke=live_smoke,
        )
    finally:
        client.close()
    catalog_ready = bool(probes["modelCatalog"].get("providerObserved"))
    live_ready = (
        bool(probes.get("liveModel", {}).get("markerObserved"))
        if live_smoke
        else None
    )
    return {
        "schema": "neyvia.nas-opencode-go-auth-repair/v1",
        "checkedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "provider": PROVIDER_ID,
        "credential": {
            "source": f"{workspace.rstrip('/')}/.agent_control/provider_secrets.json",
            "present": True,
            "valuePrinted": False,
        },
        "runtimeEnvironment": {
            "path": f"{runtime_home.rstrip('/')}/.fluxio_provider_env",
            "transport": transport,
            "changed": changed,
            "applied": bool(apply and changed),
            "ready": env_ready,
            "backupPath": str(backup) if backup else None,
            "mode": "0600" if apply and changed else "preserved",
        },
        "probes": probes,
        "ready": env_ready and catalog_ready and (live_ready is not False),
        "liveSmokeRequired": live_smoke,
        "liveSmokePassed": live_ready,
        "providerSubstitutionUsed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--credentials", type=Path, default=DEFAULT_CREDENTIALS)
    parser.add_argument("--workspace", default=DEFAULT_WORKSPACE)
    parser.add_argument("--runtime-home", default=DEFAULT_RUNTIME_HOME)
    parser.add_argument("--runtime-bin", default=DEFAULT_RUNTIME_BIN)
    parser.add_argument("--proxy-bin", default=DEFAULT_PROXY_BIN)
    parser.add_argument("--workspace-mount", type=Path, default=DEFAULT_WORKSPACE_MOUNT)
    parser.add_argument("--runtime-home-mount", type=Path, default=DEFAULT_RUNTIME_HOME_MOUNT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--live-smoke", action="store_true")
    args = parser.parse_args()
    report = repair_and_verify(
        credentials_path=args.credentials.resolve(strict=True),
        workspace=args.workspace,
        runtime_home=args.runtime_home,
        runtime_bin=args.runtime_bin,
        proxy_bin=args.proxy_bin,
        workspace_mount=args.workspace_mount,
        runtime_home_mount=args.runtime_home_mount,
        apply=args.apply,
        live_smoke=args.live_smoke,
    )
    target = args.report.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "ready": report["ready"],
                "provider": report["provider"],
                "environment": report["runtimeEnvironment"],
                "catalogReady": report["probes"]["modelCatalog"].get("providerObserved"),
                "liveSmokePassed": report["liveSmokePassed"],
                "report": str(target),
                "secretPrinted": False,
            },
            indent=2,
        )
    )
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
