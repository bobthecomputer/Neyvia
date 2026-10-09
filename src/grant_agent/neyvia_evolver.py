"""Workspace-scoped observation boundary for the frozen Evolver engine.

The application and model read the same persisted state. No endpoint accepts
judges, panel contents, scoring rules, or a public-release destination.
"""
from __future__ import annotations

from .subprocess_utils import hidden_windows_subprocess_kwargs

from pathlib import Path
from contextlib import contextmanager
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time

COMMANDS = frozenset({"evolver_state_command", "evolver_lineage_command", "evolver_receipt_command", "evolver_genome_command", "evolver_run_command", "evolver_job_command"})
RUN_DOMAINS = ("manual_compression", "cl_skill", "manual_compression_v2", "cl_skill_v2", "cl_skill_v3", "paul_intent", "manual_json_local_v1")
DOMAINS = (*RUN_DOMAINS, "laya_cpu_r4")
DEFINITIONS = [
    ("evolver.state", "Read per-domain incumbents, trial counts, frozen judge locks, Pareto front and lineage. Does not train or publish.",
     {"domain": {"type": "string"}}, []),
    ("evolver.lineage", "Read candidate ancestry and measured trial outcomes from the selected Evolver domain.",
     {"domain": {"type": "string"}}, ["domain"]),
    ("evolver.receipt", "Read an actual paired evaluation receipt, including discovery and fresh reconfirmation.",
     {"domain": {"type": "string"}, "trial": {"type": "integer", "minimum": 1}}, ["domain", "trial"]),
    ("evolver.run", "Start a bounded frozen evolution job. manual_json_local_v1 performs real lossless manual compression locally; the other domains use GPT-6 Luna. Reuse requestId on retries; changes only workspace incumbent.",
     {"domain": {"type": "string", "enum": list(RUN_DOMAINS)}, "requestId": {"type": "string", "minLength": 1}, "maxTrials": {"type": "integer", "minimum": 1, "maximum": 2}}, ["domain", "requestId"]),
    ("evolver.job", "Read persisted evolution job status after a backend restart.",
     {"requestId": {"type": "string", "minLength": 1}}, ["requestId"]),
    ("evolver.genome", "Read the exact stored instruction document for a domain's lineage member; hash checked before returning.",
     {"domain": {"type": "string"}, "genome": {"type": "string", "pattern": "^[a-f0-9]{64}$"}}, ["domain", "genome"]),
]


@contextmanager
def _jobs(root):
    directory = Path(root).resolve() / ".neyvia" / "evolver-jobs"
    directory.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(directory / "jobs.sqlite3", timeout=30)
    db.row_factory = sqlite3.Row
    try:
        db.execute("CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, domain TEXT, payload TEXT, state TEXT, pid INTEGER, created REAL, finished REAL, error TEXT)")
        with db:
            yield db, directory
    finally:
        db.close()


