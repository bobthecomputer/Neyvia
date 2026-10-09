"""Generated feature fixtures for durable coordination and local worker effects.

Each builder uses a disposable, real SQLite store. Child execution is an owned
system-Python process with an explicit environment, never a provider adapter.
"""
from __future__ import annotations
from .subprocess_utils import hidden_windows_subprocess_kwargs

import concurrent.futures
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from .proofs_a_cli_scheduler import environment

CRASH = {"a-cli.crash." + suffix for suffix in
         ("submit", "claim", "transition", "recover", "result", "summary", "time", "autonomy")}
SCHEDULER = {"a-cli.scheduler." + suffix for suffix in
             ("root", "job", "claim", "choose", "lease", "load", "stale", "expire",
              "worker", "environment", "execute", "threads", "lifecycle", "roles")}
REVIEWED = CRASH | SCHEDULER | {"a-cli.scheduler.capabilities", "a-cli.scheduler.rehome",
                              "a-cli.scheduler.queued", "a-cli.scheduler.unlimited-loop"}

# A builder reaching a feature is not enough: only perturbations affecting that
# feature count. The rest stay explicitly inapplicable or pending a distinct
# fixture instead of recycling a baseline into nominal edge coverage.
APPLICABLE = {
    "a-cli.crash.submit": {"empty", "huge", "unicode", "concurrency", "stale"},
    "a-cli.crash.claim": {"empty", "huge", "unicode", "concurrency", "interrupted", "stale"},
    "a-cli.crash.transition": {"empty", "huge", "unicode", "interrupted", "stale"},
    "a-cli.crash.recover": {"empty", "huge", "unicode", "interrupted", "stale"},
    "a-cli.crash.result": {"empty", "huge", "unicode", "concurrency", "stale"},
    "a-cli.crash.summary": {"empty", "huge", "unicode", "concurrency", "stale"},
    "a-cli.crash.time": {"empty", "huge", "stale"},
    "a-cli.crash.autonomy": {"empty", "unicode", "permissions", "stale"},
    "a-cli.scheduler.root": {"empty", "unicode"},
    "a-cli.scheduler.job": {"empty", "huge", "unicode", "concurrency", "stale"},
    "a-cli.scheduler.claim": {"empty", "huge", "unicode", "concurrency", "stale"},
    "a-cli.scheduler.choose": {"offline", "stale"},
    "a-cli.scheduler.lease": {"permissions", "concurrency", "stale"},
    "a-cli.scheduler.load": {"concurrency", "stale"},
    "a-cli.scheduler.stale": {"offline", "stale"},
    "a-cli.scheduler.expire": {"stale", "interrupted", "permissions"},
    "a-cli.scheduler.worker": {"empty", "unicode", "huge", "concurrency"},
    "a-cli.scheduler.environment": {"unicode", "permissions"},
    "a-cli.scheduler.execute": {"empty", "unicode", "huge", "interrupted"},
    "a-cli.scheduler.threads": {"concurrency"},
    "a-cli.scheduler.lifecycle": {"empty", "unicode", "huge"},
    "a-cli.scheduler.roles": {"empty", "unicode", "huge"},
}


def _assert(value, message):
    if not value:
        raise AssertionError(message)


def _text(category):
    return "" if category == "empty" else "漢字 🧪 café e\u0301" if category == "unicode" else "x" * 196608 if category == "huge" else category


def _pool(function, count):
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(count, 8)) as executor:
        return list(executor.map(function, range(count)))


