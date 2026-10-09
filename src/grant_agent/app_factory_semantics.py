"""Semantic adapter from real App Factory jobs to Living Applications.

The adapter is observational and local: it hashes files that already exist,
records verification receipts, and preserves upgrade lineage. It never invokes
the App Factory publisher, starts a service, or restarts a process.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .living_applications import ArtifactRecord, LivingApplication, LivingApplicationRegistry, sha256_file
from .durability import atomic_write_json


def _text(value: object) -> str:
    return str(value or "").strip()


def _source_revision(root: Path, paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.relative_to(root).as_posix()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(bytes.fromhex(sha256_file(path)))
    return digest.hexdigest()


def register_app_factory_job(
    job: Mapping[str, Any],
    *,
    registry: LivingApplicationRegistry | None = None,
    permissions: list[Mapping[str, Any]] | None = None,
    persist_path: str | Path | None = None,
) -> LivingApplication:
    from .harness_jobs import _exclusive_job_lock
    if persist_path:
        with _exclusive_job_lock(Path(persist_path)):
            return _register_app_factory_job(job, registry=registry, permissions=permissions, persist_path=persist_path)
    return _register_app_factory_job(job, registry=registry, permissions=permissions)


def _register_app_factory_job(job: Mapping[str, Any], *, registry=None, permissions=None, persist_path=None) -> LivingApplication:
    """Register/update an application from a completed local App Factory job.

    ``job`` is the object returned by ``AppFactory.get_job``. A source
    root and at least one real file are required. A verification receipt is
    recorded only when it exists on disk and its hash can be computed.
    """
    spec = job.get("spec") if isinstance(job.get("spec"), Mapping) else {}
    app_id = _text(spec.get("appId") or job.get("applicationId"))
    source_root = Path(_text(job.get("projectRoot"))).expanduser().resolve()
    if not app_id or not source_root.is_dir():
        raise ValueError("App Factory job requires a real application id and projectRoot")
    excluded = {".git", "node_modules", "target", ".venv", ".agent_control", "__pycache__"}
    files: list[Path] = []
    for path in source_root.rglob("*"):
        if not path.is_file() or any(part in excluded for part in path.relative_to(source_root).parts) or path.name.startswith('.env') or path.suffix in {'.key', '.pem', '.dpapi'}:
            continue
        resolved = path.resolve()
        try:
            resolved.relative_to(source_root)
        except ValueError as exc:
            raise ValueError(f"App Factory source escapes projectRoot: {path}") from exc
        files.append(resolved)
    if not files:
        raise ValueError("App Factory source root contains no files")
    registry = registry or _load_registry(persist_path)
    app = registry.get(app_id) or LivingApplication(application_id=app_id)
    previous_revision = _text(app.source.get("revision"))
    revision = _source_revision(source_root, files)
    app.source.update({"kind": "app-factory", "root": str(source_root), "revision": revision,
                       "jobId": _text(job.get("jobId")), "lineage": _text(job.get("lineageId") or job.get("parentLineageId"))})
    app.build_recipe = dict(job.get("buildRecipe") or {"target": spec.get("target"), "template": spec.get("template"), "builder": "neyvia.app_factory"})
    supplied_permissions = permissions if permissions is not None else job.get("permissions")
    if supplied_permissions is not None:
        app.permissions = [dict(item) for item in supplied_permissions if isinstance(item, Mapping)]
    if revision != previous_revision:
        app.rollback = {"previousRevision": previous_revision, "available": False,
                        "reason": "Revision lineage is recorded; an executable source restoration recipe is not yet registered",
                        "boundary": "registry-only; no service restart or publication"}
        app.history.append({"event": "app_factory_revision", "jobId": _text(job.get("jobId")), "revision": revision,
                            "previousRevision": previous_revision, "at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")})
    for index, path in enumerate(files):
        artifact_id = f"source:{path.relative_to(source_root).as_posix()}"
        app.add_artifact(ArtifactRecord.from_file(artifact_id, path, kind="source"))
    package = job.get("package") if isinstance(job.get("package"), Mapping) else {}
    package_path = Path(_text(package.get("path"))).expanduser() if package.get("path") else None
    if package_path and package_path.is_file():
        app.add_artifact(ArtifactRecord.from_file("build:package", package_path, kind="build"))
    receipt_path = Path(_text((job.get("verification") or {}).get("receiptPath"))).expanduser() if isinstance(job.get("verification"), Mapping) else None
    if receipt_path and receipt_path.is_file():
        receipt_hash = sha256_file(receipt_path)
        proof = {"kind": "app-factory-verification", "path": str(receipt_path.resolve()), "sha256": receipt_hash,
                 "state": (job.get("verification") or {}).get("state", "observed")}
        if proof not in app.proofs:
            app.proofs.append(proof)
    app.health = {"state": "observed" if (job.get("verification") or {}).get("state") == "passed" else "unknown",
                  "source": "app-factory-job", "deployment": "not attempted"}
    registry.register(app)
    if persist_path:
        atomic_write_json(Path(persist_path), registry.snapshot())
    return app


def _load_registry(path: str | Path | None) -> LivingApplicationRegistry:
    registry = LivingApplicationRegistry()
    if not path or not Path(path).is_file():
        return registry
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("Living Application registry is unreadable; preserve and reconcile it before updates") from exc
    for row in payload.get("applications", []) if isinstance(payload, Mapping) else []:
        if not isinstance(row, Mapping) or not _text(row.get("applicationId")):
            continue
        app = LivingApplication(application_id=_text(row.get("applicationId")), source=dict(row.get("source") or {}),
                                build_recipe=dict(row.get("buildRecipe") or {}), permissions=list(row.get("permissions") or []),
                                proofs=list(row.get("proofs") or []), health=dict(row.get("health") or {}), deployments=list(row.get("deployments") or []), data_contracts=list(row.get("dataContracts") or []),
                                feedback=list(row.get("feedback") or []), history=list(row.get("history") or []), rollback=dict(row.get("rollback") or {}))
        for item in row.get("artifacts") or []:
            if isinstance(item, Mapping):
                app.artifacts.append(ArtifactRecord(_text(item.get("artifactId")), _text(item.get("path")), _text(item.get("sha256")), _text(item.get("kind") or "artifact"), _text(item.get("createdAt"))))
        registry.register(app)
    return registry


__all__ = ["register_app_factory_job"]
