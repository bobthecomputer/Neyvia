"""Owned skill, SDK and preference workflows with generated perturbations.

SDK evidence is generated source/manifest evidence, never an invented provider
response. All homes and editable skills belong to the supplied scratch root.
"""
from __future__ import annotations
from .subprocess_utils import hidden_windows_subprocess_kwargs

import argparse
import contextlib
import ctypes
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import typing
import types
import uuid
from dataclasses import asdict
from concurrent.futures import ThreadPoolExecutor

TEXT = {"empty", "huge", "unicode"}
REPO = Path(__file__).resolve().parents[2]


def require(value, message):
    if not value:
        raise AssertionError(message)


def refused(action, classes=(ValueError, RuntimeError, OSError)):
    try:
        action()
    except classes as error:
        return {"type": type(error).__name__, "message": str(error)}
    raise AssertionError("Adverse operation was admitted")


def text(category):
    return "" if category == "empty" else "雪 🧭 café e\u0301 שלום" if category == "unicode" else "x" * 196608 if category == "huge" else "owned evidence workflow"


def parallel(action, count=4):
    with ThreadPoolExecutor(max_workers=count) as pool:
        return list(pool.map(action, range(count)))


def interrupted_guard(root, path):
    """A real owned process dies holding the writer's production guard."""
    script = root / "owned_interrupted_guard.py"
    ready = root / "owned_interrupted_guard.ready"
    script.write_text("import os,sys\nfrom pathlib import Path\nfrom grant_agent.proof_credential_guard import install\nfrom grant_agent.harness_jobs import _exclusive_job_lock\ninstall(Path(sys.argv[1]))\nwith _exclusive_job_lock(Path(sys.argv[2]),timeout_seconds=10):\n Path(sys.argv[3]).write_text(str(os.getpid()))\n os._exit(23)\n", encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=str(REPO / "src"))
    result = subprocess.run([sys.executable, str(script), str(root), str(path), str(ready)], env=env, capture_output=True, text=True, timeout=30, **hidden_windows_subprocess_kwargs())
    require(result.returncode == 23 and ready.is_file(), "Actual owned guard interruption failed: " + result.stderr[-500:])
    return {"pid": int(ready.read_text(encoding="utf-8")), "exit": result.returncode}


@contextlib.contextmanager
def denied_file(path):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.restype = ctypes.c_void_p
    kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.CreateFileW(str(path.resolve()), 0x80000000, 0, None, 3, 0, None)
    require(handle != ctypes.c_void_p(-1).value, "Owned sharing-denial setup failed")
    try:
        yield
    finally:
        kernel.CloseHandle(handle)


def _roots(root):
    from .proof_credential_guard import install
    install(root)
    work, home = root / ".agent_control/proofs/workspace", root / ".agent_control/proofs/home"
    for path in (work, home):
        path.mkdir(parents=True, exist_ok=True)
    return work, home


