"""Durable experience traces and evidence-gated candidate skill promotion.

The store records observations and links; it intentionally does not invent a
quality score.  Promotion requires persisted matching evidence and explicit
trusted authority.
"""
from __future__ import annotations

import hashlib
import json
import uuid
import threading
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .durability import append_jsonl_durable, atomic_write_json
from .harness_jobs import _exclusive_job_lock
from .verified_operations import VerifiedOperationStore

SCHEMA = "neyvia.experience-learning.v1"
TRACE_KINDS = {"input", "frame", "state", "error", "timing"}
CANDIDATE_STATES = {"proposed", "testing", "evidence_ready", "promoted", "rejected"}
_PROMOTION_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()).hexdigest()


class ExperienceStore:
    def __init__(self, root: str | Path, scope: str):
        self.root = Path(root).resolve()
        self.scope = str(scope).strip()
        if not self.scope:
            raise ValueError("scope is required")
        self.base = self.root / ".agent_control" / "experience_learning" / _hash(self.scope)[:24]
        self.base.mkdir(parents=True, exist_ok=True)
        self.events_path = self.base / "events.jsonl"

    def _record(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        record = {"schema": SCHEMA, "recordId": _id(kind), "kind": kind, "createdAt": _now(), **payload}
        record["recordHash"] = _hash(record)
        atomic_write_json(self.base / f"{record['recordId']}.json", record)
        append_jsonl_durable(self.events_path, record)
        return record

    def compare(self, *, experience_id: str, user_version: str, provisional_version: str, preference: str, provenance: Mapping[str, Any], observations: Mapping[str, Any] | None = None) -> dict[str, Any]:
        if preference not in {"user", "provisional", "undecided"}:
            raise ValueError("preference must be user, provisional, or undecided")
        return self._record("comparison", {"experienceId": experience_id, "userVersion": user_version, "provisionalVersion": provisional_version, "preference": preference, "observations": dict(observations or {}), "provenance": dict(provenance)})

    def trace(self, *, trace_id: str, event_kind: str, payload: Mapping[str, Any], references: list[str] | None = None, provenance: Mapping[str, Any] | None = None) -> dict[str, Any]:
        if event_kind not in TRACE_KINDS:
            raise ValueError(f"unsupported trace kind: {event_kind}")
        return self._record("trace", {"traceId": trace_id, "eventKind": event_kind, "payload": dict(payload), "references": list(references or []), "provenance": dict(provenance or {})})

    def investigate(self, *, hypothesis: str, experiment: Mapping[str, Any], references: list[str] | None = None) -> dict[str, Any]:
        return self._record("investigation", {"hypothesis": str(hypothesis), "experiment": dict(experiment), "references": list(references or []), "status": "planned"})

    def candidate(self, *, skill_id: str, version: str, changes: Mapping[str, Any], evidence_ids: list[str] | None = None) -> dict[str, Any]:
        return self._record("candidate", {"candidateId": _id("candidate"), "skillId": skill_id, "version": version, "changes": dict(changes), "evidenceIds": list(evidence_ids or []), "status": "proposed"})

    def evaluate_candidate(self, *, candidate_id: str, artifact_hash: str, receipt_id: str, verdict: str, provenance: Mapping[str, Any]) -> dict[str, Any]:
        if not (len(str(artifact_hash).strip()) == 64 and all(c in "0123456789abcdefABCDEF" for c in str(artifact_hash))):
            raise ValueError("evaluation requires a SHA-256 artifact hash")
        if str(verdict).lower() not in {"pass", "passed", "verified"}:
            raise ValueError("only a passing evaluation can be promotion evidence")
        receipt = VerifiedOperationStore(self.root, self.scope).inspect(receipt_id)
        verification = (receipt.get("result") or {}).get("verification") or {}
        if receipt.get("status") != "verified" or not isinstance(verification, dict) or verification.get("candidateId") != candidate_id or verification.get("artifactHash") != artifact_hash.lower():
            raise ValueError("Evaluation must resolve to a verified operation for this candidate and artifact")
        artifact = Path(str(provenance.get("artifactPath") or ""))
        artifact = (artifact if artifact.is_absolute() else self.root / artifact).resolve()
        artifact.relative_to(self.root)
        if not artifact.is_file() or hashlib.sha256(artifact.read_bytes()).hexdigest() != artifact_hash.lower():
            raise ValueError("Evaluation artifact is missing or changed")
        row = self._record("evaluation", {"candidateId": candidate_id, "artifactHash": artifact_hash.lower(), "receiptId": receipt_id, "receiptHash": receipt["resultHash"], "status": "verified", "provenance": {**dict(provenance), "artifactPath":str(artifact)}})
        return row

    def promote(self, candidate_id: str, *, authority: Mapping[str, Any], evidence_ids: list[str]) -> dict[str, Any]:
        if authority.get("trusted") is not True or authority.get("authorityKind") not in {"operator", "system"} or not str(authority.get("authorityId") or "").strip():
            raise PermissionError("operator or system promotion authority is required")
        with _exclusive_job_lock(self.base / "promotion.json"):
            candidate = next((row for row in self.list(kind="candidate", limit=500) if row.get("candidateId") == candidate_id or row.get("recordId") == candidate_id), None)
            if not candidate:
                raise KeyError(candidate_id)
            records = {str(item.get("recordId")): item for item in self.list(limit=500)}
            expected = set(candidate.get("evidenceIds") or [])
            supplied = set(evidence_ids or [])
            if not supplied or not expected.issubset(supplied):
                raise ValueError("candidate evidence is incomplete")
            expected = supplied
            matching = [records.get(item) for item in expected]
            if any(not row or row.get("recordHash") != _hash({k: v for k, v in row.items() if k != "recordHash"}) for row in matching):
                raise ValueError("candidate evidence is corrupt or missing")
            evaluations = [row for row in matching if row.get("kind") == "evaluation" and row.get("candidateId") == candidate.get("candidateId") and row.get("status") == "verified" and row.get("artifactHash") and row.get("receiptId")]
            if not evaluations:
                raise ValueError("promotion requires a matching verified evaluation receipt")
            for evaluation in evaluations:
                operation = VerifiedOperationStore(self.root, self.scope).inspect(evaluation["receiptId"])
                artifact = Path(evaluation["provenance"]["artifactPath"]).resolve()
                artifact.relative_to(self.root)
                if operation.get("status") != "verified" or operation.get("resultHash") != evaluation.get("receiptHash") or not artifact.is_file() or hashlib.sha256(artifact.read_bytes()).hexdigest() != evaluation["artifactHash"]:
                    raise ValueError("Promotion evidence is no longer valid")
            if any(row.get("kind") == "investigation" and row.get("status") == "planned" for row in matching):
                raise ValueError("planned investigations are not promotion evidence")
            receipt = self._record("promotion", {"candidateId": candidate_id, "status": "promoted", "authority": dict(authority), "evidenceIds": sorted(expected), "evidenceHashes": [_hash(row) for row in matching]})
            candidate["status"] = "promoted"; candidate["promotionId"] = receipt["recordId"]
            candidate["recordHash"] = _hash({k: v for k, v in candidate.items() if k != "recordHash"})
            atomic_write_json(self.base / f"{candidate['recordId']}.json", candidate)
            return receipt

    def _load(self, record_id: str) -> dict[str, Any]:
        path = self.base / f"{record_id}.json"
        path.resolve().relative_to(self.base.resolve())
        if not path.exists():
            raise KeyError(record_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def list(self, *, kind: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if kind is not None and kind not in {"comparison", "trace", "investigation", "candidate", "evaluation", "promotion", "note"}:
            raise ValueError("Unknown experience record kind")
        rows = []
        pattern = f"{kind}_*.json" if kind else "*.json"
        for path in sorted(self.base.glob(pattern), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if item.get("recordHash") != _hash({k: v for k, v in item.items() if k != "recordHash"}):
                continue
            if kind and item.get("kind") != kind:
                continue
            rows.append(item)
            if len(rows) >= max(1, min(int(limit), 500)):
                break
        return rows

    def snapshot(self, *, limit: int = 100) -> dict[str, Any]:
        rows = self.list(limit=limit)
        return {"schema": SCHEMA, "scope": self.scope, "records": rows, "recordCount": len(rows), "integrity": _hash(rows)}

    def note(self, *, lesson, conditions, invalidation, evidence):
        from .workspace_intelligence import WorkspaceIntelligence
        if not WorkspaceIntelligence(self.root, self.scope).collaboration()["preferences"]["learning"]:
            raise PermissionError("Reusable experience is not enabled for this work")
        for label, value in {"lesson": lesson, "conditions": conditions, "invalidation": invalidation}.items():
            if not isinstance(value, str) or not value.strip() or len(value) > 2000:
                raise ValueError(f"{label} requires 1 to 2000 characters")
        if not isinstance(evidence, list) or not 1 <= len(evidence) <= 8:
            raise ValueError("A note requires one to eight existing evidence artifacts")
        refs = []
        for value in evidence:
            if not isinstance(value, str):
                raise ValueError("Evidence references must be paths")
            path = (self.root / value).resolve()
            path.relative_to(self.root)
            if not path.is_file() or path.stat().st_size > 16_000_000:
                raise ValueError("Evidence must be an existing scoped artifact of at most 16 MB")
            if any(part in {".git", ".env", "credentials"} for part in path.parts) or any(word in path.name.lower() for word in ("credential", "password", "secret", "token")) or path.suffix.lower() in {".key", ".pem", ".dpapi"}:
                raise PermissionError("Protected files cannot be attached to a reusable note")
            refs.append({"path": path.relative_to(self.root).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        return self._record("note", {"lesson": lesson.strip(), "conditions": conditions.strip(),
            "invalidation": invalidation.strip(), "evidence": refs, "status": "proposed",
            "source": "agent_report", "authorityGranted": False})

    def relevant(self, query="", *, max_characters=3000, limit=5):
        if not isinstance(query, str) or len(query) > 20000:
            raise ValueError("Experience query must be at most 20000 characters")
        if type(max_characters) is not int or not 600 <= max_characters <= 12000:
            raise ValueError("Experience view budget must be 600 to 12000 characters")
        if type(limit) is not int or not 1 <= limit <= 20:
            raise ValueError("Experience limit must be one to twenty")
        tokens = set(re.findall(r"\w+", query.casefold()))
        candidates = self.list(kind="note", limit=200)
        def relevance(row):
            words = set(re.findall(r"\w+", (row.get("lesson", "") + " " + row.get("conditions", "")).casefold()))
            return len(tokens & words)
        ranked = sorted(candidates, key=relevance, reverse=True)
        result = {"scope": self.scope, "notes": [], "omittedCount": len(ranked),
                  "boundary": "Reported experience with checked artifact identities; applicability and diagnosis still need review",
                  "retrieval": {"tool": "experience.read", "workId": self.scope}}
        for row in ranked:
            if tokens and not relevance(row):
                continue
            evidence_current = True
            for item in row.get("evidence", []):
                path = (self.root / item["path"]).resolve()
                try:
                    path.relative_to(self.root)
                    matches = path.is_file() and path.stat().st_size <= 16_000_000 and hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
                except (OSError, ValueError):
                    matches = False
                evidence_current = evidence_current and matches
            summary = {key: row[key] for key in ("recordId", "recordHash", "lesson", "conditions", "invalidation", "createdAt")}
            summary.update(evidenceCurrent=evidence_current, status="proposed" if evidence_current else "stale",
                           retrievalPath=str(self.base / (row["recordId"] + ".json")))
            proposed = {**result, "notes": [*result["notes"], summary]}
            if len(json.dumps(proposed, ensure_ascii=False, separators=(",", ":"))) > max_characters:
                continue
            result["notes"].append(summary)
            if len(result["notes"]) >= limit:
                break
        result["omittedCount"] -= len(result["notes"])
        return result


__all__ = ["ExperienceStore", "SCHEMA", "TRACE_KINDS", "CANDIDATE_STATES"]
