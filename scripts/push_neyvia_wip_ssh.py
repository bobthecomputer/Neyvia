"""Upload a hash-verified N-E-Y-V-I-A work-in-progress bundle without publishing."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import tarfile
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import paramiko


def _workspace_root() -> Path:
    operator_root = Path.cwd()
    if (
        (operator_root / "pyproject.toml").is_file()
        and (operator_root / "scripts").is_dir()
    ):
        return operator_root
    return Path(__file__).resolve().parents[1]


ROOT = _workspace_root()
REMOTE_WIP_ROOT = "/volume1/Saclay/projects/syntelos/work-in-progress"
NAME_PATTERN = re.compile(r"^[0-9]{8}-[0-9]{6}-[a-z0-9][a-z0-9-]{2,96}$")


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


def _upload(
    client: paramiko.SSHClient,
    remote_path: str,
    data: bytes,
    timeout: int = 300,
) -> None:
    stdin, stdout, stderr = client.exec_command(
        f"umask 077; cat > {shlex.quote(remote_path)}",
        timeout=timeout,
    )
    stdin.write(data)
    stdin.flush()
    stdin.channel.shutdown_write()
    error = stderr.read().decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    if code:
        raise RuntimeError(f"remote upload failed ({code}): {error[-1200:]}")


def _manifest(bundle: Path) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    paths = sorted(
        bundle.rglob("*"),
        key=lambda path: (
            path.relative_to(bundle).as_posix().casefold(),
            path.relative_to(bundle).as_posix(),
        ),
    )
    for path in paths:
        if path.is_symlink():
            raise RuntimeError(f"WIP bundle cannot contain symlinks: {path}")
        if not path.is_file():
            continue
        data = path.read_bytes()
        rows.append(
            {
                "path": path.relative_to(bundle).as_posix(),
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    digest = hashlib.sha256()
    for row in rows:
        digest.update(str(row["path"]).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(row["sha256"]).encode("ascii"))
        digest.update(b"\n")
    return {
        "schema": "neyvia.wip_manifest.v1",
        "files": len(rows),
        "bytes": sum(int(row["bytes"]) for row in rows),
        "treeSha256": digest.hexdigest(),
        "sha256Manifest": rows,
    }


VERIFY_SCRIPT = r"""import hashlib,json,sys
from pathlib import Path
root=Path(sys.argv[1]).resolve(strict=True)
manifest=json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
expected={row["path"]:row for row in manifest["sha256Manifest"]}
actual={}
for path in root.rglob("*"):
    if path.is_symlink(): raise SystemExit("symlink:"+str(path))
    if not path.is_file() or path.name==".neyvia-wip-complete.json": continue
    rel=path.relative_to(root).as_posix()
    data=path.read_bytes()
    actual[rel]={"path":rel,"bytes":len(data),"sha256":hashlib.sha256(data).hexdigest()}
if actual!=expected:
    print(json.dumps({"ok":False,"missing":sorted(set(expected)-set(actual)),"extra":sorted(set(actual)-set(expected)),"changed":sorted(k for k in set(actual)&set(expected) if actual[k]!=expected[k])}))
    raise SystemExit(4)
digest=hashlib.sha256()
for row in sorted(actual.values(),key=lambda item:(item["path"].casefold(),item["path"])):
    digest.update(row["path"].encode());digest.update(b"\0");digest.update(row["sha256"].encode());digest.update(b"\n")
