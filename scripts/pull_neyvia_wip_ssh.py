"""Pull a hash-verified N-E-Y-V-I-A WIP snapshot from NAS over SSH/SFTP."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REMOTE = (
    "/volume1/Saclay/projects/syntelos/work-in-progress/"
    "20260724-091531-neyvia-full-workspace-roadmap"
)
EXPECTED_TREE = "1b3113812908c1d53cc9e5e2594f75a520fbc009509634c16ddbcce2c05c3dae"
EXPECTED_FILES = 1820
EXPECTED_BYTES = 256_464_684


def log(message: str) -> None:
    print(message, flush=True)


def _casefold_key(path: str) -> tuple[str, str]:
    return (path.casefold(), path)


def _tree_sha256(rows: list[dict[str, object]]) -> str:
    digest = hashlib.sha256()
    for row in sorted(rows, key=lambda item: _casefold_key(str(item["path"]))):
        digest.update(str(row["path"]).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(row["sha256"]).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _connect() -> paramiko.SSHClient:
    credentials = json.loads(
        (
            ROOT / ".agent_control" / "nas_codex2_100_125_54_118.json"
        ).read_text(encoding="utf-8")
    )
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    host = credentials.get("host", "192.0.2.10")
    log(f"connecting to {host}…")
    client.connect(
        hostname=host,
        port=int(credentials.get("port", 22)),
        username=credentials.get("username") or credentials.get("user") or "nas-user",
        password=credentials.get("password") or credentials.get("secret"),
        look_for_keys=False,
        allow_agent=False,
        timeout=30,
        banner_timeout=30,
        auth_timeout=30,
    )
    log("connected")
    return client


def _run(client: paramiko.SSHClient, command: str, timeout: int = 120) -> str:
    _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    output = stdout.read().decode("utf-8", "replace")
    error = stderr.read().decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    if code:
        raise RuntimeError(
            f"remote command failed ({code}): {error[-1200:] or output[-1200:]}"
        )
    return output.strip()


def inspect_remote(client: paramiko.SSHClient, remote: str) -> dict[str, object]:
    text = _run(client, f"cat {json.dumps(remote + '/.neyvia-wip-complete.json')}")
    marker = json.loads(text)
    manifest = marker.get("manifest") or {}
    summary = {
        "status": marker.get("status"),
        "files": manifest.get("files"),
        "bytes": manifest.get("bytes"),
        "treeSha256": manifest.get("treeSha256"),
        "remotePath": marker.get("remotePath") or remote,
        "completedAt": marker.get("completedAt"),
    }
    log(json.dumps({"inspect": summary}, indent=2))
    return summary


def download_tar(client: paramiko.SSHClient, remote: str, tar_path: Path) -> None:
    # Stream directly over SSH exec. Synology SFTP often cannot see /tmp archives.
    command = (
        f"tar -C {json.dumps(remote)} "
        f"--exclude='./.neyvia-wip-complete.json' "
        f"-czf - ."
    )
    log("streaming remote tar.gz over SSH…")
    _stdin, stdout, stderr = client.exec_command(command, timeout=900, bufsize=0)
    channel = stdout.channel
    channel.settimeout(900)
    started = time.time()
    done = 0
    with tar_path.open("wb") as handle:
        while True:
            chunk = stdout.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)
            done += len(chunk)
            elapsed = max(time.time() - started, 0.001)
            mbps = (done / (1024 * 1024)) / elapsed
            if done == chunk or done % (8 * 1024 * 1024) < len(chunk):
                log(f"  download {done} bytes ~{mbps:.2f} MiB/s")
    err = stderr.read().decode("utf-8", "replace")
    code = channel.recv_exit_status()
    if code:
        raise RuntimeError(f"remote tar stream failed ({code}): {err[-1200:]}")
    log(f"download complete: {done} bytes")

def extract_and_hash(tar_path: Path, destination: Path) -> list[dict[str, object]]:
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise RuntimeError(f"destination is not empty: {destination}")

    rows: list[dict[str, object]] = []
    log(f"extracting into {destination}…")
    with tarfile.open(tar_path, mode="r:gz") as tar:
        members = [m for m in tar.getmembers() if m.isfile()]
        for index, member in enumerate(members, start=1):
            name = member.name
            if name.startswith("./"):
                name = name[2:]
            name = name.replace("\\", "/")
            if name == ".neyvia-wip-complete.json" or not name:
                continue
            extracted = tar.extractfile(member)
            if extracted is None:
                raise RuntimeError(f"cannot extract {name}")
            data = extracted.read()
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            rows.append(
                {
                    "path": Path(name).as_posix(),
                    "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
            if index == len(members) or index % 100 == 0:
                log(f"  extracted {index}/{len(members)} files")
    return rows


def copy_into_workspace(staging: Path, workspace: Path) -> dict[str, object]:
    copied = 0
    skipped: list[str] = []
    for path in staging.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(staging)
        if rel.parts and rel.parts[0] in {".git", ".venv", "node_modules"}:
            skipped.append(str(rel.as_posix()))
            continue
        if rel.name == ".neyvia-wip-complete.json":
            continue
        target = workspace / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        copied += 1
        if copied % 200 == 0:
            log(f"  workspace copy {copied} files…")
    return {"copied": copied, "skipped": skipped}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remote", default=DEFAULT_REMOTE)
    parser.add_argument(
        "--destination",
        default=str(
            ROOT
            / ".agent_control"
            / "nas_pulls"
            / "20260724-091531-neyvia-full-workspace-roadmap"
        ),
    )
    parser.add_argument("--inspect-only", action="store_true")
    parser.add_argument("--into-workspace", action="store_true")
    parser.add_argument(
        "--expected-tree",
        default=EXPECTED_TREE,
    )
    parser.add_argument("--expected-files", type=int, default=EXPECTED_FILES)
    parser.add_argument("--expected-bytes", type=int, default=EXPECTED_BYTES)
    args = parser.parse_args()

    destination = Path(args.destination)
    client = _connect()
    try:
        summary = inspect_remote(client, args.remote)
        if args.inspect_only:
            return 0

        if summary.get("treeSha256") != args.expected_tree:
            raise RuntimeError(
                f"remote tree mismatch: {summary.get('treeSha256')} != {args.expected_tree}"
            )

        with tempfile.TemporaryDirectory(prefix="neyvia-wip-pull-") as tmp:
            tar_path = Path(tmp) / "bundle.tar.gz"
            download_tar(client, args.remote, tar_path)
            rows = extract_and_hash(tar_path, destination)

        # Keep completion marker beside the pull for continuity.
        marker_text = _run(
            client,
            f"cat {json.dumps(args.remote + '/.neyvia-wip-complete.json')}",
        )
        (destination / ".neyvia-wip-complete.json").write_text(
            marker_text if marker_text.endswith("\n") else marker_text + "\n",
            encoding="utf-8",
        )

        tree = _tree_sha256(rows)
        total_bytes = sum(int(row["bytes"]) for row in rows)
        proof: dict[str, object] = {
            "schema": "neyvia.wip_pull_receipt.v1",
            "ok": True,
            "files": len(rows),
            "bytes": total_bytes,
            "treeSha256": tree,
            "expectedTreeSha256": args.expected_tree,
            "treeMatches": tree == args.expected_tree,
            "filesMatch": len(rows) == args.expected_files,
            "bytesMatch": total_bytes == args.expected_bytes,
            "destination": str(destination),
            "remotePath": args.remote,
            "remoteSummary": summary,
            "pulledAt": datetime.now(timezone.utc).isoformat(),
        }
        if not (proof["treeMatches"] and proof["filesMatch"] and proof["bytesMatch"]):
            proof["ok"] = False
            raise RuntimeError(json.dumps(proof, indent=2))

        if args.into_workspace:
            log("copying verified staging tree into workspace…")
            copy_stats = copy_into_workspace(destination, ROOT)
            proof["workspaceCopied"] = copy_stats["copied"]
            proof["workspaceSkipped"] = copy_stats["skipped"]
            proof["workspaceRoot"] = str(ROOT)

        receipt_dir = ROOT / ".agent_control" / "nas_transfers"
        receipt_dir.mkdir(parents=True, exist_ok=True)
        receipt_path = (
            receipt_dir
            / f"neyvia_wip_pull_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
        )
        receipt_path.write_text(
            json.dumps(proof, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        proof["receipt"] = str(receipt_path)
        log(json.dumps(proof, indent=2))
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        log(f"ERROR: {exc}")
        raise