def _request_id(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ValueError("requestId must be nonempty text of at most 200 characters")
    return value


def job(root, request_id):
    request_id = _request_id(request_id)
    with _jobs(root) as (db, directory):
        row = db.execute("SELECT * FROM jobs WHERE id=?", (request_id,)).fetchone()
    if row is None:
        raise ValueError("Unknown evolution job")
    result = dict(row)
    result["payload"] = json.loads(result["payload"])
    output = directory / (hashlib.sha256(request_id.encode()).hexdigest() + ".result.json")
    if result["state"] in {"completed", "failed"} and output.is_file():
        result["result"] = json.loads(output.read_text(encoding="utf-8"))
    return {"ok": True, "job": result}


def start(root, args):
    if set(args) - {"domain", "requestId", "maxTrials"}:
        raise ValueError("Run accepts only domain, requestId and maxTrials; judges are frozen")
    domain = args.get("domain")
    if domain not in RUN_DOMAINS:
        raise ValueError("Choose a built-in frozen evolution domain")
    request_id = _request_id(args.get("requestId"))
    maximum = args.get("maxTrials", 1)
    if type(maximum) is not int or not 1 <= maximum <= 2:
        raise ValueError("maxTrials must be 1 or 2")
    payload = json.dumps({"domain": domain, "maxTrials": maximum}, sort_keys=True)
    with _jobs(root) as (db, _):
        prior = db.execute("SELECT payload FROM jobs WHERE id=?", (request_id,)).fetchone()
    if prior:
        if prior["payload"] != payload:
            raise ValueError("requestId was already used with different arguments")
        return {**job(root, request_id), "replayed": True}
    # The runner installs the canonical workspace network policy before CLI use.
    from .neyvia_settings import _state
    from .ui_command_bus import bus_for
    from .local_network_policy import install
    install(Path(root))
    with bus_for(Path(root)).connect() as settings_db:
        _, settings = _state(settings_db)
    if settings["localOnly"]:
        raise ValueError("Evolution runs managed child processes; local-only blocks child jobs. Turn it off in Settings before starting.")
    store = Path(root).resolve() / ".neyvia" / "evolver.sqlite3"
    if store.is_file():
        from .evolver_core import EvolverEngine
        established = EvolverEngine(store).status(domain)["domains"]
        if established:
            current = established[0]
            if not current["frozen_lock"]["ok"]:
                raise ValueError("Frozen judges changed; retain the incumbent and review a separate version")
            if maximum > current["budget"]["max_trials"] - current["trials"]:
                raise ValueError("Requested trials exceed the frozen domain's remaining budget")
    with _jobs(root) as (db, directory):
        db.execute("BEGIN IMMEDIATE")
        prior = db.execute("SELECT payload FROM jobs WHERE id=?", (request_id,)).fetchone()
        if prior:
            if prior["payload"] != payload:
                raise ValueError("requestId was already used with different arguments")
            return {**job(root, request_id), "replayed": True}
        if db.execute("SELECT 1 FROM jobs WHERE state IN ('queued','running')").fetchone():
            raise ValueError("An evolution job is already active; inspect its persisted receipt")
        db.execute("INSERT INTO jobs(id,domain,payload,state,created) VALUES(?,?,?,'queued',?)", (request_id, domain, payload, time.time()))
    logfile = directory / (hashlib.sha256(request_id.encode()).hexdigest() + ".log")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    env.update(NEYVIA_TOOL_AUTO_UPDATE="0", NEYVIA_COORDINATOR_AUTOSTART="0", FLUXIO_WATCHDOG_AUTOSTART="0")
    try:
        with logfile.open("ab") as stream:
            child = subprocess.Popen([sys.executable, "-m", "grant_agent.neyvia_evolver", "--worker", str(Path(root).resolve()), request_id],
                                     stdin=subprocess.DEVNULL, stdout=stream, stderr=stream, env=env,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        with _jobs(root) as (db, _):
            db.execute("UPDATE jobs SET pid=? WHERE id=?", (child.pid, request_id))
    except OSError as exc:
        with _jobs(root) as (db, _):
            db.execute("UPDATE jobs SET state='failed',finished=?,error=? WHERE id=?", (time.time(), str(exc), request_id))
        raise
    return job(root, request_id)


def _worker(root, request_id):
    from .local_network_policy import install
    install(Path(root))
    row = job(root, request_id)["job"]
    with _jobs(root) as (db, directory):
        changed = db.execute("UPDATE jobs SET state='running' WHERE id=? AND state='queued'", (request_id,)).rowcount
    if changed != 1:
        raise ValueError("Job is no longer queued; refusing duplicate execution")
    output = directory / (hashlib.sha256(request_id.encode()).hexdigest() + ".result.json")
    runner = Path(__file__).resolve().parents[2] / "scripts/run_t13_evolution.py"
    try:
        result = subprocess.run([sys.executable, str(runner), "--root", str(Path(root).resolve()), "--domain", row["domain"],
                                 "--max-trials", str(row["payload"]["maxTrials"]), "--output", str(output)], timeout=7200, check=False, **hidden_windows_subprocess_kwargs())
        state_, error = ("completed", None) if result.returncode == 0 and output.is_file() else ("failed", f"Evolution runner exit {result.returncode}; inspect job log")
        if state_ == "completed":
            summary = json.loads(output.read_text(encoding="utf-8"))
            blocked = [trial for domain in summary["domains"].values() for trial in domain["trials"] if trial["state"] == "blocked"]
            if blocked:
                state_, error = "failed", blocked[0].get("error", "Evaluation blocked; inspect frozen trial receipt")
    except Exception as exc:
        state_, error = "failed", str(exc)
    with _jobs(root) as (db, _):
        db.execute("UPDATE jobs SET state=?,finished=?,error=? WHERE id=?", (state_, time.time(), error, request_id))


def _store(root, domain=None):
    if domain == "laya_cpu_r4":
        from .evolver_laya import store_path
        return store_path(root)
    return Path(root).resolve() / ".neyvia" / "evolver.sqlite3"


def state(root, domain=None):
    store = _store(root, domain)
    stores = [store] if domain else [store, _store(root, "laya_cpu_r4")]
    existing = [path for path in stores if path.is_file()]
    if not existing:
        if domain:
            raise ValueError("Unknown Evolver domain")
        return {"schema": "neyvia.evolver.state.v1", "ok": True, "domains": [],
                "scope": "workspace incumbent only", "publicPromotion": False}
    from .evolver_core import EvolverEngine
    values = [EvolverEngine(path).status(domain) for path in existing]
    value = {**values[0], "domains": [row for result in values for row in result["domains"]]}
    if len(values) > 1:
        value["stores"] = [str(path) for path in existing]
    if domain and not value["domains"]:
        raise ValueError("Unknown Evolver domain")
    return {"schema": "neyvia.evolver.state.v1", "ok": True, **value,
            "scope": "workspace incumbent only", "publicPromotion": False}


def call(root, name, args):
    if name == "evolver.run":
        return start(root, args)
    if name == "evolver.job":
        if set(args) != {"requestId"}:
            raise ValueError("Job observation requires only requestId")
        return job(root, args["requestId"])
    if name == "evolver.genome":
        if set(args) != {"domain", "genome"} or not all(isinstance(value, str) and value for value in args.values()):
            raise ValueError("Genome observation requires domain and genome ID")
        from .evolver_core import EvolverEngine
        engine = EvolverEngine(_store(root, args["domain"]))
        engine._verify_frozen(args["domain"])
        return {"ok": True, "domain": args["domain"], "id": args["genome"], "genome": engine._genome(args["domain"], args["genome"])}
    if set(args) - {"domain", "trial"}:
        raise ValueError("Evolver observation does not accept judge or panel edits")
    domain = args.get("domain")
    if domain is not None and (not isinstance(domain, str) or not domain.strip()):
        raise ValueError("domain must be a nonempty string")
    value = state(root, domain)
    if name == "evolver.state":
        return value
    if not domain:
        raise ValueError("domain is required")
    # Core status carries summaries plus immutable receipts; no alternate state.
    rows = value.get("domains", [])
    selected = next((row for row in rows if row.get("id") == domain), None)
    if selected is None:
        raise ValueError("Unknown Evolver domain")
    if name == "evolver.lineage":
        return {"ok": True, "domain": domain, "lineage": selected.get("lineage", []),
                "incumbent": selected.get("incumbent"), "trials": selected.get("trials", 0),
                "pareto_front": selected.get("pareto_front", [])}
    if name == "evolver.receipt":
        trial = args.get("trial")
        if isinstance(trial, bool) or not isinstance(trial, int) or trial < 1:
            raise ValueError("trial must be a positive integer")
        receipt = next((row for row in selected.get("receipts", []) if row.get("trial_number") == trial), None)
        if receipt is None:
            raise ValueError("Unknown Evolver trial")
        return {"ok": True, "domain": domain, "receipt": receipt}
    raise ValueError("Unknown Evolver operation")


def handle_command(root, command, payload):
    if command not in COMMANDS:
        raise ValueError("Unknown Evolver command")
    expected = payload.get("_expectedStateRoot")
    if expected and Path(expected).resolve() != Path(root).resolve():
        raise ValueError("Evolver belongs to a different workspace")
    args = {key: value for key, value in payload.items() if key != "_expectedStateRoot"}
    return call(root, "evolver." + command.removeprefix("evolver_").removesuffix("_command"), args)


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] != "--worker":
        raise SystemExit("Use --worker ROOT REQUEST_ID")
    _worker(Path(sys.argv[2]), sys.argv[3])