def _registry(root, category):
    from .skills import SkillRegistry
    from .skill_library import SkillLibrary, load_codex_home_skill_rows
    work, home = _roots(root)
    data = text(category)
    count = 64 if category == "huge" else 0 if category == "empty" else 4
    rows = [{"name": f"owned-verify-{i}", "description": "verify local evidence " + data[:4096], "permissions": ["file_read"], "schema": {}, "examples": [data[:4096]]} for i in range(count)]
    source = work / "skills.json"
    source.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    registry = SkillRegistry(source)
    selected = registry.retrieve("verify " + data, top_k=4)
    require(len(selected) == min(count, 4) and all(skill.name in {row["name"] for row in rows} for skill in selected), "Skill retrieval fabricated or lost selected source records")
    control = work / ".agent_control"
    control.mkdir()
    (control / "workspaces.json").write_text("{}", encoding="utf-8")
    if category != "empty":
        for base, description in ((work, "Project " + data), (home, "Home " + data)):
            path = base / ".codex/skills/owned-guide/SKILL.md"
            path.parent.mkdir(parents=True)
            path.write_text("---\nname: owned-guide\ndescription: " + json.dumps(description, ensure_ascii=False) + "\n---\n\n# Guidance\n" + data, encoding="utf-8")
    discovered = load_codex_home_skill_rows(control, home_root=home)
    require(len(discovered) == (0 if category == "empty" else 1), "Skill discovery duplicate or missing origin")
    if discovered:
        require(discovered[0]["source"]["kind"] == "workspace" and discovered[0]["executionCapable"] is False, "Home shadowed project or guidance became executable")
    library = SkillLibrary(work, registry, home_root=home)
    brief = library.build_skill_brief(task_brief="verify " + data, mission_id="owned-" + data[:20], top_k=4)
    compact = asdict(brief)
    require(compact["mission_id"] == "owned-" + data[:20] and brief.skill_count == len(compact["selected_skills"]) <= 4, "Brief mission binding or count differs")
    if category == "huge":
        require(data not in json.dumps(compact, ensure_ascii=False), "Full instructions leaked into bounded brief")
    catalog = library.build_catalog()
    for name in ("userInstalledSkills", "learnedSkills", "curatedPacks", "recommendedPacks"):
        require(all(row["evolutionSummary"]["humanReviewRequired"] for row in catalog[name]), "Catalog bypassed operator review authority")
    identities = {"sv.skills.retrieval", "sv.skills.discovery", "sv.skills.brief", "sv.skills.catalog"}
    if category == "stale":
        path = work / ".codex/skills/owned-guide/SKILL.md"
        path.write_text("---\nname: owned-guide\ndescription: New saved guidance\n---\n# New\n", encoding="utf-8")
        reloaded = load_codex_home_skill_rows(control, home_root=home)
        require(reloaded[0]["description"] == "New saved guidance", "Discovery returned stale indexed instructions")
        identities = {"sv.skills.discovery"}
    elif category == "permissions":
        path = work / ".codex/skills/owned-guide/SKILL.md"
        with denied_file(path):
            observed = load_codex_home_skill_rows(control, home_root=home)
        require(len(observed) == 1 and observed[0]["source"]["kind"] == "codex_home_skill", "Denied project skill did not disclose permitted home fallback")
        identities = {"sv.skills.discovery"}
    return {"contracts": sorted(identities), "detail": {"sourceRecords": count, "retrieved": len(selected), "briefSkills": brief.skill_count, "guidanceBytes": len(data.encode()), "catalogOnlyGuidance": True}}


def _feedback(root, category):
    from .skills import SkillRegistry
    from .skill_library import SkillLibrary
    work, home = _roots(root)
    library = SkillLibrary(work, SkillRegistry(work / "absent-catalog.json"), home_root=home)
    data = text(category)
    selected = [] if category == "empty" else [{"skillId": "owned-" + data[:180], "label": data, "sourceKind": "workspace"}]
    failures = [data[:4096]] * 128 if category == "huge" else []
    results = []
    def record(index):
        return library.record_slice_feedback(mission_id="owned-" + str(index) + data[:20], step_id="step-" + str(index), selected_skills=selected,
            execution_ok=True, verification_failures=failures, changed_files=["owned.py"])
    if category == "concurrency":
        results = parallel(record)
    else:
        results = [record(index) for index in range(3)]
    records = json.loads(library.feedback_path.read_text(encoding="utf-8"))
    expected = [row for group in results for row in group]
    require(len(records) == len(expected) and {row["feedbackId"] for row in records} == {row["feedbackId"] for row in expected}, "Real feedback appends lost durable records")
    require(all(row["verificationFailureCount"] == len(failures) for row in records), "Feedback failure attribution changed")
    skill = (selected or [{"skillId": "repo_scan"}])[0]
    summary = library._feedback_summary(skill, skill["skillId"])
    require(summary["promotionGate"]["humanReviewRequired"] and not summary["promotionGate"]["eligible"], "Observed usage promoted skills without review")
    if category == "permissions":
        before = library.feedback_path.read_bytes()
        with denied_file(library.feedback_path):
            error = refused(lambda: record(99), (OSError,))
        require(library.feedback_path.read_bytes() == before, "Denied feedback persistence changed prior bytes")
        return {"contracts": ["sv.skills.feedback"], "detail": {"denied": error, "preservedSha256": hashlib.sha256(before).hexdigest()}}
    if category == "stale":
        library = SkillLibrary(work, SkillRegistry(work / "absent-catalog.json"), home_root=home)
        summary = library._feedback_summary(skill, skill["skillId"])
        require(summary["trend"] == "stagnant", "Restart forgot observed zero-improvement history")
    return {"contracts": ["sv.skills.feedback", "sv.skills.feedback-summary"], "detail": {"persistedRecords": len(records), "actions": [row["nextAction"] for row in records], "trend": summary["trend"], "reviewRequired": True}}


