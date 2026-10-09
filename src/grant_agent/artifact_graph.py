"""Durable content-addressed artifact lineage for N-E-Y-V-I-A."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import threading
import uuid
from pathlib import Path
from typing import Any

from .capability_contracts import ARTIFACT_GRAPH_SCHEMA, canonical_hash, utc_now
from .proofs_a_capabilities import checked_action, check_graph_registration, check_graph_relation, check_graph_lineage


VALID_RELATIONS = frozenset(
    {
        "derived_from",
        "edited_from",
        "compiled_from",
        "extracted_from",
        "references",
        "verified_by",
        "rendered_from",
        "trained_from",
        "tested_by",
        "exported_from",
        "contains",
    }
)


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ArtifactGraph:
    """Persist artifacts and source-to-result edges without storing file bodies."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.state_dir = self.root / ".agent_control" / "capability_os"
        self.state_path = self.state_dir / "artifact_graph.json"
        self._lock = threading.RLock()

    def _empty(self) -> dict[str, Any]:
        return {
            "schema": ARTIFACT_GRAPH_SCHEMA,
            "updatedAt": utc_now(),
            "artifacts": {},
            "relations": [],
        }

    def _load_unlocked(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return self._empty()
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return self._empty()
        if not isinstance(payload, dict) or payload.get("schema") != ARTIFACT_GRAPH_SCHEMA:
            return self._empty()
        if not isinstance(payload.get("artifacts"), dict):
            payload["artifacts"] = {}
        if not isinstance(payload.get("relations"), list):
            payload["relations"] = []
        return payload

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            payload = self._load_unlocked()
        artifacts = list(payload["artifacts"].values())
        artifacts.sort(key=lambda item: str(item.get("updatedAt") or ""), reverse=True)
        relations = list(payload["relations"])
        return {
            "schema": ARTIFACT_GRAPH_SCHEMA,
            "updatedAt": payload.get("updatedAt") or "",
            "summary": {
                "artifacts": len(artifacts),
                "relations": len(relations),
                "verifiedArtifacts": sum(
                    1 for item in artifacts if bool(item.get("sha256"))
                ),
            },
            "artifacts": artifacts,
            "relations": relations,
        }

    @checked_action(check_graph_registration)
    def register(
        self,
        *,
        path: str | Path | None = None,
        artifact_id: str = "",
        name: str = "",
        media_type: str = "",
        kind: str = "file",
        metadata: dict[str, Any] | None = None,
        source: str = "workspace",
    ) -> dict[str, Any]:
        resolved: Path | None = None
        exists = False
        size_bytes: int | None = None
        modified_ns: int | None = None
        sha256 = ""
        path_text = str(path or "").strip()
        if path_text:
            candidate = Path(path_text)
            if not candidate.is_absolute():
                candidate = self.root / candidate
            resolved = candidate.resolve()
            exists = resolved.is_file()
            if exists:
                stat = resolved.stat()
                size_bytes = stat.st_size
                modified_ns = stat.st_mtime_ns
                sha256 = _file_sha256(resolved)
                if not media_type:
                    media_type = (
                        mimetypes.guess_type(resolved.name)[0]
                        or "application/octet-stream"
                    )
                if not name:
                    name = resolved.name

        if not artifact_id:
            stable = {
                "path": str(resolved or path_text),
                "sha256": sha256,
                "name": name,
                "kind": kind,
            }
            artifact_id = f"artifact_{canonical_hash(stable)[:20]}"
        artifact_id = str(artifact_id).strip()
        if not artifact_id:
            raise ValueError("artifactId or path is required")

        now = utc_now()
        with self._lock:
            payload = self._load_unlocked()
            previous = payload["artifacts"].get(artifact_id) or {}
            item = {
                "artifactId": artifact_id,
                "name": str(name or previous.get("name") or artifact_id),
                "kind": str(kind or previous.get("kind") or "file"),
                "path": str(resolved or path_text or previous.get("path") or ""),
                "mediaType": str(
                    media_type
                    or previous.get("mediaType")
                    or "application/octet-stream"
                ),
                "exists": exists if path_text else bool(previous.get("exists")),
                "sizeBytes": size_bytes if size_bytes is not None else previous.get("sizeBytes"),
                "modifiedNs": (
                    modified_ns if modified_ns is not None else previous.get("modifiedNs")
                ),
                "sha256": sha256 or str(previous.get("sha256") or ""),
                "source": str(source or previous.get("source") or "workspace"),
                "metadata": {
                    **dict(previous.get("metadata") or {}),
                    **dict(metadata or {}),
                },
                "createdAt": str(previous.get("createdAt") or now),
                "updatedAt": now,
            }
            payload["artifacts"][artifact_id] = item
            payload["updatedAt"] = now
            _atomic_json(self.state_path, payload)
        return item

    @checked_action(check_graph_relation)
    def relate(
        self,
        parent_artifact_id: str,
        child_artifact_id: str,
        relation: str,
        *,
        capability_id: str = "",
        run_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        parent = str(parent_artifact_id or "").strip()
        child = str(child_artifact_id or "").strip()
        normalized_relation = str(relation or "").strip().lower()
        if not parent or not child:
            raise ValueError("parentArtifactId and childArtifactId are required")
        if parent == child:
            raise ValueError("An artifact cannot be related to itself")
        if normalized_relation not in VALID_RELATIONS:
            raise ValueError(f"Unsupported artifact relation: {normalized_relation}")

        with self._lock:
            payload = self._load_unlocked()
            missing = [
                item
                for item in (parent, child)
                if item not in payload["artifacts"]
            ]
            if missing:
                raise KeyError(f"Unknown artifact identifiers: {', '.join(missing)}")
            identity = canonical_hash(
                {
                    "parent": parent,
                    "child": child,
                    "relation": normalized_relation,
                    "capability": capability_id,
                    "run": run_id,
                }
            )
            for existing in payload["relations"]:
                if existing.get("relationId") == f"relation_{identity[:20]}":
                    return existing
            item = {
                "relationId": f"relation_{identity[:20]}",
                "parentArtifactId": parent,
                "childArtifactId": child,
                "relation": normalized_relation,
                "capabilityId": str(capability_id or ""),
                "runId": str(run_id or ""),
                "metadata": dict(metadata or {}),
                "createdAt": utc_now(),
            }
            payload["relations"].append(item)
            payload["updatedAt"] = utc_now()
            _atomic_json(self.state_path, payload)
            return item

    @checked_action(check_graph_lineage)
    def lineage(
        self,
        artifact_id: str,
        *,
        direction: str = "both",
        max_depth: int = 8,
    ) -> dict[str, Any]:
        target = str(artifact_id or "").strip()
        normalized_direction = str(direction or "both").strip().lower()
        if normalized_direction not in {"ancestors", "descendants", "both"}:
            raise ValueError("direction must be ancestors, descendants, or both")
        depth_limit = max(1, min(int(max_depth), 32))
        with self._lock:
            payload = self._load_unlocked()
        if target not in payload["artifacts"]:
            raise KeyError(f"Unknown artifact: {target}")

        selected_ids = {target}
        selected_relations: dict[str, dict[str, Any]] = {}
        frontier = {target}
        for _depth in range(depth_limit):
            next_frontier: set[str] = set()
            for relation in payload["relations"]:
                parent = str(relation.get("parentArtifactId") or "")
                child = str(relation.get("childArtifactId") or "")
                matches = False
                other = ""
                if normalized_direction in {"descendants", "both"} and parent in frontier:
                    matches = True
                    other = child
                if normalized_direction in {"ancestors", "both"} and child in frontier:
                    matches = True
                    other = parent
                if not matches:
                    continue
                relation_id = str(relation.get("relationId") or canonical_hash(relation))
                selected_relations[relation_id] = relation
                if other and other not in selected_ids:
                    selected_ids.add(other)
                    next_frontier.add(other)
            if not next_frontier:
                break
            frontier = next_frontier

        artifacts = [
            payload["artifacts"][item]
            for item in sorted(selected_ids)
            if item in payload["artifacts"]
        ]
        return {
            "schema": ARTIFACT_GRAPH_SCHEMA,
            "artifactId": target,
            "direction": normalized_direction,
            "maxDepth": depth_limit,
            "artifacts": artifacts,
            "relations": list(selected_relations.values()),
            "summary": {
                "artifactCount": len(artifacts),
                "relationCount": len(selected_relations),
            },
        }
