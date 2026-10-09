from __future__ import annotations

import argparse
import hashlib
import io
import json
import shlex
import tarfile
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
REMOTE_PROJECTS = "/volume1/Saclay/projects"
REMOTE_RELEASES = f"{REMOTE_PROJECTS}/syntelos/releases"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _verify_local_candidate(candidate: Path, manifest: dict[str, object]) -> dict[str, object]:
    expected = {
        str(row["path"]): row
        for row in manifest.get("sha256Manifest") or []
        if isinstance(row, dict) and row.get("path")
    }
    actual: dict[str, dict[str, object]] = {}
    for path in candidate.rglob("*"):
        if path.is_symlink():
            raise RuntimeError(f"candidate contains a symlink: {path}")
        if not path.is_file() or path.name == ".neyvia-candidate-complete.json":
            continue
        relative = path.relative_to(candidate).as_posix()
        data = path.read_bytes()
        actual[relative] = {
            "path": relative,
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
    if actual != expected:
        raise RuntimeError(
            "local candidate changed after sealing: "
            f"missing={len(set(expected) - set(actual))}, "
            f"extra={len(set(actual) - set(expected))}, "
            f"changed={len([key for key in set(actual) & set(expected) if actual[key] != expected[key]])}"
        )
    digest = hashlib.sha256()
    rows = sorted(
        actual.values(),
        key=lambda row: (str(row["path"]).casefold(), str(row["path"])),
    )
    for row in rows:
        digest.update(str(row["path"]).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(row["sha256"]).encode("ascii"))
        digest.update(b"\n")
    tree_hash = digest.hexdigest()
    if tree_hash != manifest.get("manifestSha256"):
        raise RuntimeError("local candidate tree digest does not match its manifest")
    return {
        "files": len(rows),
        "bytes": sum(int(row["bytes"]) for row in rows),
        "manifestSha256": tree_hash,
    }


def _run(client: paramiko.SSHClient, command: str, timeout: int = 120) -> str:
    _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    output = stdout.read().decode("utf-8", "replace")
    error = stderr.read().decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    if code:
        raise RuntimeError(f"remote command failed ({code}): {error[-1200:] or output[-1200:]}")
    return output.strip()


def _upload(client: paramiko.SSHClient, remote_path: str, data: bytes, timeout: int = 180) -> None:
    stdin, stdout, stderr = client.exec_command(f"umask 077; cat > {shlex.quote(remote_path)}", timeout=timeout)
    stdin.write(data)
    stdin.flush()
    stdin.channel.shutdown_write()
    error = stderr.read().decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    if code:
        raise RuntimeError(f"remote upload failed ({code}): {error[-1200:]}")


VERIFY_SCRIPT = r'''import hashlib,json,sys
from pathlib import Path
root=Path(sys.argv[1]).resolve(strict=True)
manifest=json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
expected={row["path"]:row for row in manifest["sha256Manifest"]}
actual={}
for path in root.rglob("*"):
    if path.is_symlink(): raise SystemExit("symlink:"+str(path))
    if not path.is_file() or path.name==".neyvia-candidate-complete.json": continue
    rel=path.relative_to(root).as_posix()
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    actual[rel]={"path":rel,"bytes":path.stat().st_size,"sha256":digest}
if actual!=expected:
    print(json.dumps({"ok":False,"missing":sorted(set(expected)-set(actual)),"extra":sorted(set(actual)-set(expected)),"changed":sorted(k for k in set(actual)&set(expected) if actual[k]!=expected[k])}))
    raise SystemExit(4)
rows=sorted(actual.values(),key=lambda row:(row["path"].casefold(),row["path"]))
d=hashlib.sha256()
for row in rows:
    d.update(row["path"].encode());d.update(b"\0");d.update(row["sha256"].encode());d.update(b"\n")
proof={"ok":True,"files":len(rows),"bytes":sum(row["bytes"] for row in rows),"manifestSha256":d.hexdigest()}
if proof["manifestSha256"]!=manifest["manifestSha256"]: raise SystemExit("tree digest mismatch")
print(json.dumps(proof))
'''


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload and verify an immutable Neyvia candidate without publishing it.")
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument(
        "--credentials",
        default=str(ROOT / ".agent_control" / "nas_codex2_100_125_54_118.json"),
        help="Path to the private NAS SSH credential JSON (never included in the candidate).",
    )
    args = parser.parse_args()
    candidate = Path(args.candidate).resolve(strict=True)
    manifest_path = Path(args.manifest).resolve(strict=True)
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    name = candidate.name
    if name != manifest["candidate"] or not name.startswith("neyvia-candidate-"):
        raise RuntimeError("candidate name does not match the signed manifest")
    local_verification = _verify_local_candidate(candidate, manifest)
    transfer_id = f"nas_batch_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    stage = f"{REMOTE_RELEASES}/.incomplete-{name}-{uuid.uuid4().hex[:8]}"
    final = f"{REMOTE_RELEASES}/{name}"
    remote_manifest = f"/tmp/{transfer_id}.manifest.json"
    remote_verifier = f"/tmp/{transfer_id}.verify.py"

    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w:gz") as bundle:
        for path in sorted(candidate.rglob("*")):
            if path.is_file() and not path.is_symlink():
                bundle.add(path, arcname=path.relative_to(candidate).as_posix(), recursive=False)
    credentials = json.loads(Path(args.credentials).expanduser().resolve(strict=True).read_text(encoding="utf-8"))
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=credentials.get("host", "192.0.2.10"), port=int(credentials.get("port", 22)),
        username=credentials.get("username", "nas-user"), password=credentials.get("password") or credentials.get("secret"),
        look_for_keys=False, allow_agent=False, timeout=15,
    )
    stage_created = False
    try:
        current_before = _run(client, "readlink -f /volume1/Saclay/projects/syntelos/current")
        _run(client, f"test ! -e {shlex.quote(final)}; mkdir -p {shlex.quote(REMOTE_RELEASES)}; mkdir {shlex.quote(stage)}")
        stage_created = True
        stdin, stdout, stderr = client.exec_command(f"tar -xzf - -C {shlex.quote(stage)}", timeout=300)
        stdin.write(archive.getvalue())
        stdin.flush()
        stdin.channel.shutdown_write()
        error = stderr.read().decode("utf-8", "replace")
        if stdout.channel.recv_exit_status():
            raise RuntimeError(f"remote candidate extraction failed: {error[-1200:]}")
        _upload(client, remote_manifest, manifest_bytes)
        _upload(client, remote_verifier, VERIFY_SCRIPT.encode("utf-8"))
        verified = json.loads(_run(client, f"python3 {shlex.quote(remote_verifier)} {shlex.quote(stage)} {shlex.quote(remote_manifest)}", timeout=300))
        completion = {
            "schema": "neyvia.nas_transfer.candidate_completion.v1", "status": "complete", "transferId": transfer_id,
            "destinationRoot": f"syntelos/releases/{name}", "manifestSchema": manifest["schema"], "transferMode": "immutable-candidate",
            "sourceManifestSha256": _sha256_bytes(manifest_bytes), "candidateTreeSha256": verified["manifestSha256"],
            "files": verified["files"], "bytes": verified["bytes"], "sha256Manifest": manifest["sha256Manifest"],
            "nasReceiptRelativePath": f".agent_control/neyvia_transfers/receipts/{transfer_id}.json",
            "completedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        completion_bytes = json.dumps(completion, indent=2, ensure_ascii=False).encode("utf-8")
        _upload(client, f"{stage}/.neyvia-candidate-complete.json", completion_bytes)
        receipt = {
            "schema": "neyvia.nas_transfer.batch.v1", "status": "completed", "transferId": transfer_id,
            "destinationRoot": completion["destinationRoot"], "sourceManifestSha256": completion["sourceManifestSha256"],
            "candidateStatus": "complete", "completionProofSha256": _sha256_bytes(completion_bytes), "verification": verified,
            "localVerification": local_verification, "publicLiveChanged": False, "previousCurrent": current_before,
        }
        receipt_bytes = json.dumps(receipt, indent=2, ensure_ascii=False).encode("utf-8")
        remote_receipt = f"{REMOTE_PROJECTS}/.agent_control/neyvia_transfers/receipts/{transfer_id}.json"
        _run(client, f"mkdir -p {shlex.quote(str(Path(remote_receipt).parent).replace(chr(92), '/'))}; mv {shlex.quote(stage)} {shlex.quote(final)}")
        stage_created = False
        _upload(client, remote_receipt, receipt_bytes)
        verified_final = json.loads(_run(client, f"python3 {shlex.quote(remote_verifier)} {shlex.quote(final)} {shlex.quote(remote_manifest)}", timeout=300))
        current_after = _run(client, "readlink -f /volume1/Saclay/projects/syntelos/current")
        if current_after != current_before:
            raise RuntimeError("public current symlink changed during candidate upload")
        receipt.update({"verification": verified_final, "currentAfter": current_after, "remoteCandidate": final, "remoteReceipt": remote_receipt})
        local_receipt = ROOT / ".agent_control" / "nas_transfers" / f"{transfer_id}.json"
        local_receipt.parent.mkdir(parents=True, exist_ok=True)
        local_receipt.write_text(json.dumps(receipt, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps({"ok": True, "candidate": final, "transferId": transfer_id, "treeSha256": verified_final["manifestSha256"], "files": verified_final["files"], "currentUnchanged": True, "receipt": str(local_receipt)}, ensure_ascii=False))
    except Exception:
        if stage_created:
            failed_stage = stage.replace("/.incomplete-", "/.failed-")
            try:
                _run(
                    client,
                    f"test ! -e {shlex.quote(stage)} || mv {shlex.quote(stage)} {shlex.quote(failed_stage)}",
                )
            except Exception:
                pass
        raise
    finally:
        try:
            _run(client, f"rm -f {shlex.quote(remote_manifest)} {shlex.quote(remote_verifier)}")
        except Exception:
            pass
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
