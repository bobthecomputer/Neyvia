"""Durable spawned-agent contracts and receipts for Neyvia Native."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


SPAWN_SCHEMA = "neyvia.native-spawn-contract/v1"
SPAWN_RECEIPT_SCHEMA = "neyvia.native-spawn-receipt/v1"
_VALID_ROLES = {
    "planner",
    "executor",
    "verifier",
    "investigator",
    "researcher",
    "designer",
    "critic",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _hash(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _safe_role(value: object) -> str:
    normalized = re.sub(r"[^a-z]+", "-", str(value or "").strip().lower()).strip("-")
    if normalized not in _VALID_ROLES:
        raise ValueError(f"Unsupported Neyvia specialist role: {normalized or 'missing'}")
    return normalized


@dataclass(frozen=True)
class SpecialistRoute:
    role: str
    provider: str
    model: str
    effort: str
    maximum_turns: int
    allow_mutations: bool
    required_evidence: tuple[str, ...]

    @classmethod
    def from_mapping(
        cls,
        role: str,
        value: dict[str, Any],
        *,
        default_model: str,
        default_effort: str = "high",
    ) -> "SpecialistRoute":
        normalized_role = _safe_role(role)
        return cls(
            role=normalized_role,
            provider=str(value.get("provider") or "active-provider").strip(),
            model=str(value.get("model") or default_model).strip(),
            effort=str(value.get("effort") or default_effort).strip().lower(),
            maximum_turns=max(1, min(16, int(value.get("maximumTurns") or 5))),
            allow_mutations=bool(value.get("allowMutations", normalized_role == "executor")),
            required_evidence=tuple(
                str(item).strip()
                for item in value.get("requiredEvidence", ())
                if str(item).strip()
            ),
        )

    def public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["maximumTurns"] = value.pop("maximum_turns")
        value["allowMutations"] = value.pop("allow_mutations")
        value["requiredEvidence"] = list(value.pop("required_evidence"))
        return value


_ROLE_DEFAULTS: dict[str, dict[str, Any]] = {
    "planner": {
        "maximumTurns": 4,
        "allowMutations": False,
        "requiredEvidence": ["dependency-aware plan", "risks", "proof gates"],
    },
    "executor": {
        "maximumTurns": 8,
        "allowMutations": True,
        "requiredEvidence": ["workspace delta", "tool receipts"],
    },
    "verifier": {
        "maximumTurns": 5,
        "allowMutations": False,
        "requiredEvidence": ["independent evidence audit", "blocking findings"],
    },
    "investigator": {
        "maximumTurns": 6,
        "allowMutations": False,
        "requiredEvidence": ["reproduction", "cause candidates", "falsifiers"],
    },
    "researcher": {
        "maximumTurns": 7,
        "allowMutations": False,
        "requiredEvidence": ["source ledger", "contradictory evidence"],
    },
    "designer": {
        "maximumTurns": 7,
        "allowMutations": False,
        "requiredEvidence": ["visual thesis", "alternative compositions"],
    },
    "critic": {
        "maximumTurns": 6,
        "allowMutations": False,
        "requiredEvidence": ["rendered critique", "highest-leverage revision"],
    },
}


def build_specialist_routes(
    default_model: str,
    *,
    raw_overrides: object = None,
    behavior_plan: dict[str, Any] | None = None,
    resource_profile: dict[str, Any] | None = None,
) -> dict[str, SpecialistRoute]:
    overrides: dict[str, Any] = {}
    if isinstance(raw_overrides, str) and raw_overrides.strip():
        try:
            decoded = json.loads(raw_overrides)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid specialist route JSON: {exc}") from exc
        if isinstance(decoded, dict):
            overrides = decoded
    elif isinstance(raw_overrides, dict):
        overrides = raw_overrides
    capsule = (behavior_plan or {}).get("capsule") or {}
    requested_roles = [
        str(item) for item in capsule.get("specialistRoles", ("planner", "verifier"))
    ]
    limit = int((resource_profile or {}).get("specialistLimit") or len(requested_roles))
    requested_roles = requested_roles[: max(0, limit)]
    routes: dict[str, SpecialistRoute] = {}
    for role in requested_roles:
        normalized = _safe_role(role)
        merged = {**_ROLE_DEFAULTS[normalized], **(overrides.get(normalized) or {})}
        # Only an explicitly approved executor route may mutate. Every other specialist is read-only.
        if normalized != "executor":
            merged["allowMutations"] = False
        routes[normalized] = SpecialistRoute.from_mapping(
            normalized,
            merged,
            default_model=default_model,
            default_effort="high",
        )
    from .proofs_d_native import check_routes
    check_routes(routes, [_safe_role(role) for role in requested_roles], overrides)
    return routes


def specialist_instructions(route: SpecialistRoute, behavior_plan: dict[str, Any]) -> str:
    common = (
        "You are a bounded specialist spawned by Neyvia Native. The parent owns the user "
        "conversation, workspace authority, and completion claim. Return one concise result "
        "with explicit evidence and unresolved uncertainty. Never claim tools or mutations "
        "that you did not directly observe."
    )
    role_text = {
        "planner": "Produce a dependency-aware plan, risks, and executable proof gates. Do not execute.",
        "executor": "Implement only the assigned bounded task and return concrete changed paths and receipts.",
        "verifier": "Audit independently. A persuasive narrative cannot override a failed deterministic check.",
        "investigator": "Reproduce or falsify the suspected cause before recommending repair.",
        "researcher": "Prefer primary sources, preserve provenance, and seek contradictory evidence.",
        "designer": "Generate genuinely different compositions using the active design-taste contract.",
        "critic": "Judge the rendered result, name causal weaknesses, and reject generic visual polish.",
    }[route.role]
    return (
        f"{common} {role_text} Required evidence: {', '.join(route.required_evidence) or 'bounded result'}. "
        f"Parent behavior plan hash: {behavior_plan.get('planHash') or 'unknown'}."
    )


class NativeSpawnRegistry:
    def __init__(self, root: Path, parent_session_id: str) -> None:
        self.root = root.resolve()
        self.parent_session_id = parent_session_id
        self.state_root = self.root / ".agent_control" / "neyvia_agent"
        self.receipt_root = self.state_root / "spawn_receipts"
        self.receipt_root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.state_root / "spawned_agents.sqlite3"
        self.session_db_path = self.state_root / "sessions.sqlite3"
        self._initialize()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS spawn_contracts (
                    spawn_id TEXT PRIMARY KEY,
                    parent_session_id TEXT NOT NULL,
                    child_session_id TEXT NOT NULL UNIQUE,
                    role TEXT NOT NULL,
                    task TEXT NOT NULL,
                    model TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    effort TEXT NOT NULL,
                    maximum_turns INTEGER NOT NULL,
                    allow_mutations INTEGER NOT NULL,
                    plan_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    receipt_path TEXT,
                    output_hash TEXT,
                    error TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_spawn_parent
                    ON spawn_contracts(parent_session_id, created_at);
                """
            )

    def start(self, route: SpecialistRoute, task: str, plan_hash: str) -> dict[str, Any]:
        spawn_id = f"spawn_{uuid.uuid4().hex}"
        child_session_id = f"{self.parent_session_id}.{route.role}.{uuid.uuid4().hex[:10]}"
        created = _utc_now()
        contract = {
            "schema": SPAWN_SCHEMA,
            "spawnId": spawn_id,
            "parentSessionId": self.parent_session_id,
            "childSessionId": child_session_id,
            "role": route.role,
            "task": str(task or "").strip(),
            "route": route.public_dict(),
            "planHash": plan_hash,
            "status": "running",
            "createdAt": created,
            "startedAt": created,
        }
        contract["contractHash"] = _hash(contract)
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO spawn_contracts(
                    spawn_id, parent_session_id, child_session_id, role, task,
                    model, provider, effort, maximum_turns, allow_mutations,
                    plan_hash, status, created_at, started_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    spawn_id,
                    self.parent_session_id,
                    child_session_id,
                    route.role,
                    contract["task"],
                    route.model,
                    route.provider,
                    route.effort,
                    route.maximum_turns,
                    int(route.allow_mutations),
                    plan_hash,
                    "running",
                    created,
                    created,
                ),
            )
            from .proofs_d_native import check_spawn
            check_spawn(connection, contract)
        return contract

    def finish(
        self,
        contract: dict[str, Any],
        *,
        status: str,
        output: str = "",
        usage: dict[str, Any] | None = None,
        run_items: list[str] | None = None,
        error: str = "",
    ) -> dict[str, Any]:
        normalized_status = status if status in {"completed", "failed", "blocked", "cancelled"} else "failed"
        output_text = str(output or "")
        finished = _utc_now()
        receipt = {
            **contract,
            "schema": SPAWN_RECEIPT_SCHEMA,
            "status": normalized_status,
            "finishedAt": finished,
            "output": output_text,
            "outputHash": hashlib.sha256(output_text.encode("utf-8")).hexdigest(),
            "usage": dict(usage or {}),
            "runItems": list(run_items or []),
            "error": str(error or "")[-4000:],
            "verifiedContract": bool(contract.get("contractHash")),
        }
        receipt["receiptHash"] = _hash({key: value for key, value in receipt.items() if key != "receiptHash"})
        path = self.receipt_root / f"{contract['spawnId']}.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
        with self.connection() as connection:
            connection.execute(
                """
                UPDATE spawn_contracts
                SET status = ?, finished_at = ?, receipt_path = ?, output_hash = ?, error = ?
                WHERE spawn_id = ?
                """,
                (
                    normalized_status,
                    finished,
                    str(path),
                    receipt["outputHash"],
                    receipt["error"],
                    contract["spawnId"],
                ),
            )
            from .proofs_d_native import check_spawn
            check_spawn(connection, contract, receipt, path)
        return {**receipt, "receiptPath": str(path)}

    def snapshot(self) -> dict[str, Any]:
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM spawn_contracts
                WHERE parent_session_id = ?
                ORDER BY created_at ASC
                """,
                (self.parent_session_id,),
            ).fetchall()
        children = []
        for row in rows:
            item = dict(row)
            item["allow_mutations"] = bool(item["allow_mutations"])
            children.append(item)
        return {
            "schema": "neyvia.native-spawn-tree/v1",
            "parentSessionId": self.parent_session_id,
            "children": children,
            "counts": {
                "total": len(children),
                "running": sum(1 for item in children if item["status"] == "running"),
                "completed": sum(1 for item in children if item["status"] == "completed"),
                "failed": sum(1 for item in children if item["status"] in {"failed", "blocked"}),
            },
        }