def _crash(root, category, emit):
    from .crashproof import CrashProofStore
    store = CrashProofStore(root)
    now, later = "2026-01-01T00:00:00Z", "2026-01-01T00:02:01Z"
    value = _text(category)
    count = 32 if category == "huge" else 8 if category == "concurrency" else 2
    payload = {"text": value} if category != "empty" else {}
    def submit(index):
        return CrashProofStore(root).submit_task(mission_id="fixture", kind="local", idempotency_key="stable", payload=payload, now=now)
    tasks = _pool(submit, count) if category == "concurrency" else [submit(i) for i in range(count)]
    task_id = tasks[0]["taskId"]
    reopened = CrashProofStore(root)
    _assert(len({task["taskId"] for task in tasks}) == 1 and reopened.get_task(task_id)["payload"] == payload and len(reopened.list_tasks()) == 1, "durable idempotency or payload round trip failed")
    emit("submit", "duplicate submissions reopened as one durable task with exact payload")
    if category == "interrupted":
        marker = root / "claimed.json"
        program = "from pathlib import Path; import json,time; from grant_agent.crashproof import CrashProofStore; s=CrashProofStore(Path(" + repr(str(root)) + ")); t=s.claim_next(worker_id='owned-child',lease_seconds=1,now=" + repr(now) + "); Path(" + repr(str(marker)) + ").write_text(json.dumps(t)); time.sleep(20)"
        child = subprocess.Popen([sys.executable, "-c", program], env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, **hidden_windows_subprocess_kwargs())
        try:
            deadline = time.monotonic() + 15
            while not marker.exists() and child.poll() is None and time.monotonic() < deadline:
                time.sleep(.02)
            _assert(marker.exists(), "owned interrupted worker never claimed task")
            claimed = json.loads(marker.read_text(encoding="utf-8"))
        finally:
            if child.poll() is None:
                child.terminate()
            child.communicate(timeout=5)
    elif category == "concurrency":
        claimed_rows = _pool(lambda i: CrashProofStore(root).claim_next(worker_id=f"worker-{i}", now=now), count)
        _assert(sum(row is not None for row in claimed_rows) == 1, "concurrent workers double claimed one task")
        claimed = next(row for row in claimed_rows if row is not None)
    else:
        claimed = reopened.claim_next(worker_id="owned", now=now)
    _assert(CrashProofStore(root).get_task(task_id)["workerId"] == claimed["workerId"] and claimed["payload"] == payload, "claimed owner/payload absent from reopened store")
    emit("claim", "real claim persisted exact ownership; empty poll returned no second claim")
    _assert(reopened.claim_next(worker_id="another", now=now) is None, "working task was claimed twice")
    recovered = reopened.recover_interrupted(now=later)
    _assert(recovered == [task_id] and CrashProofStore(root).get_task(task_id)["workerId"] is None, "expired working task did not recover")
    emit("recover", "expired claim recovered with independently reopened owner removal")
    reopened.claim_next(worker_id="completion", now=later)
    reopened.transition_task(task_id, "waiting", checkpoint=payload, now=later)
    reopened.transition_task(task_id, "completed", result=payload, now=later)
    terminal = CrashProofStore(root).get_task(task_id)
    _assert(terminal["checkpoint"] == payload and terminal["result"] == payload and terminal["leaseUntil"] is None, "terminal result/checkpoint or lease release lost")
    try:
        reopened.transition_task(task_id, "working")
    except ValueError:
        pass
    else:
        raise AssertionError("terminal task accepted invalid transition")
    emit("transition", "checkpoint/result survived reopening; terminal state rejected resurrection")
    results = reopened.create_result_set(mission_id="fixture", kind="local")
    rid = results["resultSetId"]
    add = lambda i: CrashProofStore(root).add_result_item(rid, payload={"index": i, "text": value}, dedupe_key=str(i), status="failed" if i == 0 else "completed")
    items = _pool(add, count) if category == "concurrency" else [add(i) for i in range(count)]
    duplicate = add(0)
    _assert(duplicate["itemId"] == items[0]["itemId"] and duplicate["deduplicated"], "result item dedupe lost")
    summary = CrashProofStore(root).summarize_result_set(rid, sample_limit=0 if category == "empty" else 3)
    _assert(summary["total"] == count and summary["byStatus"] == {"failed": 1, "completed": count - 1} and len(summary["samples"]) == (0 if category == "empty" else min(3, count)), "durable result counts/samples differ")
    emit("result", "result dedupe observed through persisted summary")
    emit("summary", "independent store counted generated completed/failed items and bounded samples")
    absent = reopened.time_snapshot(deadline_at=None, now=now)
    optional = reopened.time_snapshot(deadline_at="2026-01-01T00:00:01Z", estimated_next_seconds=2, optional=True, now=now)
    required = reopened.time_snapshot(deadline_at=now, estimated_next_seconds=10**30 if category == "huge" else 2, optional=False, now=later)
    _assert(absent["shouldContinue"] and optional["skipOptional"] and required["shouldContinue"] and required["deadlineRisk"], "time admission violated required/optional distinction")
    emit("time", "real deadline feature admitted required work and declined overdue optional work")
    scope = root / ("範囲" if category == "unicode" else "scope"); scope.mkdir()
    lease = reopened.create_autonomy_lease(mission_id="fixture", policy={"allowedActions": ["file.write"], "allowedRoots": [str(scope)], "maxSpend": 0}, duration_seconds=120, now=now)
    checks = [("file.write", {"path": scope / "out.txt"}, True), ("file.write", {"path": root / "outside.txt"}, False), ("file.write", {"path": scope / "out.txt", "destructive": True}, False), ("file.write", {"publicCommunication": True}, False), ("file.write", {"spend": 1}, False), ("forbidden", {}, False)]
    for action, context, expected in checks:
        _assert(CrashProofStore(root).autonomy_allows(lease["leaseId"], action=action, context=context, now=now)["allowed"] == expected, "durable autonomy permission escaped policy")
    _assert(not reopened.autonomy_allows(lease["leaseId"], action="file.write", now=later)["allowed"], "expired autonomy lease granted")
    reopened.revoke_autonomy_lease(lease["leaseId"], now=now)
    _assert(not CrashProofStore(root).autonomy_allows(lease["leaseId"], action="file.write", now=now)["allowed"], "persisted revocation granted")
    if category == "empty":
        empty_lease = reopened.create_autonomy_lease(mission_id="fixture", policy={}, duration_seconds=120, now=now)
        _assert(not reopened.autonomy_allows(empty_lease["leaseId"], action="file.write", now=now)["allowed"], "empty autonomy policy granted action")
    emit("autonomy", "persisted grant, root/action/spend/destruction/communication denials, expiry and revocation")


