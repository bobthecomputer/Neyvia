"""Bounded, privacy-preserving recovery of value from prior Neyvia work.

The treasury reads only explicitly supported local asset roots.  It stores no
file bodies or transcript text in its output.  Hashes, schemas, typed status,
counts, and lineage references become review-only recovery missions.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .model_portfolio import recommended_route
from .proofs_a_capabilities import checked_action, check_treasury


CAPABILITY_TREASURY_SCHEMA = "neyvia.capability_treasury.v1"
CAPABILITY_RECOVERY_SCHEMA = "neyvia.capability_recovery_mission.v1"
MAX_HASHABLE_FILE_BYTES = 16 * 1024 * 1024
MAX_BUNDLE_FILES = 160
MAX_ASSETS = 180
PASS_STATES = {
    "complete",
    "completed",
    "done",
    "pass",
    "passed",
    "ready",
    "success",
    "succeeded",
    "verified",
}
PLAN_NAME_PATTERN = re.compile(
    r"(?:plan|roadmap|handoff|contract|ecosystem|continuation)",
    re.IGNORECASE,
)
EXCLUDED_DIRECTORY_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "build",
    "dist",
    "node_modules",
    "target",
    "venv",
}
SECRET_NAME_PATTERN = re.compile(
    r"(?:^|[-_.])(?:auth|cookie|credential|password|private[-_.]?key|secret|token)"
    r"(?:[-_.]|$)",
    re.IGNORECASE,
)
TOPIC_STOP_WORDS = {
    "2026",
    "20260721",
    "20260724",
    "20260725",
    "20260727",
    "20260728",
    "20260729",
    "20260730",
    "agent",
    "and",
    "app",
    "complete",
    "contract",
    "docs",
    "ecosystem",
    "final",
    "handoff",
    "living",
    "neyvia",
    "plan",
    "proof",
    "receipt",
    "report",
    "runtime",
    "session",
    "the",
    "wip",
}


def _utc_from_timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat().replace(
        "+00:00",
        "Z",
    )


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalized_status(value: object) -> str:
    return re.sub(
        r"[^a-z0-9]+",
        "_",
        str(value or "").strip().casefold(),
    ).strip("_")


def _title(value: object) -> str:
    text = re.sub(r"[_-]+", " ", str(value or "").strip())
    return " ".join(part.upper() if part.isupper() else part.capitalize() for part in text.split())


def _topic_tokens(value: object) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", str(value or "").casefold())
    return sorted(
        {
            token
            for token in tokens
            if len(token) >= 3
            and token not in TOPIC_STOP_WORDS
            and not token.isdigit()
        }
    )[:14]


def _safe_json(path: Path) -> dict[str, Any]:
    try:
        if path.stat().st_size > 2 * 1024 * 1024:
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _json_status(payload: dict[str, Any]) -> str:
    summary = (
        dict(payload.get("summary") or {})
        if isinstance(payload.get("summary"), dict)
        else {}
    )
    result = (
        dict(payload.get("result") or {})
        if isinstance(payload.get("result"), dict)
        else {}
    )
    for candidate in (
        payload.get("status"),
        payload.get("state"),
        summary.get("status"),
        summary.get("state"),
        result.get("status"),
        result.get("state"),
    ):
        status = _normalized_status(candidate)
        if status:
            return status
    return "passed" if payload.get("passed") is True else ""


def _is_supported_file(path: Path) -> bool:
    if path.is_symlink() or not path.is_file():
        return False
    if any(part.casefold() in EXCLUDED_DIRECTORY_NAMES for part in path.parts):
        return False
    if SECRET_NAME_PATTERN.search(path.name):
        return False
    try:
        return path.stat().st_size <= MAX_HASHABLE_FILE_BYTES
    except OSError:
        return False


def _bounded_files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    rows: list[Path] = []
    try:
        candidates = root.rglob("*")
        for path in candidates:
            if _is_supported_file(path):
                rows.append(path)
                if len(rows) >= MAX_BUNDLE_FILES:
                    break
    except OSError:
        return rows
    return sorted(rows, key=lambda item: str(item).casefold())


class CapabilityTreasury:
    """Build a live, transcript-free inventory and review queue."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().absolute()

    def _relative(self, path: Path) -> str:
        try:
            return path.absolute().relative_to(self.root).as_posix()
        except ValueError:
            return path.name

    def _bundle_facts(self, paths: Iterable[Path]) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        total_bytes = 0
        newest = 0.0
        for path in list(paths)[:MAX_BUNDLE_FILES]:
            if not _is_supported_file(path):
                continue
            try:
                stat = path.stat()
                sha256 = _file_digest(path)
            except OSError:
                continue
            total_bytes += stat.st_size
            newest = max(newest, stat.st_mtime)
            rows.append(
                {
                    "path": self._relative(path),
                    "bytes": stat.st_size,
                    "sha256": sha256,
                }
            )
        return {
            "digest": _canonical_digest(rows),
            "fileCount": len(rows),
            "sizeBytes": total_bytes,
            "updatedAt": _utc_from_timestamp(newest) if newest else "",
            "files": rows,
        }

    def _base_capsule(
        self,
        *,
        kind: str,
        label: str,
        path: str,
        digest: str,
        file_count: int,
        size_bytes: int,
        updated_at: str,
        verification_state: str,
        topic_tokens: list[str] | None = None,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        asset_id = (
            f"treasury_{hashlib.sha256(f'{kind}:{path}:{digest}'.encode('utf-8')).hexdigest()[:20]}"
        )
        return {
            "assetId": asset_id,
            "kind": kind,
            "label": label,
            "path": path,
            "digest": digest,
            "digestAlgorithm": "sha256",
            "fileCount": int(file_count),
            "sizeBytes": int(size_bytes),
            "updatedAt": updated_at,
            "verificationState": verification_state,
            "topicTokens": list(topic_tokens or _topic_tokens(f"{label} {path}")),
            "details": dict(details or {}),
            "contentStored": False,
            "transcriptsIncluded": False,
            "trustRaised": False,
            "activated": False,
        }

    def _plan_capsules(self) -> list[dict[str, Any]]:
        docs_root = self.root / "docs"
        if not docs_root.is_dir():
            return []
        capsules: list[dict[str, Any]] = []
        for path in sorted(docs_root.glob("*.md")):
            if not PLAN_NAME_PATTERN.search(path.name) or not _is_supported_file(path):
                continue
            facts = self._bundle_facts([path])
            open_tasks = 0
            completed_tasks = 0
            try:
                text = path.read_text(encoding="utf-8")
                open_tasks = len(re.findall(r"(?im)^\s*[-*]\s+\[\s\]", text))
                completed_tasks = len(re.findall(r"(?im)^\s*[-*]\s+\[[xX]\]", text))
            except (OSError, UnicodeDecodeError):
                pass
            capsules.append(
                self._base_capsule(
                    kind="plan",
                    label=_title(path.stem),
                    path=self._relative(path),
                    digest=facts["digest"],
                    file_count=facts["fileCount"],
                    size_bytes=facts["sizeBytes"],
                    updated_at=facts["updatedAt"],
                    verification_state="review_required",
                    details={
                        "openChecklistCount": open_tasks,
                        "completedChecklistCount": completed_tasks,
                        "checklistCountsAreSignalsOnly": True,
                    },
                )
            )
        return capsules

    def _proof_capsules(self) -> list[dict[str, Any]]:
        proof_root = self.root / "proof"
        if not proof_root.is_dir():
            return []
        bundles: list[tuple[str, list[Path]]] = []
        root_files = [
            path
            for path in proof_root.iterdir()
            if path.is_file() and _is_supported_file(path)
        ]
        if root_files:
            bundles.append(("proof/root-ledger", root_files))
        for directory in sorted(
            (path for path in proof_root.iterdir() if path.is_dir()),
            key=lambda item: item.name.casefold(),
        ):
            files = _bounded_files(directory)
            if files:
                bundles.append((self._relative(directory), files))

        capsules: list[dict[str, Any]] = []
        for relative_path, files in bundles:
            facts = self._bundle_facts(files)
            schemas: Counter[str] = Counter()
            statuses: Counter[str] = Counter()
            passing_receipts = 0
            for path in files:
                if path.suffix.casefold() != ".json":
                    continue
                payload = _safe_json(path)
                schema = str(payload.get("schema") or "").strip()
                status = _json_status(payload)
                if schema:
                    schemas[schema] += 1
                if status:
                    statuses[status] += 1
                if status in PASS_STATES:
                    passing_receipts += 1
            verification_state = (
                "verified"
                if passing_receipts
                else "recorded"
                if schemas
                else "unverified"
            )
            name = relative_path.rsplit("/", 1)[-1]
            capsules.append(
                self._base_capsule(
                    kind="proof_bundle",
                    label=_title(name),
                    path=relative_path,
                    digest=facts["digest"],
                    file_count=facts["fileCount"],
                    size_bytes=facts["sizeBytes"],
                    updated_at=facts["updatedAt"],
                    verification_state=verification_state,
                    details={
                        "schemaCount": sum(schemas.values()),
                        "schemas": [
                            {"schema": key, "count": value}
                            for key, value in schemas.most_common(8)
                        ],
                        "explicitPassingReceiptCount": passing_receipts,
                        "statuses": [
                            {"status": key, "count": value}
                            for key, value in statuses.most_common(8)
                        ],
                    },
                )
            )
        return capsules

    @staticmethod
    def _verified_app_jobs(
        app_factory_jobs: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        verified: dict[str, dict[str, Any]] = {}
        for raw in app_factory_jobs:
            if not isinstance(raw, dict):
                continue
            verification = (
                dict(raw.get("verification") or {})
                if isinstance(raw.get("verification"), dict)
                else {}
            )
            package = (
                dict(raw.get("package") or {})
                if isinstance(raw.get("package"), dict)
                else {}
            )
            spec = (
                dict(raw.get("spec") or {})
                if isinstance(raw.get("spec"), dict)
                else {}
            )
            if (
                _normalized_status(verification.get("state")) != "passed"
                or not str(package.get("sha256") or "").strip()
            ):
                continue
            for key in (
                spec.get("slug"),
                spec.get("appId"),
                raw.get("jobId"),
            ):
                normalized = str(key or "").strip().casefold()
                if normalized:
                    verified[normalized] = raw
        return verified

    def _app_capsules(
        self,
        app_factory_jobs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        apps_root = self.root / "apps"
        verified_jobs = self._verified_app_jobs(app_factory_jobs)
        capsules: list[dict[str, Any]] = []
        if apps_root.is_dir():
            for directory in sorted(
                (path for path in apps_root.iterdir() if path.is_dir()),
                key=lambda item: item.name.casefold(),
            ):
                facts = self._bundle_facts(_bounded_files(directory))
                if not facts["fileCount"]:
                    continue
                job = verified_jobs.get(directory.name.casefold())
                verification_state = "verified" if job else "local_candidate"
                details: dict[str, Any] = {
                    "appFactoryBound": bool(job),
                }
                if job:
                    verification = dict(job.get("verification") or {})
                    package = dict(job.get("package") or {})
                    spec = dict(job.get("spec") or {})
                    details.update(
                        {
                            "jobId": str(job.get("jobId") or ""),
                            "appId": str(spec.get("appId") or ""),
                            "packageSha256": str(package.get("sha256") or ""),
                            "verificationReceiptPath": str(
                                verification.get("receiptPath") or ""
                            ),
                        }
                    )
                capsules.append(
                    self._base_capsule(
                        kind="local_app",
                        label=_title(directory.name),
                        path=self._relative(directory),
                        digest=facts["digest"],
                        file_count=facts["fileCount"],
                        size_bytes=facts["sizeBytes"],
                        updated_at=facts["updatedAt"],
                        verification_state=verification_state,
                        details=details,
                    )
                )

        for job in app_factory_jobs:
            if not isinstance(job, dict):
                continue
            verification = (
                dict(job.get("verification") or {})
                if isinstance(job.get("verification"), dict)
                else {}
            )
            package = (
                dict(job.get("package") or {})
                if isinstance(job.get("package"), dict)
                else {}
            )
            spec = (
                dict(job.get("spec") or {})
                if isinstance(job.get("spec"), dict)
                else {}
            )
            if (
                _normalized_status(verification.get("state")) != "passed"
                or not package.get("sha256")
            ):
                continue
            job_id = str(job.get("jobId") or "")
            capsules.append(
                self._base_capsule(
                    kind="app_factory_package",
                    label=_title(spec.get("name") or spec.get("slug") or job_id),
                    path=str(package.get("path") or ""),
                    digest=str(package.get("sha256") or ""),
                    file_count=int(package.get("fileCount") or 1),
                    size_bytes=int(package.get("bytes") or 0),
                    updated_at=str(
                        verification.get("verifiedAt")
                        or job.get("updatedAt")
                        or ""
                    ),
                    verification_state="verified",
                    details={
                        "jobId": job_id,
                        "appId": str(spec.get("appId") or ""),
                        "template": str(spec.get("template") or ""),
                        "receiptPath": str(
                            verification.get("receiptPath") or ""
                        ),
                    },
                )
            )
        return capsules

    def _skill_capsules(self) -> list[dict[str, Any]]:
        skills_root = self.root / ".codex" / "skills"
        if not skills_root.is_dir():
            return []
        capsules: list[dict[str, Any]] = []
        for directory in sorted(
            (path for path in skills_root.iterdir() if path.is_dir()),
            key=lambda item: item.name.casefold(),
        ):
            skill_path = directory / "SKILL.md"
            if not _is_supported_file(skill_path):
                continue
            package_files = [skill_path]
            metadata_path = directory / "agents" / "openai.yaml"
            if _is_supported_file(metadata_path):
                package_files.append(metadata_path)
            facts = self._bundle_facts(package_files)
            revision_backups = len(
                [
                    path
                    for path in directory.glob("SKILL.md.bak*")
                    if _is_supported_file(path)
                ]
            )
            capsules.append(
                self._base_capsule(
                    kind="skill_package",
                    label=_title(directory.name),
                    path=self._relative(directory),
                    digest=facts["digest"],
                    file_count=facts["fileCount"],
                    size_bytes=facts["sizeBytes"],
                    updated_at=facts["updatedAt"],
                    verification_state=(
                        "revision_history_present"
                        if revision_backups
                        else "review_required"
                    ),
                    details={
                        "revisionBackupCount": revision_backups,
                        "metadataPresent": metadata_path in package_files,
                        "backupsIndexed": False,
                    },
                )
            )
        return capsules

    def _receipt_capsules(self) -> list[dict[str, Any]]:
        receipts_root = self.root / "receipts"
        files = _bounded_files(receipts_root)
        if not files:
            return []
        facts = self._bundle_facts(files)
        return [
            self._base_capsule(
                kind="receipt_ledger",
                label="Prior sealed release receipts",
                path=self._relative(receipts_root),
                digest=facts["digest"],
                file_count=facts["fileCount"],
                size_bytes=facts["sizeBytes"],
                updated_at=facts["updatedAt"],
                verification_state="recorded",
                details={"receiptBodiesStored": False},
            )
        ]

    def _artifact_capsules(
        self,
        artifact_graph: dict[str, Any],
    ) -> list[dict[str, Any]]:
        artifacts = [
            dict(item)
            for item in artifact_graph.get("artifacts") or []
            if isinstance(item, dict)
        ]
        relations = [
            dict(item)
            for item in artifact_graph.get("relations") or []
            if isinstance(item, dict)
        ]
        by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for artifact in artifacts:
            source = str(artifact.get("source") or "artifact_graph").strip()
            by_source[source].append(artifact)
        capsules: list[dict[str, Any]] = []
        for source, rows in sorted(by_source.items()):
            artifact_ids = {
                str(item.get("artifactId") or "")
                for item in rows
                if item.get("artifactId")
            }
            relation_count = sum(
                1
                for relation in relations
                if relation.get("parentArtifactId") in artifact_ids
                or relation.get("childArtifactId") in artifact_ids
            )
            verified_count = sum(
                1
                for item in rows
                if item.get("exists") is True and item.get("sha256")
            )
            digest = _canonical_digest(
                [
                    {
                        "artifactId": item.get("artifactId"),
                        "sha256": item.get("sha256"),
                        "updatedAt": item.get("updatedAt"),
                    }
                    for item in rows
                ]
            )
            capsules.append(
                self._base_capsule(
                    kind="artifact_lineage",
                    label=_title(source.rsplit(":", 1)[-1]),
                    path=f"artifact-graph:{source}",
                    digest=digest,
                    file_count=len(rows),
                    size_bytes=sum(int(item.get("sizeBytes") or 0) for item in rows),
                    updated_at=max(
                        (str(item.get("updatedAt") or "") for item in rows),
                        default="",
                    ),
                    verification_state=(
                        "verified" if verified_count == len(rows) else "mixed"
                    ),
                    topic_tokens=_topic_tokens(source),
                    details={
                        "source": source,
                        "artifactCount": len(rows),
                        "verifiedArtifactCount": verified_count,
                        "relationCount": relation_count,
                    },
                )
            )
        return capsules

    @staticmethod
    def _tokens_overlap(
        left: dict[str, Any],
        right: dict[str, Any],
    ) -> int:
        return len(
            set(left.get("topicTokens") or [])
            & set(right.get("topicTokens") or [])
        )

    def _recovery(
        self,
        *,
        action: str,
        title: str,
        reason: str,
        assets: list[dict[str, Any]],
        lane_id: str,
        priority: int,
        model_portfolio: dict[str, Any],
    ) -> dict[str, Any]:
        asset_ids = [str(item.get("assetId") or "") for item in assets]
        evidence_refs = [str(item.get("path") or "") for item in assets[:6]]
        route = recommended_route(model_portfolio, lane_id)
        recovery_id = (
            "recovery_"
            + hashlib.sha256(
                f"{action}:{'|'.join(asset_ids)}".encode("utf-8")
            ).hexdigest()[:20]
        )
        prompt = "\n".join(
            [
                f"Recover existing Neyvia value: {title}.",
                f"Why this is reviewable now: {reason}",
                "Start with inspection only. Rehash every referenced asset and verify its typed proof state.",
                (
                    "Prefer reuse or the smallest repair over rebuilding. Do not "
                    "activate a skill, publish an app, widen authority, or promote "
                    "a release without a separate human decision and current proof."
                ),
                "Evidence references:",
                *[f"- {item}" for item in evidence_refs],
            ]
        )
        return {
            "schema": CAPABILITY_RECOVERY_SCHEMA,
            "recoveryId": recovery_id,
            "action": action,
            "title": title,
            "reason": reason,
            "priority": priority,
            "assetIds": asset_ids,
            "assetKinds": sorted(
                {str(item.get("kind") or "") for item in assets}
            ),
            "evidenceRefs": evidence_refs,
            "evidenceCount": len(assets),
            "recommendedLaneId": lane_id,
            "recommendedRoute": route or {},
            "prompt": prompt,
            "state": "review_required",
            "humanApprovalRequired": True,
            "trustRaised": False,
            "candidateActivated": False,
            "published": False,
            "transcriptsIncluded": False,
        }

    def _recoveries(
        self,
        capsules: list[dict[str, Any]],
        model_portfolio: dict[str, Any],
    ) -> list[dict[str, Any]]:
        recoveries: list[dict[str, Any]] = []
        verified_apps = [
            item
            for item in capsules
            if item["kind"] in {"local_app", "app_factory_package"}
            and item["verificationState"] == "verified"
        ]
        for app in verified_apps[:2]:
            recoveries.append(
                self._recovery(
                    action="reuse_verified_app",
                    title=f"Reuse {app['label']}",
                    reason=(
                        "A deterministic app package and passing App Factory "
                        "verification receipt already exist."
                    ),
                    assets=[app],
                    lane_id="routine",
                    priority=0,
                    model_portfolio=model_portfolio,
                )
            )

        evolving_skills = [
            item
            for item in capsules
            if item["kind"] == "skill_package"
            and int(item.get("details", {}).get("revisionBackupCount") or 0) >= 2
        ]
        for skill in evolving_skills[:1]:
            recoveries.append(
                self._recovery(
                    action="review_skill_lineage",
                    title=f"Review the {skill['label']} lineage",
                    reason=(
                        f"{skill['details']['revisionBackupCount']} recoverable "
                        "revisions exist, but revision count alone does not prove lift."
                    ),
                    assets=[skill],
                    lane_id="verification",
                    priority=1,
                    model_portfolio=model_portfolio,
                )
            )

        artifact_lineages = [
            item
            for item in capsules
            if item["kind"] == "artifact_lineage"
            and int(item.get("details", {}).get("verifiedArtifactCount") or 0) >= 2
        ]
        for lineage in artifact_lineages[:2]:
            recoveries.append(
                self._recovery(
                    action="compose_verified_lineage",
                    title=f"Package {lineage['label']} as reusable leverage",
                    reason=(
                        f"{lineage['details']['verifiedArtifactCount']} hashed "
                        f"artifacts and {lineage['details']['relationCount']} lineage "
                        "edges already exist."
                    ),
                    assets=[lineage],
                    lane_id="routine",
                    priority=2,
                    model_portfolio=model_portfolio,
                )
            )

        proof_bundles = [
            item
            for item in capsules
            if item["kind"] == "proof_bundle"
            and item["verificationState"] == "verified"
        ]
        represented = [
            item
            for item in capsules
            if item["kind"] in {"local_app", "skill_package"}
        ]
        unmatched_proofs = [
            proof
            for proof in proof_bundles
            if not any(self._tokens_overlap(proof, item) for item in represented)
        ]
        for proof in unmatched_proofs[:2]:
            recoveries.append(
                self._recovery(
                    action="package_existing_proof",
                    title=f"Recover the {proof['label']} proof",
                    reason=(
                        f"{proof['details']['explicitPassingReceiptCount']} explicit "
                        "passing receipt is present without a matching local app or "
                        "project skill package."
                    ),
                    assets=[proof],
                    lane_id="routine",
                    priority=3,
                    model_portfolio=model_portfolio,
                )
            )

        plans = [item for item in capsules if item["kind"] == "plan"]
        unproved_plans = [
            plan
            for plan in plans
            if not any(self._tokens_overlap(plan, proof) for proof in proof_bundles)
        ]
        for plan in unproved_plans[:2]:
            recoveries.append(
                self._recovery(
                    action="review_shelved_plan",
                    title=f"Decide the next life of {plan['label']}",
                    reason=(
                        "The plan is locally hashed but no matching passing proof "
                        "bundle was found from filename-level topic signals."
                    ),
                    assets=[plan],
                    lane_id="deep",
                    priority=5,
                    model_portfolio=model_portfolio,
                )
            )

        unique: dict[str, dict[str, Any]] = {}
        for recovery in recoveries:
            unique.setdefault(recovery["recoveryId"], recovery)
        return sorted(
            unique.values(),
            key=lambda item: (int(item["priority"]), str(item["title"])),
        )[:8]

    @checked_action(check_treasury)
    def snapshot(
        self,
        *,
        app_factory_jobs: list[dict[str, Any]] | None = None,
        artifact_graph: dict[str, Any] | None = None,
        model_portfolio: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return bounded asset capsules and review-only recovery missions."""

        jobs = [
            dict(item)
            for item in app_factory_jobs or []
            if isinstance(item, dict)
        ]
        portfolio = (
            dict(model_portfolio)
            if isinstance(model_portfolio, dict)
            else {"lanes": []}
        )
        capsules = [
            *self._plan_capsules(),
            *self._proof_capsules(),
            *self._app_capsules(jobs),
            *self._skill_capsules(),
            *self._receipt_capsules(),
            *self._artifact_capsules(
                dict(artifact_graph)
                if isinstance(artifact_graph, dict)
                else {}
            ),
        ][:MAX_ASSETS]
        capsules.sort(
            key=lambda item: (
                {
                    "verified": 0,
                    "revision_history_present": 1,
                    "recorded": 2,
                    "local_candidate": 3,
                    "review_required": 4,
                    "unverified": 5,
                }.get(str(item.get("verificationState") or ""), 9),
                str(item.get("kind") or ""),
                str(item.get("label") or ""),
            )
        )
        recoveries = self._recoveries(capsules, portfolio)
        kind_counts = Counter(str(item.get("kind") or "") for item in capsules)
        verified_count = sum(
            1 for item in capsules if item.get("verificationState") == "verified"
        )
        return {
            "schema": CAPABILITY_TREASURY_SCHEMA,
            "generatedAt": _utc_from_timestamp(datetime.now().timestamp()),
            "scanPolicy": {
                "roots": [
                    "docs/*.md (plan-like filenames only)",
                    "proof/",
                    "receipts/",
                    "apps/",
                    ".codex/skills/*/SKILL.md",
                    ".agent_control/neyvia/app_factory (typed jobs supplied by App Factory)",
                    ".agent_control/capability_os/artifact_graph.json (typed graph only)",
                ],
                "maxAssets": MAX_ASSETS,
                "maxBundleFiles": MAX_BUNDLE_FILES,
                "maxHashableFileBytes": MAX_HASHABLE_FILE_BYTES,
                "secretNamedFilesExcluded": True,
                "contentStored": False,
                "transcriptsIncluded": False,
            },
            "summary": {
                "assetCount": len(capsules),
                "verifiedAssetCount": verified_count,
                "reviewRequiredAssetCount": len(capsules) - verified_count,
                "recoveryMissionCount": len(recoveries),
                "kindCounts": dict(sorted(kind_counts.items())),
                "indexedBytes": sum(
                    int(item.get("sizeBytes") or 0) for item in capsules
                ),
            },
            "differentiation": {
                "claimStatus": "implemented_local_contract",
                "claim": (
                    "Neyvia can turn prior local plans, receipts, verified apps, "
                    "skills, and artifact lineage into bounded review missions "
                    "without importing transcript bodies or auto-promoting trust."
                ),
                "competitorFeatureParityNotClaimed": True,
            },
            "recoveries": recoveries,
            "assets": capsules,
            "humanApprovalRequired": True,
            "trustRaised": False,
            "candidateActivated": False,
            "published": False,
            "transcriptsIncluded": False,
        }
