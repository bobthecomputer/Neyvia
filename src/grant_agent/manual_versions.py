"""Scoped manual revisions: quarantined JSON patches, explicit promotion and lineage."""
from __future__ import annotations
import copy
import hashlib
import json
import re
import uuid
from .durability import atomic_write_json
from .manual_state import pointer


def revision(root, identity, digest, data):
    path = root / "manual-versions" / (identity + ".json")
    if not path.exists():
        return digest, data
    saved = json.loads(path.read_text(encoding="utf-8"))
    raw = (root / "manual-versions" / identity / (saved["sha256"] + ".json")).read_bytes()
    if hashlib.sha256(raw).hexdigest() != saved["sha256"]:
        raise ValueError("Manual revision integrity check failed")
    return saved["sha256"], json.loads(raw)


def apply_operations(data, operations):
    """Deliberately bounded RFC 6902 subset; never executes source or expressions."""
    result = copy.deepcopy(data)
    if not isinstance(operations, list) or not 1 <= len(operations) <= 100:
        raise ValueError("Patch requires 1..100 operations")
    for op in operations:
        if op.get("op") not in {"test", "add", "remove", "replace"}:
            raise ValueError("Supported patch operations: test/add/remove/replace")
        path = op.get("path", "")
        if not path.startswith("/chapters/"):
            raise ValueError("Patches are scoped to chapter content")
        parent_path, _, key = path.rpartition("/")
        key = key.replace("~1", "/").replace("~0", "~")
        parent = pointer(result, parent_path)
        if op["op"] == "test":
            if pointer(result, path) != op["value"]:
                raise ValueError("Patch test precondition failed")
            continue
        if isinstance(parent, list):
            index = len(parent) if key == "-" and op["op"] == "add" else int(key)
            if index < 0 or index > len(parent) or (op["op"] != "add" and index == len(parent)):
                raise ValueError("Patch array index outside bounds")
            if op["op"] == "add":
                parent.insert(index, copy.deepcopy(op["value"]))
            elif op["op"] == "remove":
                del parent[index]
            else:
                parent[index] = copy.deepcopy(op["value"])
        else:
            if op["op"] in {"replace", "remove"} and key not in parent:
                raise ValueError("Patch target must exist")
            if op["op"] == "remove":
                del parent[key]
            else:
                parent[key] = copy.deepcopy(op["value"])
    return result


def quarantine(root, identity, digest, note, observed, operations=None):
    patch = {"patchId": uuid.uuid4().hex, "id": identity, "baseSha256": digest, "status": "quarantined", "note": note,
             "observed": observed, "operations": operations or [], "promotion": "manual.patch.apply requires explicit approval, reviewer, evidence and current base hash."}
    atomic_write_json(root / "manual-patches" / (patch["patchId"] + ".json"), patch)
    return patch


def promote(root, args, digest, data, registry):
    from .neyvia_manuals import validate, get_manual, REPO
    if args.get("approved") is not True or not str(args.get("reviewer", "")).strip() or not args.get("evidence"):
        raise PermissionError("Explicit approval, reviewer and evidence are required")
    if not re.fullmatch(r"[a-f0-9]{32}", args["patchId"]):
        raise ValueError("Invalid patch ID")
    path = root / "manual-patches" / (args["patchId"] + ".json")
    patch = json.loads(path.read_text(encoding="utf-8"))
    if patch["id"] != args["id"] or patch["status"] != "quarantined" or patch["baseSha256"] != digest or args["expectedSha256"] != digest:
        raise ValueError("Patch must be quarantined and bound to the current manual hash")
    candidate = apply_operations(data, patch["operations"])
    validate(candidate, registry)
    raw = (json.dumps(candidate, ensure_ascii=False, indent=2) + "\n").encode()
    new_digest = hashlib.sha256(raw).hexdigest()
    folder = root / "manual-versions" / args["id"]
    from .durability import atomic_write_bytes, atomic_write_text
    record, original_source_sha, original_data = get_manual(args["id"])
    if digest == original_source_sha:
        # The initial manual may be authored in CL while its executable
        # artifact is JSON. They are different byte streams and must retain
        # their own hashes; a JSON file cannot honestly be named by CL SHA.
        source_path = REPO / record.get("clSource", record["path"])
        source_raw = source_path.read_bytes()
        artifact_raw = (REPO / record["path"]).read_bytes()
        if (hashlib.sha256(source_raw).hexdigest() != digest
                or json.loads(artifact_raw) != data or original_data != data):
            raise ValueError("Cannot preserve original manual source and executable bytes")
        if record.get("clSource"):
            source_copy = folder / (digest + ".cl")
            if source_copy.exists():
                if source_copy.read_bytes() != source_raw:
                    raise ValueError("Preserved manual source differs from current CL bytes")
            else:
                atomic_write_bytes(source_copy, source_raw)
    else:
        artifact_raw = (folder / (digest + ".json")).read_bytes()
        if hashlib.sha256(artifact_raw).hexdigest() != digest or json.loads(artifact_raw) != data:
            raise ValueError("Current manual version bytes do not match the selected base")
    parent_artifact_sha = hashlib.sha256(artifact_raw).hexdigest()
    artifact_copy = folder / (parent_artifact_sha + ".json")
    if artifact_copy.exists():
        if artifact_copy.read_bytes() != artifact_raw:
            raise ValueError("Preserved manual artifact differs from current bytes")
    else:
        atomic_write_bytes(artifact_copy, artifact_raw)
    atomic_write_text(folder / (new_digest + ".json"), raw.decode())
    history_path = root / "manual-versions" / (args["id"] + ".json")
    history = json.loads(history_path.read_text(encoding="utf-8")) if history_path.exists() else {"id": args["id"], "lineage": []}
    demoted = [chapter + "/" + name for chapter, row in data["chapters"].items() for name in row["procedures"]
               if chapter not in candidate["chapters"] or name not in candidate["chapters"][chapter]["procedures"]]
    entry = {"sha256": new_digest, "parentSha256": digest, "parentArtifactSha256": parent_artifact_sha,
             "patchId": patch["patchId"], "reviewer": args["reviewer"],
             "evidence": args["evidence"], "demoted": demoted, "grounded": True}
    history.update(sha256=new_digest, lineage=history["lineage"] + [entry])
    atomic_write_json(history_path, history)
    patch.update(status="promoted", promotedSha256=new_digest)
    atomic_write_json(path, patch)
    return {"ok": True, "id": args["id"], **entry, "scope": "selected workspace only"}