def _skill_writes(root, category):
    from .web_backend import _create_codex_skill, _save_codex_skill_file
    work, home = _roots(root)
    data = text(category)
    initial = {"name": "owned-workflow", "description": "Preserve observed local receipts " + data[:300], "instructions": "1. Inspect owned state.\n2. Verify exact receipts.\n" + data, "scope": "project"}
    if category == "empty":
        refused(lambda: _create_codex_skill({}, root=work, home_root=home))
        require(not (work / ".codex/skills").exists(), "Empty skill creation wrote a partial directory")
    created = _create_codex_skill(initial, root=work, home_root=home)
    path = Path(created["path"])
    original = path.read_bytes()
    history = Path(created["evolutionReceiptPath"])
    require(hashlib.sha256(original).hexdigest() == created["afterSha256"] and json.loads(history.read_text(encoding="utf-8"))[0]["receiptId"] == created["receiptId"], "Real skill creation lacks exact interface/hash/history")
    interruption = None
    if category == "interrupted":
        before_history = history.read_bytes()
        interruption = interrupted_guard(root, history)
        require(path.read_bytes() == original and history.read_bytes() == before_history, "Writer interruption altered prior skill/history before admission")
    if category == "permissions":
        with denied_file(path):
            error = refused(lambda: _save_codex_skill_file({"path": str(path), "content": original.decode("utf-8") + "\nchanged\n"}, root=work, home_root=home))
        require(path.read_bytes() == original, "Denied save changed original skill bytes")
        return {"contracts": ["sv.skills.save"], "detail": {"denied": error, "preservedSha256": created["afterSha256"]}}
    if category == "empty":
        before_history = history.read_bytes()
        refused(lambda: _save_codex_skill_file({"path": str(path), "content": ""}, root=work, home_root=home))
        require(path.read_bytes() == original and history.read_bytes() == before_history, "Empty save changed content/history")
    content = original.decode("utf-8") + "\n## Observed result\n" + (data or "exact local receipt") + "\n"
    if category == "concurrency":
        outcomes = parallel(lambda index: _save_codex_skill_file({"path": str(path), "content": content + str(index) + "\n"}, root=work, home_root=home))
        records = json.loads(history.read_text(encoding="utf-8"))
        require(sorted(row["revision"] for row in outcomes) == [1, 2, 3, 4] and len(records) == 5, "Concurrent skill saves lost monotone revisions or history")
        creations = parallel(lambda index: _create_codex_skill({**initial, "name": f"owned-other-{index}"}, root=work, home_root=home))
        durable = json.loads(history.read_text(encoding="utf-8"))
        require(len(durable) == 9 and all(any(row["receiptId"] == created["receiptId"] for row in durable) for created in creations), "Concurrent distinct skill creation lost shared evolution history")
    else:
        saved = _save_codex_skill_file({"path": str(path), "content": content}, root=work, home_root=home)
        require(Path(saved["backupPath"]).read_bytes() == original and saved["revision"] == 1 and hashlib.sha256(path.read_bytes()).hexdigest() == saved["afterSha256"], "Reviewed save lost prior bytes or manufactured revision")
        outcomes = [saved]
    before = (path.read_bytes(), history.read_bytes())
    unchanged = _save_codex_skill_file({"path": str(path), "content": path.read_text(encoding="utf-8")}, root=work, home_root=home)
    require(not unchanged["changed"] and (path.read_bytes(), history.read_bytes()) == before, "Identical restart save altered durable content/history")
    if category == "stale":
        refused(lambda: _create_codex_skill(initial, root=work, home_root=home))
        require((path.read_bytes(), history.read_bytes()) == before, "Stale duplicate creation altered existing skill")
    return {"contracts": ["sv.skills.save"] if category == "interrupted" else ["sv.skills.create", "sv.skills.save"], "detail": {"skillSha256": hashlib.sha256(path.read_bytes()).hexdigest(), "instructionBytes": len(original), "savedRevisions": [row["revision"] for row in outcomes], "idempotentReplayPreserved": True, "interruption": interruption}}


