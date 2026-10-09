from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import secrets
import signal
import socket
import sqlite3
import subprocess
import threading
import time
import uuid
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .models import utc_now_iso
from .subprocess_utils import hidden_windows_subprocess_kwargs
from .proofs_a_cli import checked
from .proofs_a_cli_scheduler import check_load, check_lease, check_stale, check_expired

CLUSTER_SCHEMA_VERSION = "fluxio.cluster_registry.v4"
DEFAULT_LEASE_TTL_SECONDS = 90
DEFAULT_HOST_STALE_SECONDS = 120
DEFAULT_PROCESS_STALE_SECONDS = 5 * 60
DEFAULT_PROCESS_TTL_SECONDS = 60 * 60
PROCESS_ACTIVE_STATUSES = {"registered", "launching", "running"}
RUNTIME_DETECTION_CACHE_SECONDS = 60.0
PROVIDER_AUTH_COOLDOWN_SECONDS = 300
PROVIDER_CREDIT_COOLDOWN_SECONDS = 300
PROVIDER_RATE_LIMIT_DEFAULT_COOLDOWN_SECONDS = 60
PROVIDER_RATE_LIMIT_MIN_COOLDOWN_SECONDS = 5
PROVIDER_RATE_LIMIT_MAX_COOLDOWN_SECONDS = 900
PROVIDER_TRANSIENT_FAILURE_THRESHOLD = 3
PROVIDER_TRANSIENT_DEFAULT_COOLDOWN_SECONDS = 60
PROVIDER_TRANSIENT_MAX_COOLDOWN_SECONDS = 300
PROVIDER_PROBE_INCONCLUSIVE_COOLDOWN_SECONDS = 60
_RUNTIME_DETECTION_CACHE: dict[tuple[str, str], tuple[float, list[str]]] = {}
_RUNTIME_DETECTION_LOCK = threading.Lock()
NAS_EXECUTION_POLICY_DEFAULT = "efficient"
NAS_EXECUTION_POLICIES = {"control_only", "disabled", "efficient", "unrestricted"}
DEFAULT_CLUSTER_HOSTS = (
    {
        "host_id": "ASUS-ROG-STRIX",
        "label": "ASUS ROG Strix",
        "host_type": "workstation",
        "role": "primary_worker",
        "tailscale_ip": "192.0.2.10",
        "os_name": "windows",
        "max_concurrent_jobs": 0,
    },
    {
        "host_id": "nas.example.invalid",
        "label": "Synology NAS",
        "host_type": "nas_control",
        "role": "controller_storage",
        "tailscale_ip": "192.0.2.10",
        "os_name": "linux",
        "max_concurrent_jobs": 0,
    },
    {
        "host_id": "ZENPAUL",
        "label": "ZENPAUL",
        "host_type": "workstation",
        "role": "opportunistic_worker",
        "tailscale_ip": "192.0.2.10",
        "os_name": "windows",
        "max_concurrent_jobs": 0,
    },
    {
        "host_id": "ASUSPSDLB",
        "label": "ASUSPSDLB",
        "host_type": "workstation",
        "role": "opportunistic_worker",
        "tailscale_ip": "192.0.2.10",
        "os_name": "windows",
        "max_concurrent_jobs": 0,
    },
)


class _ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        result = super().__exit__(exc_type, exc, traceback)
        self.close()
        return bool(result)


@dataclass
class WorkerCapabilities:
    host_id: str
    label: str = ""
    host_type: str = "workstation"
    role: str = "worker"
    tailscale_ip: str = ""
    os_name: str = ""
    runtimes: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    workspace_mappings: dict[str, str] = field(default_factory=dict)
    # Zero means that NEYVIA does not impose an application-level ceiling.
    max_concurrent_jobs: int = 0
    current_load: int = 0
    cpu_percent: float = 0.0
    memory_percent: float = 0.0


def current_host_id() -> str:
    configured = str(os.environ.get("FLUXIO_HOST_ID") or "").strip()
    if configured:
        return configured
    return (socket.gethostname() or platform.node() or "unknown-host").strip()


def current_host_type(root: Path | None = None) -> str:
    host = current_host_id().lower()
    root_text = str(root or "").replace("\\", "/").lower()
    if "nas.example.invalid" in host or root_text.startswith("/volume1/") or "/volume1/" in root_text:
        return "nas_control"
    return "workstation"


def nas_execution_policy() -> str:
    raw = str(os.environ.get("FLUXIO_NAS_EXECUTION_POLICY") or "").strip().lower()
    if not raw and "FLUXIO_ALLOW_NAS_RUNTIME_FALLBACK" in os.environ:
        return "efficient" if _truthy(os.environ.get("FLUXIO_ALLOW_NAS_RUNTIME_FALLBACK")) else "control_only"
    aliases = {
        "": NAS_EXECUTION_POLICY_DEFAULT,
        "control": "control_only",
        "controller": "control_only",
        "controller_only": "control_only",
        "off": "disabled",
        "false": "disabled",
        "0": "disabled",
        "full": "unrestricted",
        "true": "efficient",
        "1": "efficient",
        "yes": "efficient",
    }
    policy = aliases.get(raw, raw)
    return policy if policy in NAS_EXECUTION_POLICIES else NAS_EXECUTION_POLICY_DEFAULT


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


def _json_loads(value: object, fallback: Any) -> Any:
    if value in {None, ""}:
        return fallback
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return fallback


def _normalize_host_id(value: object) -> str:
    text = str(value or "").strip()
    return text or current_host_id()


def _normalize_provider(value: object) -> str:
    return str(value or "").strip().lower()


def _normalize_runtime_id(value: object) -> str:
    return str(value or "").strip().lower()


def _redact_provider_circuit_text(value: object, *, limit: int) -> str:
    """Keep operator evidence useful without persisting credential material."""
    text = re.sub(r"\s+", " ", str(value or "").strip())
    text = re.sub(
        r"(?i)\b(bearer)\s+[^\s,;]+",
        r"\1 <redacted>",
        text,
    )
    text = re.sub(
        r"(?i)\b(token|api[_ -]?key|authorization|credential|password|secret)\s*[:=]\s*[^\s,;]+",
        r"\1=<redacted>",
        text,
    )
    text = re.sub(
        r"(?i)\b(?:sk|sess|pat|ghp|github_pat)-?[A-Za-z0-9_\-]{8,}\b",
        "<redacted>",
        text,
    )
    return text[: max(0, int(limit))]


def _job_target_provider(job: dict[str, Any]) -> str:
    payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
    route = payload.get("route") if isinstance(payload.get("route"), dict) else {}
    return _normalize_provider(
        job.get("targetProvider")
        or payload.get("targetProvider")
        or payload.get("target_provider")
        or route.get("provider")
        or payload.get("provider")
    )


def _job_target_model(job: dict[str, Any]) -> str:
    payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
    route = payload.get("route") if isinstance(payload.get("route"), dict) else {}
    return str(
        job.get("targetModel")
        or payload.get("targetModel")
        or payload.get("target_model")
        or route.get("model")
        or payload.get("model")
        or ""
    ).strip()


def _provider_route_key(job: dict[str, Any], host_id: str) -> tuple[str, str, str] | None:
    runtime_id = _normalize_runtime_id(job.get("runtimeId"))
    provider = _job_target_provider(job)
    if not runtime_id or not provider:
        return None
    return (_normalize_host_id(host_id), runtime_id, provider)


def _result_text(result: dict[str, Any]) -> str:
    return "\n".join(
        str(result.get(key) or "")
        for key in ("detail", "error", "message", "stdout", "stderr", "providerError")
    ).strip()


def _result_status_code(result: dict[str, Any], text: str) -> int:
    for key in ("statusCode", "status_code", "httpStatus", "http_status", "providerStatusCode"):
        try:
            value = int(result.get(key))
        except (TypeError, ValueError):
            continue
        if 100 <= value <= 599:
            return value
    match = re.search(r"\b(?:HTTP\s*)?(401|402|403|429|5\d\d)\b", text, flags=re.IGNORECASE)
    return int(match.group(1)) if match else 0


def _result_retry_after(result: dict[str, Any], text: str) -> int:
    for key in ("retryAfterSeconds", "retry_after_seconds", "retryAfter", "retry_after"):
        try:
            value = int(float(result.get(key)))
        except (TypeError, ValueError):
            continue
        return max(PROVIDER_RATE_LIMIT_MIN_COOLDOWN_SECONDS, min(PROVIDER_RATE_LIMIT_MAX_COOLDOWN_SECONDS, value))
    match = re.search(r"retry[- ]after\s*[:=]\s*(\d+)", text, flags=re.IGNORECASE)
    if match:
        return max(
            PROVIDER_RATE_LIMIT_MIN_COOLDOWN_SECONDS,
            min(PROVIDER_RATE_LIMIT_MAX_COOLDOWN_SECONDS, int(match.group(1))),
        )
    return PROVIDER_RATE_LIMIT_DEFAULT_COOLDOWN_SECONDS


def classify_provider_result(job: dict[str, Any], result: dict[str, Any] | None) -> dict[str, Any]:
    """Classify provider failures without retaining raw command output."""
    payload = result if isinstance(result, dict) else {}
    text = _result_text(payload)
    status_code = _result_status_code(payload, text)
    auth_context = bool(
        re.search(
            r"auth(?:entication|orization)?|token|credential|api[ _-]?key|oauth|unauthori[sz]ed|forbidden",
            text,
            flags=re.IGNORECASE,
        )
    )
    credit_context = bool(
        re.search(
            r"insufficient[_ -]?(?:credit|quota|balance|funds)|"
            r"(?:credit|quota|balance|funds).*(?:exhausted|exceeded|depleted)|"
            r"payment required|billing (?:limit|hard limit)",
            text,
            flags=re.IGNORECASE,
        )
    )
    provider = _job_target_provider(job)
    model = _job_target_model(job)
    base = {
        "provider": provider,
        "model": model,
        "statusCode": status_code,
        "retryAfterSeconds": 0,
        "context": "",
    }
    if not provider:
        base.update({"kind": "none", "providerFailure": False})
        return base
    return_code = payload.get("returnCode", payload.get("return_code"))
    status = str(payload.get("status") or "").strip().lower()
    explicit_success = (
        payload.get("ok") is True
        or (
            status in {"completed", "success", "succeeded"}
            and (return_code in (None, "") or str(return_code) == "0")
        )
    )
    if explicit_success:
        base.update({"kind": "success", "providerFailure": False, "success": True, "context": "explicit_success"})
        return base
    if status_code in {401, 403} and auth_context:
        base.update(
            {
                "kind": "auth",
                "providerFailure": True,
                "context": "http_status_with_credential_context",
                "retryAfterSeconds": PROVIDER_AUTH_COOLDOWN_SECONDS,
            }
        )
        return base
    if status_code == 402 or credit_context:
        base.update(
            {
                "kind": "credit",
                "providerFailure": True,
                "context": "provider_credit_or_quota_exhausted",
                "retryAfterSeconds": PROVIDER_CREDIT_COOLDOWN_SECONDS,
            }
        )
        return base
    if status_code == 429:
        base.update(
            {
                "kind": "rate_limit",
                "providerFailure": True,
                "context": "http_429",
                "retryAfterSeconds": _result_retry_after(payload, text),
            }
        )
        return base
    if 500 <= status_code <= 599:
        base.update(
            {"kind": "provider_overload", "providerFailure": True, "context": "http_5xx"}
        )
        return base
    failure_type = str(
        payload.get("failureKind") or payload.get("failure_kind") or payload.get("errorType") or payload.get("error_type") or ""
    ).strip().lower()
    if failure_type in {"timeout", "timed_out", "connection", "connection_error", "transport"}:
        base.update({"kind": "provider_transport", "providerFailure": True, "context": failure_type})
        return base
    if re.search(r"timed?\s*out|timeout|connection\s+(?:reset|refused|closed|error)", text, flags=re.IGNORECASE):
        base.update({"kind": "provider_transport", "providerFailure": True, "context": "transport_error"})
        return base
    base.update({"kind": "none", "providerFailure": False})
    return base


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@checked('a-cli.scheduler.root')
def resolve_cluster_root(root: str | Path, *, use_configured_root: bool = True) -> Path:
    """Resolve the one scheduler root shared by mission workspaces and workers."""
    requested = Path(root).expanduser().resolve()
    if not use_configured_root:
        return requested
    for env_name in ("FLUXIO_CLUSTER_ROOT", "FLUXIO_CONTROL_PROJECT_ROOT"):
        configured = str(os.environ.get(env_name) or "").strip()
        if configured:
            return Path(configured).expanduser().resolve()
    return requested


