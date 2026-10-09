from __future__ import annotations

import argparse
import getpass
import json
import os
import shlex
import socket
import subprocess
import sys
from pathlib import PurePosixPath
from typing import Any


def _json_result(**payload: Any) -> None:
    print(json.dumps(payload, indent=2))


def _socket_probe(host: str, port: int, timeout: float) -> dict[str, Any]:
    sock = socket.socket()
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
    except OSError as exc:
        return {
            "ok": False,
            "stage": "socket",
            "error": str(exc),
            "errorType": type(exc).__name__,
        }
    finally:
        sock.close()
    return {"ok": True, "stage": "socket"}


def _load_password(env_name: str, prompt: bool) -> str:
    password = os.environ.get(env_name, "")
    if password:
        return password
    if prompt and sys.stdin.isatty():
        return getpass.getpass("NAS SSH password: ")
    return ""


def _run_command(command: list[str], timeout: float) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except Exception as exc:
        return 1, "", str(exc)
    return completed.returncode, completed.stdout.strip(), completed.stderr.strip()


def _diagnose_windows_route(host: str, port: int, timeout: float) -> dict[str, Any]:
    if os.name != "nt":
        return {}
    firewall_script = (
        "$ErrorActionPreference='SilentlyContinue'; "
        "$rules = Get-NetFirewallRule -Enabled True -Direction Outbound -Action Block "
        "| Where-Object { $_.DisplayName -eq 'codex_sandbox_offline_block_outbound' -or $_.Description -like '*Codex Sandbox Offline*' }; "
        "if ($null -eq $rules) { '[]' } else { "
        "$rules | Select-Object DisplayName,Description,Profile,Action | ConvertTo-Json -Compress "
        "}"
    )
    route_script = (
        "Get-NetRoute -AddressFamily IPv4 "
        f"| Where-Object {{ '{host}' -like ($_.DestinationPrefix -replace '/32','') -or $_.InterfaceAlias -eq 'Tailscale' }} "
        "| Sort-Object RouteMetric,DestinationPrefix "
        "| Select-Object -First 6 DestinationPrefix,NextHop,InterfaceAlias,RouteMetric "
        "| ConvertTo-Json -Compress"
    )
    firewall_code, firewall_out, firewall_err = _run_command(
        ["powershell", "-NoProfile", "-Command", firewall_script],
        timeout,
    )
    route_code = 0
    route_out = ""
    route_err = ""
    blockers: list[dict[str, str]] = []
    tailscale_status: dict[str, Any] = {}
    if firewall_out:
        try:
            decoded = json.loads(firewall_out)
            rows = decoded if isinstance(decoded, list) else [decoded]
            for row in rows:
                name = str(row.get("DisplayName") or "")
                description = str(row.get("Description") or "")
                if "codex_sandbox_offline_block_outbound" in name or "Codex Sandbox Offline" in description:
                    blockers.append(
                        {
                            "kind": "windows_firewall",
                            "name": name,
                            "description": description,
                            "fix": "Run scripts/unblock_codex_network.ps1 from an elevated PowerShell prompt or approve the app's unlock action.",
                        }
                    )
        except json.JSONDecodeError:
            pass
    if not blockers:
        route_code, route_out, route_err = _run_command(
            ["powershell", "-NoProfile", "-Command", route_script],
            timeout,
        )
        tailscale_code, tailscale_out, tailscale_err = _run_command(
            ["tailscale", "status", "--json"],
            timeout,
        )
        tailscale_status = {
            "exitCode": tailscale_code,
            "stderr": tailscale_err,
        }
        if tailscale_out:
            try:
                decoded_status = json.loads(tailscale_out)
                self_status = decoded_status.get("Self") or {}
                tailscale_status.update(
                    {
                        "backendState": decoded_status.get("BackendState"),
                        "selfOnline": self_status.get("Online"),
                        "tailscaleIPs": self_status.get("TailscaleIPs") or [],
                    }
                )
                if decoded_status.get("BackendState") == "NoState":
                    blockers.append(
                        {
                            "kind": "tailscale",
                            "name": "Tailscale backend is NoState",
                            "description": "Tailscale has network access, but this machine is not currently attached to the tailnet route.",
                            "fix": "Open the Tailscale desktop app once and reconnect or sign in. Re-run this probe after a 100.x route appears.",
                        }
                    )
            except json.JSONDecodeError:
                tailscale_status["raw"] = tailscale_out
    route = {}
    if route_out:
        try:
            route = json.loads(route_out)
        except json.JSONDecodeError:
            route = {"raw": route_out}
    return {
        "windowsRoute": route,
        "blockers": blockers,
        "firewallProbe": {
            "exitCode": firewall_code,
            "stderr": firewall_err,
        },
        "tcpProbe": {
            "exitCode": route_code,
            "stderr": route_err,
        },
        "tailscaleStatus": tailscale_status,
    }


