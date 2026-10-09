"""Generated capability feature journeys against real local production owners.

Each builder mutates feature inputs and observes independent disk/state effects.
The matrix deliberately does not convert a missing builder into impossibility.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def _require(condition, message):
    if not condition:
        raise AssertionError(message)


def _rejected(action, kinds=(ValueError, KeyError, RuntimeError)):
    try:
        action()
    except kinds as error:
        return str(error)
    raise AssertionError("Invalid feature input was accepted")


def _text(category, ordinary="Inspect and verify the local feature"):
    return {"empty": "", "huge": ordinary + " evidence" * 12000,
            "unicode": ordinary + " café 東京 🧭 e\u0301"}.get(category, ordinary)


def _parallel(action, count=12):
    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(action, range(count)))


def _behavior(root, category):
    from .behavior_capsules import BehaviorCapsuleRegistry, canonical_hash
    registry = BehaviorCapsuleRegistry(root)
    task = _text(category, "Research and compare two architectures")
    profile = {"maximumTurns": 100000, "toolCatalogLimit": 999, "specialistLimit": 999} if category == "huge" else {}
    adjustment = {"applied": True, "evidenceRuns": 2, "behaviorVectorDelta": {"initiative": 999, "verificationPressure": -999}}
    first = registry.compile(task, resource_profile=profile, learned_adjustment=adjustment)
    expected_hash = canonical_hash({k: v for k, v in first.items() if k not in {"compiledAt", "planHash"}})
    _require(first["planHash"] == expected_hash, "Compiled effect hash differs from content")
    _require(first["skillRuntime"]["executableGates"] == first["capsule"]["proofGates"], "Learned mutation changed proof gates")
    _require(all(0 <= value <= 1 for value in first["behaviorVector"].values()), "Behavior escaped bounded coordinates")
    _require(first["maximumTurns"] <= 64 and first["toolCatalogLimit"] <= 20, "Huge resource request bypassed budgets")
    # Mutating a returned plan must never corrupt the cached production value.
    first["capsule"]["id"] = "caller-corruption"
    if category == "concurrency":
        plans = _parallel(lambda _: registry.compile(task, resource_profile=profile, learned_adjustment=adjustment))
    else:
        plans = [registry.compile(task, resource_profile=profile, learned_adjustment=adjustment)]
    _require(all(p["planHash"] == expected_hash and p["capsule"]["id"] != "caller-corruption" for p in plans), "Cache returned mutated caller state")
    if category == "stale":
        changed = registry.compile(task, resource_profile={"maximumTurns": 1}, learned_adjustment=adjustment)
        _require(changed["planHash"] != expected_hash and changed["maximumTurns"] == 1, "Stale profile reused old plan")
    return {"inputCharacters": len(task), "cache": registry.cache_snapshot(), "planHash": expected_hash,
            "observed": "Actual compiler, independent hash, learned gates, caller-copy isolation and cache reuse"}


def _checkpoint(root, category):
    from .checkpoints import CheckpointStore
    from .models import RunState
    store = CheckpointStore(root)
    objective = _text(category)
    state = RunState(objective=objective, plan_steps=["inspect", "verify"], acceptance_checks=["actual checkpoint reread"], completed_steps=["inspect"], next_actions=["verify"])
    context = {"payload": _text(category), "revision": 1}
    count = 16 if category == "concurrency" else 1
    save = lambda index: store.save("fixture", index + 1, state, context, ["résumé.md"])
    paths = _parallel(save, count) if count > 1 else [save(0)]
    for index, path in enumerate(paths, 1):
        loaded = CheckpointStore.load(path)
        _require(loaded["objective"] == objective and loaded["context"] == context and loaded["iteration"] == index and loaded["state"]["next_actions"] == ["verify"], "Checkpoint disk roundtrip lost exact input")
    if category == "concurrency":
        def same_target(index):
            competing = RunState(objective=f"writer-{index}", plan_steps=["verify"], acceptance_checks=[f"writer-{index}-proof"])
            return CheckpointStore(root).save("fixture", 1, competing, {"writer": index, "payload": str(index) * (2 * 1024 * 1024)}, [])
        _parallel(same_target, 8)
        final = CheckpointStore.load(paths[0])
        winner = final["context"]["writer"]
        _require(final["objective"] == f"writer-{winner}" and final["state"]["acceptance_checks"] == [f"writer-{winner}-proof"] and final["context"]["payload"] == str(winner) * (2 * 1024 * 1024), "Same-checkpoint competing writers produced mixed or torn record")
        _require(not list((store.checkpoint_dir / ".abandoned-writes").glob("*")), "Active competing writer's real temporary bytes were incorrectly archived")
    if category == "stale":
        context["revision"] = 2
        path = store.save("fixture", 1, state, context, [])
        _require(CheckpointStore.load(path)["context"]["revision"] == 2, "Overwrite reread returned stale checkpoint")
    _require(len(CheckpointStore.list(root)) == count, "Concurrent or interrupted checkpoint listing lost entries")
    return {"checkpointCount": count, "inputCharacters": len(objective), "paths": [str(p) for p in paths], "observed": "Complete actual checkpoint disk records and restart listing"}


def _checkpoint_interruption(root, category):
    """Kill an owned process inside the real production atomic write boundary."""
    from .checkpoints import CheckpointStore
    from .models import RunState
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    state = RunState(objective="recover interrupted writer", plan_steps=["verify"], acceptance_checks=["disk reread"])
    store = CheckpointStore(root)
    path = store.save("interruption", 1, state, {"revision": 1}, [])
    previous = CheckpointStore.load(path)
    script = root / "owned_checkpoint_writer.py"
    script.write_text(
        "import sys\nfrom pathlib import Path\n"
        "from grant_agent.proof_credential_guard import install\n"
        "root=Path(sys.argv[1]).resolve()\ninstall(root)\n"
        "from grant_agent.checkpoints import CheckpointStore\n"
        "from grant_agent.models import RunState\n"
        "state=RunState(objective='recover interrupted writer',plan_steps=['verify'],acceptance_checks=['disk reread'])\n"
        "store=CheckpointStore(root)\n"
        "for revision in range(2,30):\n"
        " store.save('interruption',1,state,{'revision':revision,'payload':'x'*(24*1024*1024)},[])\n",
        encoding="utf-8")
    process = subprocess.Popen([sys.executable, str(script), str(root)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, **hidden_windows_subprocess_kwargs())
    interrupted_tail = None
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and process.poll() is None:
            tails = list(store.checkpoint_dir.glob(".ckpt_001.json.*.tmp"))
            for tail in tails:
                if tail.exists() and tail.stat().st_size > 0:
                    interrupted_tail = tail
                    break
            if interrupted_tail:
                process.terminate()
                process.wait(timeout=5)
                break
            time.sleep(.002)
        _require(interrupted_tail is not None and process.returncode is not None, "Failed to observe and stop the actual owned production writer")
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        process.communicate(timeout=5)
    loaded = CheckpointStore.load(path)
    _require(loaded["session_id"] == previous["session_id"] and loaded["state"] == previous["state"], "Abrupt writer produced torn published record")
    _require(interrupted_tail.is_file(), "Actual stopped writer did not retain interrupted unpublished bytes")
    interrupted_bytes = interrupted_tail.read_bytes()
    interrupted_sha256 = hashlib.sha256(interrupted_bytes).hexdigest()
    # Recreate the actual owner and require a subsequent normal save to recover.
    try:
        recovered = CheckpointStore(root).save("interruption", 1, state, {"revision": 30}, [])
    except Exception as error:
        error.fixture_effects = {"childExitCode": process.returncode, "interruptedTemporary": str(interrupted_tail), "retainedRevision": loaded["context"]["revision"], "publishedAfterRecovery": CheckpointStore.load(path)["context"], "observed": "Actual production writer terminated while unpublished bytes existed; complete old record survived and resumed save published before its observer failed"}
        raise
    _require(CheckpointStore.load(recovered)["context"] == {"revision": 30}, "Restarted writer did not recover normal operation")
    archives = list((store.checkpoint_dir / ".abandoned-writes").glob("*"))
    _require(len(archives) == 1 and archives[0].is_relative_to(store.checkpoint_dir) and archives[0].read_bytes() == interrupted_bytes, "Interrupted unpublished bytes were lost or changed during confined archival")
    _require(not list(store.checkpoint_dir.glob(".ckpt_001.json.*.tmp")) and not interrupted_tail.exists(), "Recovery retained target temporary tails")
    return {"childExitCode": process.returncode, "interruptedTemporary": str(interrupted_tail), "retainedRevision": loaded["context"]["revision"], "recoveredPath": str(recovered), "archivedPath": str(archives[0]), "archivedBytes": len(interrupted_bytes), "archivedSha256": interrupted_sha256, "observed": "Actual owned production writer terminated inside unpublished write; complete record survived, restart archived exact orphan bytes and saved complete replacement"}


def _permissions(root, category):
    from .capability_runtime import CapabilityPermissionEngine
    engine = CapabilityPermissionEngine()
    permissions = [] if category == "empty" else ["artifact.read", "artifact.write", "process.execute", "network.write", "destructive"]
    if category == "huge":
        permissions *= 4000
    if category == "unicode":
        permissions += ["未知.操作🧭"]
    modes = ["review_only", "always_ask", "workspace_safe", "autonomous_scoped"]
    def evaluate(index):
        mode = modes[index % len(modes)]
        scoped = index % 2 == 0
        approved = ["destructive"] if index >= 4 else []
        rows = engine.decide(permissions, mode=mode, approved_permissions=approved, workspace_scoped=scoped)
        expected = {}
        for requested in permissions:
            if requested in approved or requested == "artifact.read":
                expected[requested] = "allowed"
            elif mode == "review_only":
                expected[requested] = "denied"
            elif requested in {"artifact.write", "process.execute"} and scoped and mode != "always_ask":
                expected[requested] = "allowed"
            else:
                expected[requested] = "approval_required"
        _require({row.permission: row.status for row in rows} == expected and len(rows) == len(expected), "Feature policy differs from independent authority decisions")
        return {"mode": mode, "scoped": scoped, "summary": engine.summarize(rows)}
    outcomes = _parallel(evaluate, 8) if category == "concurrency" else [evaluate(i) for i in range(8)]
    return {"inputPermissions": len(permissions), "decisions": outcomes, "observed": "Actual permission engine across review, approval, workspace and high risk boundaries"}


def _artifacts(root, category):
    from .artifact_graph import ArtifactGraph
    graph = ArtifactGraph(root)
    content = _text(category, "actual artifact bytes").encode("utf-8")
    count = 20 if category in {"huge", "concurrency"} else 3
    paths = []
    for i in range(count):
        path = root / f"{'résumé東京' if category == 'unicode' else 'source'}-{i}.txt"
        path.write_bytes(content if category == "empty" else content + str(i).encode())
        paths.append(path)
    register = lambda i: graph.register(path=paths[i], metadata={"category": category, "index": i})
    records = _parallel(register, count) if category == "concurrency" else [register(i) for i in range(count)]
    for path, record in zip(paths, records):
        _require(record["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest() and record["sizeBytes"] == path.stat().st_size, "Artifact does not bind independently read file bytes")
    for i in range(1, count):
        graph.relate(records[i - 1]["artifactId"], records[i]["artifactId"], "derived_from")
    restarted = ArtifactGraph(root)
    lineage = restarted.lineage(records[-1]["artifactId"], direction="ancestors", max_depth=100)
    _require({r["artifactId"] for r in lineage["artifacts"]} == {r["artifactId"] for r in records} and len(lineage["relations"]) == count - 1, "Restart lineage lost actual durable effects")
    _rejected(lambda: graph.relate(records[0]["artifactId"], records[0]["artifactId"], "derived_from"))
    _rejected(lambda: graph.relate(records[0]["artifactId"], "missing", "derived_from"))
    if category == "stale":
        paths[0].write_bytes(b"new content after registration")
        updated = graph.register(path=paths[0], artifact_id=records[0]["artifactId"])
        _require(updated["sha256"] != records[0]["sha256"] and updated["sha256"] == hashlib.sha256(paths[0].read_bytes()).hexdigest(), "Re-registration preserved stale digest")
    stored = json.loads(graph.state_path.read_text(encoding="utf-8"))
    _require(len(stored["artifacts"]) == count and len(stored["relations"]) == count - 1, "Disk effects differ from graph actions")
    return {"artifactCount": count, "relationCount": count - 1, "bytesPerInput": len(content), "statePath": str(graph.state_path), "observed": "Real files, byte hashes, durable relations, invalid endpoint refusal and restarted lineage"}


def _catalog(root, category):
    from .capability_adapters import CapabilityAdapterRegistry
    from .capability_catalog import CapabilityRegistry, CapabilityPlanner
    from .capability_contracts import canonical_hash
    from .capability_runtime import CapabilityPermissionEngine
    adapters = CapabilityAdapterRegistry(root)
    catalog = Path(__file__).resolve().parents[2] / "config/capability_packs.json"
    copied = root / "catalog.json"
    copied.write_bytes(catalog.read_bytes())
    registry = CapabilityRegistry(copied, adapters=adapters)
    query = _text(category, "OCR scanned PDF and extract text")
    limit = 100000 if category == "huge" else 7
    search = lambda _: registry.search(query, limit=limit)
    searches = _parallel(search) if category == "concurrency" else [search(0)]
    for search_result in searches:
        ids = [row["capabilityId"] for row in search_result["results"]]
        _require(len(ids) == len(set(ids)) and len(ids) <= min(limit, 50) and set(ids) <= set(registry.capabilities), "Search routing invented, duplicated or over-returned capabilities")
        _require(all("inputSchema" not in row for row in search_result["results"]), "Search expanded deferred schemas")
    snap = registry.snapshot()
    expanded = registry.snapshot(include_capabilities=True)
    _require(snap["summary"]["packs"] == len(registry.packs) and snap["summary"]["capabilities"] == len(registry.capabilities), "Actual loaded catalog differs from snapshot")
    _require(all("capabilities" not in row for row in snap["packs"]) and all("capabilities" in row for row in expanded["packs"]), "Explicit schema expansion boundary failed")
    identity = searches[0]["results"][0]["capabilityId"]
    description = registry.describe(identity)
    detected = adapters.descriptor(description["adapter"]).as_dict()
    _require(description["available"] == detected["available"] and description["adapterDescriptor"] == detected, "Catalog adapter differs from detected real descriptor")
    planner = CapabilityPlanner(registry, CapabilityPermissionEngine())
    plan_goal = query or "OCR scanned PDF"
    plan = planner.plan(plan_goal, permission_mode="review_only" if category == "permissions" else "workspace_safe", max_capabilities=999 if category == "huge" else 4)
    _require(plan["planHash"] == canonical_hash({k: v for k, v in plan.items() if k not in {"planId", "planHash"}}), "Plan compilation lost content binding")
    _require(plan["stages"][-1]["steps"][0]["kind"] == "verification" and len(plan["capabilityIds"]) <= 8 and set(plan["capabilityIds"]) <= set(registry.capabilities), "Planner did not retain actual selected features and final verification")
    if category == "empty":
        _rejected(lambda: planner.plan(""))
    if category == "stale":
        before = registry.catalog_hash
        payload = json.loads(copied.read_text(encoding="utf-8"))
        payload["packs"][0]["description"] += " Changed fixture revision."
        copied.write_text(json.dumps(payload), encoding="utf-8")
        registry.reload()
        _require(registry.catalog_hash != before, "Catalog reload retained stale source digest")
    return {"queryCharacters": len(query), "returned": len(searches[0]["results"]), "selected": plan["capabilityIds"], "readiness": plan["readiness"], "observed": "Actual production catalog search/expansion/detected adapters and compiled stage graph"}


def _challenges(root, category):
    from .challenge_presets import ChallengePresetRegistry
    config = Path(__file__).resolve().parents[2] / "config/challenge_presets.json"
    path = root / "presets.json"
    original = json.loads(config.read_text(encoding="utf-8"))
    payload = {} if category == "empty" else original
    if category == "huge":
        sample = next(iter(original.values()))
        payload = {f"preset-{i}": sample for i in range(400)}
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    registry = ChallengePresetRegistry(path)
    _require(registry.list_names() == sorted(payload), "Challenge registry differs from real configured file")
    objective = _text(category, "secret leak resistance refusal policy")
    preset = registry.get(next(iter(payload), "fallback"))
    def select(_):
        result = preset.pick_selectors(objective, top_k=2)
        import re
        tokens = lambda text: set(re.findall(r"[a-z0-9]+", text.lower()))
        ranked = sorted(preset.selector_keywords, key=lambda word: len(tokens(objective) & tokens(word)), reverse=True)
        matched = [word for word in ranked if tokens(objective) & tokens(word)]
        _require(result == (matched or ranked)[:2], "Selector differs from independent token ranking")
        return result
    outcomes = _parallel(select) if category == "concurrency" else [select(0)]
    return {"presetCount": len(payload), "objectiveCharacters": len(objective), "selected": outcomes[0], "observed": "Actual configured preset loading and relevant selector ranking"}


def _runs(root, category):
    from .capability_runtime import CapabilityRunStore
    from .capability_contracts import PreviewEvent
    store = CapabilityRunStore(root)
    goal = _text(category)
    if category == "empty":
        _rejected(lambda: store.create({}, permission_summary={}))
    run = store.create({"planId": "plan-fixture", "goal": goal}, permission_summary={"approvalRequired": ["destructive"] if category == "permissions" else []})
    _require(run["status"] == ("awaiting_approval" if category == "permissions" else "ready"), "Run admission missed modeled approval")
    count = 40 if category in {"huge", "concurrency"} else 2
    def append(index):
        return store.append_preview(PreviewEvent(run_id=run["runId"], phase="live", kind="fixture", summary=f"{goal}:{index}", payload={"index": index}, artifact_ids=(f"artifact-{index}",)))
    if category == "concurrency":
        _parallel(append, count)
    else:
        for i in range(count):
            append(i)
    loaded = CapabilityRunStore(root).get(run["runId"])
    _require(len(loaded["previewEvents"]) == count + 1 and len(loaded["artifactIds"]) == count, "Live preview restart lost events or actual artifact IDs")
    done = store.finish(run["runId"], status="cancelled" if category == "interrupted" else "completed", summary=goal)
    _require(store.get(run["runId"]) == done and done["completedAt"] and done["previewEvents"][-1]["phase"] == "result", "Terminal actual run effect is not durable")
    _rejected(lambda: append(count))
    if category == "stale":
        _require(store.finish(run["runId"], status="failed", summary="stale writer") == done, "Stale terminal replay overwrote completed result")
    return {"runId": run["runId"], "liveEvents": count, "status": done["status"], "observed": "Actual ordered durable run lifecycle with concurrent append/restart/terminal write refusal"}


def _factory(root, category):
    from .app_factory import AppFactory
    from zipfile import ZipFile
    factory = AppFactory(root)
    name = "Fixture Notes 東京" if category == "unicode" else "Fixture Notes"
    brief = "Keep actual local notes and export portable JSON records"
    if category in {"empty", "huge"}:
        invalid = "" if category == "empty" else "N" * 100000
        rejection = _rejected(lambda: factory.create(name=invalid, brief=brief, target="neyvia", template="notes"))
        _require(not list(factory.jobs_root.glob("*.json")), "Rejected draft left a published job")
    else:
        rejection = ""
    job = factory.create(name=name, brief=brief, target="neyvia", template="notes", theme="paper")
    project = Path(job["projectRoot"])
    package = Path(job["package"]["path"])
    _require(project.is_relative_to(root) and package.is_file(), "Actual factory escaped workspace or omitted package")
    _require(hashlib.sha256(package.read_bytes()).hexdigest() == job["package"]["sha256"], "Package differs from actual bytes")
    manifest = json.loads((project / "neyvia.application.json").read_text(encoding="utf-8"))
    _require(manifest["valid"] and manifest["applicationId"] == job["spec"]["appId"] and job["status"] == "ready" and job["verification"]["state"] == "passed", "Draft did not produce actual verified application")
    _require(job["registration"]["state"] == "draft-ready" and job["marketplace"]["state"] == "draft", "Local draft raised external activation authority")
    with ZipFile(package) as archive:
        files = archive.namelist()
        _require(files and not any(name.startswith("/") or ".." in Path(name).parts for name in files), "Actual package contains unsafe member paths")
    preview, media = factory.resolve_preview_asset(job["jobId"], "")
    _require(preview.is_relative_to(project / "dist") and preview.name == "index.html" and preview.read_bytes() and media.startswith("text/html"), "Actual preview omitted public generated assets")
    for unsafe in ["../README.md", ".gitignore"]:
        _rejected(lambda unsafe=unsafe: factory.resolve_preview_asset(job["jobId"], unsafe))
    occupied = root / "apps/occupied"
    occupied.mkdir(parents=True)
    keeper = occupied / "keeper.txt"
    keeper.write_text("actual preexisting keeper", encoding="utf-8")
    _rejected(lambda: factory.create(name="Protected Notes", brief=brief, target="neyvia", directory="apps/occupied"))
    _require(keeper.read_text(encoding="utf-8") == "actual preexisting keeper", "Factory overwrote occupied destination")
    _rejected(lambda: factory.create(name="Escape Notes", brief=brief, target="neyvia", directory="../escape"))
    if category == "stale":
        resumed = factory.resume(job["jobId"])
        _require(resumed["package"]["sha256"] == job["package"]["sha256"], "Restart changed sealed draft bytes")
    return {"jobId": job["jobId"], "package": str(package), "sha256": job["package"]["sha256"], "fileCount": len(files), "rejection": rejection, "observed": "Production factory generated validated app, real archive/public assets, inactive registration and destination preservation"}


def _evolution(root, category):
    from .capability_evolution import NeyviaCapabilityEvolution
    import sqlite3
    service = NeyviaCapabilityEvolution(root, database_path=root / "evolution.sqlite3", hermes_import_dir=root / "hermes")
    if category == "empty":
        _rejected(lambda: service.create_trial({}))
    identity = "local-proof-fixture"
    trial = service.create_trial({"capabilityId": identity, "capabilityKind": "skill", "action": "branch", "label": _text(category, "Proof fixture")})
    target = trial["candidate"]["targetSkillId"]
    body = _text(category, "Inspect the active contract and preserve exact proof identity.") or "Inspect and verify the local proof contract."
    markdown = f"---\nname: {target}\ndescription: Preserve exact local proof identity.\n---\n\n# Local proof\n\n1. {body}\n2. Verify the local result and retain evidence.\n"
    before = trial["candidate"]
    _rejected(lambda: service.seal_skill_candidate(trial["trialId"], skill_markdown=markdown, review_confirmed=False))
    with sqlite3.connect(service.database_path) as connection:
        unchanged = json.loads(connection.execute("SELECT candidate_json FROM capability_evolution_trials WHERE trial_id=?", (trial["trialId"],)).fetchone()[0])
    _require(unchanged == before, "Unapproved sealing changed durable candidate")
    sealed = service.seal_skill_candidate(trial["trialId"], skill_markdown=markdown, review_confirmed=True)
    candidate = sealed["candidate"]
    _require(hashlib.sha256(candidate["skillMarkdown"].encode()).hexdigest() == candidate["skillSha256"] and hashlib.sha256(candidate["openaiYaml"].encode()).hexdigest() == candidate["metadataSha256"], "Actual sealed content differs from independent hashes")
    _require(candidate["activated"] is False and not (root / ".codex/skills" / target).exists(), "Sealing activated skill instructions")
    with sqlite3.connect(service.database_path) as connection:
        stored = json.loads(connection.execute("SELECT candidate_json FROM capability_evolution_trials WHERE trial_id=?", (trial["trialId"],)).fetchone()[0])
    _require(stored == candidate, "Returned sealed candidate differs from actual SQLite record")
    restarted = NeyviaCapabilityEvolution(root, database_path=service.database_path, hermes_import_dir=root / "hermes")
    seal = lambda _: restarted.seal_skill_candidate(trial["trialId"], skill_markdown=markdown, review_confirmed=True)
    repeats = _parallel(seal) if category == "concurrency" else [seal(0)]
    _require(all(row["candidate"]["packageDigest"] == candidate["packageDigest"] for row in repeats), "Concurrent/restarted identical sealing changed candidate identity")
    _rejected(lambda: restarted.seal_skill_candidate(trial["trialId"], skill_markdown=markdown.replace("retain evidence", "different workflow"), review_confirmed=True))
    return {"trialId": trial["trialId"], "packageDigest": candidate["packageDigest"], "database": str(service.database_path), "skillCharacters": len(markdown), "observed": "Real reviewed sealing, SQLite durability, byte hashes, inactive boundary, immutable replay and unapproved write refusal"}


FAMILIES = {
    "behavior": (_behavior, {"a.behavior-plan", "a.behavior-cache", "a.behavior-gates"}, {"empty", "huge", "unicode", "concurrency", "stale"}),
    "checkpoint": (_checkpoint, {"a.checkpoint-durable"}, {"empty", "huge", "unicode", "concurrency", "stale"}),
    "permissions": (_permissions, {"a.permission-modes"}, {"empty", "huge", "unicode", "concurrency", "permissions"}),
    "artifacts": (_artifacts, {"a.artifact-durable", "a.artifact-relations", "a.artifact-lineage"}, {"empty", "huge", "unicode", "concurrency", "stale"}),
    "catalog": (_catalog, {"a.catalog-observer", "a.catalog-routing", "a.catalog-adapter", "a.capability-plan"}, {"empty", "huge", "unicode", "concurrency", "permissions", "stale"}),
    "challenges": (_challenges, {"a.challenge-catalog", "a.challenge-selection"}, {"empty", "huge", "unicode", "concurrency"}),
    "runs": (_runs, {"a.capability-preview"}, {"empty", "huge", "unicode", "concurrency", "permissions", "stale"}),
    "checkpoint-interruption": (_checkpoint_interruption, {"a.checkpoint-durable"}, {"interrupted"}),
    "factory": (_factory, {"a.factory-draft", "a.factory-package", "a.factory-paths"}, {"empty", "huge", "unicode", "permissions", "stale"}),
    "evolution": (_evolution, {"a.evolution-sealed"}, {"empty", "huge", "unicode", "concurrency", "permissions", "stale"}),
}


def run(root, contracts, categories):
    base = Path(root).resolve()
    rows = []
    for name, (builder, identities, supported) in FAMILIES.items():
        requested = sorted(identities & set(contracts))
        if not requested:
            continue
        for category in categories:
            if category not in supported:
                continue
            scratch = base / f"capabilities-{name}-{category}"
            scratch.mkdir(parents=True, exist_ok=False)
            row = {"id": f"capabilities.{name}.{category}", "category": category, "contracts": requested}
            try:
                row.update(status="passed", detail=builder(scratch, category))
            except Exception as error:
                row.update(status="failed", detail={"error": str(error), "type": type(error).__name__, "scratch": str(scratch), **getattr(error, "fixture_effects", {})})
            rows.append(row)
    return rows


def blocked_reason(identity, category):
    if any(identity in identities and category in supported for _, identities, supported in FAMILIES.values()):
        return None
    for name, (_, identities, supported) in FAMILIES.items():
        if identity not in identities:
            continue
        if category in supported:
            return None
        if category == "offline":
            return {"kind": "not_applicable", "reason": f"{identity} owns local deterministic {name} state; it has no transport or connectivity input. Unavailable adapter execution belongs to separate adapter contracts."}
        if category == "permissions" and name not in {"catalog", "runs", "permissions", "factory", "evolution"}:
            if name in {"checkpoint", "artifacts", "challenges"}:
                return {"kind": "fixture_gap", "reason": f"{identity} needs an actual OS-denied file/directory fixture to observe its {name} error and state boundary. No restricted-principal or denied-ACL fixture is implemented; normal access is not denial proof."}
            return {"kind": "not_applicable", "reason": f"{identity} owns pure compiled behavior content and does not decide permissions; approval admission is separately exercised by a.permission-modes and a.capability-plan."}
        if category == "interrupted" and name in {"permissions", "challenges", "catalog", "behavior"}:
            return {"kind": "not_applicable", "reason": f"{identity} is a read/compute action without persisted partial state or a resumable execution boundary; interrupted writer contracts are exercised separately."}
        return {"kind": "fixture_gap", "reason": f"No reviewed {category} mutation builder yet for exact {identity} {name} behavior; this is not an impossibility claim."}
    if identity.startswith("a.factory-") and identity.endswith("-ui"):
        return {"kind": "fixture_gap", "reason": "Generated app UI needs an authorized actual owned Chromium journey against served assets; its builder remains missing. Local factory files alone cannot prove this exact rendered contract."}
    return None
