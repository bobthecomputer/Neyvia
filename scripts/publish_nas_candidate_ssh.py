#!/usr/bin/env python3
"""Invoke the transactional Neyvia candidate publisher over private NAS SSH."""

from __future__ import annotations

import argparse
import json
import shlex
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CREDENTIALS = ROOT / ".agent_control" / "nas_codex2_100_125_54_118.json"
BASE = "/volume1/Saclay/projects/syntelos"
RELEASES = f"{BASE}/releases"
CONTROL_ROOT = "/volume1/Saclay/projects/vibe-coding-platform"
MANAGED_PYTHON = f"{BASE}/.venv/bin/python"


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


def publish(candidate_name: str, manifest_sha256: str, credentials_path: Path, *, control_root: str = CONTROL_ROOT) -> dict:
    name = PurePosixPath(candidate_name).name
    if name != candidate_name or not name.startswith("neyvia-candidate-"):
        raise RuntimeError("Candidate must be one direct neyvia-candidate-* release name.")
    digest = manifest_sha256.strip().lower()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise RuntimeError("Manifest SHA-256 must be one complete lowercase digest.")
    candidate = f"{RELEASES}/{name}"
    publisher = f"{candidate}/scripts/publish_nas_candidate.py"
    command = shlex.join(
        [
            MANAGED_PYTHON,
            publisher,
            candidate,
            "--base",
            BASE,
            "--control-root",
            control_root,
            "--expected-manifest-sha256",
            digest,
        ]
    )
    client = _connect(credentials_path)
    try:
        _stdin, stdout, stderr = client.exec_command(command, timeout=7200)
        output = stdout.read().decode("utf-8", "replace")
        error = stderr.read().decode("utf-8", "replace")
        exit_code = stdout.channel.recv_exit_status()
    finally:
        client.close()
    if exit_code:
        raise RuntimeError(error[-4000:] or output[-4000:] or f"Publisher exited {exit_code}.")
    lines = [line for line in output.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("Publisher returned no receipt.")
    receipt = json.loads(lines[-1])
    if receipt.get("status") != "published":
        raise RuntimeError(f"Publisher did not return a published receipt: {receipt.get('status')}")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidate")
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--credentials", type=Path, default=DEFAULT_CREDENTIALS)
    parser.add_argument("--control-root", default=CONTROL_ROOT,
                        help="Existing persistent data root verified from the managed backend process")
    args = parser.parse_args()
    receipt = publish(
        args.candidate,
        args.expected_manifest_sha256,
        args.credentials.resolve(strict=True),
        control_root=args.control_root,
    )
    print(
        json.dumps(
            {
                "status": receipt.get("status"),
                "candidate": receipt.get("candidate"),
                "activeRelease": receipt.get("activeRelease"),
                "previousRelease": receipt.get("previousRelease"),
                "managedBackend": receipt.get("managedBackend"),
                "receiptPath": receipt.get("receiptPath"),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