def _remote_root_exists(sftp: Any, remote_root: str) -> bool:
    if not remote_root:
        return False
    try:
        return bool(sftp.stat(str(PurePosixPath(remote_root))))
    except OSError:
        return False


def _remote_root_exists_ssh(client: Any, remote_root: str, timeout: float) -> bool:
    if not remote_root:
        return False
    remote_path = str(PurePosixPath(remote_root))
    command = f"test -e {shlex.quote(remote_path)}"
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    try:
        return stdout.channel.recv_exit_status() == 0
    finally:
        stdin.close()
        stdout.close()
        stderr.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe a NAS SSH/SFTP route without logging secrets.")
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=24)
    parser.add_argument("--user", required=True)
    parser.add_argument("--remote-root", default="")
    parser.add_argument("--password-env", default="FLUXIO_NAS_SSH_PASSWORD")
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--prompt", action="store_true")
    parser.add_argument("--diagnose", action="store_true")
    args = parser.parse_args()

    socket_result = _socket_probe(args.host, args.port, args.timeout)
    if not socket_result.get("ok"):
        _json_result(
            ok=False,
            stage="socket",
            host=args.host,
            port=args.port,
            user=args.user,
            remoteRoot=args.remote_root,
            error=socket_result.get("error", ""),
            errorType=socket_result.get("errorType", "OSError"),
            diagnostics=_diagnose_windows_route(args.host, args.port, args.timeout)
            if args.diagnose
            else {},
        )
        return 2

    password = _load_password(args.password_env, args.prompt)
    if not password:
        _json_result(
            ok=False,
            stage="credentials",
            host=args.host,
            port=args.port,
            user=args.user,
            remoteRoot=args.remote_root,
            error=f"Set {args.password_env} or run with --prompt to verify password login.",
            errorType="MissingCredential",
        )
        return 3

    try:
        import paramiko
    except ImportError:
        _json_result(
            ok=False,
            stage="dependency",
            host=args.host,
            port=args.port,
            user=args.user,
            remoteRoot=args.remote_root,
            error="Install paramiko to verify password-based SSH from Python.",
            errorType="MissingDependency",
        )
        return 4

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname=args.host,
            port=args.port,
            username=args.user,
            password=password,
            timeout=args.timeout,
            auth_timeout=args.timeout,
            banner_timeout=args.timeout,
            look_for_keys=False,
            allow_agent=False,
        )
        sftp_available = True
        sftp_error = ""
        try:
            sftp = client.open_sftp()
            root_exists = _remote_root_exists(sftp, args.remote_root)
            sftp.close()
        except Exception as exc:
            sftp_available = False
            sftp_error = str(exc)
            root_exists = _remote_root_exists_ssh(client, args.remote_root, args.timeout)
    except Exception as exc:  # pragma: no cover - depends on live NAS/network.
        _json_result(
            ok=False,
            stage="auth",
            host=args.host,
            port=args.port,
            user=args.user,
            remoteRoot=args.remote_root,
            error=str(exc),
            errorType=type(exc).__name__,
        )
        return 5
    finally:
        client.close()

    _json_result(
        ok=True,
        stage="ready",
        host=args.host,
        port=args.port,
        user=args.user,
        remoteRoot=args.remote_root,
        remoteRootExists=root_exists,
        sftpAvailable=sftp_available,
        sftpError=sftp_error,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