def _sdk_bindings(root, category):
    from .sdk_codegen import generated_bindings, generate_sdk_bindings, PYTHON_OUTPUT, TYPESCRIPT_OUTPUT
    work, _ = _roots(root)
    config = work / "config"
    config.mkdir()
    for name in ("neyvia_module_manifest_schema.json", "neyvia_application_surface_schema.json"):
        shutil.copyfile(REPO / "config" / name, config / name)
    module = config / "neyvia_module_manifest_schema.json"
    schema = json.loads(module.read_text(encoding="utf-8"))
    values = [""] if category == "empty" else [text(category)] if category == "unicode" else [f"{i}-" + "x" * 256 for i in range(512)] if category == "huge" else ["owned-value"]
    schema["properties"]["edgeFixture"] = {"type": "string", "enum": values}
    module.write_text(json.dumps(schema, ensure_ascii=False), encoding="utf-8")
    generated = generated_bindings(work)
    interruption = None
    if category == "interrupted":
        (work / ".agent_control").mkdir(exist_ok=True)
        interruption = interrupted_guard(root, work / ".agent_control/sdk-binding-generation")
    if category == "concurrency":
        receipts = parallel(lambda _: generate_sdk_bindings(work))
    else:
        receipts = [generate_sdk_bindings(work)]
    require(all(receipt["ok"] for receipt in receipts) and all((work / path).read_bytes() == content for path, content in generated.items()), "Generated SDK receipt differs from actual bytes")
    namespace = types.ModuleType("owned_generated_" + uuid.uuid4().hex)
    sys.modules[namespace.__name__] = namespace
    try:
        exec(compile((work / PYTHON_OUTPUT).read_bytes(), str(work / PYTHON_OUTPUT), "exec"), namespace.__dict__)
        hints = typing.get_type_hints(namespace.NeyviaModuleManifest)
        annotation = hints["edgeFixture"]
        if typing.get_origin(annotation) in {typing.NotRequired, typing.Required}:
            annotation = typing.get_args(annotation)[0]
        require(typing.get_args(annotation) == tuple(values), "Generated Python literals weakened exact portable choices")
    finally:
        sys.modules.pop(namespace.__name__, None)
    if category == "stale":
        target = work / PYTHON_OUTPUT
        target.write_bytes(target.read_bytes() + b"\n# stale bytes\n")
        require(not generate_sdk_bindings(work, check=True)["ok"], "SDK checker accepted stale source bytes")
        require(generate_sdk_bindings(work)["ok"], "SDK could not regenerate stale source")
    if category == "permissions":
        target = work / PYTHON_OUTPUT
        before = target.read_bytes()
        with denied_file(target):
            error = refused(lambda: generate_sdk_bindings(work), (OSError,))
        require(target.read_bytes() == before, "Denied SDK replacement altered locked generated bytes")
        return {"contracts": ["sv.sdk.generation"], "detail": {"denied": error, "preservedSha256": hashlib.sha256(before).hexdigest()}}
    command = ["node", str(REPO / "node_modules/typescript/bin/tsc"), "--noEmit", "--skipLibCheck", "--target", "ES2022", "--module", "NodeNext", "--moduleResolution", "NodeNext", str(work / TYPESCRIPT_OUTPUT)]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=45, **hidden_windows_subprocess_kwargs())
    require(completed.returncode == 0, "Actual generated TypeScript compilation failed: " + completed.stdout[-500:] + completed.stderr[-500:])
    return {"contracts": ["sv.sdk.generation"] if category in {"interrupted", "stale", "concurrency"} else ["sv.sdk.bindings", "sv.sdk.generation", "sv.sdk.portable-schema"], "detail": {"literalChoices": len(values), "outputs": receipts[-1]["outputs"], "typeScriptExit": completed.returncode, "pythonImportResolved": True, "interruption": interruption}}