def _scheduler(root, category, emit):
    from .cluster import ClusterRegistry
    from .worker import _write_worker_state, _worker_state_path, execute_job, run_local_worker_once, _start_unlimited_worker_attempt
    value = _text(category)
    configured = root / "配置" if category == "unicode" else root / "shared"
    with environment(FLUXIO_CLUSTER_ROOT=str(configured)):
        registry = ClusterRegistry(root)
        _assert(registry.root == configured.resolve() and ClusterRegistry(root, use_configured_root=False).root == root.resolve(), "configured root affinity differs")
    emit("root", "both configured and explicit roots wrote separate real SQLite databases")
    registry = ClusterRegistry(root, use_configured_root=False)
    reopen = lambda: ClusterRegistry(root, use_configured_root=False)
    # These are actual observed capabilities for the controlled local command,
    # passed through the production API rather than patching any detector.
    host = {"hostId": "C7B-OWNED", "hostType": "workstation", "capabilities": ["command.run"], "maxConcurrentJobs": 2, "workspaceMappings": {"fixture": str(root)}}
    registry.heartbeat_host(host)
    count = 32 if category == "huge" else 8 if category == "concurrency" else 2
    def enqueue(index):
        return reopen().upsert_job(dedupe_key=f"stable-{index}", mission_id=f"mission-{index}", workspace_id=f"workspace-{index}", runtime_id="controlled", required_capabilities=["command.run"], planned_file_scope=["out.txt"], payload={"text": value})
    jobs = _pool(enqueue, count) if category == "concurrency" else [enqueue(i) for i in range(count)]
    _assert(enqueue(0)["jobId"] == jobs[0]["jobId"] and reopen().get_job(jobs[0]["jobId"])["payload"]["text"] == value and len(reopen().list_jobs(limit=100)) == count, "real job upsert/dedupe payload lost")
    emit("job", "generated job payload persisted exactly with one canonical dedupe row")
    chosen = registry.choose_host(jobs[0], preferred_host=host["hostId"], allow_remote=True, allow_nas_fallback=False)
    _assert(chosen and chosen["hostId"] == host["hostId"], "compatible online local host not selected")
    emit("choose", "actual host admission required online capability and recorded selection")
    claims = _pool(lambda i: reopen().claim_next_job(host), count) if category == "concurrency" else [registry.claim_next_job(host) for _ in range(3)]
    active = [claim for claim in claims if claim.get("job")]
    _assert(len(active) == 2 and len({row["job"]["jobId"] for row in active}) == 2 and reopen().get_host(host["hostId"])["currentLoad"] == 2, "capacity or exclusive job claim violated")
    emit("claim", "production claims persisted unique jobs and rejected over-capacity admission")
    emit("load", "reopened host load equals two actual active leases")
    first = active[0]
    lease_id, job_id = first["lease"]["leaseId"], first["job"]["jobId"]
    _assert(reopen().get_lease(lease_id)["jobId"] == job_id and reopen().get_job(job_id)["leaseId"] == lease_id, "exact durable lease affinity lost")
    def state():
        with registry._connect() as db:
            # Public host projections include heartbeatAgeSeconds, which can
            # change while an unauthorized completion correctly writes nothing.
            # Compare every durable row instead of a wall-clock projection.
            return {table: [dict(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY rowid")]
                    for table in ("jobs", "leases", "hosts", "events", "artifacts")}
    def deny_completion(label, caller):
        previous = state()
        denied = registry.complete_job(job_id=job_id, lease_id=lease_id, host_id=caller, status="completed", artifacts=[{"artifactId": "rogue", "path": str(root / "forbidden") }])
        _assert(not denied.get("ok") and state() == previous, label + " completion changed durable job/lease/host/events/artifacts")
    if category == "permissions":
        deny_completion("unowned host", "UNAUTHORIZED")
    emit("lease", "exact durable job/lease/host affinity independently reobserved")
    before = reopen().get_lease(lease_id)["expiresAt"]
    heartbeat = registry.heartbeat_lease(lease_id=lease_id, host_id=host["hostId"], ttl_seconds=600)
    _assert(heartbeat["ok"] and reopen().get_job(job_id)["status"] == "running" and reopen().get_lease(lease_id)["expiresAt"] >= before, "heartbeat did not persist running state/extension")
    wrong = registry.heartbeat_lease(lease_id=lease_id, host_id="UNAUTHORIZED")
    _assert(not wrong["ok"], "foreign lease heartbeat accepted")
    with registry._connect() as db:
        db.execute("UPDATE leases SET expires_at='2020-01-01T00:00:00Z' WHERE lease_id=?", (lease_id,))
    if category == "permissions":
        deny_completion("elapsed active lease", host["hostId"])
    _assert(registry.expire_stale_leases() == 1 and reopen().get_job(job_id)["status"] == "queued" and reopen().get_lease(lease_id)["status"] == "expired", "aged durable lease did not requeue")
    if category == "permissions":
        new_claim = registry.claim_next_job(host)
        _assert(new_claim["job"]["jobId"] == job_id and new_claim["lease"]["leaseId"] != lease_id, "reassignment failed to establish a fresh lease")
        deny_completion("reassigned old lease", host["hostId"])
    emit("expire", "persisted historical lease expired/requeued without retaining execution ownership")
    with registry._connect() as db:
        db.execute("UPDATE hosts SET last_heartbeat_at='2020-01-01T00:00:00Z' WHERE host_id=?", (host["hostId"],))
    _assert(registry.mark_stale_hosts(stale_seconds=1) >= 1 and not reopen().get_host(host["hostId"])["online"], "stale durable host remained online")
    _assert(not registry.choose_host(jobs[0], preferred_host=host["hostId"], allow_remote=True, allow_nas_fallback=False), "offline/stale host selected for execution")
    emit("stale", "historical heartbeat persisted offline host and denied actual dispatch")
    execution = root / ("実行 🧪" if category == "unicode" else "execution"); execution.mkdir()
    env = {str(k): str(v) for k, v in os.environ.items()}
    output = execution / "effect.txt"
    code = "from pathlib import Path; import os,json; Path('effect.txt').write_text(" + repr(value) + ",encoding='utf-8'); print(json.dumps({'control':os.environ.get('FLUXIO_CONTROL_PROJECT_ROOT'),'cluster':os.environ.get('FLUXIO_CLUSTER_ROOT')}))"
    job = {"missionId": "local", "workspaceId": "local", "payload": {"executionRoot": str(execution), "controlProjectRoot": str(execution / "authority"), "command": [sys.executable, "-c", code]}}
    # Windows imposes a command-line bound: huge text is a real input artifact.
    if category == "huge":
        (execution / "input.txt").write_text(value, encoding="utf-8")
        job["payload"]["command"][-1] = "from pathlib import Path; import os,json; Path('effect.txt').write_bytes(Path('input.txt').read_bytes()); print(json.dumps({'control':os.environ.get('FLUXIO_CONTROL_PROJECT_ROOT'),'cluster':os.environ.get('FLUXIO_CLUSTER_ROOT')}))"
    with environment(FLUXIO_CLUSTER_ROOT=str(root / "authority-cluster")):
        result = execute_job(job, {}, root=execution, process_environment=env)
    _assert(result["status"] == "completed" and output.read_text(encoding="utf-8") == value, "actual Python worker output differs from input: " + str(result))
    observed = json.loads(result["stdout"])
    _assert(observed == {"control": str((execution / "authority").resolve()), "cluster": str(root / "authority-cluster")}, "actual child environment lost control/cluster authority")
    emit("environment", "owned child reported exact control and cluster roots")
    if category == "interrupted":
        job["payload"].update(command=[sys.executable, "-c", "import time; time.sleep(20)"], timeoutSeconds=1)
    elif category == "empty":
        job["payload"]["command"] = []
    elif category in {"offline", "permissions"}:
        job["payload"]["command"] = [sys.executable, "-c", "raise SystemExit(7)"]
    else:
        job["payload"]["command"] = [sys.executable, "-c", "raise SystemExit(3)"]
    negative = execute_job(job, {}, root=execution, process_environment=env)
    _assert(negative["status"] in {"blocked", "failed"} and negative["returnCode"] != 0, "empty/failing/interrupted local command falsely completed")
    emit("execute", "real artifact command completed and negative command failed/blocked correctly")
    worker_root = root / ("作業 🧪" if category == "unicode" else "worker"); worker_root.mkdir()
    (worker_root / "worker-input.txt").write_text(value, encoding="utf-8")
    worker_registry = ClusterRegistry(worker_root)
    worker_command = "from pathlib import Path; Path('worker-effect.txt').write_bytes(Path('worker-input.txt').read_bytes())"
    if category == "concurrency":
        worker_command = "from pathlib import Path; import time; end=time.monotonic()+15\nwhile not Path('release').exists() and time.monotonic()<end: time.sleep(.02)\n" + worker_command
    child_job = worker_registry.upsert_job(mission_id="worker", workspace_id="fixture", runtime_id="controlled", required_capabilities=["command.run"], payload={"executionRoot": str(worker_root), "command": [sys.executable, "-c", worker_command]})
    worker_host = {**host, "workspaceRoot": str(worker_root), "runtimes": [], "workspaceMappings": {"fixture": str(worker_root)}}
    def attempt(observer):
        return run_local_worker_once(worker_root, host_id=host["hostId"], observed_capabilities=worker_host, process_environment=env, claim_observer=observer)
    completion, admission, thread = _start_unlimited_worker_attempt(attempt)
    admitted = admission.result(timeout=15)
    if not admitted:
        completion.result(timeout=20)
    _assert(admitted, "real worker thread did not independently admit job")
    if category == "concurrency":
        _assert(not completion.done(), "worker admission waited for completion rather than independently announcing running child")
        (worker_root / "release").write_text("owned child released")
    worked = completion.result(timeout=20); thread.join(timeout=5)
    terminal = ClusterRegistry(worker_root).get_job(child_job["jobId"])
    _assert(worked["claimed"] and terminal["status"] == "completed" and (worker_root / "worker-effect.txt").read_text(encoding="utf-8") == value and any(event["kind"] == "job.completed" for event in ClusterRegistry(worker_root).list_events(job_id=child_job["jobId"])), "actual worker failed artifact/durable terminal journey")
    emit("worker", "actual worker child wrote artifact and durable completed job/event survived reopening")
    emit("threads", "independent admission and completion futures drove an actual durable worker")
    state = _write_worker_state(worker_root, host_id=host["hostId"], status="stopped", controller="", error=value[:4096])
    _assert(json.loads(_worker_state_path(worker_root).read_text(encoding="utf-8")) == state, "worker lifecycle state failed disk round trip")
    emit("lifecycle", "production atomic lifecycle writer independently reopened from disk")
    from .models import DelegatedRuntimeSession
    from .runtime_supervisor import _cluster_required_capabilities
    planner = DelegatedRuntimeSession(delegated_id="planner", runtime_id="controlled", launch_command=value, target_role="planner", target_phase="plan")
    browser = DelegatedRuntimeSession(delegated_id="browser", runtime_id="controlled", launch_command=value, target_role="browser_verifier", target_phase="verify")
    _assert(_cluster_required_capabilities(planner) == ["runtime.launch"] and _cluster_required_capabilities(browser) == ["browser.verify", "runtime.launch"], "runtime roles derived authority from free-text prompt")
    emit("roles", "production typed session roles ignored generated command text")


def blocked_reason(identity, category):
    if identity not in REVIEWED:
        return None
    if identity == "a-cli.scheduler.capabilities":
        return {"kind": "authority_boundary", "reason": "Real host capability detection invokes installed runtime doctors that may inspect user credential files; fixtures use explicit observed local command capabilities instead."}
    if identity in {"a-cli.scheduler.rehome", "a-cli.scheduler.queued", "a-cli.scheduler.unlimited-loop"}:
        return {"kind": "fixture_not_implemented", "reason": "A distinct supervisor migration or production CLI admission-loop fixture is required; durable local worker fixtures do not prove that separate control flow."}
    if category not in APPLICABLE.get(identity, set()):
        if category == "offline" and identity.startswith("a-cli.crash."):
            return {"kind": "not_applicable", "reason": "This store feature uses local SQLite and has no network admission or transport dependency; host offline dispatch is proved in scheduler fixtures."}
        return {"kind": "fixture_not_implemented", "reason": "The current family journey reaches this feature but does not perturb its specific " + category + " boundary; reusing baseline execution would overstate semantic coverage."}
    return {"kind": "fixture_failed", "reason": "The reviewed family builder did not reach this pair; its failed fixture row records the exact execution failure."}


def run(root, contracts, categories):
    allowed = {row["id"] if isinstance(row, dict) else str(row) for row in contracts}
    rows = []
    for category in categories:
        for family, builder, identities in (("crash", _crash, CRASH), ("scheduler", _scheduler, SCHEDULER)):
            selected = {identity for identity in allowed & identities if category in APPLICABLE[identity]}
            if not selected:
                continue
            path = Path(root).resolve() / (family + "-" + category); path.mkdir(parents=True, exist_ok=True)
            emitted = set()
            def emit(suffix, detail):
                identity = "a-cli." + family + "." + suffix
                emitted.add(identity)
                if identity in selected:
                    rows.append({"id": family + "-" + category + "-" + suffix, "category": category, "contracts": [identity], "status": "passed", "detail": detail})
            try:
                with environment(FLUXIO_CLUSTER_ROOT=None, FLUXIO_CONTROL_PROJECT_ROOT=None, FLUXIO_HOST_ID="C7B-OWNED"):
                    builder(path, category, emit)
            except Exception as exc:
                remaining = sorted(selected - emitted)
                rows.append({"id": family + "-" + category + "-failure", "category": category, "contracts": remaining, "status": "failed", "detail": type(exc).__name__ + ": " + str(exc)})
    return rows
