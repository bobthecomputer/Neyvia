"""Read the local tailnet roster without treating network presence as control."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
from pathlib import Path
from typing import Any

from .subprocess_utils import hidden_windows_subprocess_kwargs


def _tailscale_executable() -> str | None:
    found = shutil.which("tailscale")
    if found:
        return found
    if os.name == "nt":
        candidate = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Tailscale" / "tailscale.exe"
        if candidate.is_file():
            return str(candidate)
    return None


def _tailscale_json(executable: str, *arguments: str) -> dict[str, Any]:
    completed = subprocess.run(
        [executable, *arguments, "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=4,
        check=False,
        **hidden_windows_subprocess_kwargs(),
    )
    if completed.returncode:
        raise RuntimeError(f"Tailscale {arguments[0]} is unavailable")
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise ValueError("Tailscale returned an invalid device snapshot")
    return value


def _device_name(raw: dict[str, Any]) -> str:
    hostname = str(raw.get("HostName") or "").strip()
    dns_name = str(raw.get("DNSName") or "").strip().rstrip(".").split(".")[0]
    if hostname.lower() in {"", "localhost"} and dns_name:
        return dns_name
    return hostname or dns_name or "Unnamed device"


def _device(raw: dict[str, Any], *, local: bool = False) -> dict[str, Any]:
    name = _device_name(raw)
    os_name = str(raw.get("OS") or "").strip()
    lower_name = name.lower()
    kind = (
        "phone" if os_name.lower() in {"ios", "android"}
        else "nas" if os_name.lower() == "linux" and any(
            hint in lower_name for hint in ("nas", "synology", "nas.example.invalid", "diskstation")
        )
        else "computer" if os_name.lower() in {"windows", "macos", "linux"}
        else "device"
    )
    return {
        "id": str(raw.get("ID") or name),
        "name": name,
        "kind": kind,
        "os": os_name,
        "local": local,
        "online": bool(raw.get("Online")) and not bool(raw.get("Expired")),
        "expired": bool(raw.get("Expired")),
        "lastSeen": str(raw.get("LastSeen") or ""),
        "controlStatus": "unverified",
    }


def connected_device_snapshot(*, backend_port: int | None = None, remote_port: int = 8443) -> dict[str, Any]:
    """Return observed names and the phone URL only when Serve targets this backend."""
    hostname = socket.gethostname()
    fallback = {
        "source": "local-host",
        "host": {"id": hostname, "name": hostname, "kind": "computer", "os": os.name,
                 "local": True, "online": True, "controlStatus": "unverified"},
        "devices": [],
        "phoneUrl": "",
        "remoteStatus": "unavailable",
        "detail": "Tailscale device discovery is unavailable.",
    }
    executable = _tailscale_executable()
    if not executable:
        return fallback
    try:
        status = _tailscale_json(executable, "status")
        self_node = status.get("Self") or {}
        if not isinstance(self_node, dict) or not self_node:
            return fallback
        host = _device(self_node, local=True)
        peers = status.get("Peer") or {}
        devices = [_device(peer) for peer in peers.values() if isinstance(peer, dict)] if isinstance(peers, dict) else []
        devices.sort(key=lambda device: (not device["online"], device["kind"], device["name"].casefold()))
        result = {
            "source": "tailscale",
            "host": host,
            "devices": devices,
            "phoneUrl": "",
            "remoteStatus": "unavailable",
            "detail": "Tailnet presence does not prove Neyvia control or screen access.",
        }
        try:
            serve = _tailscale_json(executable, "serve", "status")
            dns = str(self_node.get("DNSName") or "").strip().rstrip(".")
            route = ((serve.get("Web") or {}).get(f"{dns}:{remote_port}") or {}).get("Handlers") or {}
            proxy = str((route.get("/") or {}).get("Proxy") or "").rstrip("/")
            backend_ports = {backend_port} if backend_port is not None else {47880, 47881}
            expected_proxies = {f"http://{host}:{port}" for host in ("127.0.0.1", "localhost") for port in backend_ports}
            if proxy in expected_proxies and dns:
                result["phoneUrl"] = f"https://{dns}:{remote_port}/control?surface=agent&controller=desktop"
                result["remoteStatus"] = "configured"
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError):
            pass
        return result
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return fallback