def _sdk_manifest(root, category):
    from .sdk import build_app_manifest, write_app_manifest
    work, _ = _roots(root)
    data = text(category)
    count = 32 if category == "huge" else 0 if category == "empty" else 3
    tasks = [{"task_id": f"owned-{i}", "label": data[:300], "description": data[:8192], "requires_approval": True} for i in range(count)]
    hooks = [{"hook_id": f"write-{i}", "label": data[:300], "description": data[:8192], "mutability": "write"} for i in range(count)]
    manifest = build_app_manifest(app_id=data[:64], name=data, description=data, endpoint="http://127.0.0.1:48749/", tasks=tasks, context_surfaces=[], action_hooks=hooks)
    target = write_app_manifest(work / "manifest.json", manifest)
    require(json.loads(target.read_text(encoding="utf-8")) == manifest and
            all(all(saved[key] == value for key, value in declared.items()) for saved, declared in zip(manifest["tasks"], tasks, strict=True)) and
            all(all(saved[key] == value for key, value in declared.items()) for saved, declared in zip(manifest["action_hooks"], hooks, strict=True)), "SDK manifest disk round trip lost declared action authority/content")
    require(manifest["bridge"]["endpoint"] == "http://127.0.0.1:48749", "SDK bridge endpoint changed")
    return {"contracts": ["sv.sdk.manifest"], "detail": {"tasks": count, "manifestBytes": target.stat().st_size, "sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "contactedEndpoint": False}}


def _capsules(root, category):
    from .skill_capsules import SkillCapsuleRegistry
    work, _ = _roots(root)
    data = text(category)
    instruction = work / ".codex/skills/owned-guide/SKILL.md"
    instruction.parent.mkdir(parents=True)
    instruction.write_text(data, encoding="utf-8")
    (work / "config").mkdir()
    definition = {"id": "owned-guide", "label": "Observed " + data[:300], "instructionPaths": [str(instruction.relative_to(work))],
                  "requiredToolScopes": ["file.read"], "proofGates": ["receipt_integrity"], "phaseBindings": {"verify": ["observe bytes"]},
                  "minimumEvidence": 1, "executableChecks": [[sys.executable, "-c", "print('owned verification')"]]}
    (work / "config/neyvia_skill_capsules.json").write_text(json.dumps({"capsules": [definition]}, ensure_ascii=False), encoding="utf-8")
    registry = SkillCapsuleRegistry(work)
    selected = [] if category == "empty" else ["owned-guide", "missing-owned-guide"]
    plans = parallel(lambda _: registry.compile(selected)) if category == "concurrency" else [registry.compile(selected)]
    plan = plans[0]
    require(all(row == plan for row in plans), "Actual concurrent capsule readers observed divergent plans")
    if category == "empty":
        require(not plan["skills"] and not plan["instructionReceipts"] and not plan["executableChecks"], "Empty capsule selection acquired scopes/checks")
    else:
        receipt = plan["instructionReceipts"][0]
        require(receipt["available"] and receipt["sha256"] == hashlib.sha256(instruction.read_bytes()).hexdigest() and
                plan["missingSkillIds"] == ["missing-owned-guide"] and plan["requiredToolScopes"] == ["file.read"], "Capsule lost source digest, missing declaration or tool authority")
        require(plan["executableChecks"] == definition["executableChecks"], "Instruction capsule invented executed check evidence")
    if category == "permissions":
        before = instruction.read_bytes()
        with denied_file(instruction):
            error = refused(lambda: registry.compile(selected), (OSError,))
        require(instruction.read_bytes() == before, "Denied capsule compile changed instructions")
        return {"contracts": ["sv.skills.capsule"], "detail": {"denied": error, "preservedSha256": hashlib.sha256(before).hexdigest(), "checksExecuted": 0}}
    if category == "stale":
        instruction.write_text("New independently observed instruction", encoding="utf-8")
        newer = registry.compile(selected)
        require(newer["planHash"] != plan["planHash"] and newer["instructionReceipts"][0]["sha256"] == hashlib.sha256(instruction.read_bytes()).hexdigest(), "Capsule restart retained stale instruction identity")
        plan = newer
    return {"contracts": ["sv.skills.capsule"], "detail": {"planHash": plan["planHash"], "instructionBytes": len(data.encode()), "missing": plan["missingSkillIds"], "checksExecuted": 0}}


def _preferences(root, category):
    from . import cli
    from .models import Mission
    from datetime import datetime, timezone, timedelta
    from .proofs_a_cli_scheduler import environment
    work, _ = _roots(root)
    data = text(category)
    now = datetime(2026, 10, 4, 12, tzinfo=timezone.utc)
    objective = "" if category == "empty" else data + " run for 7 minutes"
    budget = cli._mission_budget_settings(objective, 0, "pause_on_failure", now=now)
    require(budget["max_runtime_seconds"] == (0 if category == "empty" else 420), "Preference timer lost objective semantics")
    if category != "empty":
        require(datetime.fromisoformat(budget["deadline_at"]) == now + timedelta(seconds=420), "Timer deadline differs from requested duration")
    mission = Mission(mission_id="owned", workspace_id="scratch", runtime_id="local", objective=data, success_checks=[])
    mission.run_budget.run_until_behavior = "continue_until_blocked"
    with environment(FLUXIO_MISSION_POLL_SECONDS="" if category == "empty" else "1000000" if category == "huge" else data if category == "unicode" else "3"):
        poll = cli._mission_poll_interval_seconds(mission)
    require(poll >= 1, "Continuation poll lost safe positive deadline")
    mission.state.status = "blocked" if category == "stale" else "running"
    mission.title = data
    compact = cli._compact_mission_action_payload(mission)
    require(compact["mission"]["mission_id"] == "owned" and compact["mission"]["title"] == data and compact["mission"]["state"]["status"] == mission.state.status and "snapshot" not in compact, "Compact preference receipt invented mission state or embedded full snapshot")
    mission.run_budget.run_until_behavior = "pause_on_failure"
    require(cli._mission_poll_interval_seconds(mission) == 0, "Inactive continuation still scheduled polling")
    require(not cli._mission_should_continue_after_result(mission, {"status": "ok", "autopilot_status": "paused", "autopilot_pause_reason": "delegated_runtime_running", "remaining_steps": [data]}), "Delegated runtime caused duplicate continuation loop")
    identities = ["a-cli.preferences.budget", "a-cli.preferences.poll", "a-cli.preferences.compact"]
    if category == "stale":
        identities = ["a-cli.preferences.compact", "a-cli.preferences.continue"]
    elif category == "empty":
        identities.append("a-cli.preferences.continue")
    return {"contracts": identities, "detail": {"inputCharacters": len(data), "runtimeSeconds": budget["max_runtime_seconds"], "pollSeconds": poll, "status": compact["mission"]["state"]["status"], "providerCalls": 0}}


def _workspace(root, category):
    from . import cli
    from .mission_control import ControlRoomStore
    work, _ = _roots(root)
    data = text(category)
    values = argparse.Namespace(root=str(work), path=str(work), name=data, default_runtime="hermes", user_profile="builder",
        preferred_harness="fluxio_hybrid", routing_strategy="uniform_quality", route_overrides_json="[]", auto_optimize_routing="true",
        openai_codex_auth_mode="none", minimax_auth_mode="none", commit_message_style="detailed", execution_target_preference="workspace_root",
        workspace_id=None, skip_snapshot=True)
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = cli.cmd_workspace_save(values)
    payload = json.loads(output.getvalue())
    workspace = payload["workspace"]
    stored = ControlRoomStore(work).get_workspace(workspace["workspace_id"])
    require(code == 0 and stored is not None and asdict(stored) == workspace and "snapshot" not in payload and
            stored.preferred_harness == values.preferred_harness and stored.routing_strategy == values.routing_strategy and stored.auto_optimize_routing,
            "Actual workspace command lost saved preferences or acquired snapshot/provider effects")
    require(stored.name == data, "Workspace command changed declared name")
    if category == "stale":
        values.workspace_id = stored.workspace_id
        values.name = "Updated saved preference"
        values.preferred_harness = "legacy_autonomous_engine"
        with contextlib.redirect_stdout(io.StringIO()):
            require(cli.cmd_workspace_save(values) == 0, "Saved preference update failed")
        restored = ControlRoomStore(work).get_workspace(stored.workspace_id)
        require(restored.name == values.name and restored.preferred_harness == values.preferred_harness, "Fresh CLI store retained stale preference")
    return {"contracts": ["a-cli.preferences.workspace"], "detail": {"workspaceId": stored.workspace_id, "nameCharacters": len(data), "snapshotRequested": False,
            "savedHarness": values.preferred_harness, "autoSyncToNas": stored.auto_sync_to_nas, "providerCalls": 0}}


FAMILIES = {
    "workspace": (_workspace, {"a-cli.preferences.workspace"}, TEXT | {"stale"}),
    "capsules": (_capsules, {"sv.skills.capsule"}, TEXT | {"stale", "permissions", "concurrency"}),
    "skills-read": (_registry, {"sv.skills.retrieval", "sv.skills.discovery", "sv.skills.brief", "sv.skills.catalog"}, TEXT | {"stale", "permissions"}),
    "feedback": (_feedback, {"sv.skills.feedback", "sv.skills.feedback-summary"}, TEXT | {"stale", "concurrency", "permissions"}),
    "skill-writes": (_skill_writes, {"sv.skills.create", "sv.skills.save"}, TEXT | {"stale", "concurrency", "permissions", "interrupted"}),
    "sdk-bindings": (_sdk_bindings, {"sv.sdk.bindings", "sv.sdk.generation", "sv.sdk.portable-schema"}, TEXT | {"stale", "concurrency", "permissions", "interrupted"}),
    "sdk-manifest": (_sdk_manifest, {"sv.sdk.manifest"}, TEXT),
    "preferences": (_preferences, {"a-cli.preferences.budget", "a-cli.preferences.poll", "a-cli.preferences.compact", "a-cli.preferences.continue"}, TEXT | {"stale"}),
}

PAIR_CATEGORIES = {
    **{identity: TEXT for identity in ("sv.skills.retrieval", "sv.skills.brief", "sv.skills.catalog", "sv.sdk.bindings", "sv.sdk.portable-schema", "sv.sdk.manifest", "a-cli.preferences.budget", "a-cli.preferences.poll")},
    "sv.skills.discovery": TEXT | {"stale", "permissions"},
    "sv.skills.feedback": TEXT | {"stale", "concurrency", "permissions"},
    "sv.skills.feedback-summary": TEXT | {"stale", "concurrency"},
    "sv.skills.create": TEXT | {"stale", "concurrency"},
    "sv.skills.save": TEXT | {"stale", "concurrency", "permissions", "interrupted"},
    "sv.skills.capsule": TEXT | {"stale", "permissions", "concurrency"},
    "sv.sdk.generation": TEXT | {"stale", "permissions", "concurrency", "interrupted"},
    "a-cli.preferences.compact": TEXT | {"stale"},
    "a-cli.preferences.continue": {"empty", "stale"},
    "a-cli.preferences.workspace": TEXT | {"stale"},
}


def run(root, contracts, categories):
    base = Path(root).resolve()
    base.mkdir(parents=True, exist_ok=True)
    rows = []
    for family, (builder, identities, supported) in FAMILIES.items():
        if not identities.intersection(contracts):
            continue
        for category in categories:
            if category not in supported:
                continue
            target = base / f"{family}-{category}-{uuid.uuid4().hex[:8]}"
            target.mkdir()
            row = {"id": f"preferences-skills:{family}:{category}", "category": category, "scratchRoot": str(target), "boundary": "actual owned production skill/config/source generation effect with independent disk/type observations"}
            try:
                row.update(status="passed", **builder(target, category))
            except Exception as error:
                row.update(status="failed", contracts=sorted(identities), detail={"error": str(error), "type": type(error).__name__, **getattr(error, "fixture_effects", {})})
            row["contracts"] = [identity for identity in row["contracts"] if identity in contracts]
            rows.append(row)
    return rows


def blocker(contract, category):
    identity = contract["id"]
    for family, (_, identities, supported) in FAMILIES.items():
        if identity not in identities:
            continue
        if category in PAIR_CATEGORIES[identity]:
            return None
        if category == "offline":
            return {"kind": "not_applicable", "reason": f"Audited {identity} {family} owner uses local skill/config/generated source only and has no transport; real SDK HTTP delivery is governed by sv.sdk.transport."}
        if family in {"preferences", "sdk-manifest"} and category in {"concurrency", "interrupted", "permissions"}:
            return {"kind": "not_applicable", "reason": f"Audited {identity} is a synchronous caller-owned value builder without shared process state, asynchronous interruption or authority grants. Durable writers are separate contracts."}
        if identity in {"sv.skills.retrieval", "sv.skills.brief", "sv.skills.catalog", "sv.skills.discovery", "sv.skills.capsule", "sv.sdk.bindings", "sv.sdk.portable-schema"} and category == "interrupted":
            return {"kind": "not_applicable", "reason": f"Audited {identity} is a synchronous reader/compiler with no owned durable mutation; process termination cannot leave a partial write. Actual interrupted skill save and SDK output generation are proved separately."}
        return {"kind": "fixture_gap", "reason": f"Exact {identity}/{category} still needs an additional real {family} effect builder; another completed workflow is not coverage."}
    if identity.startswith("a-cli.preferences.") or identity in {"sv.sdk.transport", "sv.sdk.plan-only", "sv.skills.capsule", "a-cli.catalog.selection"}:
        return {"kind": "fixture_gap", "reason": f"Audited exact owner for {identity} requires a separate real command/runtime/capsule workflow for {category}; controlled provider responses and runtime detector substitutions are not accepted semantic proof."}
    return None


if __name__ == "__main__":
    from .edge_contracts import inventory
    started = time.monotonic()
    _, contracts = inventory()
    rows = run(Path(sys.argv[1]), contracts, ["empty", "huge", "unicode", "concurrency", "interrupted", "permissions", "offline", "stale"])
    report = {"schema": "neyvia.c7b.preferences-skills.v1", "ok": all(row["status"] == "passed" for row in rows), "rows": rows,
              "passedPairs": len({(identity, row["category"]) for row in rows if row["status"] == "passed" for identity in row["contracts"]}), "durationMs": round((time.monotonic() - started) * 1000)}
    Path(sys.argv[2]).write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "rows"}))
    sys.exit(0 if report["ok"] else 1)
