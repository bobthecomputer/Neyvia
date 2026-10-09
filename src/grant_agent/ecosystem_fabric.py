from __future__ import annotations

from .proofs_b_engine import checked as _proofs_b_checked

import hashlib
import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse

from .communication_archive import inspect_communication_archive
from .proofs_a_cli import checked

COMMUNICATION_ROUTES = {
    "delegated-oauth",
    "imap-smtp",
    "jmap",
    "outlook-bridge",
    "thunderbird-bridge",
    "file-import",
    "forward-ingestion",
}
COMMUNICATION_STATES = {
    "connected",
    "limited",
    "approval-required",
    "blocked-by-organization",
    "credentials-missing",
    "not-configured",
}
COMMUNICATION_PERMISSIONS = {
    "read",
    "draft",
    "send",
    "forward",
    "delete",
    "unsubscribe",
}
PER_ACTION_COMMUNICATION_PERMISSIONS = {"send", "delete", "unsubscribe"}
EXPERIMENT_TIERS = {"observe", "simulate", "act"}
PROMPT_PROFILES = {
    "implementation": "Implement the requested change within the supplied scope and return concrete artifacts.",
    "diagnosis": "Diagnose the cause first. Do not modify anything unless the task explicitly authorizes a fix.",
    "research": "Separate sourced facts, uncertainty, and interpretation. Preserve source lineage.",
    "writing": "Optimize for a coherent finished document while preserving the author's intent and voice.",
    "image-generation": "Translate the visual intent into composition, subject, lighting, materials, camera, and exclusions.",
    "explanation": "Explain at the user's level, expose assumptions, and prefer a clear mental model.",
}
SECRET_PATTERNS = (
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("openai-style-key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")),
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    (
        "credential-assignment",
        re.compile(
            r"(?i)\b(?:api[_-]?key|access[_-]?token|password|client[_-]?secret)"
            r"\s*[:=]\s*[\"']?[^\s,\"']{8,}"
        ),
    ),
)
WINDOWS_PATH = re.compile(r"\b[A-Za-z]:\\(?:[^\\\r\n]+\\)*[^\\\r\n]*")
POSIX_HOME_PATH = re.compile(r"(?<!\w)/(?:home|Users)/[^/\s]+(?:/[^\s,;]+)*")
EMAIL_ADDRESS = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
SENSITIVE_CONFIGURATION_KEYS = {
    "password",
    "secret",
    "token",
    "accessToken",
    "refreshToken",
    "clientSecret",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _decode(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _redacted_preview(value: str, *, limit: int = 96) -> str:
    compact = " ".join(str(value or "").split())
    return compact[:limit] + ("…" if len(compact) > limit else "")


class NeyviaEcosystemFabric:
    """Durable local contracts for the expanded Neyvia ecosystem.

    External sends, provider logins, device actions, and public publishing are
    deliberately not performed here. This service records truthful readiness,
    user-reviewed handoffs, approval requirements, evidence, and lineage.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        database_path: str | Path | None = None,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.database_path = (
            Path(database_path).expanduser().resolve()
            if database_path
            else self.root / ".agent_control" / "ecosystem.sqlite3"
        )
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA busy_timeout=30000")
        try:
            yield connection
        finally:
            connection.close()

    def _ensure_schema(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS communication_accounts (
                    account_id TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    address_hint TEXT NOT NULL DEFAULT '',
                    route TEXT NOT NULL,
                    state TEXT NOT NULL,
                    limitation TEXT NOT NULL DEFAULT '',
                    credential_ref TEXT NOT NULL DEFAULT '',
                    organization TEXT NOT NULL DEFAULT '',
                    permissions_json TEXT NOT NULL DEFAULT '[]',
                    configuration_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS presentation_captures (
                    capture_id TEXT PRIMARY KEY,
                    direction TEXT NOT NULL,
                    project_id TEXT NOT NULL DEFAULT '',
                    conversation_id TEXT NOT NULL DEFAULT '',
                    mission_id TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    content_json TEXT NOT NULL,
                    lineage_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS experiments (
                    experiment_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    hypothesis TEXT NOT NULL,
                    baseline_json TEXT NOT NULL DEFAULT '{}',
                    variants_json TEXT NOT NULL DEFAULT '[]',
                    lifetime_json TEXT NOT NULL DEFAULT '{}',
                    authorization_context TEXT NOT NULL DEFAULT '',
                    state TEXT NOT NULL DEFAULT 'active',
                    verdict TEXT NOT NULL DEFAULT '',
                    journal_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS benchmark_runs (
                    run_id TEXT PRIMARY KEY,
                    task_contract_json TEXT NOT NULL,
                    budget_json TEXT NOT NULL,
                    subjects_json TEXT NOT NULL,
                    results_json TEXT NOT NULL DEFAULT '[]',
                    claim_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS communication_imports (
                    import_id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    archive_format TEXT NOT NULL,
                    source_digest TEXT NOT NULL,
                    summary_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            connection.commit()

    @_proofs_b_checked("proofs-b.engine.account")
    def register_communication_account(self, payload: dict[str, Any]) -> dict[str, Any]:
        route = str(payload.get("route") or "").strip().casefold()
        state = str(payload.get("state") or "not-configured").strip().casefold()
        if route not in COMMUNICATION_ROUTES:
            raise ValueError(f"unsupported communication route: {route}")
        if state not in COMMUNICATION_STATES:
            raise ValueError(f"unsupported communication state: {state}")
        permissions = sorted(
            {
                str(item).strip().casefold()
                for item in payload.get("permissions") or []
                if str(item).strip()
            }
        )
        unknown_permissions = set(permissions) - COMMUNICATION_PERMISSIONS
        if unknown_permissions:
            raise ValueError(
                "unsupported communication permissions: "
                + ", ".join(sorted(unknown_permissions))
            )
        configuration = dict(payload.get("configuration") or {})
        forbidden = SENSITIVE_CONFIGURATION_KEYS.intersection(configuration)
        if forbidden:
            raise ValueError(
                "Credentials must be stored by the secret broker and referenced by credentialRef; "
                "remove: " + ", ".join(sorted(forbidden))
            )
        credential_ref = str(payload.get("credentialRef") or "").strip()
        if state == "connected" and route not in {"file-import", "forward-ingestion"}:
            if not credential_ref:
                raise ValueError("Connected provider accounts require credentialRef")
        account_id = str(payload.get("accountId") or "").strip() or _id("account")
        timestamp = utc_now()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO communication_accounts (
                    account_id, label, address_hint, route, state, limitation,
                    credential_ref, organization, permissions_json,
                    configuration_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id) DO UPDATE SET
                    label = excluded.label,
                    address_hint = excluded.address_hint,
                    route = excluded.route,
                    state = excluded.state,
                    limitation = excluded.limitation,
                    credential_ref = excluded.credential_ref,
                    organization = excluded.organization,
                    permissions_json = excluded.permissions_json,
                    configuration_json = excluded.configuration_json,
                    updated_at = excluded.updated_at
                """,
                (
                    account_id,
                    str(payload.get("label") or "Communication account").strip(),
                    str(payload.get("addressHint") or "").strip(),
                    route,
                    state,
                    str(payload.get("limitation") or "").strip(),
                    credential_ref,
                    str(payload.get("organization") or "").strip(),
                    _json(permissions),
                    _json(configuration),
                    timestamp,
                    timestamp,
                ),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM communication_accounts WHERE account_id = ?",
                (account_id,),
            ).fetchone()
        return self._communication_account(row)

    def communication_snapshot(self) -> dict[str, Any]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM communication_accounts ORDER BY label, account_id"
            ).fetchall()
            imports = connection.execute(
                """
                SELECT import_id, account_id, source_path, archive_format,
                       source_digest, summary_json, created_at
                FROM communication_imports
                ORDER BY created_at DESC, import_id
                LIMIT 100
                """
            ).fetchall()
        return {
            "schema": "neyvia.communication-fabric.v1",
            "generatedAt": utc_now(),
            "accounts": [self._communication_account(row) for row in rows],
            "imports": [
                {
                    "importId": row["import_id"],
                    "accountId": row["account_id"],
                    "sourcePath": row["source_path"],
                    "format": row["archive_format"],
                    "sourceDigest": row["source_digest"],
                    "summary": _decode(row["summary_json"], {}),
                    "createdAt": row["created_at"],
                }
                for row in imports
            ],
            "permissionLadder": [
                {
                    "permission": permission,
                    "approval": (
                        "per-action"
                        if permission in PER_ACTION_COMMUNICATION_PERMISSIONS
                        else "per-account"
                    ),
                }
                for permission in (
                    "read",
                    "draft",
                    "send",
                    "forward",
                    "delete",
                    "unsubscribe",
                )
            ],
        }

    def inspect_communication_archive(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("userInitiated") is not True:
            raise ValueError("Archive inspection must be explicitly user-initiated")
        source_path = str(payload.get("sourcePath") or "").strip()
        if not source_path:
            raise ValueError("sourcePath is required")
        return inspect_communication_archive(
            source_path,
            limit=int(payload.get("limit") or 100),
        )

    @checked('a-cli.archive.import')
    def import_communication_archive(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("userInitiated") is not True:
            raise ValueError("Archive import must be explicitly user-initiated")
        account_id = str(payload.get("accountId") or "").strip()
        if not account_id:
            raise ValueError("accountId is required")
        with self._connection() as connection:
            account = connection.execute(
                "SELECT route FROM communication_accounts WHERE account_id = ?",
                (account_id,),
            ).fetchone()
        if not account:
            raise KeyError(account_id)
        if account["route"] not in {
            "file-import",
            "outlook-bridge",
            "thunderbird-bridge",
        }:
            raise ValueError("Selected account route does not accept local archives")
        inspection = self.inspect_communication_archive(payload)
        if inspection["status"] != "ready":
            raise RuntimeError(
                "; ".join(inspection["limitations"])
                or "Archive is not ready to import"
            )
        import_id = _id("mailimport")
        timestamp = utc_now()
        summary = {
            "messageCount": inspection["messageCount"],
            "attachmentCount": inspection["attachmentCount"],
            "truncated": inspection["truncated"],
            "limitations": inspection["limitations"],
            "messages": inspection["messages"],
        }
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO communication_imports
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    import_id,
                    account_id,
                    inspection["sourcePath"],
                    inspection["format"],
                    inspection["sourceDigest"],
                    _json(summary),
                    timestamp,
                ),
            )
            connection.commit()
        return {
            "schema": "neyvia.communication-archive-import.v1",
            "importId": import_id,
            "accountId": account_id,
            "sourcePath": inspection["sourcePath"],
            "format": inspection["format"],
            "sourceDigest": inspection["sourceDigest"],
            "summary": summary,
            "state": "imported-local",
            "createdAt": timestamp,
        }

    @_proofs_b_checked("proofs-b.engine.presentation")
    def compile_presentation_prompt(self, payload: dict[str, Any]) -> dict[str, Any]:
        profile = str(payload.get("profile") or "explanation").strip().casefold()
        if profile not in PROMPT_PROFILES:
            raise ValueError(f"unknown prompt profile: {profile}")
        user_prompt = str(payload.get("prompt") or "").strip()
        if not user_prompt:
            raise ValueError("prompt is required")
        context = dict(payload.get("context") or {})
        additions = [
            {"kind": "profile", "text": PROMPT_PROFILES[profile]},
            {
                "kind": "lineage",
                "text": (
                    "Treat the following as user-reviewed Neyvia context. "
                    "Do not imply access to anything outside it."
                ),
            },
        ]
        if context:
            additions.append(
                {
                    "kind": "context",
                    "text": json.dumps(context, indent=2, ensure_ascii=False),
                }
            )
        compiled = "\n\n".join(
            [user_prompt, *[str(item["text"]) for item in additions]]
        )
        return {
            "schema": "neyvia.presentation-prompt.v1",
            "surface": "chatgpt.com",
            "profile": profile,
            "original": user_prompt,
            "compiled": compiled,
            "additions": additions,
            "requiresExplicitInsert": True,
            "automatedLogin": False,
            "transcriptHarvesting": False,
        }

    @_proofs_b_checked("proofs-b.engine.capture")
    def capture_presentation_content(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("userInitiated") is not True:
            raise ValueError("Presentation capture must be explicitly user-initiated")
        source = str(payload.get("source") or "").strip()
        parsed = urlparse(source)
        if parsed.scheme not in {"https", "file"}:
            raise ValueError("Capture source must be an HTTPS URL or explicit file export")
        content = payload.get("content")
        if content in (None, "", [], {}):
            raise ValueError("captured content is required")
        encoded = _json(content)
        capture_id = _id("capture")
        timestamp = utc_now()
        lineage = {
            "userInitiated": True,
            "capturedAt": timestamp,
            "source": source,
            "destination": {
                "projectId": str(payload.get("projectId") or ""),
                "conversationId": str(payload.get("conversationId") or ""),
                "missionId": str(payload.get("missionId") or ""),
            },
        }
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO presentation_captures VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    capture_id,
                    str(payload.get("direction") or "chatgpt-to-neyvia"),
                    lineage["destination"]["projectId"],
                    lineage["destination"]["conversationId"],
                    lineage["destination"]["missionId"],
                    source,
                    hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
                    encoded,
                    _json(lineage),
                    timestamp,
                ),
            )
            connection.commit()
        return {
            "schema": "neyvia.presentation-capture.v1",
            "captureId": capture_id,
            "contentSha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
            "lineage": lineage,
        }

    def scan_share_capsule(self, payload: dict[str, Any]) -> dict[str, Any]:
        selected = dict(payload.get("content") or {})
        findings: list[dict[str, Any]] = []
        for location, text in self._walk_strings(selected):
            for kind, pattern in SECRET_PATTERNS:
                for match in pattern.finditer(text):
                    findings.append(
                        self._finding(kind, "blocker", location, match.group(0))
                    )
            for match in WINDOWS_PATH.finditer(text):
                findings.append(
                    self._finding("personal-filesystem-path", "warning", location, match.group(0))
                )
            for match in POSIX_HOME_PATH.finditer(text):
                findings.append(
                    self._finding("personal-filesystem-path", "warning", location, match.group(0))
                )
            for match in EMAIL_ADDRESS.finditer(text):
                findings.append(
                    self._finding("private-account-identifier", "warning", location, match.group(0))
                )
        deduplicated = {
            (item["kind"], item["location"], item["fingerprint"]): item
            for item in findings
        }
        rows = list(deduplicated.values())
        return {
            "schema": "neyvia.share-capsule-scan.v1",
            "generatedAt": utc_now(),
            "findings": rows,
            "blocked": any(item["severity"] == "blocker" for item in rows),
            "checks": [
                "secrets-and-credentials",
                "personal-filesystem-paths",
                "organization-material-declarations",
                "private-account-identifiers",
                "hidden-metadata-declarations",
            ],
        }

    @_proofs_b_checked("proofs-b.engine.capsule")
    def build_share_capsule(self, payload: dict[str, Any]) -> dict[str, Any]:
        content = dict(payload.get("content") or {})
        scan = self.scan_share_capsule({"content": content})
        resolved = {
            str(item)
            for item in payload.get("resolvedFindingIds") or []
            if str(item)
        }
        unresolved = [
            item
            for item in scan["findings"]
            if item["severity"] == "blocker" and item["findingId"] not in resolved
        ]
        if unresolved:
            raise RuntimeError(
                "Share Capsule is blocked by unresolved secret findings"
            )
        capsule_id = _id("capsule")
        record = {
            "schema": "neyvia.share-capsule.v1",
            "capsuleId": capsule_id,
            "createdAt": utc_now(),
            "mode": str(payload.get("mode") or "standard-export"),
            "selection": list(payload.get("selection") or ["result"]),
            "content": content,
            "inspection": {
                **scan,
                "resolvedFindingIds": sorted(resolved),
            },
            "transportState": "prepared-not-sent",
            "requiresExplicitShare": True,
        }
        target = self.root / ".agent_control" / "share_capsules" / f"{capsule_id}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(record, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        temporary.replace(target)
        return {**record, "recordPath": str(target)}

    def create_experiment(self, payload: dict[str, Any]) -> dict[str, Any]:
        title = str(payload.get("title") or "").strip()
        hypothesis = str(payload.get("hypothesis") or "").strip()
        if not title or not hypothesis:
            raise ValueError("Experiment title and hypothesis are required")
        experiment_id = _id("experiment")
        timestamp = utc_now()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO experiments VALUES (?, ?, ?, ?, ?, ?, ?, 'active', '', '[]', ?, ?)
                """,
                (
                    experiment_id,
                    title,
                    hypothesis,
                    _json(dict(payload.get("baseline") or {})),
                    _json(list(payload.get("variants") or [])),
                    _json(dict(payload.get("lifetime") or {})),
                    str(payload.get("authorizationContext") or "").strip(),
                    timestamp,
                    timestamp,
                ),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM experiments WHERE experiment_id = ?",
                (experiment_id,),
            ).fetchone()
        return self._experiment(row)

    def experiment_snapshot(self) -> dict[str, Any]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM experiments ORDER BY updated_at DESC, experiment_id"
            ).fetchall()
        return {
            "schema": "neyvia.experimental-systems.v1",
            "generatedAt": utc_now(),
            "experiments": [self._experiment(row) for row in rows],
        }

    def record_experiment_observation(self, payload: dict[str, Any]) -> dict[str, Any]:
        experiment_id = str(payload.get("experimentId") or "").strip()
        observation = str(payload.get("observation") or "").strip()
        if not experiment_id or not observation:
            raise ValueError("experimentId and observation are required")
        timestamp = utc_now()
        with self._connection() as connection:
            # Acquire the writer before reading the journal being extended.
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM experiments WHERE experiment_id = ?",
                (experiment_id,),
            ).fetchone()
            if not row:
                raise KeyError(experiment_id)
            journal = list(_decode(row["journal_json"], []))
            journal.append(
                {
                    "observation": observation,
                    "kind": str(payload.get("kind") or "measurement").strip(),
                    "evidence": dict(payload.get("evidence") or {}),
                    "recordedAt": timestamp,
                }
            )
            connection.execute(
                """
                UPDATE experiments
                SET journal_json = ?, updated_at = ?
                WHERE experiment_id = ?
                """,
                (_json(journal), timestamp, experiment_id),
            )
            connection.commit()
            updated = connection.execute(
                "SELECT * FROM experiments WHERE experiment_id = ?",
                (experiment_id,),
            ).fetchone()
        return self._experiment(updated)

    def conclude_experiment(self, payload: dict[str, Any]) -> dict[str, Any]:
        experiment_id = str(payload.get("experimentId") or "").strip()
        verdict = str(payload.get("verdict") or "").strip()
        if not experiment_id or not verdict:
            raise ValueError("experimentId and verdict are required")
        timestamp = utc_now()
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM experiments WHERE experiment_id = ?",
                (experiment_id,),
            ).fetchone()
            if not row:
                raise KeyError(experiment_id)
            connection.execute(
                """
                UPDATE experiments
                SET state = 'concluded', verdict = ?, updated_at = ?
                WHERE experiment_id = ?
                """,
                (verdict, timestamp, experiment_id),
            )
            connection.commit()
            updated = connection.execute(
                "SELECT * FROM experiments WHERE experiment_id = ?",
                (experiment_id,),
            ).fetchone()
        return self._experiment(updated)

    @_proofs_b_checked("proofs-b.engine.authorization")
    def plan_experiment_action(self, payload: dict[str, Any]) -> dict[str, Any]:
        experiment_id = str(payload.get("experimentId") or "").strip()
        tier = str(payload.get("tier") or "").strip().casefold()
        if tier not in EXPERIMENT_TIERS:
            raise ValueError(f"unknown experiment action tier: {tier}")
        target = str(payload.get("target") or "").strip()
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM experiments WHERE experiment_id = ?",
                (experiment_id,),
            ).fetchone()
        if not row:
            raise KeyError(experiment_id)
        authorization = str(row["authorization_context"] or "").strip()
        if tier == "act" and (not target or not authorization):
            raise ValueError(
                "Act-tier operations require a named target and authorization context"
            )
        return {
            "schema": "neyvia.experiment-action-plan.v1",
            "experimentId": experiment_id,
            "tier": tier,
            "target": target or None,
            "simulated": tier == "simulate",
            "executable": False,
            "approval": "per-action" if tier == "act" else "session",
            "authorizationContextRecorded": bool(authorization),
            "state": "approval-required" if tier == "act" else "planned",
        }

    def create_benchmark_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        subjects = list(payload.get("subjects") or [])
        budget = dict(payload.get("budget") or {})
        task_contract = dict(payload.get("taskContract") or {})
        if len(subjects) < 2:
            raise ValueError("A benchmark comparison requires at least two subjects")
        if not budget or not task_contract:
            raise ValueError("Comparable taskContract and budget are required")
        run_id = _id("benchmark")
        timestamp = utc_now()
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO benchmark_runs VALUES (?, ?, ?, ?, '[]', '{}', ?, ?)",
                (
                    run_id,
                    _json(task_contract),
                    _json(budget),
                    _json(subjects),
                    timestamp,
                    timestamp,
                ),
            )
            connection.commit()
        return self.get_benchmark_run(run_id)

    def record_benchmark_result(
        self,
        run_id: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM benchmark_runs WHERE run_id = ?",
                (str(run_id or "").strip(),),
            ).fetchone()
            if not row:
                raise KeyError(run_id)
            results = list(_decode(row["results_json"], []))
            normalized = dict(result or {})
            normalized.setdefault("recordedAt", utc_now())
            results.append(normalized)
            claim = self._benchmark_claim(
                list(_decode(row["subjects_json"], [])),
                dict(_decode(row["budget_json"], {})),
                results,
            )
            timestamp = utc_now()
            connection.execute(
                """
                UPDATE benchmark_runs
                SET results_json = ?, claim_json = ?, updated_at = ?
                WHERE run_id = ?
                """,
                (_json(results), _json(claim), timestamp, run_id),
            )
            connection.commit()
        return self.get_benchmark_run(run_id)

    def get_benchmark_run(self, run_id: str) -> dict[str, Any]:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM benchmark_runs WHERE run_id = ?",
                (str(run_id or "").strip(),),
            ).fetchone()
        if not row:
            raise KeyError(run_id)
        return {
            "schema": "neyvia.deep-benchmark-run.v1",
            "runId": row["run_id"],
            "taskContract": _decode(row["task_contract_json"], {}),
            "budget": _decode(row["budget_json"], {}),
            "subjects": _decode(row["subjects_json"], []),
            "results": _decode(row["results_json"], []),
            "claim": _decode(row["claim_json"], {}),
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    def benchmark_snapshot(self) -> dict[str, Any]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT run_id FROM benchmark_runs ORDER BY updated_at DESC, run_id"
            ).fetchall()
        return {
            "schema": "neyvia.deep-benchmark-lab.v1",
            "generatedAt": utc_now(),
            "runs": [self.get_benchmark_run(row["run_id"]) for row in rows],
        }

    @staticmethod
    @_proofs_b_checked("proofs-b.engine.benchmark")
    def _benchmark_claim(
        subjects: list[Any],
        budget: dict[str, Any],
        results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        result_by_subject = {
            str(item.get("subjectId") or ""): item
            for item in results
            if isinstance(item, dict) and item.get("subjectId")
        }
        exclusions = []
        for subject in subjects:
            subject_id = str(
                subject.get("subjectId") if isinstance(subject, dict) else subject
            )
            result = result_by_subject.get(subject_id)
            if not result:
                exclusions.append({"subjectId": subject_id, "reason": "not-reported"})
                continue
            if result.get("budgetExceeded") is True:
                exclusions.append({"subjectId": subject_id, "reason": "budget-exceeded"})
            if result.get("comparableContext") is False:
                exclusions.append({"subjectId": subject_id, "reason": "context-not-comparable"})
        return {
            "eligible": not exclusions and len(result_by_subject) == len(subjects),
            "equalBudget": budget,
            "exclusions": exclusions,
            "measuredFacts": results,
            "interpretation": "not-reported",
        }

    @staticmethod
    def _communication_account(row: sqlite3.Row) -> dict[str, Any]:
        permissions = list(_decode(row["permissions_json"], []))
        return {
            "accountId": row["account_id"],
            "label": row["label"],
            "addressHint": row["address_hint"],
            "route": row["route"],
            "state": row["state"],
            "limitation": row["limitation"] or None,
            "credentialRef": row["credential_ref"] or None,
            "organization": row["organization"] or None,
            "permissions": permissions,
            "perActionApprovals": sorted(
                set(permissions) & PER_ACTION_COMMUNICATION_PERMISSIONS
            ),
            "configuration": _decode(row["configuration_json"], {}),
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    @staticmethod
    @_proofs_b_checked("proofs-b.engine.experiment")
    def _experiment(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "schema": "neyvia.experimental-system.v1",
            "experimentId": row["experiment_id"],
            "title": row["title"],
            "hypothesis": row["hypothesis"],
            "baseline": _decode(row["baseline_json"], {}),
            "variants": _decode(row["variants_json"], []),
            "lifetime": _decode(row["lifetime_json"], {}),
            "authorizationContextRecorded": bool(row["authorization_context"]),
            "state": row["state"],
            "verdict": row["verdict"] or None,
            "journal": _decode(row["journal_json"], []),
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    @staticmethod
    def _walk_strings(value: Any, location: str = "content") -> Iterator[tuple[str, str]]:
        if isinstance(value, str):
            yield location, value
        elif isinstance(value, dict):
            for key, item in value.items():
                yield from NeyviaEcosystemFabric._walk_strings(
                    item,
                    f"{location}.{key}",
                )
        elif isinstance(value, list):
            for index, item in enumerate(value):
                yield from NeyviaEcosystemFabric._walk_strings(
                    item,
                    f"{location}[{index}]",
                )

    @staticmethod
    def _finding(
        kind: str,
        severity: str,
        location: str,
        evidence: str,
    ) -> dict[str, Any]:
        fingerprint = hashlib.sha256(evidence.encode("utf-8")).hexdigest()[:16]
        return {
            "findingId": f"finding_{fingerprint}",
            "kind": kind,
            "severity": severity,
            "location": location,
            "fingerprint": fingerprint,
            "preview": _redacted_preview(evidence[:4] + "…" + evidence[-4:]),
        }