class ClusterRegistry:
    def __init__(self, root: str | Path, *, use_configured_root: bool = True) -> None:
        self.requested_root = Path(root).expanduser().resolve()
        self.root = resolve_cluster_root(
            self.requested_root,
            use_configured_root=use_configured_root,
        )
        self.control_dir = self.root / ".agent_control"
        self.control_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.control_dir / "cluster_registry.sqlite3"
        self._ensure_schema()
        self.seed_default_hosts()

    @contextmanager
    def connection_scope(self):
        """Keep WAL open across a worker lifetime, without holding a transaction.

        Each mutation still commits independently. Keeping an idle reader
        avoids SQLite checkpointing/syncing the WAL on every last close.
        """
        connection = self._connect()
        try:
            connection.execute("SELECT host_id FROM hosts LIMIT 1").fetchone()
            yield self
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(self.db_path),
            timeout=30,
            factory=_ClosingConnection,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _ensure_schema(self) -> None:
        with self._connect() as db:
            try:
                marker = db.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
            except sqlite3.OperationalError as error:
                if 'no such table' not in str(error):
                    raise
                marker = None
            if marker is not None and marker[0] == CLUSTER_SCHEMA_VERSION:
                # Older v4 stores may still need the additive job migrations.
                columns = {row["name"] for row in db.execute("PRAGMA table_info(jobs)")}
                if {"dedupe_key", "target_provider", "target_model"} <= columns:
                    return
            db.executescript(
                """
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS hosts (
                    host_id TEXT PRIMARY KEY,
                    label TEXT NOT NULL DEFAULT '',
                    host_type TEXT NOT NULL DEFAULT 'workstation',
                    role TEXT NOT NULL DEFAULT 'worker',
                    tailscale_ip TEXT NOT NULL DEFAULT '',
                    os_name TEXT NOT NULL DEFAULT '',
                    online INTEGER NOT NULL DEFAULT 0,
                    capabilities_json TEXT NOT NULL DEFAULT '[]',
                    runtimes_json TEXT NOT NULL DEFAULT '[]',
                    workspace_mappings_json TEXT NOT NULL DEFAULT '{}',
                    max_concurrent_jobs INTEGER NOT NULL DEFAULT 0,
                    current_load INTEGER NOT NULL DEFAULT 0,
                    cpu_percent REAL NOT NULL DEFAULT 0,
                    memory_percent REAL NOT NULL DEFAULT 0,
                    last_heartbeat_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    dedupe_key TEXT NOT NULL DEFAULT '',
                    mission_id TEXT NOT NULL DEFAULT '',
                    workspace_id TEXT NOT NULL DEFAULT '',
                    lane_role TEXT NOT NULL DEFAULT '',
                    runtime_id TEXT NOT NULL DEFAULT '',
                    target_provider TEXT NOT NULL DEFAULT '',
                    target_model TEXT NOT NULL DEFAULT '',
                    job_kind TEXT NOT NULL DEFAULT 'runtime_lane',
                    status TEXT NOT NULL DEFAULT 'queued',
                    preferred_host TEXT NOT NULL DEFAULT '',
                    assigned_host TEXT NOT NULL DEFAULT '',
                    lease_id TEXT NOT NULL DEFAULT '',
                    required_capabilities_json TEXT NOT NULL DEFAULT '[]',
                    planned_file_scope_json TEXT NOT NULL DEFAULT '[]',
                    required_artifacts_json TEXT NOT NULL DEFAULT '[]',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    status_detail TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    completed_at TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS leases (
                    lease_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    host_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    heartbeat_at TEXT NOT NULL DEFAULT '',
                    expires_at TEXT NOT NULL DEFAULT '',
                    process_id INTEGER NOT NULL DEFAULT 0,
                    cancel_reason TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL DEFAULT '',
                    lease_id TEXT NOT NULL DEFAULT '',
                    host_id TEXT NOT NULL DEFAULT '',
                    kind TEXT NOT NULL,
                    message TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL DEFAULT '',
                    lease_id TEXT NOT NULL DEFAULT '',
                    host_id TEXT NOT NULL DEFAULT '',
                    kind TEXT NOT NULL DEFAULT 'artifact',
                    path TEXT NOT NULL DEFAULT '',
                    url TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS managed_processes (
                    process_key TEXT PRIMARY KEY,
                    process_id INTEGER NOT NULL DEFAULT 0,
                    parent_process_id INTEGER NOT NULL DEFAULT 0,
                    host_id TEXT NOT NULL DEFAULT '',
                    job_id TEXT NOT NULL DEFAULT '',
                    lease_id TEXT NOT NULL DEFAULT '',
                    mission_id TEXT NOT NULL DEFAULT '',
                    kind TEXT NOT NULL DEFAULT 'process',
                    command TEXT NOT NULL DEFAULT '',
                    cwd TEXT NOT NULL DEFAULT '',
                    port INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'registered',
                    heartbeat_at TEXT NOT NULL DEFAULT '',
                    started_at TEXT NOT NULL DEFAULT '',
                    expires_at TEXT NOT NULL DEFAULT '',
                    completed_at TEXT NOT NULL DEFAULT '',
                    termination_reason TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS provider_circuits (
                    host_id TEXT NOT NULL,
                    runtime_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'closed',
                    failure_count INTEGER NOT NULL DEFAULT 0,
                    opened_at TEXT NOT NULL DEFAULT '',
                    retry_after TEXT NOT NULL DEFAULT '',
                    last_failure_at TEXT NOT NULL DEFAULT '',
                    last_failure_kind TEXT NOT NULL DEFAULT '',
                    last_failure_code INTEGER NOT NULL DEFAULT 0,
                    last_failure_context TEXT NOT NULL DEFAULT '',
                    last_retry_after_seconds INTEGER NOT NULL DEFAULT 0,
                    probe_job_id TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (host_id, runtime_id, provider)
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
                CREATE INDEX IF NOT EXISTS idx_jobs_mission ON jobs(mission_id);
                CREATE INDEX IF NOT EXISTS idx_leases_job_status ON leases(job_id, status);
                CREATE INDEX IF NOT EXISTS idx_events_job ON events(job_id);
                CREATE INDEX IF NOT EXISTS idx_managed_processes_status ON managed_processes(status);
                CREATE INDEX IF NOT EXISTS idx_managed_processes_job ON managed_processes(job_id);
                CREATE INDEX IF NOT EXISTS idx_provider_circuits_state ON provider_circuits(state, retry_after);
                """
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            job_columns = {
                str(row["name"])
                for row in db.execute("PRAGMA table_info(jobs)").fetchall()
            }
            if "dedupe_key" not in job_columns:
                db.execute(
                    "ALTER TABLE jobs ADD COLUMN dedupe_key TEXT NOT NULL DEFAULT ''"
                )
            if "target_provider" not in job_columns:
                db.execute(
                    "ALTER TABLE jobs ADD COLUMN target_provider TEXT NOT NULL DEFAULT ''"
                )
            if "target_model" not in job_columns:
                db.execute(
                    "ALTER TABLE jobs ADD COLUMN target_model TEXT NOT NULL DEFAULT ''"
                )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_dedupe ON jobs(dedupe_key)"
            )
            db.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_active_dedupe
                ON jobs(dedupe_key)
                WHERE dedupe_key <> ''
                  AND status IN ('queued', 'leased', 'running')
                """
            )
            db.execute(
                "INSERT INTO meta(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value "
                "WHERE meta.value IS NOT excluded.value",
                ("schema", CLUSTER_SCHEMA_VERSION),
            )

    def seed_default_hosts(self) -> None:
        now = utc_now_iso()
        with self._connect() as db:
            existing = {row[0] for row in db.execute("SELECT host_id FROM hosts")}
            for host in DEFAULT_CLUSTER_HOSTS:
                if host["host_id"] in existing:
                    continue
                db.execute(
                    """
                    INSERT INTO hosts (
                        host_id, label, host_type, role, tailscale_ip, os_name,
                        online, capabilities_json, runtimes_json,
                        workspace_mappings_json, max_concurrent_jobs, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, 0, '[]', '[]', '{}', ?, ?)
                    ON CONFLICT(host_id) DO NOTHING
                    """,
                    (
                        host["host_id"],
                        host["label"],
                        host["host_type"],
                        host["role"],
                        host["tailscale_ip"],
                        host["os_name"],
                        int(host["max_concurrent_jobs"]),
                        now,
                    ),
                )

    def ensure_worker_token(self) -> str:
        token_path = self.control_dir / "cluster_worker_token.txt"
        env_token = str(os.environ.get("FLUXIO_CLUSTER_WORKER_TOKEN") or "").strip()
        if env_token:
            return env_token
        if token_path.exists():
            token = token_path.read_text(encoding="utf-8").strip()
            if token:
                return token
        token = secrets.token_urlsafe(32)
        token_path.write_text(token + "\n", encoding="utf-8")
        try:
            os.chmod(token_path, 0o600)
        except OSError:
            pass
        return token

    def verify_worker_token(self, authorization: str) -> bool:
        token = self.ensure_worker_token()
        candidate = str(authorization or "").strip()
        if candidate.lower().startswith("bearer "):
            candidate = candidate[7:].strip()
        return bool(candidate) and secrets.compare_digest(_sha256(candidate), _sha256(token))

    def heartbeat_host(self, payload: dict[str, Any], *, db=None) -> dict[str, Any]:
        capabilities = _capabilities_from_payload(payload, self.root)
        now = utc_now_iso()
        with (self._connect() if db is None else nullcontext(db)) as db:
            db.execute(
                """
                INSERT INTO hosts (
                    host_id, label, host_type, role, tailscale_ip, os_name,
                    online, capabilities_json, runtimes_json,
                    workspace_mappings_json, max_concurrent_jobs, current_load,
                    cpu_percent, memory_percent, last_heartbeat_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(host_id) DO UPDATE SET
                    label=excluded.label,
                    host_type=excluded.host_type,
                    role=excluded.role,
                    tailscale_ip=excluded.tailscale_ip,
                    os_name=excluded.os_name,
                    online=1,
                    capabilities_json=excluded.capabilities_json,
                    runtimes_json=excluded.runtimes_json,
                    workspace_mappings_json=excluded.workspace_mappings_json,
                    max_concurrent_jobs=excluded.max_concurrent_jobs,
                    current_load=excluded.current_load,
                    cpu_percent=excluded.cpu_percent,
                    memory_percent=excluded.memory_percent,
                    last_heartbeat_at=excluded.last_heartbeat_at,
                    updated_at=excluded.updated_at
                """,
                (
                    capabilities.host_id,
                    capabilities.label or capabilities.host_id,
                    capabilities.host_type,
                    capabilities.role,
                    capabilities.tailscale_ip,
                    capabilities.os_name,
                    _json_dumps(capabilities.capabilities),
                    _json_dumps(capabilities.runtimes),
                    _json_dumps(capabilities.workspace_mappings),
                    normalize_concurrency_limit(capabilities.max_concurrent_jobs),
                    max(0, int(capabilities.current_load or 0)),
                    float(capabilities.cpu_percent or 0),
                    float(capabilities.memory_percent or 0),
                    now,
                    now,
                ),
            )
            self._refresh_host_load_db(db, capabilities.host_id)
            host = db.execute("SELECT * FROM hosts WHERE host_id = ?", (capabilities.host_id,)).fetchone()
        return {"ok": True, "host": _host_row_to_payload(host)}

    def get_host(self, host_id: str) -> dict[str, Any]:
        self.mark_stale_hosts()
        with self._connect() as db:
            row = db.execute("SELECT * FROM hosts WHERE host_id = ?", (host_id,)).fetchone()
        return _host_row_to_payload(row) if row else {}

    def list_hosts(self) -> list[dict[str, Any]]:
        self.mark_stale_hosts()
        with self._connect() as db:
            rows = db.execute("SELECT * FROM hosts ORDER BY host_type, host_id").fetchall()
        return [_host_row_to_payload(row) for row in rows]

    @staticmethod
    def _active_host_load_db(db: sqlite3.Connection, host_id: str) -> int:
        row = db.execute(
            """
            SELECT COUNT(*) AS active_count
            FROM leases
            JOIN jobs ON jobs.job_id = leases.job_id
            WHERE leases.host_id = ?
              AND leases.status = 'active'
              AND jobs.status IN ('leased', 'running')
            """,
            (host_id,),
        ).fetchone()
        return int(row["active_count"] if row else 0)

    def active_host_load(self, host_id: str) -> int:
        with self._connect() as db:
            return self._active_host_load_db(db, host_id)

    def _refresh_host_load_db(self, db: sqlite3.Connection, host_id: str) -> int:
        load = self._active_host_load_db(db, host_id)
        db.execute(
            "UPDATE hosts SET current_load = ?, updated_at = ? WHERE host_id = ?",
            (load, utc_now_iso(), host_id),
        )
        check_load(db, host_id, load)
        return load

    def mark_stale_hosts(self, stale_seconds: int = DEFAULT_HOST_STALE_SECONDS) -> int:
        cutoff = _utc_now() - timedelta(seconds=max(1, int(stale_seconds)))
        changed = 0
        with self._connect() as db:
            # A host becoming offline is one transition even when multiple
            # scheduler callers inspect stale heartbeats at the same time.
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                "SELECT host_id, online, last_heartbeat_at FROM hosts WHERE online = 1"
            ).fetchall()
            for row in rows:
                heartbeat = _parse_time(row["last_heartbeat_at"])
                if heartbeat is None or heartbeat < cutoff:
                    db.execute(
                        "UPDATE hosts SET online = 0, current_load = 0, updated_at = ? WHERE host_id = ?",
                        (utc_now_iso(), row["host_id"]),
                    )
                    changed += 1
                    check_stale(db, row['host_id'])
        return changed

    def expire_stale_leases(self, *, db=None) -> int:
        now = _utc_now()
        changed = 0
        affected_hosts: set[str] = set()
        own_transaction = db is None
        with (self._connect() if own_transaction else nullcontext(db)) as db:
            # Own the transition before observing active rows, so competing
            # expiry callers cannot count the same selected lease again.
            if own_transaction:
                db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                "SELECT lease_id, job_id, host_id, expires_at FROM leases WHERE status = 'active'"
            ).fetchall()
            for row in rows:
                expires_at = _parse_time(row["expires_at"])
                if expires_at is None or expires_at >= now:
                    continue
                db.execute(
                    """
                    UPDATE leases SET status = 'expired', cancel_reason = ?,
                        updated_at = ? WHERE lease_id = ?
                    """,
                    ("lease_heartbeat_expired", utc_now_iso(), row["lease_id"]),
                )
                db.execute(
                    """
                    UPDATE jobs SET status = 'queued', assigned_host = '',
                        lease_id = '', status_detail = ?, updated_at = ?
                    WHERE job_id = ? AND lease_id = ? AND status IN ('leased', 'running')
                    """,
                    (
                        "Worker lease expired; job returned to the queue.",
                        utc_now_iso(),
                        row["job_id"],
                        row["lease_id"],
                    ),
                )
                self._append_event_db(
                    db,
                    job_id=row["job_id"],
                    lease_id=row["lease_id"],
                    host_id="",
                    kind="lease.expired",
                    message="Worker lease expired; job was requeued.",
                    payload={},
                )
                affected_hosts.add(str(row["host_id"] or ""))
                check_expired(db, row['lease_id'], row['job_id'])
                changed += 1
            for host_id in affected_hosts:
                if host_id:
                    self._refresh_host_load_db(db, host_id)
        return changed

    @checked('a-cli.scheduler.job')
    def upsert_job(
        self,
        *,
        job_id: str = "",
        dedupe_key: str = "",
        mission_id: str = "",
        workspace_id: str = "",
        lane_role: str = "",
        runtime_id: str = "",
        target_provider: str = "",
        target_model: str = "",
        job_kind: str = "runtime_lane",
        preferred_host: str = "",
        required_capabilities: list[str] | None = None,
        planned_file_scope: list[str] | None = None,
        required_artifacts: list[str] | None = None,
        payload: dict[str, Any] | None = None,
        status: str = "queued",
        status_detail: str = "",
    ) -> dict[str, Any]:
        resolved_job_id = job_id or f"job_{uuid.uuid4().hex[:12]}"
        resolved_dedupe_key = str(dedupe_key or "").strip()
        now = utc_now_iso()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if resolved_dedupe_key:
                existing = db.execute(
                    """
                    SELECT * FROM jobs
                    WHERE dedupe_key = ? AND status IN ('queued', 'leased', 'running')
                    ORDER BY created_at ASC
                    LIMIT 1
                    """,
                    (resolved_dedupe_key,),
                ).fetchone()
                if existing is not None:
                    payload_result = _job_row_to_payload(existing)
                    payload_result["deduplicated"] = True
                    return payload_result
            db.execute(
                """
                INSERT INTO jobs (
                    job_id, dedupe_key, mission_id, workspace_id, lane_role, runtime_id,
                    target_provider, target_model, job_kind, status, preferred_host, required_capabilities_json,
                    planned_file_scope_json, required_artifacts_json, payload_json,
                    status_detail, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    dedupe_key=excluded.dedupe_key,
                    mission_id=excluded.mission_id,
                    workspace_id=excluded.workspace_id,
                    lane_role=excluded.lane_role,
                    runtime_id=excluded.runtime_id,
                    target_provider=excluded.target_provider,
                    target_model=excluded.target_model,
                    job_kind=excluded.job_kind,
                    preferred_host=excluded.preferred_host,
                    required_capabilities_json=excluded.required_capabilities_json,
                    planned_file_scope_json=excluded.planned_file_scope_json,
                    required_artifacts_json=excluded.required_artifacts_json,
                    payload_json=excluded.payload_json,
                    status_detail=excluded.status_detail,
                    updated_at=excluded.updated_at
                """,
                (
                    resolved_job_id,
                    resolved_dedupe_key,
                    mission_id,
                    workspace_id,
                    lane_role,
                    runtime_id,
                    _normalize_provider(target_provider),
                    str(target_model or "").strip(),
                    job_kind,
                    status,
                    preferred_host,
                    _json_dumps(required_capabilities or []),
                    _json_dumps(planned_file_scope or []),
                    _json_dumps(required_artifacts or []),
                    _json_dumps(payload or {}),
                    status_detail,
                    now,
                    now,
                ),
            )
            self._append_event_db(
                db,
                job_id=resolved_job_id,
                lease_id="",
                host_id="",
                kind="job.queued",
                message=status_detail or "Cluster job queued.",
                payload={
                    "missionId": mission_id,
                    "runtimeId": runtime_id,
                    "laneRole": lane_role,
                    "targetProvider": _normalize_provider(target_provider),
                    "targetModel": str(target_model or "").strip(),
                },
            )
        result = self.get_job(resolved_job_id)
        result["deduplicated"] = False
        return result

    def get_job(self, job_id: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        return _job_row_to_payload(row) if row else {}

    def list_jobs(self, *, limit: int = 100) -> list[dict[str, Any]]:
        self.expire_stale_leases()
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM jobs ORDER BY updated_at DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        return [_job_row_to_payload(row) for row in rows]

    @staticmethod
    def _ensure_provider_circuit_db(
        db: sqlite3.Connection,
        key: tuple[str, str, str],
    ) -> sqlite3.Row:
        db.execute(
            """
            INSERT INTO provider_circuits (host_id, runtime_id, provider, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(host_id, runtime_id, provider) DO NOTHING
            """,
            (*key, utc_now_iso()),
        )
        row = db.execute(
            """
            SELECT * FROM provider_circuits
            WHERE host_id = ? AND runtime_id = ? AND provider = ?
            """,
            key,
        ).fetchone()
        if row is None:
            raise RuntimeError("Provider circuit row could not be created.")
        return row

    def get_provider_circuit(
        self,
        *,
        host_id: str,
        runtime_id: str,
        provider: str,
    ) -> dict[str, Any]:
        key = (_normalize_host_id(host_id), _normalize_runtime_id(runtime_id), _normalize_provider(provider))
        if not key[1] or not key[2]:
            return {}
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM provider_circuits WHERE host_id = ? AND runtime_id = ? AND provider = ?",
                key,
            ).fetchone()
        return _provider_circuit_row_to_payload(row) if row else {
            "hostId": key[0],
            "runtimeId": key[1],
            "provider": key[2],
            "state": "closed",
            "failureCount": 0,
            "reason": "",
        }

    def list_provider_circuits(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM provider_circuits ORDER BY updated_at DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        return [_provider_circuit_row_to_payload(row) for row in rows]

    def reset_provider_circuit(
        self,
        *,
        host_id: str,
        runtime_id: str,
        provider: str,
        actor: str = "operator",
        reason: str = "Manual provider circuit reset.",
    ) -> dict[str, Any]:
        key = (_normalize_host_id(host_id), _normalize_runtime_id(runtime_id), _normalize_provider(provider))
        if not key[1] or not key[2]:
            return {"ok": False, "error": "runtime_and_provider_required"}
        now = utc_now_iso()
        safe_reason = _redact_provider_circuit_text(
            reason or "Manual provider circuit reset.",
            limit=240,
        )
        safe_actor = _redact_provider_circuit_text(actor or "operator", limit=120)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._ensure_provider_circuit_db(db, key)
            db.execute(
                """
                UPDATE provider_circuits SET state = 'half_open', failure_count = 0,
                    opened_at = ?, retry_after = ?, last_failure_kind = 'manual_reset',
                    last_failure_code = 0, last_failure_context = ?,
                    last_retry_after_seconds = 0, probe_job_id = '', updated_at = ?
                WHERE host_id = ? AND runtime_id = ? AND provider = ?
                """,
                (now, now, safe_reason, now, *key),
            )
            self._append_event_db(
                db,
                job_id="",
                lease_id="",
                host_id=key[0],
                kind="provider.circuit_manual_reset",
                message="Provider circuit manually reset to half-open for a canary.",
                payload={
                    "runtimeId": key[1],
                    "provider": key[2],
                    "actor": safe_actor,
                    "reason": safe_reason,
                    "state": "half_open",
                    "resetAt": now,
                },
            )
            row = db.execute(
                "SELECT * FROM provider_circuits WHERE host_id = ? AND runtime_id = ? AND provider = ?",
                key,
            ).fetchone()
            from .proofs_d_runtime_auth import check_circuit_reset
            check_circuit_reset(row, key, safe_actor, safe_reason)
        return {"ok": True, "circuit": _provider_circuit_row_to_payload(row)}

    def _provider_circuit_admission_db(
        self,
        db: sqlite3.Connection,
        job: dict[str, Any],
        host_id: str,
    ) -> dict[str, Any]:
        key = _provider_route_key(job, host_id)
        if key is None:
            return {"allowed": True, "probe": False}
        row = self._ensure_provider_circuit_db(db, key)
        state = str(row["state"] or "closed")
        job_id = str(job.get("jobId") or "")
        if state == "closed":
            return {"allowed": True, "probe": False, "circuit": _provider_circuit_row_to_payload(row)}
        if state == "half_open":
            probe_job_id = str(row["probe_job_id"] or "")
            if probe_job_id and probe_job_id != job_id:
                probe = db.execute(
                    """
                    SELECT jobs.status AS job_status, leases.status AS lease_status
                    FROM jobs LEFT JOIN leases ON leases.lease_id = jobs.lease_id
                    WHERE jobs.job_id = ?
                    """,
                    (probe_job_id,),
                ).fetchone()
                probe_active = bool(
                    probe
                    and str(probe["job_status"] or "") in {"leased", "running"}
                    and str(probe["lease_status"] or "") == "active"
                )
                if probe_active:
                    return {"allowed": False, "probe": False, "reason": "half_open_probe_in_flight"}
                db.execute(
                    """
                    UPDATE provider_circuits SET state = 'open', probe_job_id = '',
                        retry_after = ?, updated_at = ?
                    WHERE host_id = ? AND runtime_id = ? AND provider = ?
                    """,
                    (utc_now_iso(), utc_now_iso(), *key),
                )
                row = self._ensure_provider_circuit_db(db, key)
            if not probe_job_id or probe_job_id == job_id:
                if not probe_job_id:
                    now = utc_now_iso()
                    db.execute(
                        """
                        UPDATE provider_circuits SET probe_job_id = ?, updated_at = ?
                        WHERE host_id = ? AND runtime_id = ? AND provider = ?
                        """,
                        (job_id, now, *key),
                    )
                    row = self._ensure_provider_circuit_db(db, key)
                return {"allowed": True, "probe": True, "circuit": _provider_circuit_row_to_payload(row)}
            state = "open"
        if state == "open":
            retry_at = _parse_time(row["retry_after"])
            if retry_at is not None and retry_at > _utc_now():
                return {
                    "allowed": False,
                    "probe": False,
                    "reason": str(row["last_failure_kind"] or "provider_circuit_open"),
                    "circuit": _provider_circuit_row_to_payload(row),
                }
            now = utc_now_iso()
            db.execute(
                """
                UPDATE provider_circuits SET state = 'half_open', probe_job_id = ?, updated_at = ?
                WHERE host_id = ? AND runtime_id = ? AND provider = ?
                """,
                (job_id, now, *key),
            )
            self._append_event_db(
                db,
                job_id=job_id,
                lease_id="",
                host_id=key[0],
                kind="provider.circuit_half_open",
                message="Provider circuit admitted one cooldown canary probe.",
                payload={
                    "runtimeId": key[1],
                    "provider": key[2],
                    "jobId": job_id,
                    "previousReason": str(row["last_failure_kind"] or ""),
                    "retryAfter": str(row["retry_after"] or ""),
                },
            )
            updated_row = db.execute(
                "SELECT * FROM provider_circuits WHERE host_id = ? AND runtime_id = ? AND provider = ?",
                key,
            ).fetchone()
            return {"allowed": True, "probe": True, "circuit": _provider_circuit_row_to_payload(updated_row)}
        return {"allowed": False, "probe": False, "reason": "provider_circuit_unknown_state"}

    def record_provider_result(
        self,
        *,
        job: dict[str, Any],
        lease_id: str,
        host_id: str,
        result: dict[str, Any] | None,
    ) -> dict[str, Any]:
        classification = classify_provider_result(job, result)
        job_id = str(job.get("jobId") or "")
        now = utc_now_iso()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if lease_id:
                lease_row = db.execute(
                    """
                    SELECT leases.job_id, leases.host_id, leases.status,
                        jobs.status AS job_status
                    FROM leases JOIN jobs ON jobs.job_id = leases.job_id
                    WHERE leases.lease_id = ?
                    """,
                    (str(lease_id),),
                ).fetchone()
                if (
                    lease_row is None
                    or str(lease_row["job_id"] or "") != job_id
                    or not _same_host_id(lease_row["host_id"], host_id)
                    or str(lease_row["status"] or "") != "active"
                    or str(lease_row["job_status"] or "") not in {"leased", "running"}
                ):
                    return {
                        "ok": False,
                        "error": "provider_result_lease_mismatch",
                        "classification": classification,
                        "circuit": {},
                    }
                from .proofs_d_runtime_auth import check_circuit_reporting
                check_circuit_reporting(lease_row, job_id, host_id)
            key = _provider_route_key(job, host_id)
            if key is None:
                return {"ok": True, "classification": classification, "circuit": {}}
            row = self._ensure_provider_circuit_db(db, key)
            state = str(row["state"] or "closed")
            is_probe = state == "half_open" and str(row["probe_job_id"] or "") == job_id
            kind = str(classification.get("kind") or "none")
            provider_failure = bool(classification.get("providerFailure"))
            next_state = state
            failure_count = int(row["failure_count"] or 0)
            opened_at = str(row["opened_at"] or "")
            retry_after = str(row["retry_after"] or "")
            prior_kind = str(row["last_failure_kind"] or "")
            last_kind = prior_kind
            last_code = int(row["last_failure_code"] or 0)
            last_context = str(row["last_failure_context"] or "")
            last_failure_at = str(row["last_failure_at"] or "")
            last_retry_seconds = int(row["last_retry_after_seconds"] or 0)
            probe_job_id = str(row["probe_job_id"] or "")
            prior_opened_at = opened_at
            prior_retry_after = retry_after
            prior_last_kind = prior_kind
            prior_last_code = last_code
            prior_last_context = last_context
            prior_last_failure_at = last_failure_at
            prior_last_retry_seconds = last_retry_seconds

            if provider_failure:
                last_kind = kind
                last_code = int(classification.get("statusCode") or 0)
                last_context = str(classification.get("context") or "")[:120]
                last_failure_at = now
                last_retry_seconds = int(classification.get("retryAfterSeconds") or 0)
                if kind in {"auth", "credit"}:
                    failure_count = 1
                    next_state = "open"
                    opened_at = now
                    cooldown = (
                        PROVIDER_AUTH_COOLDOWN_SECONDS
                        if kind == "auth"
                        else PROVIDER_CREDIT_COOLDOWN_SECONDS
                    )
                    retry_after = (_utc_now() + timedelta(seconds=cooldown)).isoformat()
                elif kind == "rate_limit":
                    failure_count = max(1, failure_count)
                    next_state = "open"
                    opened_at = now
                    retry_after = (_utc_now() + timedelta(seconds=last_retry_seconds or PROVIDER_RATE_LIMIT_DEFAULT_COOLDOWN_SECONDS)).isoformat()
                elif kind == "provider_overload" or kind == "provider_transport":
                    failure_count = (
                        failure_count + 1
                        if prior_kind in {"provider_overload", "provider_transport"}
                        else 1
                    )
                    if is_probe:
                        failure_count = max(PROVIDER_TRANSIENT_FAILURE_THRESHOLD, failure_count)
                    if failure_count >= PROVIDER_TRANSIENT_FAILURE_THRESHOLD or is_probe:
                        next_state = "open"
                        opened_at = now
                        cooldown = min(
                            PROVIDER_TRANSIENT_MAX_COOLDOWN_SECONDS,
                            PROVIDER_TRANSIENT_DEFAULT_COOLDOWN_SECONDS
                            * (2 ** max(0, failure_count - PROVIDER_TRANSIENT_FAILURE_THRESHOLD)),
                        )
                        retry_after = (_utc_now() + timedelta(seconds=cooldown)).isoformat()
                        last_retry_seconds = cooldown
                    else:
                        next_state = "closed"
                        retry_after = ""
                probe_job_id = "" if is_probe else probe_job_id
            elif is_probe and bool(classification.get("success")):
                next_state = "closed"
                failure_count = 0
                opened_at = ""
                retry_after = ""
                last_kind = ""
                last_code = 0
                last_context = ""
                last_failure_at = ""
                last_retry_seconds = 0
                probe_job_id = ""
            elif is_probe:
                next_state = "open"
                failure_count = max(1, failure_count)
                opened_at = now
                retry_after = (_utc_now() + timedelta(seconds=PROVIDER_PROBE_INCONCLUSIVE_COOLDOWN_SECONDS)).isoformat()
                last_kind = "probe_inconclusive"
                last_code = 0
                last_context = "non_provider_probe_failure"
                last_failure_at = now
                last_retry_seconds = PROVIDER_PROBE_INCONCLUSIVE_COOLDOWN_SECONDS
                probe_job_id = ""
            elif state == "closed":
                failure_count = 0
                retry_after = ""
            if state == "open" and not is_probe:
                # A late in-flight result must not weaken an already-open
                # circuit. In particular, an auth cooldown cannot be erased
                # by a first transient failure from another job.
                next_state = "open"
                if prior_last_kind in {"auth", "credit"} and kind != prior_last_kind:
                    candidate_retry = _parse_time(retry_after)
                    existing_retry = _parse_time(prior_retry_after)
                    if candidate_retry and (existing_retry is None or candidate_retry > existing_retry):
                        last_retry_seconds = max(last_retry_seconds, int((candidate_retry - _utc_now()).total_seconds()))
                    else:
                        opened_at = prior_opened_at
                        retry_after = prior_retry_after
                        last_kind = prior_last_kind
                        last_code = prior_last_code
                        last_context = prior_last_context
                        last_failure_at = prior_last_failure_at
                        last_retry_seconds = prior_last_retry_seconds
                elif not retry_after:
                    opened_at = prior_opened_at
                    retry_after = prior_retry_after
            if not provider_failure and not is_probe and state == "half_open":
                next_state = "half_open"
            if provider_failure and not is_probe and state == "open" and next_state != "open":
                next_state = "open"
            if next_state == "closed" and not provider_failure:
                opened_at = ""
                retry_after = ""
                probe_job_id = ""
            db.execute(
                """
                UPDATE provider_circuits SET state = ?, failure_count = ?, opened_at = ?,
                    retry_after = ?, last_failure_at = ?, last_failure_kind = ?,
                    last_failure_code = ?, last_failure_context = ?,
                    last_retry_after_seconds = ?, probe_job_id = ?, updated_at = ?
                WHERE host_id = ? AND runtime_id = ? AND provider = ?
                """,
                (
                    next_state,
                    failure_count,
                    opened_at,
                    retry_after,
                    last_failure_at,
                    last_kind,
                    last_code,
                    last_context,
                    last_retry_seconds,
                    probe_job_id,
                    now,
                    *key,
                ),
            )
            if is_probe and not provider_failure and next_state == "closed":
                event_kind = "provider.circuit_closed"
                message = "Provider canary probe succeeded; circuit closed."
            elif provider_failure and next_state == "open":
                event_kind = "provider.circuit_opened"
                message = f"Provider circuit opened for {kind}."
            elif is_probe:
                event_kind = "provider.circuit_reopened"
                message = "Provider canary probe was inconclusive; circuit reopened briefly."
            else:
                event_kind = "provider.failure_recorded"
                message = f"Provider failure recorded ({kind}); circuit threshold not reached."
            self._append_event_db(
                db,
                job_id=job_id,
                lease_id=str(lease_id or ""),
                host_id=key[0],
                kind=event_kind,
                message=message,
                payload={
                    "runtimeId": key[1],
                    "provider": key[2],
                    "model": _job_target_model(job),
                    "state": next_state,
                    "failureKind": kind,
                    "statusCode": int(classification.get("statusCode") or 0),
                    "context": str(classification.get("context") or "")[:120],
                    "retryAfter": retry_after,
                    "retryAfterSeconds": last_retry_seconds,
                    "failureCount": failure_count,
                    "probe": is_probe,
                },
            )
            circuit_row = db.execute(
                "SELECT * FROM provider_circuits WHERE host_id = ? AND runtime_id = ? AND provider = ?",
                key,
            ).fetchone()
            from .proofs_d_runtime_auth import check_circuit_result
            check_circuit_result(row, circuit_row, classification, is_probe=is_probe, key=key)
        return {
            "ok": True,
            "classification": classification,
            "circuit": _provider_circuit_row_to_payload(circuit_row),
        }

    def assign_job(
        self,
        job_id: str,
        *,
        preferred_host: str = "",
        allow_remote: bool = False,
        allow_nas_fallback: bool = True,
        lease_ttl_seconds: int = DEFAULT_LEASE_TTL_SECONDS,
    ) -> dict[str, Any]:
        self.expire_stale_leases()
        job = self.get_job(job_id)
        if not job:
            return {"ok": False, "error": f"Unknown cluster job: {job_id}"}
        if str(job.get("status") or "") in {"leased", "running"} and job.get("leaseId"):
            lease = self.get_lease(str(job.get("leaseId") or ""))
            host = self.get_host(str(job.get("assignedHost") or ""))
            if lease and str(lease.get("status") or "") == "active":
                return {"ok": True, "host": host, "lease": lease, "job": job, "reused": True}
        if str(job.get("status") or "") not in {"queued", "leased", "running"}:
            return {"ok": False, "job": job, "error": "job_not_active"}
        conflict = self._active_scope_conflict(job)
        if conflict:
            detail = (
                "Waiting for active lease "
                f"{conflict.get('leaseId', '')} on overlapping workspace files."
            )
            self._mark_scope_waiting(job_id, detail=detail, conflict=conflict)
            return {"ok": False, "job": self.get_job(job_id), "error": "file_scope_conflict"}
        host = self.choose_host(
            job,
            preferred_host=preferred_host or job.get("preferredHost", ""),
            allow_remote=allow_remote,
            allow_nas_fallback=allow_nas_fallback,
        )
        if not host:
            blocked_circuits: list[dict[str, Any]] = []
            provider = _job_target_provider(job)
            if provider:
                for candidate in self.list_hosts():
                    if preferred_host and not _same_host_id(candidate.get("hostId"), preferred_host):
                        continue
                    if not allow_remote and not _same_host_id(candidate.get("hostId"), current_host_id()):
                        continue
                    circuit = self.get_provider_circuit(
                        host_id=str(candidate.get("hostId") or ""),
                        runtime_id=str(job.get("runtimeId") or ""),
                        provider=provider,
                    )
                    if str(circuit.get("state") or "closed") in {"open", "half_open"}:
                        blocked_circuits.append(circuit)
            if blocked_circuits:
                circuit = blocked_circuits[0]
                detail = (
                    f"Provider circuit for {provider} on {circuit.get('hostId')} is "
                    f"{circuit.get('state')}; retry after {circuit.get('retryAfter') or 'a canary window'}."
                )
                self.update_job_status(job_id, "queued", status_detail=detail)
                return {
                    "ok": False,
                    "job": self.get_job(job_id),
                    "error": "provider_circuit_open",
                    "circuit": circuit,
                }
            self.update_job_status(
                job_id,
                "queued",
                status_detail="No healthy worker can currently claim this job.",
            )
            return {"ok": False, "job": self.get_job(job_id), "error": "no_healthy_worker"}
        lease = self._create_lease(job_id, host["hostId"], lease_ttl_seconds=lease_ttl_seconds)
        if not lease:
            refreshed = self.get_job(job_id)
            existing_lease = self.get_lease(str(refreshed.get("leaseId") or ""))
            if existing_lease and str(existing_lease.get("status") or "") == "active":
                return {
                    "ok": True,
                    "host": self.get_host(str(existing_lease.get("hostId") or "")),
                    "lease": existing_lease,
                    "job": refreshed,
                    "reused": True,
                }
            circuit = self.get_provider_circuit(
                host_id=str(host.get("hostId") or ""),
                runtime_id=str(refreshed.get("runtimeId") or ""),
                provider=_job_target_provider(refreshed),
            )
            if str(circuit.get("state") or "closed") in {"open", "half_open"}:
                return {
                    "ok": False,
                    "job": refreshed,
                    "error": "provider_circuit_open",
                    "circuit": circuit,
                }
            return {"ok": False, "job": refreshed, "error": "job_not_queueable"}
        assigned_host = self.get_host(str(lease.get("hostId") or "")) or host
        return {"ok": True, "host": assigned_host, "lease": lease, "job": self.get_job(job_id)}

    @checked('a-cli.scheduler.choose')
    def choose_host(
        self,
        job: dict[str, Any],
        *,
        preferred_host: str = "",
        allow_remote: bool = False,
        allow_nas_fallback: bool = True,
        db: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        current = current_host_id()
        if db is not None:
            host_rows = db.execute("SELECT * FROM hosts ORDER BY host_type, host_id").fetchall()
            hosts = [_host_row_to_payload(row) for row in host_rows]
        else:
            hosts = self.list_hosts()
        job_runtime = str(job.get("runtimeId") or "").strip().lower()
        required = {str(item).strip().lower() for item in job.get("requiredCapabilities", []) if str(item).strip()}
        effective_allow_nas_fallback = bool(allow_nas_fallback) and _job_allows_nas_fallback(job)

        def compatible(host: dict[str, Any]) -> bool:
            if not host.get("online"):
                return False
            concurrency_limit = normalize_concurrency_limit(host.get("maxConcurrentJobs"))
            if concurrency_limit and int(host.get("currentLoad") or 0) >= concurrency_limit:
                return False
            runtimes = {str(item).strip().lower() for item in host.get("runtimes", [])}
            capabilities = {str(item).strip().lower() for item in host.get("capabilities", [])}
            if job_runtime and runtimes and job_runtime not in runtimes:
                return False
            if required and not required.issubset(capabilities | runtimes):
                return False
            if host.get("hostType") == "nas_control" and not effective_allow_nas_fallback:
                return False
            if not _same_host_id(host.get("hostId", ""), current) and not _host_has_workspace_locality(host, job):
                return False
            circuit_key = _provider_route_key(job, str(host.get("hostId") or ""))
            if circuit_key and db is not None:
                circuit_row = db.execute(
                    "SELECT * FROM provider_circuits WHERE host_id = ? AND runtime_id = ? AND provider = ?",
                    circuit_key,
                ).fetchone()
                circuit = _provider_circuit_row_to_payload(circuit_row) if circuit_row else {}
            elif circuit_key:
                circuit = self.get_provider_circuit(
                    host_id=circuit_key[0], runtime_id=circuit_key[1], provider=circuit_key[2]
                )
            else:
                circuit = {}
            if circuit and str(circuit.get("state") or "closed") == "open":
                retry_after = _parse_time(circuit.get("retryAfter"))
                if retry_after is not None and retry_after > _utc_now():
                    return False
            if circuit and str(circuit.get("state") or "closed") == "half_open":
                probe_job_id = str(circuit.get("probeJobId") or "")
                if probe_job_id and probe_job_id != str(job.get("jobId") or ""):
                    return False
            return True

        if preferred_host:
            preferred = next((host for host in hosts if host["hostId"] == preferred_host), None)
            if preferred and compatible(preferred):
                return preferred

        candidates = [host for host in hosts if compatible(host)]
        if not allow_remote:
            candidates = [
                host
                for host in candidates
                if _same_host_id(host.get("hostId", ""), current)
            ]
        if not candidates:
            return {}

        def score(host: dict[str, Any]) -> tuple[int, int, float, str]:
            host_type = str(host.get("hostType") or "")
            role = str(host.get("role") or "")
            workstation_bonus = 0 if host_type == "workstation" else 20
            primary_bonus = 0 if role == "primary_worker" else 5
            local_bonus = 0 if _same_host_id(host.get("hostId", ""), current) else 2
            return (
                workstation_bonus + primary_bonus + local_bonus,
                int(host.get("currentLoad") or 0),
                float(host.get("memoryPercent") or 0),
                str(host.get("hostId") or ""),
            )

        return sorted(candidates, key=score)[0]

    @checked('a-cli.scheduler.claim')
    def claim_next_job(
        self,
        host_payload: dict[str, Any],
        *,
        lease_ttl_seconds: int = DEFAULT_LEASE_TTL_SECONDS,
    ) -> dict[str, Any]:
        with self._connect() as db:
            # Publish the host, expired leases and new claim atomically. Separate
            # commits let startup bookkeeping compete with admission on slow IO.
            # Capacity and scope checks still run under the same writer lock.
            db.execute("BEGIN IMMEDIATE")
            host = self.heartbeat_host(host_payload, db=db)["host"]
            self.expire_stale_leases(db=db)
            active_load = self._refresh_host_load_db(db, host["hostId"])
            host = {**host, "currentLoad": active_load}
            concurrency_limit = normalize_concurrency_limit(host.get("maxConcurrentJobs"))
            if concurrency_limit and active_load >= concurrency_limit:
                return {"ok": True, "job": None, "lease": None, "host": host}

            rows = db.execute(
                """
                SELECT * FROM jobs
                WHERE status = 'queued'
                ORDER BY created_at ASC
                """
            ).fetchall()
            for row in rows:
                job = _job_row_to_payload(row)
                conflict = self._active_scope_conflict(job, db=db)
                if conflict:
                    self._mark_scope_waiting(
                        job["jobId"],
                        detail=(
                            "Waiting for another active worker lease on overlapping "
                            "workspace files."
                        ),
                        conflict=conflict,
                        db=db,
                    )
                    continue
                chosen = self.choose_host(
                    job,
                    preferred_host=job.get("preferredHost", ""),
                    allow_remote=True,
                    allow_nas_fallback=_job_allows_nas_fallback(job),
                    db=db,
                )
                if chosen.get("hostId") != host.get("hostId"):
                    continue
                admission = self._provider_circuit_admission_db(db, job, host["hostId"])
                if not admission.get("allowed"):
                    continue
                lease = self._create_lease(
                    job["jobId"],
                    host["hostId"],
                    lease_ttl_seconds=lease_ttl_seconds,
                    db=db,
                )
                # The lease belongs to this still-open transaction. A separate
                # reader sees the previous queued row until commit.
                claimed_row = db.execute("SELECT * FROM jobs WHERE job_id = ?", (job["jobId"],)).fetchone()
                return {"ok": True, "job": _job_row_to_payload(claimed_row), "lease": lease, "host": host}
        return {"ok": True, "job": None, "lease": None, "host": host}

    def _active_scope_conflict(
        self,
        job: dict[str, Any],
        *,
        db: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        planned_scope = _normalized_scope(job.get("plannedFileScope", []))
        if not planned_scope:
            return {}
        workspace_id = str(job.get("workspaceId") or "")
        job_id = str(job.get("jobId") or "")
        owns_db = db is None
        connection = db or self._connect()
        try:
            rows = connection.execute(
                """
                SELECT jobs.*, leases.lease_id AS active_lease_id
                FROM jobs
                JOIN leases ON leases.lease_id = jobs.lease_id
                WHERE jobs.status IN ('leased', 'running')
                    AND leases.status = 'active'
                    AND jobs.job_id != ?
                    AND jobs.workspace_id = ?
                """,
                (job_id, workspace_id),
            ).fetchall()
            for row in rows:
                other = _job_row_to_payload(row)
                other_scope = _normalized_scope(other.get("plannedFileScope", []))
                if _scopes_overlap(planned_scope, other_scope):
                    lease_id = str(row["active_lease_id"] or other.get("leaseId") or "")
                    return {
                        "jobId": other.get("jobId", ""),
                        "leaseId": lease_id,
                        "hostId": other.get("assignedHost", ""),
                        "plannedFileScope": other.get("plannedFileScope", []),
                    }
        finally:
            if owns_db:
                connection.close()
        return {}

    def _mark_scope_waiting(
        self,
        job_id: str,
        *,
        detail: str,
        conflict: dict[str, Any],
        db: sqlite3.Connection | None = None,
    ) -> None:
        owns_db = db is None
        connection = db or self._connect()
        try:
            now = utc_now_iso()
            connection.execute(
                """
                UPDATE jobs SET status = 'queued', status_detail = ?,
                    updated_at = ? WHERE job_id = ?
                """,
                (detail, now, job_id),
            )
            self._append_event_db(
                connection,
                job_id=job_id,
                lease_id="",
                host_id=str(conflict.get("hostId", "")),
                kind="job.waiting_for_file_scope",
                message=detail,
                payload={"conflict": conflict},
            )
            if owns_db:
                connection.commit()
        finally:
            if owns_db:
                connection.close()

    def heartbeat_lease(
        self,
        *,
        lease_id: str,
        host_id: str,
        process_id: int = 0,
        ttl_seconds: int = DEFAULT_LEASE_TTL_SECONDS,
        db=None,
    ) -> dict[str, Any]:
        now = utc_now_iso()
        expires_at = (_utc_now() + timedelta(seconds=max(1, int(ttl_seconds)))).isoformat()
        with (self._connect() if db is None else nullcontext(db)) as db:
            row = db.execute(
                """
                SELECT leases.*, jobs.lease_id AS job_lease_id,
                    jobs.status AS job_status
                FROM leases
                JOIN jobs ON jobs.job_id = leases.job_id
                WHERE leases.lease_id = ? AND leases.host_id = ?
                """,
                (lease_id, host_id),
            ).fetchone()
            if row is None:
                return {"ok": False, "error": "unknown_lease"}
            if (
                str(row["status"] or "") != "active"
                or str(row["job_lease_id"] or "") != lease_id
                or str(row["job_status"] or "") not in {"leased", "running"}
            ):
                return {
                    "ok": False,
                    "error": "inactive_lease",
                    "lease": self.get_lease(lease_id),
                    "job": self.get_job(row["job_id"]),
                }
            db.execute(
                """
                UPDATE leases SET heartbeat_at = ?, expires_at = ?,
                    process_id = ?, updated_at = ?
                WHERE lease_id = ?
                """,
                (now, expires_at, int(process_id or 0), now, lease_id),
            )
            db.execute(
                """
                UPDATE jobs SET status = 'running', updated_at = ?
                WHERE job_id = ? AND lease_id = ? AND status IN ('leased', 'running')
                """,
                (now, row["job_id"], lease_id),
            )
            self._refresh_host_load_db(db, host_id)
            refreshed_lease = db.execute("SELECT * FROM leases WHERE lease_id=?", (lease_id,)).fetchone()
            refreshed_job = db.execute("SELECT * FROM jobs WHERE job_id=?", (row["job_id"],)).fetchone()
        return {"ok": True, "lease": _lease_row_to_payload(refreshed_lease), "job": _job_row_to_payload(refreshed_job)}

    def complete_job(
        self,
        *,
        job_id: str,
        lease_id: str,
        host_id: str,
        status: str,
        detail: str = "",
        artifacts: list[dict[str, Any]] | None = None,
        changed_files: list[str] | None = None,
        result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized = str(status or "").strip().lower()
        if normalized not in {"completed", "failed", "blocked", "stopped"}:
            normalized = "failed"
        now = utc_now_iso()
        with self._connect() as db:
            # Serialize ownership validation with the terminal writes. An old
            # writer must not finish a job that a new lease already owns.
            db.execute("BEGIN IMMEDIATE")
            lease = db.execute(
                """SELECT leases.*, jobs.lease_id AS job_lease_id,
                    jobs.status AS job_status, jobs.assigned_host AS job_host_id
                FROM leases JOIN jobs ON jobs.job_id = leases.job_id
                WHERE leases.lease_id = ? AND leases.job_id = ?
                    AND leases.host_id = ?""",
                (lease_id, job_id, host_id),
            ).fetchone()
            if lease is None:
                return {"ok": False, "error": "unknown_lease"}
            expiry = _parse_time(lease["expires_at"])
            if (lease["status"] != "active" or lease["job_lease_id"] != lease_id
                    or lease["job_status"] not in {"leased", "running"}
                    or lease["job_host_id"] != host_id
                    or expiry is None or expiry <= _utc_now()):
                return {"ok": False, "error": "inactive_lease"}
            db.execute(
                """
                UPDATE leases SET status = ?, updated_at = ?
                WHERE lease_id = ?
                """,
                ("completed" if normalized == "completed" else normalized, now, lease_id),
            )
            db.execute(
                """
                UPDATE jobs SET status = ?, status_detail = ?, completed_at = ?,
                    updated_at = ? WHERE job_id = ?
                """,
                (normalized, detail, now, now, job_id),
            )
            self._refresh_host_load_db(db, host_id)
            payload = {
                "detail": detail,
                "changedFiles": changed_files or [],
                "result": result or {},
            }
            self._append_event_db(
                db,
                job_id=job_id,
                lease_id=lease_id,
                host_id=host_id,
                kind=f"job.{normalized}",
                message=detail or f"Cluster job {normalized}.",
                payload=payload,
            )
            for artifact in artifacts or []:
                artifact_id = str(artifact.get("artifactId") or artifact.get("artifact_id") or f"artifact_{uuid.uuid4().hex[:12]}")
                db.execute(
                    """
                    INSERT OR REPLACE INTO artifacts (
                        artifact_id, job_id, lease_id, host_id, kind, path, url,
                        metadata_json, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        artifact_id,
                        job_id,
                        lease_id,
                        host_id,
                        str(artifact.get("kind") or "artifact"),
                        str(artifact.get("path") or ""),
                        str(artifact.get("url") or ""),
                        _json_dumps(artifact.get("metadata") or {}),
                        now,
                    ),
                )
        return {"ok": True, "job": self.get_job(job_id), "lease": self.get_lease(lease_id)}

    def update_job_status(self, job_id: str, status: str, *, status_detail: str = "") -> dict[str, Any]:
        with self._connect() as db:
            db.execute(
                "UPDATE jobs SET status = ?, status_detail = ?, updated_at = ? WHERE job_id = ?",
                (status, status_detail, utc_now_iso(), job_id),
            )
        return self.get_job(job_id)

    def record_event(
        self,
        *,
        job_id: str,
        lease_id: str = "",
        host_id: str = "",
        kind: str,
        message: str = "",
        payload: dict[str, Any] | None = None,
        db=None,
    ) -> dict[str, Any]:
        with (self._connect() if db is None else nullcontext(db)) as db:
            self._append_event_db(
                db,
                job_id=job_id,
                lease_id=lease_id,
                host_id=host_id,
                kind=kind,
                message=message,
                payload=payload or {},
            )
        return {"ok": True}

    def register_process(
        self,
        *,
        process_id: int,
        parent_process_id: int = 0,
        host_id: str = "",
        job_id: str = "",
        lease_id: str = "",
        mission_id: str = "",
        kind: str = "process",
        command: str = "",
        cwd: str = "",
        port: int = 0,
        ttl_seconds: int = DEFAULT_PROCESS_TTL_SECONDS,
        metadata: dict[str, Any] | None = None,
        status: str = "running",
        db=None,
    ) -> dict[str, Any]:
        resolved_host = _normalize_host_id(host_id)
        resolved_pid = max(0, int(process_id or 0))
        process_key = _process_key(resolved_host, resolved_pid, job_id, lease_id, kind)
        now = utc_now_iso()
        expires_at = (
            (_utc_now() + timedelta(seconds=max(1, int(ttl_seconds)))).isoformat()
            if ttl_seconds > 0
            else ""
        )
        normalized_status = str(status or "registered").strip().lower() or "registered"
        with (self._connect() if db is None else nullcontext(db)) as db:
            db.execute(
                """
                INSERT INTO managed_processes (
                    process_key, process_id, parent_process_id, host_id, job_id,
                    lease_id, mission_id, kind, command, cwd, port, status,
                    heartbeat_at, started_at, expires_at, metadata_json, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(process_key) DO UPDATE SET
                    parent_process_id=excluded.parent_process_id,
                    host_id=excluded.host_id,
                    job_id=excluded.job_id,
                    lease_id=excluded.lease_id,
                    mission_id=excluded.mission_id,
                    kind=excluded.kind,
                    command=excluded.command,
                    cwd=excluded.cwd,
                    port=excluded.port,
                    status=excluded.status,
                    heartbeat_at=excluded.heartbeat_at,
                    expires_at=excluded.expires_at,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    process_key,
                    resolved_pid,
                    max(0, int(parent_process_id or 0)),
                    resolved_host,
                    str(job_id or ""),
                    str(lease_id or ""),
                    str(mission_id or ""),
                    str(kind or "process"),
                    str(command or "")[:2000],
                    str(cwd or "")[:1000],
                    max(0, int(port or 0)),
                    normalized_status,
                    now,
                    now,
                    expires_at,
                    _json_dumps(metadata or {}),
                    now,
                ),
            )
            self._append_event_db(
                db,
                job_id=str(job_id or ""),
                lease_id=str(lease_id or ""),
                host_id=resolved_host,
                kind="process.registered",
                message=f"Registered {kind or 'process'} PID {resolved_pid}.",
                payload={
                    "processKey": process_key,
                    "processId": resolved_pid,
                    "kind": kind,
                    "expiresAt": expires_at,
                },
            )
            process = db.execute("SELECT * FROM managed_processes WHERE process_key=?", (process_key,)).fetchone()
        return _process_row_to_payload(process)

    def heartbeat_process(
        self,
        *,
        process_key: str = "",
        process_id: int = 0,
        host_id: str = "",
        job_id: str = "",
        lease_id: str = "",
        status: str = "running",
    ) -> dict[str, Any]:
        key = str(process_key or "").strip()
        if not key:
            key = _process_key(_normalize_host_id(host_id), int(process_id or 0), job_id, lease_id, "")
        now = utc_now_iso()
        normalized_status = str(status or "running").strip().lower() or "running"
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM managed_processes WHERE process_key = ?",
                (key,),
            ).fetchone()
            if row is None and process_id:
                row = db.execute(
                    """
                    SELECT * FROM managed_processes
                    WHERE process_id = ? AND host_id = ?
                    ORDER BY updated_at DESC LIMIT 1
                    """,
                    (int(process_id), _normalize_host_id(host_id)),
                ).fetchone()
            if row is None:
                return {"ok": False, "error": "unknown_process"}
            db.execute(
                """
                UPDATE managed_processes SET heartbeat_at = ?, status = ?,
                    updated_at = ? WHERE process_key = ?
                """,
                (now, normalized_status, now, row["process_key"]),
            )
            key = row["process_key"]
        return {"ok": True, "process": self.get_process(key)}

    def complete_process(
        self,
        *,
        process_key: str = "",
        process_id: int = 0,
        host_id: str = "",
        status: str = "completed",
        reason: str = "",
    ) -> dict[str, Any]:
        normalized = str(status or "completed").strip().lower()
        if normalized not in {"completed", "failed", "stopped", "terminated", "missing"}:
            normalized = "completed"
        row = self._find_process_row(process_key=process_key, process_id=process_id, host_id=host_id)
        if row is None:
            return {"ok": False, "error": "unknown_process"}
        now = utc_now_iso()
        with self._connect() as db:
            db.execute(
                """
                UPDATE managed_processes SET status = ?, completed_at = ?,
                    termination_reason = ?, updated_at = ?
                WHERE process_key = ?
                """,
                (normalized, now, str(reason or ""), now, row["process_key"]),
            )
            self._append_event_db(
                db,
                job_id=row["job_id"],
                lease_id=row["lease_id"],
                host_id=row["host_id"],
                kind=f"process.{normalized}",
                message=str(reason or f"Managed process {normalized}."),
                payload={
                    "processKey": row["process_key"],
                    "processId": int(row["process_id"]),
                    "kind": row["kind"],
                },
            )
        return {"ok": True, "process": self.get_process(str(row["process_key"]))}

    def get_process(self, process_key: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM managed_processes WHERE process_key = ?",
                (process_key,),
            ).fetchone()
        return _process_row_to_payload(row) if row else {}

    def list_processes(self, *, limit: int = 100, active_only: bool = False) -> list[dict[str, Any]]:
        with self._connect() as db:
            if active_only:
                rows = db.execute(
                    """
                    SELECT * FROM managed_processes
                    WHERE status IN ('registered', 'launching', 'running')
                    ORDER BY updated_at DESC LIMIT ?
                    """,
                    (max(1, int(limit)),),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM managed_processes ORDER BY updated_at DESC LIMIT ?",
                    (max(1, int(limit)),),
                ).fetchall()
        return [_process_row_to_payload(row) for row in rows]

    def process_reaper(
        self,
        *,
        dry_run: bool = True,
        stale_seconds: int = DEFAULT_PROCESS_STALE_SECONDS,
        limit: int = 100,
    ) -> dict[str, Any]:
        candidates = self._process_reaper_candidates(
            stale_seconds=stale_seconds,
            limit=limit,
        )
        actions: list[dict[str, Any]] = []
        if not dry_run:
            for candidate in candidates:
                action = self._apply_process_reaper_candidate(candidate)
                actions.append(action)
        return {
            "schema": "fluxio.process_reaper.v1",
            "dryRun": bool(dry_run),
            "generatedAt": utc_now_iso(),
            "candidateCount": len(candidates),
            "candidates": candidates,
            "actions": actions,
            "status": "candidates" if candidates else "clear",
        }

    def architecture_doctor(self) -> dict[str, Any]:
        snapshot = self.snapshot(job_limit=50)
        process_report = self.process_reaper(dry_run=True, limit=100)
        issues: list[dict[str, Any]] = []
        policy = nas_execution_policy()
        hosts = snapshot.get("hosts", [])
        online_workstations = [
            host for host in hosts if host.get("online") and host.get("hostType") == "workstation"
        ]
        asus = next((host for host in hosts if host.get("hostId") == "ASUS-ROG-STRIX"), {})
        nas = next((host for host in hosts if host.get("hostId") == "nas.example.invalid"), {})
        nas_runtime_ready = (
            bool(nas.get("online"))
            and "runtime.launch" in {str(item) for item in nas.get("capabilities", [])}
        )
        if not online_workstations and not nas_runtime_ready:
            issues.append(
                {
                    "severity": "warn",
                    "kind": "no_online_executor",
                    "detail": "No workstation worker or NAS efficient runtime worker is online; runtime jobs should remain queued.",
                }
            )
        if policy in {"control_only", "disabled"} and nas.get("online") and int(nas.get("currentLoad") or 0) > 0:
            issues.append(
                {
                    "severity": "warn",
                    "kind": "nas_has_runtime_load",
                    "detail": "NAS reports load while current policy says it should be controller/storage only.",
                }
            )
        if process_report["candidateCount"]:
            issues.append(
                {
                    "severity": "warn",
                    "kind": "stale_managed_processes",
                    "detail": f"{process_report['candidateCount']} managed process(es) are stale or expired.",
                }
            )
        return {
            "schema": "fluxio.architecture_doctor.v1",
            "status": "blocked" if any(item["severity"] == "bad" for item in issues) else ("warn" if issues else "ready"),
            "generatedAt": utc_now_iso(),
            "policy": {
                "productionHarness": "fluxio_hybrid",
                "defaultLongMissionRuntime": "hermes",
                "secondaryRuntime": "openclaw",
                "primaryHeavyWorker": "ASUS-ROG-STRIX",
                "nasRole": "controller_storage_artifact_index_scheduler_watchdog_efficient_executor",
                "nasExecutionPolicy": policy,
                "nasExecutionDefault": (
                    "runtime_lanes_allowed_browser_build_blocked"
                    if policy == "efficient"
                    else policy
                ),
            },
            "primaryHeavyWorker": asus,
            "nasController": nas,
            "issues": issues,
            "cluster": snapshot,
            "processReaperDryRun": process_report,
        }

    def _find_process_row(
        self,
        *,
        process_key: str = "",
        process_id: int = 0,
        host_id: str = "",
    ) -> sqlite3.Row | None:
        with self._connect() as db:
            if process_key:
                return db.execute(
                    "SELECT * FROM managed_processes WHERE process_key = ?",
                    (process_key,),
                ).fetchone()
            if process_id:
                return db.execute(
                    """
                    SELECT * FROM managed_processes
                    WHERE process_id = ? AND host_id = ?
                    ORDER BY updated_at DESC LIMIT 1
                    """,
                    (int(process_id), _normalize_host_id(host_id)),
                ).fetchone()
        return None

    def _process_reaper_candidates(self, *, stale_seconds: int, limit: int) -> list[dict[str, Any]]:
        now = _utc_now()
        candidates: list[dict[str, Any]] = []
        for process in self.list_processes(limit=limit, active_only=True):
            reason = ""
            expires_at = _parse_time(process.get("expiresAt"))
            heartbeat_at = _parse_time(process.get("heartbeatAt"))
            if expires_at is not None and expires_at < now:
                reason = "process_ttl_expired"
            elif heartbeat_at is None:
                reason = "process_missing_heartbeat"
            elif (now - heartbeat_at).total_seconds() > max(1, int(stale_seconds)):
                reason = "process_heartbeat_stale"
            if not reason:
                continue
            candidate = dict(process)
            candidate["reason"] = reason
            candidate["canApply"] = _same_host_id(process.get("hostId"), current_host_id())
            candidate["applyMode"] = "local_terminate" if candidate["canApply"] else "remote_worker_required"
            candidates.append(candidate)
        return candidates

    def _apply_process_reaper_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        process_key = str(candidate.get("processKey") or "")
        pid = int(candidate.get("processId") or 0)
        host_id = str(candidate.get("hostId") or "")
        reason = str(candidate.get("reason") or "process_reaped")
        if not candidate.get("canApply"):
            self.complete_process(
                process_key=process_key,
                status="missing",
                reason=f"{reason}; remote host reaper required.",
            )
            return {
                "processKey": process_key,
                "processId": pid,
                "status": "remote_reaper_required",
                "reason": reason,
            }
        alive = _pid_alive(pid)
        if alive:
            _terminate_pid(pid)
            status = "terminated"
        else:
            status = "missing"
        self.complete_process(
            process_key=process_key,
            process_id=pid,
            host_id=host_id,
            status=status,
            reason=reason,
        )
        return {
            "processKey": process_key,
            "processId": pid,
            "status": status,
            "reason": reason,
        }

    def get_lease(self, lease_id: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute("SELECT * FROM leases WHERE lease_id = ?", (lease_id,)).fetchone()
        return _lease_row_to_payload(row) if row else {}

    def list_events(self, *, job_id: str = "", limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as db:
            if job_id:
                rows = db.execute(
                    "SELECT * FROM events WHERE job_id = ? ORDER BY event_id DESC LIMIT ?",
                    (job_id, max(1, int(limit))),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM events ORDER BY event_id DESC LIMIT ?",
                    (max(1, int(limit)),),
                ).fetchall()
        return [_event_row_to_payload(row) for row in reversed(rows)]

    def snapshot(self, *, include_token_path: bool = False, job_limit: int = 100) -> dict[str, Any]:
        stale_hosts = self.mark_stale_hosts()
        expired_leases = self.expire_stale_leases()
        hosts = self.list_hosts()
        jobs = self.list_jobs(limit=job_limit)
        processes = self.list_processes(limit=50)
        provider_circuits = self.list_provider_circuits(limit=100)
        status_counts: dict[str, int] = {}
        for job in jobs:
            status = str(job.get("status") or "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
        process_status_counts: dict[str, int] = {}
        for process in processes:
            status = str(process.get("status") or "unknown")
            process_status_counts[status] = process_status_counts.get(status, 0) + 1
        payload = {
            "schema": CLUSTER_SCHEMA_VERSION,
            "root": str(self.root),
            "dbPath": str(self.db_path),
            "generatedAt": utc_now_iso(),
            "currentHostId": current_host_id(),
            "hosts": hosts,
            "jobs": jobs,
            "processes": processes,
            "providerCircuits": provider_circuits,
            "recentEvents": self.list_events(limit=30),
            "summary": {
                "hostCount": len(hosts),
                "onlineHostCount": sum(1 for host in hosts if host.get("online")),
                "workerHostCount": sum(1 for host in hosts if host.get("hostType") == "workstation"),
                "queuedJobCount": status_counts.get("queued", 0),
                "runningJobCount": status_counts.get("running", 0) + status_counts.get("leased", 0),
                "terminalJobCount": sum(status_counts.get(key, 0) for key in ("completed", "failed", "blocked", "stopped")),
                "managedProcessCount": len(processes),
                "activeManagedProcessCount": sum(
                    process_status_counts.get(key, 0)
                    for key in PROCESS_ACTIVE_STATUSES
                ),
                "staleHostsMarkedOffline": stale_hosts,
                "expiredLeasesRequeued": expired_leases,
            },
            "statusCounts": status_counts,
            "processStatusCounts": process_status_counts,
        }
        if include_token_path:
            payload["workerTokenPath"] = str(self.control_dir / "cluster_worker_token.txt")
        return payload

    def scheduler_doctor(self) -> dict[str, Any]:
        snapshot = self.snapshot(include_token_path=True)
        hosts = snapshot["hosts"]
        jobs = snapshot["jobs"]
        issues: list[dict[str, Any]] = []
        if not any(host.get("online") and host.get("hostType") == "workstation" for host in hosts):
            issues.append(
                {
                    "severity": "warn",
                    "kind": "no_online_workstation_worker",
                    "detail": "Only NAS/local fallback is available; heavy delegated jobs should wait for a workstation worker.",
                }
            )
        queued = [job for job in jobs if job.get("status") == "queued"]
        if queued and not any(host.get("online") for host in hosts):
            issues.append(
                {
                    "severity": "bad",
                    "kind": "queued_jobs_without_online_hosts",
                    "detail": f"{len(queued)} job(s) are queued and no host is online.",
                }
            )
        return {
            "schema": "fluxio.scheduler_doctor.v1",
            "status": "blocked" if any(item["severity"] == "bad" for item in issues) else ("warn" if issues else "ready"),
            "issues": issues,
            "snapshot": snapshot,
        }

    def _create_lease(
        self,
        job_id: str,
        host_id: str,
        *,
        lease_ttl_seconds: int,
        db: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        lease_id = f"lease_{uuid.uuid4().hex[:12]}"
        now = utc_now_iso()
        expires_at = (_utc_now() + timedelta(seconds=max(1, int(lease_ttl_seconds)))).isoformat()
        owns_db = db is None
        connection = db or self._connect()
        try:
            if owns_db:
                connection.execute("BEGIN IMMEDIATE")
            job_row = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            if job_row is None:
                return {}
            if str(job_row["status"] or "") != "queued":
                existing_lease_id = str(job_row["lease_id"] or "")
                existing = None
                if existing_lease_id:
                    existing = connection.execute(
                        "SELECT * FROM leases WHERE lease_id = ? AND status = 'active'",
                        (existing_lease_id,),
                    ).fetchone()
                if existing is not None:
                    return _lease_row_to_payload(existing)
                return {}
            admission = self._provider_circuit_admission_db(
                connection,
                _job_row_to_payload(job_row),
                host_id,
            )
            if not admission.get("allowed"):
                return {}
            connection.execute(
                """
                INSERT INTO leases (
                    lease_id, job_id, host_id, status, heartbeat_at, expires_at,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, 'active', ?, ?, ?, ?)
                """,
                (lease_id, job_id, host_id, now, expires_at, now, now),
            )
            connection.execute(
                """
                UPDATE jobs SET status = 'leased', assigned_host = ?,
                    lease_id = ?, status_detail = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (host_id, lease_id, f"Assigned to {host_id}.", now, job_id),
            )
            self._append_event_db(
                connection,
                job_id=job_id,
                lease_id=lease_id,
                host_id=host_id,
                kind="lease.created",
                message=f"Cluster job leased to {host_id}.",
                payload={"expiresAt": expires_at},
            )
            self._refresh_host_load_db(connection, host_id)
            check_lease(connection, job_id, host_id, lease_id)
            if owns_db:
                connection.commit()
            else:
                row = connection.execute(
                    "SELECT * FROM leases WHERE lease_id = ?",
                    (lease_id,),
                ).fetchone()
                return _lease_row_to_payload(row)
        finally:
            if owns_db:
                connection.close()
        return self.get_lease(lease_id)

    def _append_event_db(
        self,
        db: sqlite3.Connection,
        *,
        job_id: str,
        lease_id: str,
        host_id: str,
        kind: str,
        message: str,
        payload: dict[str, Any],
    ) -> None:
        db.execute(
            """
            INSERT INTO events (
                job_id, lease_id, host_id, kind, message, payload_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                lease_id,
                host_id,
                kind,
                message,
                _json_dumps(payload),
                utc_now_iso(),
            ),
        )


def _browser_preflight_proves_available(root: Path) -> bool:
    receipt_path = root / ".agent_control" / "browser_dependency_preflight.json"
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    if not isinstance(receipt, dict):
        return False
    if str(receipt.get("status") or "").strip().lower() != "passed":
        return False
    if not _truthy(receipt.get("browserProofAvailable")):
        return False
    executable = str(receipt.get("chromeExecutable") or "").strip()
    return bool(executable and Path(executable).expanduser().is_file())


@checked('a-cli.scheduler.capabilities')
def build_local_worker_capabilities(
    root: str | Path,
    *,
    host_id: str = "",
    label: str = "",
    current_load: int = 0,
    max_concurrent_jobs: int | None = None,
) -> dict[str, Any]:
    root_path = Path(root).expanduser().resolve()
    runtimes = _detect_runtime_names(root_path)
    resolved_host_id = _normalize_host_id(host_id)
    host_type = "nas_control" if resolved_host_id.lower() == "nas.example.invalid" else current_host_type(root_path)
    role = "controller_storage" if host_type == "nas_control" else "worker"
    if resolved_host_id == "ASUS-ROG-STRIX":
        role = "primary_worker"
    if host_type == "nas_control":
        policy = nas_execution_policy()
        capabilities = [
            "artifact.index",
            "artifact.write",
            "control.watchdog",
            "mission.reconcile",
            "reaper.dry_run",
            "scheduler",
        ]
        if policy in {"efficient", "unrestricted"}:
            capabilities.extend(
                ["command.run", "runtime.launch", "app.self_repair", "nas.efficient"]
            )
        if policy == "unrestricted":
            capabilities.extend(["browser.verify", "frontend.build"])
        elif policy == "efficient" and _browser_preflight_proves_available(root_path):
            capabilities.append("browser.verify")
    else:
        capabilities = ["command.run", "runtime.launch", "artifact.write", "app.self_repair"]
        capabilities.extend(["browser.verify", "frontend.build"])
    concurrency_limit = normalize_concurrency_limit(
        max_concurrent_jobs
        if max_concurrent_jobs is not None
        else os.environ.get("FLUXIO_WORKER_MAX_JOBS", "unlimited")
    )
    return {
        "hostId": resolved_host_id,
        "label": label or resolved_host_id,
        "hostType": host_type,
        "role": role,
        "tailscaleIp": str(os.environ.get("TAILSCALE_IP") or ""),
        "osName": platform.system().lower() or os.name,
        "runtimes": runtimes,
        "capabilities": capabilities,
        "workspaceMappings": _workspace_mappings_from_env(),
        "maxConcurrentJobs": concurrency_limit,
        "concurrencyMode": "limited" if concurrency_limit else "unlimited",
        "currentLoad": max(0, int(current_load or 0)),
        "cpuPercent": 0.0,
        "memoryPercent": 0.0,
    }


def _detect_runtime_names(root: Path) -> list[str]:
    cache_key = (str(root.resolve()), str(os.environ.get("PATH") or ""))
    with _RUNTIME_DETECTION_LOCK:
        cached = _RUNTIME_DETECTION_CACHE.get(cache_key)
        now = time.monotonic()
        if cached and now - cached[0] < RUNTIME_DETECTION_CACHE_SECONDS:
            return list(cached[1])

        names: list[str] = []
        try:
            from .runtimes import runtime_adapter_map

            for runtime_id, adapter in runtime_adapter_map().items():
                try:
                    status = adapter.doctor(root)
                except Exception:
                    continue
                if status.detected:
                    names.append(runtime_id)
        except Exception:
            pass
        detected = sorted(set(names))
        _RUNTIME_DETECTION_CACHE[cache_key] = (now, detected)
        return list(detected)


def _workspace_mappings_from_env() -> dict[str, str]:
    mappings: dict[str, str] = {}
    raw = str(os.environ.get("FLUXIO_WORKSPACE_MAPPINGS") or "").strip()
    if not raw:
        return mappings
    for pair in raw.split(";"):
        if "=" not in pair:
            continue
        key, value = pair.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key and value:
            mappings[key] = value
    return mappings


def _normalized_scope(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    normalized: list[str] = []
    for value in values:
        text = str(value or "").strip().replace("\\", "/")
        if not text:
            continue
        while text.startswith("./"):
            text = text[2:]
        text = text.strip("/")
        normalized.append(text.lower() or ".")
    return sorted(set(normalized))


def _scopes_overlap(left: list[str], right: list[str]) -> bool:
    if not left or not right:
        return False
    for first in left:
        for second in right:
            if first in {".", "*"} or second in {".", "*"}:
                return True
            if first == second:
                return True
            if first.startswith(second.rstrip("/") + "/"):
                return True
            if second.startswith(first.rstrip("/") + "/"):
                return True
    return False


def _same_host_id(left: object, right: object) -> bool:
    return str(left or "").strip().lower() == str(right or "").strip().lower()


def _process_key(host_id: str, process_id: int, job_id: str, lease_id: str, kind: str) -> str:
    material = "|".join(
        [
            str(host_id or ""),
            str(int(process_id or 0)),
            str(job_id or ""),
            str(lease_id or ""),
            str(kind or ""),
        ]
    )
    return f"process_{_sha256(material)[:16]}"


def _pid_alive(pid: int) -> bool:
    pid = int(pid or 0)
    if pid <= 0:
        return False
    if os.name == "nt":
        from .subprocess_utils import windows_pid_alive
        return windows_pid_alive(pid) is True
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _terminate_pid(pid: int) -> None:
    pid = int(pid or 0)
    if pid <= 0:
        return
    if os.name == "nt":
        try:
            subprocess.run(  # noqa: S603
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
                **hidden_windows_subprocess_kwargs(),
            )
        except Exception:
            return
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return


def _host_has_workspace_locality(host: dict[str, Any], job: dict[str, Any]) -> bool:
    mappings = host.get("workspaceMappings", {})
    if not isinstance(mappings, dict) or not mappings:
        return False
    workspace_id = str(job.get("workspaceId") or "").strip()
    if workspace_id and workspace_id in mappings:
        return True
    payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
    roots = [
        payload.get("executionRoot"),
        payload.get("execution_root"),
        payload.get("workspaceRoot"),
        payload.get("workspace_root"),
    ]
    normalized_values = {
        str(value or "").strip().replace("\\", "/").rstrip("/").lower()
        for value in mappings.values()
        if str(value or "").strip()
    }
    for root in roots:
        normalized_root = str(root or "").strip().replace("\\", "/").rstrip("/").lower()
        if normalized_root and normalized_root in normalized_values:
            return True
    return False


def _job_payload(job: dict[str, Any]) -> dict[str, Any]:
    payload = job.get("payload")
    return payload if isinstance(payload, dict) else {}


def _job_is_heavy(job: dict[str, Any]) -> bool:
    required = {
        str(item).strip().lower()
        for item in job.get("requiredCapabilities", [])
        if str(item).strip()
    }
    kind = str(job.get("jobKind") or "").strip().lower()
    runtime_id = str(job.get("runtimeId") or "").strip().lower()
    lane_role = str(job.get("laneRole") or "").strip().lower()
    command = str(_job_payload(job).get("command") or _job_payload(job).get("launchCommand") or "").lower()
    heavy_capabilities = {"runtime.launch", "browser.verify", "frontend.build"}
    if required & heavy_capabilities:
        return True
    if kind in {"runtime_lane", "browser_verify", "frontend_build"}:
        return True
    if runtime_id or lane_role in {"executor", "verifier"}:
        return True
    return any(token in command for token in ("hermes", "openclaw", "opencode", "npm run", "vite", "playwright"))


def _job_requires_workstation_surface(job: dict[str, Any]) -> bool:
    required = {
        str(item).strip().lower()
        for item in job.get("requiredCapabilities", [])
        if str(item).strip()
    }
    kind = str(job.get("jobKind") or "").strip().lower()
    command = str(_job_payload(job).get("command") or _job_payload(job).get("launchCommand") or "").lower()
    if required & {"browser.verify", "frontend.build"}:
        return True
    if kind in {"browser_verify", "frontend_build"}:
        return True
    return any(token in command for token in ("playwright", "vite", "npm run frontend", "tauri build"))


def _job_is_nas_efficient_compatible(job: dict[str, Any]) -> bool:
    required = {
        str(item).strip().lower()
        for item in job.get("requiredCapabilities", [])
        if str(item).strip()
    }
    kind = str(job.get("jobKind") or "").strip().lower()
    command = str(
        _job_payload(job).get("command")
        or _job_payload(job).get("launchCommand")
        or ""
    ).lower()
    # Browser verification is efficient on a NAS that truthfully advertises it.
    # Host capability matching remains the final gate. Frontend build workloads
    # stay workstation-only under the efficient policy.
    if "frontend.build" in required or kind == "frontend_build":
        return False
    if any(token in command for token in ("vite build", "npm run frontend", "tauri build")):
        return False
    return True


def _job_allows_nas_fallback(job: dict[str, Any]) -> bool:
    payload = _job_payload(job)
    for key in ("allowNasFallback", "allow_nas_fallback"):
        if key in payload:
            return _truthy(payload.get(key))
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    for key in ("allowNasFallback", "allow_nas_fallback"):
        if key in metadata:
            return _truthy(metadata.get(key))
    policy = nas_execution_policy()
    if policy == "disabled":
        return False
    if policy == "control_only":
        return not _job_is_heavy(job)
    if policy == "unrestricted":
        return True
    return _job_is_nas_efficient_compatible(job)


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def normalize_concurrency_limit(value: object) -> int:
    """Return zero for unlimited, otherwise a positive explicit job limit."""
    normalized = str(value if value is not None else "").strip().lower()
    if not normalized or normalized in {"0", "none", "unbounded", "unlimited", "infinite"}:
        return 0
    try:
        parsed = int(normalized)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)


def _capabilities_from_payload(payload: dict[str, Any], root: Path) -> WorkerCapabilities:
    host_id = _normalize_host_id(payload.get("hostId") or payload.get("host_id"))
    return WorkerCapabilities(
        host_id=host_id,
        label=str(payload.get("label") or host_id),
        host_type=str(payload.get("hostType") or payload.get("host_type") or current_host_type(root)),
        role=str(payload.get("role") or "worker"),
        tailscale_ip=str(payload.get("tailscaleIp") or payload.get("tailscale_ip") or ""),
        os_name=str(payload.get("osName") or payload.get("os_name") or platform.system().lower()),
        runtimes=[str(item) for item in payload.get("runtimes", []) if str(item or "").strip()],
        capabilities=[str(item) for item in payload.get("capabilities", []) if str(item or "").strip()],
        workspace_mappings=dict(payload.get("workspaceMappings") or payload.get("workspace_mappings") or {}),
        max_concurrent_jobs=normalize_concurrency_limit(
            payload.get("maxConcurrentJobs")
            if "maxConcurrentJobs" in payload
            else payload.get("max_concurrent_jobs")
        ),
        current_load=max(0, int(payload.get("currentLoad") or payload.get("current_load") or 0)),
        cpu_percent=float(payload.get("cpuPercent") or payload.get("cpu_percent") or 0),
        memory_percent=float(payload.get("memoryPercent") or payload.get("memory_percent") or 0),
    )


def _host_row_to_payload(row: sqlite3.Row | None) -> dict[str, Any]:
    if row is None:
        return {}
    heartbeat = _parse_time(row["last_heartbeat_at"])
    age = int((_utc_now() - heartbeat).total_seconds()) if heartbeat else None
    return {
        "hostId": row["host_id"],
        "label": row["label"],
        "hostType": row["host_type"],
        "role": row["role"],
        "tailscaleIp": row["tailscale_ip"],
        "osName": row["os_name"],
        "online": bool(row["online"]),
        "capabilities": _json_loads(row["capabilities_json"], []),
        "runtimes": _json_loads(row["runtimes_json"], []),
        "workspaceMappings": _json_loads(row["workspace_mappings_json"], {}),
        "maxConcurrentJobs": normalize_concurrency_limit(row["max_concurrent_jobs"]),
        "concurrencyMode": (
            "limited" if normalize_concurrency_limit(row["max_concurrent_jobs"]) else "unlimited"
        ),
        "currentLoad": int(row["current_load"]),
        "cpuPercent": float(row["cpu_percent"]),
        "memoryPercent": float(row["memory_percent"]),
        "lastHeartbeatAt": row["last_heartbeat_at"],
        "heartbeatAgeSeconds": age,
        "updatedAt": row["updated_at"],
    }


def _job_row_to_payload(row: sqlite3.Row | None) -> dict[str, Any]:
    if row is None:
        return {}
    payload = _json_loads(row["payload_json"], {})
    if not isinstance(payload, dict):
        payload = {}
    route = payload.get("route") if isinstance(payload.get("route"), dict) else {}
    target_provider = _normalize_provider(
        row["target_provider"]
        or payload.get("targetProvider")
        or payload.get("target_provider")
        or route.get("provider")
        or payload.get("provider")
    )
    target_model = str(
        row["target_model"]
        or payload.get("targetModel")
        or payload.get("target_model")
        or route.get("model")
        or payload.get("model")
        or ""
    ).strip()
    return {
        "jobId": row["job_id"],
        "dedupeKey": row["dedupe_key"],
        "missionId": row["mission_id"],
        "workspaceId": row["workspace_id"],
        "laneRole": row["lane_role"],
        "runtimeId": row["runtime_id"],
        "targetProvider": target_provider,
        "targetModel": target_model,
        "jobKind": row["job_kind"],
        "status": row["status"],
        "preferredHost": row["preferred_host"],
        "assignedHost": row["assigned_host"],
        "leaseId": row["lease_id"],
        "requiredCapabilities": _json_loads(row["required_capabilities_json"], []),
        "plannedFileScope": _json_loads(row["planned_file_scope_json"], []),
        "requiredArtifacts": _json_loads(row["required_artifacts_json"], []),
        "payload": payload,
        "statusDetail": row["status_detail"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "completedAt": row["completed_at"],
    }


def _provider_circuit_row_to_payload(row: sqlite3.Row | None) -> dict[str, Any]:
    if row is None:
        return {}
    retry_after = str(row["retry_after"] or "")
    retry_at = _parse_time(retry_after)
    return {
        "hostId": row["host_id"],
        "runtimeId": row["runtime_id"],
        "provider": row["provider"],
        "state": row["state"],
        "failureCount": int(row["failure_count"] or 0),
        "openedAt": row["opened_at"],
        "retryAfter": retry_after,
        "retryAfterSecondsRemaining": max(0, int((retry_at - _utc_now()).total_seconds())) if retry_at else 0,
        "lastFailureAt": row["last_failure_at"],
        "lastFailureKind": row["last_failure_kind"],
        "lastFailureCode": int(row["last_failure_code"] or 0),
        "lastFailureContext": row["last_failure_context"],
        "lastRetryAfterSeconds": int(row["last_retry_after_seconds"] or 0),
        "probeJobId": row["probe_job_id"],
        "updatedAt": row["updated_at"],
        "reason": row["last_failure_kind"] or ("half_open_probe" if row["state"] == "half_open" else ""),
    }


def _lease_row_to_payload(row: sqlite3.Row | None) -> dict[str, Any]:
    if row is None:
        return {}
    return {
        "leaseId": row["lease_id"],
        "jobId": row["job_id"],
        "hostId": row["host_id"],
        "status": row["status"],
        "heartbeatAt": row["heartbeat_at"],
        "expiresAt": row["expires_at"],
        "processId": int(row["process_id"]),
        "cancelReason": row["cancel_reason"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def _process_row_to_payload(row: sqlite3.Row | None) -> dict[str, Any]:
    if row is None:
        return {}
    started_at = _parse_time(row["started_at"])
    heartbeat_at = _parse_time(row["heartbeat_at"])
    now = _utc_now()
    age = int((now - started_at).total_seconds()) if started_at else None
    heartbeat_age = int((now - heartbeat_at).total_seconds()) if heartbeat_at else None
    expires_at = _parse_time(row["expires_at"])
    return {
        "processKey": row["process_key"],
        "processId": int(row["process_id"]),
        "parentProcessId": int(row["parent_process_id"]),
        "hostId": row["host_id"],
        "jobId": row["job_id"],
        "leaseId": row["lease_id"],
        "missionId": row["mission_id"],
        "kind": row["kind"],
        "command": row["command"],
        "cwd": row["cwd"],
        "port": int(row["port"]),
        "status": row["status"],
        "heartbeatAt": row["heartbeat_at"],
        "heartbeatAgeSeconds": heartbeat_age,
        "startedAt": row["started_at"],
        "ageSeconds": age,
        "expiresAt": row["expires_at"],
        "expired": bool(expires_at is not None and expires_at < now),
        "completedAt": row["completed_at"],
        "terminationReason": row["termination_reason"],
        "metadata": _json_loads(row["metadata_json"], {}),
        "updatedAt": row["updated_at"],
    }


def _event_row_to_payload(row: sqlite3.Row | None) -> dict[str, Any]:
    if row is None:
        return {}
    return {
        "eventId": int(row["event_id"]),
        "jobId": row["job_id"],
        "leaseId": row["lease_id"],
        "hostId": row["host_id"],
        "kind": row["kind"],
        "message": row["message"],
        "payload": _json_loads(row["payload_json"], {}),
        "createdAt": row["created_at"],
    }


def small_sleep(seconds: float) -> None:
    time.sleep(max(0.0, float(seconds)))


from .proofs_d_runtime_auth import circuit_admission as _checked_circuit_admission, classification as _checked_classification
ClusterRegistry._provider_circuit_admission_db = _checked_circuit_admission(ClusterRegistry._provider_circuit_admission_db)
classify_provider_result = _checked_classification(classify_provider_result)