proof={"ok":True,"files":len(actual),"bytes":sum(row["bytes"] for row in actual.values()),"treeSha256":digest.hexdigest()}
if proof["treeSha256"]!=manifest["treeSha256"]: raise SystemExit("tree digest mismatch")
print(json.dumps(proof))
"""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Upload a verified WIP bundle; never seal or publish current."
    )
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--credential-file", default=str(ROOT / ".agent_control" / "nas_codex2_100_125_54_118.json"))
    args = parser.parse_args()
    bundle = Path(args.bundle).resolve(strict=True)
    if not bundle.is_dir():
        raise RuntimeError("--bundle must be a directory")
    name = str(args.name).strip().lower()
    if not NAME_PATTERN.fullmatch(name):
        raise RuntimeError(
            "--name must be a timestamped lowercase slug such as "
            "20260723-154105-neyvia-capability-backend"
        )
    manifest = _manifest(bundle)
    if not manifest["files"]:
        raise RuntimeError("WIP bundle is empty")
    manifest_bytes = json.dumps(
        manifest,
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8")
    archive_directory = tempfile.TemporaryDirectory(prefix="neyvia-wip-")
    archive_path = Path(archive_directory.name) / "workspace.tar.gz"
    with tarfile.open(archive_path, mode="w:gz") as tar:
        for path in sorted(
            bundle.rglob("*"),
            key=lambda item: (
                item.relative_to(bundle).as_posix().casefold(),
                item.relative_to(bundle).as_posix(),
            ),
        ):
            if path.is_file() and not path.is_symlink():
                tar.add(
                    path,
                    arcname=path.relative_to(bundle).as_posix(),
                    recursive=False,
                )

    credentials = json.loads(Path(args.credential_file).read_text(encoding="utf-8"))
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=credentials.get("host", "192.0.2.10"),
        port=int(credentials.get("port", 22)),
        username=credentials.get("username", "nas-user"),
        password=credentials.get("password") or credentials.get("secret"),
        look_for_keys=False,
        allow_agent=False,
        timeout=20,
    )
    transfer_id = (
        "neyvia_wip_"
        + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        + "_"
        + uuid.uuid4().hex[:8]
    )
    final = f"{REMOTE_WIP_ROOT}/{name}"
    stage = f"{REMOTE_WIP_ROOT}/.incomplete-{name}-{uuid.uuid4().hex[:8]}"
    remote_manifest = f"/tmp/{transfer_id}.manifest.json"
    remote_verifier = f"/tmp/{transfer_id}.verify.py"
    try:
        current_before = _run(
            client,
            "readlink -f /volume1/Saclay/projects/syntelos/current",
        )
        _run(
            client,
            (
                f"test ! -e {shlex.quote(final)}; "
                f"mkdir -p {shlex.quote(REMOTE_WIP_ROOT)}; "
                f"mkdir {shlex.quote(stage)}"
            ),
        )
        stdin, stdout, stderr = client.exec_command(
            f"tar -xzf - -C {shlex.quote(stage)}",
            timeout=300,
        )
        with archive_path.open("rb") as archive:
            while chunk := archive.read(1024 * 1024):
                stdin.write(chunk)
        stdin.flush()
        stdin.channel.shutdown_write()
        error = stderr.read().decode("utf-8", "replace")
        if stdout.channel.recv_exit_status():
            raise RuntimeError(f"remote WIP extraction failed: {error[-1200:]}")
        _upload(client, remote_manifest, manifest_bytes)
        _upload(client, remote_verifier, VERIFY_SCRIPT.encode("utf-8"))
        staged_proof = json.loads(
            _run(
                client,
                (
                    f"python3 {shlex.quote(remote_verifier)} "
                    f"{shlex.quote(stage)} {shlex.quote(remote_manifest)}"
                ),
                timeout=300,
            )
        )
        completion = {
            "schema": "neyvia.wip_completion.v1",
            "status": "complete",
            "transferId": transfer_id,
            "remotePath": final,
            "manifest": manifest,
            "publicLiveChanged": False,
            "currentBefore": current_before,
            "completedAt": datetime.now(timezone.utc).isoformat(),
        }
        _upload(
            client,
            f"{stage}/.neyvia-wip-complete.json",
            json.dumps(completion, ensure_ascii=False, indent=2).encode("utf-8"),
        )
        _run(client, f"mv {shlex.quote(stage)} {shlex.quote(final)}")
        final_proof = json.loads(
            _run(
                client,
                (
                    f"python3 {shlex.quote(remote_verifier)} "
                    f"{shlex.quote(final)} {shlex.quote(remote_manifest)}"
                ),
                timeout=300,
            )
        )
        current_after = _run(
            client,
            "readlink -f /volume1/Saclay/projects/syntelos/current",
        )
        if current_after != current_before:
            raise RuntimeError("public current changed during WIP upload")
        receipt = {
            "schema": "neyvia.wip_transfer_receipt.v1",
            "status": "completed",
            "transferId": transfer_id,
            "remotePath": final,
            "verification": final_proof,
            "stagedVerification": staged_proof,
            "currentBefore": current_before,
            "currentAfter": current_after,
            "publicLiveChanged": False,
        }
        receipt_path = (
            ROOT
            / ".agent_control"
            / "nas_transfers"
            / f"{transfer_id}.json"
        )
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "ok": True,
                    "remotePath": final,
                    "files": final_proof["files"],
                    "bytes": final_proof["bytes"],
                    "treeSha256": final_proof["treeSha256"],
                    "currentUnchanged": True,
                    "receipt": str(receipt_path),
                },
                ensure_ascii=False,
            )
        )
    finally:
        try:
            _run(
                client,
                (
                    f"rm -f {shlex.quote(remote_manifest)} "
                    f"{shlex.quote(remote_verifier)}"
                ),
            )
        except Exception:
            pass
        client.close()
        archive_directory.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
