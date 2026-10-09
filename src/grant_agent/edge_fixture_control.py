"""Generated control-room and local harness feature mutations.

Only direct calls at reviewed contract owners are bound. No aggregate self-check
is relabelled as an edge campaign; the fixtures observe durable bytes and local
projection facts and never launch a provider or inspect an operator home.
"""
from __future__ import annotations

import hashlib
import json
import os
import struct
import subprocess
import sys
import threading
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

TEXTS = {"empty": "", "huge": "receipt " * 10000,
         "unicode": "雪🙂e\u0301\u202e العربية\x00"}
CONTROL_PURE = {"mode", "title", "scope", "budget", "verification",
                "mission-counts", "workspace-queue", "git-actions", "storage-triage",
                "goal-audit", "loss-audit", "release-quality"}
CONTROL_FILES = {"workspaces", "events", "cache", "replace-lock", "images",
                 "attachment", "evidence", "validation-actions", "preview", "queue", "delete"}
HARNESS_TEXT = {"identity", "lifecycle", "observation", "public-profile",
                "instruction", "model-policy", "budget-input", "gateway"}


def blocker(contract, category):
    identity = contract.get("id", "")
    pure = {"proofs-c.control." + name for name in CONTROL_PURE}
    pure |= {"proofs-b.harness.model-policy", "proofs-b.harness.budget-input"}
    if identity in pure and category in {"concurrency", "interrupted", "permissions", "offline", "stale"}:
        return {"kind": "not_applicable", "reason":
                f"{identity} is the audited deterministic argument-only projector/parser at "
                f"{contract.get('checkedAt', [])}; it does not acquire a grant, launch a worker, "
                f"read network or durable state, or accept revision tokens for {category}."}
    # Only owners whose checked input is genuinely pure get a blanket category
    # exclusion. File-backed projections are exercised after their inputs move.
    projection_only = {
        "proofs-c.control.proof-digest": "ControlRoomStore._mission_proof_digest_payload",
        "proofs-c.control.progress": "ControlRoomStore._mission_summary_payload",
        "proofs-c.control.overnight": "ControlRoomStore._overnight_progress_projection",
        "proofs-c.control.mission-loop": "build_mission_loop_snapshot",
        "proofs-c.control.harness-summary": "build_summary_harness_lab_snapshot",
        "proofs-c.control.notifications": "ControlRoomStore._build_notification_feed",
        "proofs-c.control.route-trust": "_build_route_trust_coverage_summary",
    }
    if identity in projection_only and category in {"concurrency", "interrupted", "permissions"} and identity != "proofs-c.control.notifications":
        return {"kind": "not_applicable", "reason":
                f"{identity} checked owner {projection_only[identity]} consumes an already materialized mission value and has no durable mutation boundary to interrupt or authorize; backing-store readers are separately checked at their file owners ({contract.get('checkedAt', [])})."}
    if identity == "proofs-c.control.notifications" and category == "offline":
        return {"kind": "not_applicable", "reason":
                f"{projection_only[identity]} hydrates only local runtime-session JSON and supplied activity; it makes no endpoint call, so remote connectivity is not an input to this notification contract ({contract.get('checkedAt', [])})."}
    if identity in {"proofs-c.control.mission-loop", "proofs-c.control.overnight"} and category == "stale":
        return {"kind": "not_applicable", "reason":
                f"{identity} checked owner {projection_only[identity]} recomputes synchronously from caller-owned Mission values on each call; it has no retained snapshot, filesystem read, cursor, or revision cache that can become stale ({contract.get('checkedAt', [])})."}
    if identity == "proofs-c.control.queue" and category == "concurrency":
        return {"kind": "not_applicable", "reason":
                f"{identity} checked owner mutates only the list supplied by one caller and owns no shared queue store or lock; caller-level synchronization is outside this function contract ({contract.get('checkedAt', [])})."}
    # These checked methods only read local files or rebalance caller-owned
    # objects in memory. They expose no durable mutation boundary to interrupt
    # or serialize, and accept no revision token. Their normal feature cases
    # independently assert returned data against the underlying local source.
    read_only = {
        "proofs-c.control.workspaces": "ControlRoomStore.load_workspaces",
        "proofs-c.control.events": "ControlRoomStore.recent_events",
        "proofs-c.control.cache": "ControlRoomStore._load_json",
        "proofs-c.control.images": "_build_generated_image_artifacts_snapshot",
        "proofs-c.control.evidence": "_recover_evidence_path",
        "proofs-c.control.preview": "mission_artifact_manifest_preview_url",
        "proofs-c.control.validation-actions": "_build_validation_actions",
        "proofs-c.control.queue": "ControlRoomStore._rebalance_workspace_queue_in_place",
    }
    if identity in read_only and category == "interrupted" and identity not in {"proofs-c.control.workspaces", "proofs-c.control.cache", "proofs-c.control.events"}:
        return {"kind": "not_applicable", "reason":
                f"{identity} checked owner {read_only[identity]} only performs a bounded local observation and has no durable mutation to resume; its file-presence/read behavior is verified separately ({contract.get('checkedAt', [])})."}
    if identity in {"proofs-c.control.cache", "proofs-c.control.events"} and category == "interrupted":
        return {"kind": "not_applicable", "reason":
                f"{identity} checked owner {read_only[identity]} performs a read only and commits no state; terminating a caller cannot leave a partial durable effect or resumable operation ({contract.get('checkedAt', [])})."}
    if identity == "proofs-c.control.notifications" and category == "interrupted":
        return {"kind": "not_applicable", "reason":
                f"{projection_only[identity]} only reads the runtime ledger and builds a returned list; the interrupted caller has no write or resumable notification side effect ({contract.get('checkedAt', [])})."}
    if identity in read_only and category == "stale" and identity not in {"proofs-c.control.workspaces", "proofs-c.control.cache", "proofs-c.control.events", "proofs-c.control.images", "proofs-c.control.evidence", "proofs-c.control.preview"}:
        return {"kind": "not_applicable", "reason":
                f"{identity} checked owner {read_only[identity]} consumes an in-memory collection with no retained revision/cache token; changing durable inputs cannot stale that caller-owned value ({contract.get('checkedAt', [])})."}
    if identity in read_only and category == "permissions" and identity in {"proofs-c.control.images", "proofs-c.control.evidence"}:
        return {"kind": "not_applicable", "reason":
                f"{identity} checked owner {read_only[identity]} uses filesystem metadata (exists/stat) and does not open the image/evidence payload; Windows sharing denial cannot deny that metadata query, so this exact owner has no file-handle permission boundary ({contract.get('checkedAt', [])})."}
    if identity == "proofs-c.control.queue" and category == "permissions":
        return {"kind": "not_applicable", "reason":
                f"{read_only[identity]} mutates only caller-owned Mission objects in memory and opens no protected resource; filesystem permission denial cannot affect this checked function ({contract.get('checkedAt', [])})."}
    no_revision = {
        "proofs-c.control.attachment": "attach_verifier_proof_bundle(root, mission_id, flow_id, artifacts)",
        "proofs-c.control.delete": "ControlRoomStore.delete_workspace(workspace_id)",
        "proofs-c.control.replace-lock": "ControlRoomStore._write_json_if_changed(path, payload)",
    }
    if identity in no_revision and category == "stale" and identity not in {"proofs-c.control.attachment", "proofs-c.control.delete"}:
        return {"kind": "not_applicable", "reason":
                f"{identity} owner {no_revision[identity]} at {contract.get('checkedAt', [])} "
                "accepts no observed revision, cursor, or compare-and-swap token to reuse after "
                "a state change; its direct behavior is covered by independent effect checks."}
    # Every remaining control contract is explicitly local by its checked
    # owner; none establishes or calls a remote endpoint. Offline behavior is
    # therefore outside the contract's effects, while local failure behavior
    # remains covered by its ordinary and permission/concurrency cases.
    local_control = {"proofs-c.control." + name for name in CONTROL_FILES}
    local_control |= {"proofs-c.control." + name for name in CONTROL_PURE}
    local_control |= set(projection_only)
    if identity in local_control and category == "offline" and identity != "proofs-c.control.notifications":
        return {"kind": "not_applicable", "reason":
                f"{identity} checked owner {contract.get('checkedAt', [])} performs only a local filesystem/value operation and makes no endpoint call; offline state has no input to this contract."}
    return None


def _require(condition, detail):
    if not condition:
        raise AssertionError(detail)


def _reject(action, detail, types=(ValueError, RuntimeError)):
    try:
        action()
    except types:
        return
    raise AssertionError(detail)


def _mission(identity, objective="", status="draft"):
    from .models import Mission
    row = Mission(mission_id=identity, workspace_id="fixture", runtime_id="manual-local",
                  objective=objective, success_checks=[])
    row.state.status = status
    return row


def _store(root):
    from .mission_control import ControlRoomStore
    store = ControlRoomStore(root)
    _require(store.root == root.resolve(), "scratch authority redirected outside owned root")
    return store


def _png():
    def chunk(name, value):
        return struct.pack(">I", len(value)) + name + value + struct.pack(">I", zlib.crc32(name + value) & 0xffffffff)
    pixels = b"".join(b"\x00" + bytes([index, 90, 180]) * 16 for index in range(16))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 16, 16, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(pixels, 0)) + chunk(b"IEND", b"")


def _control_pure(kind, category, text):
    from . import mission_control as c
    from .models import MissionRunBudget
    if kind == "mode":
        for source, expected in [(text, "autopilot"), (" FOCUS ", "fast"), ("Deep Run", "deep_run"), ("Research", "swarms")]:
            _require(c.mission_mode_to_engine_mode(source) == expected, "mode vocabulary or fallback changed")
    elif kind == "title":
        result = c._mission_title(text)
        _require(result == ("New Mission" if category == "empty" else "E" if category == "unicode" else "Receipt receipt receipt receipt receipt receipt"), "generated title fallback/significant token bound differs")
        _require(c._mission_title("Please repair " + text + " durable receipt.").split()[0] == "Repair", "prompt filler retained")
    elif kind == "scope":
        path = "generated/" + ("unicode-雪🙂é" if category == "unicode" else "x" * 200 if category == "huge" else "empty")
        result = c.infer_planned_file_scope(f"Source: `read-only/source`\nFusion workspace: `{path}`\nFusion workspace: `{path}`", [])
        _require(result == [path], "scope lost explicit workspace, duplicated it or admitted source")
        _require(c.infer_planned_file_scope(text, []) == [], "ordinary prose became edit scope")
    elif kind == "budget":
        row = _mission("budget", text)
        row.created_at = "2026-10-02T22:00:00Z"
        row.run_budget = MissionRunBudget(mode="Autopilot", max_runtime_seconds=0 if category == "empty" else 999999,
                                         deadline_at="2026-10-03T08:00:00Z", enforced=True)
        result = c.mission_time_budget_window(row, now=datetime(2026, 10, 3, 1, tzinfo=timezone.utc))
        _require(tuple(result[key] for key in ("maxRuntimeSeconds", "elapsedSeconds", "remainingSeconds")) == (36000, 10800, 25200), "explicit deadline lost to nominal budget")
    elif kind == "verification":
        row = _mission("verification", text)
        if category != "empty":
            row.proof.failed_checks = [{"checkId": text, "detail": "wrong-priority"}, {"title": "second"}, {"title": "must-not-render"}]
            expected = "Failed: " + text.strip() + ", second"
        else:
            expected = "Verification failed."
        _require(c._verification_summary_for_mission(row, "failed") == expected, "failure label priority, count or bytes differ")
    elif kind in {"mission-counts", "workspace-queue"}:
        rows = [] if category == "empty" else [_mission(f"m-{i}", text, ("running", "queued", "blocked", "completed")[i % 4]) for i in range(400 if category == "huge" else 4)]
        for row in rows:
            if row.state.status == "queued":
                row.state.queue_position = 1
        if kind == "mission-counts":
            result = c._control_mission_counts_projection(rows)
            expected = len(rows) // 4
            _require(result["queued"] == expected and result["blocked"] == expected and result["attention"] == expected, "lifecycle counters differ from supplied rows")
        else:
            result = c._control_workspace_queue_projection("fixture", rows)
            _require(result["missionCount"] == len(rows) and result["queuedMissionIds"] == [row.mission_id for row in rows if row.state.status == "queued"], "workspace queue omitted/mixed supplied owners")
            _require(result["activeMissionId"] == ("m-0" if rows else ""), "active workspace owner differs")
    elif kind == "git-actions":
        if category == "empty":
            _require(c._build_git_actions({}, {}) == [], "non-repository exposes git mutations")
        else:
            result = c._build_git_actions({"repoDetected": True, "trackingBranch": text, "dirty": True, "remotes": [{"name": text}], "suggestedCommitMessage": text}, {})
            _require([row["actionId"] for row in result] == ["inspect_repo_state", "pull_branch", "commit_changes", "push_branch"], "git suggestion order changed")
            _require(result[1]["command"] == "git pull --ff-only" and result[1]["requiresApproval"] and result[3]["requiresApproval"], "git projection widens authority")
    elif kind == "storage-triage":
        result = c._storage_triage_summary(nas_storage_pressure={"probeConnectFailed": True, "measuredUsageAvailable": False, "status": "probe_connect_failed", "mount": text}, nas_storage_cleanup_plan={})
        _require(result["status"] != "blocked" and not result["measuredUsageAvailable"] and not result["destructiveActionsExecuted"] and any(row["severity"] == "warn" for row in result["rows"]), "unknown recorded capacity became measured blockage/destruction")
    elif kind == "release-quality":
        values = (0, 0, 0, 0, 0, 0, 0) if category == "empty" else (999999, 999999, 999999, 999999, -999999, 999999, 999999) if category == "huge" else (13, 20, 30, 25, 17, 61, 80)
        result = c._release_quality_score(**dict(zip(("completion_rate", "delegated_run_rate", "resume_run_rate", "resume_completion_rate", "verification_pause_rate", "completed_or_continuing_rate", "resume_completed_or_continuing_rate"), values)))
        _require(result == (38 if category == "empty" else 100 if category == "huge" else 66), "bounded release-quality components differ from recorded facts")
    elif kind == "loss-audit":
        count = 0 if category == "empty" else 400 if category == "huge" else 3
        scores = [{"category": f"category-{i}-" + text[:20], "fluxioScore": i % 21, "t3Score": 15} for i in range(count)]
        result = c._system_loss_breakdown(categories=scores, deficits=[], score_cap_reason=text,
                                         route_trust={}, red_summary={}, release={}, live_progress={})
        expected = round(max(0, 20 - round(sum(i % 21 for i in range(count)) / max(1, count), 1)), 1)
        _require(result["averageLossOutOf20"] == expected,
                 f"numeric zero scored category excluded: expected loss {expected}, observed {result['averageLossOutOf20']} across {count} recorded scores")
    elif kind == "goal-audit":
        keys = ("system_loss_breakdown", "speed_supervisor_summary", "design_debt_summary", "mission_advancement_summary", "storage_triage_summary", "deployment_durability_summary", "public_launch_readiness", "route_trust", "red_summary", "live_progress", "t3_reference", "must_beat_status")
        facts = {key: {} for key in keys}
        if category != "empty":
            facts["design_debt_summary"] = {"schema": "recorded", "interfaceScoreOutOf20": 17, "agentFirstViewProofPathPassed": True, "detail": text}
            facts["mission_advancement_summary"] = {"repairMissionCount": 999 if category == "huge" else 0, "realOutputMissionCount": 1}
            facts["live_progress"] = {"missionCount": 999 if category == "huge" else 1, "completedMissionCount": 1}
        result = c._goal_completion_audit_summary(**facts)
        rows = {row["id"]: row for row in result["rows"]}
        _require(rows["beginner-interface"]["status"] == ("missing" if category == "empty" else "partial" if category == "huge" else "passed"), "first-view/repair audit classification differs")
        _require(rows["mission-output-quality"]["status"] == ("missing" if category == "empty" else "blocked" if category == "huge" else "passed"), "recorded output status differs")
        weights = sum(row["weight"] for row in result["rows"])
        score = sum({"passed": 1, "partial": .55, "blocked": .2, "missing": 0}[row["status"]] * row["weight"] for row in result["rows"])
        _require(result["completionPercent"] == round(score / weights * 100), "audit weighted requirement score differs")


def _control_files(root, kind, category, text):
    from . import mission_control as c
    from .models import MissionEvent
    store = _store(root)
    if kind == "workspaces":
        if category == "empty":
            store.workspaces_path.write_text("", encoding="utf-8")
        else:
            payload = asdict(store._default_workspace_profile())
            payload.update(name=text, root_path=str(root / "separate-雪"))
            store.workspaces_path.write_text(json.dumps([payload]), encoding="utf-8")
        result = store.load_workspaces()
        durable = json.loads(store.workspaces_path.read_text(encoding="utf-8"))
        _require(durable == [asdict(row) for row in result] and len(result) == 1, "workspace projection not faithful and durable")
        if category != "empty":
            _require(result[0].name == text and result[0].root_path == str(root / "separate-雪"), "unrelated workspace moved or lost name")
    elif kind == "events":
        count = 0 if category == "empty" else 300 if category == "huge" else 5
        for index in range(count):
            store.append_event(MissionEvent(mission_id="fixture", kind=f"record.{index}", message=text[:10000]))
        result = store.recent_events(3)
        _require([row["kind"] for row in result] == [f"record.{i}" for i in range(count - 1, max(-1, count - 4), -1)], "durable tail order/bound differs")
        _require(store.recent_events(0) == [] and store.recent_events(-1) == [], "zero/negative tail exposed events")
        if count:
            _require(all(row["message"] == text[:10000] for row in result), "event text bytes changed")
    elif kind in {"cache", "replace-lock"}:
        target = store.control_dir / "generated.json"
        first = [] if category == "empty" else [{"text": text, "version": 1}]
        store._write_json_if_changed(target, first)
        parsed = store._load_json(target, {})
        _require(parsed == first, "durable JSON differs from submitted payload")
        if kind == "cache":
            _require(store._load_json(target, {}) is parsed, "unchanged cached parse identity lost")
            second = {"version": 2, "text": text}
            store._write_json_if_changed(target, second)
            _require(store._load_json(target, {}) == second and parsed == first, "new durable value reused stale cache")
        _require(not list(target.parent.glob(target.name + ".tmp*")), "write left staging file")
    elif kind == "images":
        count = 0 if category == "empty" else 45 if category == "huge" else 3
        folder = root / ".agent_control/generated_image_artifacts"
        folder.mkdir(parents=True, exist_ok=True)
        paths = []
        for index in range(count):
            path = folder / (f"image-{index:03d}-雪.png" if category == "unicode" else f"image-{index:03d}.png")
            path.write_bytes(_png()); os.utime(path, (1700000000 + index, 1700000000 + index)); paths.append(path)
        result = c._build_generated_image_artifacts_snapshot(root)
        expected = list(reversed(paths))[:40]
        _require([Path(row["artifactPath"]) for row in result["items"]] == expected and result["summary"]["total"] == len(expected), "direct image scan retention/order/count differs")
        _require(all(row["artifactId"] == Path(row["artifactPath"]).stem for row in result["items"]), "direct image lost stem identity")
    elif kind == "attachment":
        source = root / "proof-source.txt"
        source.write_bytes(text.encode("utf-8"))
        entries = [] if category == "empty" else [{"path": str(source), "kind": "report"}]
        result = c.attach_verifier_proof_bundle(root, "fixture", category, entries)
        _require(result["artifactCount"] == len(entries) and json.loads(Path(result["manifestPath"]).read_text(encoding="utf-8")) == result, "attachment manifest or count differs")
        for row in result["artifacts"]:
            _require(Path(row["path"]).read_bytes() == source.read_bytes() and row["bytes"] == source.stat().st_size, "attachment bytes not faithful")
    elif kind == "evidence":
        source = root / "evidence-雪.events.jsonl"
        source.write_text(text, encoding="utf-8")
        result = c._recover_evidence_path(root, f"/mnt/c/nonexistent-prefix/{source}")
        _require(result == source.resolve() and result.read_text(encoding="utf-8") == text, "embedded Windows evidence not recovered faithfully")
    elif kind == "validation-actions":
        if category == "empty":
            _require(c._build_validation_actions(root) == [], "empty workspace invented validation")
        else:
            (root / "package.json").write_text(json.dumps({"name": text, "scripts": {"build": "echo synthetic-declaration"}}), encoding="utf-8")
            result = c._build_validation_actions(root)
            _require(len(result) == 1 and result[0]["commandSurface"] == "validate.workspace" and "npm run build" in result[0]["commands"], "local package build declaration omitted")
    elif kind == "preview":
        row = _mission("fixture", text)
        _require(c.mission_artifact_manifest_preview_url(row, root=root) == "", "absent artifact invented preview")
        folder = root / ".agent_control/mission_artifacts/fixture"
        folder.mkdir(parents=True, exist_ok=True)
        if category != "empty":
            entry = folder / "index.html"; entry.write_text(text, encoding="utf-8")
            expected = "/api/artifact?path=" + quote(str(entry), safe="")
            _require(c.mission_artifact_manifest_preview_url(row, root=root) == expected, "bare artifact preview not bound to actual file")
    elif kind == "queue":
        rows = [] if category == "empty" else [_mission(f"owner-{i:03d}", text, "running" if i == 0 else "queued") for i in range(80 if category == "huge" else 3)]
        store._rebalance_workspace_queue_in_place(rows, "fixture")
        _require([row.state.queue_position for row in rows] == list(range(len(rows))), "queue positions not contiguous from actual owner")
        if rows:
            _require(all(row.state.blocking_mission_id == rows[0].mission_id for row in rows[1:]), "queued row lacks actual owner")
            rows[0].state.status = "completed"
            store._rebalance_workspace_queue_in_place(rows, "fixture")
            _require(rows[1].state.queue_position == 0 and rows[1].state.blocking_mission_id is None and "front of the workspace queue" in rows[1].proof.summary, "finished owner did not promote observed queued successor")
    elif kind == "delete":
        primary = store.load_workspaces()[0]
        secondary = asdict(primary); secondary.update(workspace_id="secondary", name=text, root_path=str(root / "secondary"))
        from .models import WorkspaceProfile
        store.save_workspaces([primary, WorkspaceProfile(**secondary)])
        rows = [] if category == "empty" else [_mission(f"target-{i}", text) for i in range(80 if category == "huge" else 3)]
        for row in rows:
            row.workspace_id = "secondary"
        keeper = _mission("keeper", "keeper"); keeper.workspace_id = primary.workspace_id
        store.save_missions([keeper, *rows])
        store._write_json_if_changed(store.workspace_actions_path, {primary.workspace_id: [{"keeper": True}], "secondary": [{"text": text}]})
        removed, count = store.delete_workspace("secondary")
        _require(removed.workspace_id == "secondary" and count == len(rows) and [row.mission_id for row in store.load_missions()] == ["keeper"], "workspace delete lost unrelated mission or wrong removed count")
        _require(store.load_workspace_actions() == {primary.workspace_id: [{"keeper": True}]}, "workspace delete lost unrelated history")
        _reject(lambda: store.delete_workspace(primary.workspace_id), "last workspace removed")


def _harness(root, kind, category, text):
    from .harness_jobs import HarnessJobStore
    from . import harness_registry as r
    if kind in {"identity", "lifecycle", "observation"}:
        store = HarnessJobStore(root)
        request = {"message": text, "harnessId": "neyvia-agent", "workspacePath": str(root)}
        identity = "harness-job-generated"
        created = store.create(request, job_id=identity)
        path = store.job_path(identity)
        if kind == "identity":
            before = path.read_bytes()
            _require(store.create(request, job_id=identity)["id"] == identity and path.read_bytes() == before, "idempotent create changed receipt")
            _reject(lambda: store.create({**request, "message": text + "conflict"}, job_id=identity), "conflicting identity accepted")
            _require(path.read_bytes() == before and json.loads(before)["request"] == request, "conflicting create changed saved request")
        elif kind == "lifecycle":
            for status in ("completed", "interrupted", "blocked"):
                job = store.create({**request, "message": text + status})["id"]
                result = store.finish(job, result={"status": status, "message": text})
                before = store.job_path(job).read_bytes()
                store.finish(job, result={"status": "completed", "late": True})
                store.mark_started(job, pid=os.getpid())
                _require(store.job_path(job).read_bytes() == before and result["status"] == status, "late worker revived stopped/blocked job")
        else:
            started = store.mark_started(identity, pid=os.getpid())
            finished = store.finish(identity, result={"status": "completed", "text": text})
            before = path.read_bytes(); observed = store.load(identity, reconcile=False)
            _require(observed["metrics"]["terminal"] and observed["metrics"]["receiptPresent"] and path.read_bytes() == before, "observation mutates receipt/loses terminal result")
            _require([row["phase"] for row in observed["timeline"]] == ["queued", "running", "completed"] and observed["request"] == request, "timeline order/request differs")
    elif kind == "public-profile":
        saved = r.save_harness_profile(root, {"id": "generated", "harnessId": "neyvia-agent", "label": text, "secret": "synthetic-noncredential", "apiKey": "synthetic-noncredential", "model": "m"})
        raw = (root / r.HARNESS_PROFILE_RELATIVE_PATH).read_text(encoding="utf-8")
        _require("synthetic-noncredential" not in raw and set(saved) <= r.PROFILE_FIELDS | {"updatedAt"} and r.resolve_harness_profile(root, "neyvia-agent", saved["id"]) == saved, "public profile persisted secret or lost durable projection")
    elif kind == "instruction":
        initial = r.save_harness_instruction(root, "AGENTS.md", "keeper")
        saved = r.save_harness_instruction(root, "AGENTS.md", text)
        _require(Path(saved["backupPath"]).read_bytes() == b"keeper\n" and Path(saved["path"]).read_bytes() == text.encode().rstrip() + b"\n", "instruction lost backup or UTF8 normalization")
        before = Path(saved["path"]).read_bytes()
        _reject(lambda: r.save_harness_instruction(root, "../AGENTS.md", text), "instruction escape accepted")
        _require(Path(saved["path"]).read_bytes() == before, "rejected instruction escape changed state")
    elif kind == "model-policy":
        from .runtimes.managed_cli import normalize_managed_cli_model
        if category == "empty":
            from .runtimes.managed_cli import MANAGED_CLI_SPECS
            _require(normalize_managed_cli_model("grok-build", "") == MANAGED_CLI_SPECS["grok-build"].default_model, "missing model does not select documented default")
        else:
            _reject(lambda: normalize_managed_cli_model("grok-build", text), "invalid Grok model identifier accepted")
            _require(normalize_managed_cli_model("grok-build", "research/explicit-model") == "research/explicit-model", "custom explicit Grok model rewritten")
            _reject(lambda: normalize_managed_cli_model("claude-code", text), "unapproved foreign Claude alias accepted")
    elif kind == "budget-input":
        from .harness_job_worker import _hard_runtime_budget_seconds as _runtime_budget_seconds
        if category == "empty":
            _require(_runtime_budget_seconds({"budget": {"maxRuntimeSeconds": ""}}) == 0, "empty budget not zero")
        else:
            _reject(lambda: _runtime_budget_seconds({"budget": {"maxRuntimeSeconds": text}, "maxRuntimeSeconds": 1}), "invalid explicit budget fell through to fallback")
        _require(_runtime_budget_seconds({"budget": {"maxRuntimeSeconds": 77}, "maxRuntimeSeconds": 1}) == 77, "nested explicit budget priority lost")
    elif kind == "gateway":
        model = "generated-model"
        profile = r.save_harness_profile(root, {"id": "generated", "harnessId": "neyvia-agent", "model": model, "baseUrl": "http://127.0.0.1:48749/v1", "credentialEnv": "C7_CONTROL_SYNTHETIC", "label": text})
        env = r.harness_gateway_environment(root, "neyvia-agent", profile["id"], {"C7_CONTROL_SYNTHETIC": "synthetic-noncredential"})
        _require(env["FLUXIO_HARNESS_MODEL"] == model and env["OPENAI_BASE_URL"] == "http://127.0.0.1:48749/v1" and env["OPENAI_API_KEY"] == "synthetic-noncredential", "explicit public route/environment map lost")
        _require("synthetic-noncredential" not in (root / r.HARNESS_PROFILE_RELATIVE_PATH).read_text(encoding="utf-8"), "gateway sentinel persisted")


def _concurrent_profiles(root):
    from .harness_registry import save_harness_profile, _load_profiles
    barrier = threading.Barrier(8)
    def save(index):
        barrier.wait(timeout=10)
        return save_harness_profile(root, {"id": f"row-{index}", "harnessId": "neyvia-agent", "label": f"row-{index}-雪"})
    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(save, range(8)))
    durable = _load_profiles(root)["profiles"]
    _require({row["id"] for row in rows} == {row["id"] for row in durable} and len(durable) == 8, "concurrent profile saves lost durable rows")


def _admission(root):
    from .harness_jobs import HarnessJobStore
    store = HarnessJobStore(root, max_open_jobs=3)
    barrier = threading.Barrier(8)
    def create(index):
        barrier.wait(timeout=10)
        try:
            return store.create({"message": f"row-{index}", "harnessId": "neyvia-agent"})["id"]
        except RuntimeError as error:
            _require("capacity" in str(error), "concurrent refusal not admission pressure")
            return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(create, range(8)))
    winners = [row for row in rows if row]
    _require(len(winners) == 3 and store.capacity()["openJobs"] == 3, "serialized admission exceeded durable operator limit")
    store.finish(winners[0], result={"status": "completed"})
    _require(store.capacity()["openJobs"] == 2 and store.create({"message": "after-release"})["id"], "terminal result did not release admission")


def _policy(root, category):
    from .harness_jobs import HarnessJobStore
    wide = HarnessJobStore(root, max_open_jobs=8)
    _require(wide.capacity()["maxOpenJobs"] == 8, "initial explicit admission limit lost")
    narrow = HarnessJobStore(root, max_open_jobs=2)
    _require(narrow.capacity()["maxOpenJobs"] == 2 and wide.capacity()["maxOpenJobs"] == 2, "old instance expanded tightened durable policy")
    if category == "permissions":
        from .edge_fixture_native import _sharing_denied
        policy_path = wide._admission_policy_path()
        before = policy_path.read_bytes()
        with _sharing_denied(policy_path):
            _reject(wide.capacity, "unreadable policy admitted capacity", (OSError, RuntimeError))
        _require(policy_path.read_bytes() == before, "unreadable policy changed durable operator limit")


def _instruction_permission(root):
    from .harness_registry import save_harness_instruction
    from .edge_fixture_native import _sharing_denied
    saved = save_harness_instruction(root, "AGENTS.md", "keeper-雪")
    target = Path(saved["path"]); before = target.read_bytes()
    with _sharing_denied(target):
        _reject(lambda: save_harness_instruction(root, "AGENTS.md", "forbidden change"), "sharing-denied instruction replaced", (OSError,))
    _require(target.read_bytes() == before, "denied instruction changed keeper bytes")


def _attachment_permission(root):
    from .mission_control import attach_verifier_proof_bundle
    outside = root.parent / (root.name + "-outside.txt")
    outside.write_bytes(b"outside-scope-keeper")
    _reject(lambda: attach_verifier_proof_bundle(root, "fixture", "denied", [{"path": str(outside)}]), "out-of-root artifact attached")
    _require(outside.read_bytes() == b"outside-scope-keeper" and not (root / ".agent_control/mission_artifacts/fixture/ui_verifier_proof/denied/manifest.json").exists(), "authority refusal published manifest or changed external fixture")


def _attachment_interrupted(root):
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    root.mkdir(parents=True, exist_ok=True)
    source = root / "owned-report.txt"
    source.write_bytes(b"durable source keeper\n")
    ready = root / "copy-complete.json"
    code = "\n".join([
        "import shutil,sys,time",
        "from pathlib import Path",
        "sys.path.insert(0,sys.argv[1])",
        "from grant_agent import mission_control",
        "original=mission_control.shutil.copy2",
        "def copy_then_wait(src,dst,*args,**kwargs):",
        " result=original(src,dst,*args,**kwargs)",
        " Path(sys.argv[4]).write_text(str(dst),encoding='utf-8')",
        " time.sleep(60)",
        " return result",
        "mission_control.shutil.copy2=copy_then_wait",
        "mission_control.attach_verifier_proof_bundle(Path(sys.argv[2]),'fixture','interrupted',[{'path':sys.argv[3]}])",
    ])
    repo_src = str(Path(__file__).resolve().parents[1])
    child = subprocess.Popen([sys.executable, "-c", code, repo_src, str(root), str(source), str(ready)],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                             **hidden_windows_subprocess_kwargs())
    try:
        deadline = time.monotonic() + 15
        while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(.03)
        _require(ready.exists(), "attachment worker did not reach post-copy/pre-manifest boundary")
        copied = Path(ready.read_text(encoding="utf-8"))
        _require(copied.is_file() and copied.read_bytes() == source.read_bytes(),
                 "owned worker did not durably copy the source before interruption")
        child.kill(); child.wait(timeout=10)
        manifests = list((root / ".agent_control/mission_artifacts/fixture/ui_verifier_proof/interrupted").glob("manifest.json"))
        _require(not manifests, "interrupted attachment published a completion manifest")
        _require(source.read_bytes() == b"durable source keeper\n", "interrupted attachment changed its source")
    finally:
        if child.poll() is None:
            child.kill(); child.wait(timeout=10)
        child.stderr.close()


def _parallel_attachments(root):
    from .mission_control import attach_verifier_proof_bundle
    root.mkdir(parents=True, exist_ok=True)
    sources = []
    for index in range(6):
        source = root / f"source-{index}.txt"
        source.write_bytes(f"attachment-{index}-雪".encode("utf-8"))
        sources.append(source)
    barrier = threading.Barrier(len(sources))
    def attach(index):
        barrier.wait(timeout=10)
        return attach_verifier_proof_bundle(root, "fixture", f"parallel-{index}",
                                            [{"path": str(sources[index]), "kind": "report"}])
    with ThreadPoolExecutor(max_workers=len(sources)) as pool:
        manifests = list(pool.map(attach, range(len(sources))))
    _require(len(manifests) == len(sources), "concurrent attachment lost a completion manifest")
    for index, manifest in enumerate(manifests):
        saved = json.loads(Path(manifest["manifestPath"]).read_text(encoding="utf-8"))
        row = saved["artifacts"][0]
        _require(saved["artifactCount"] == 1 and Path(row["path"]).read_bytes() == sources[index].read_bytes(),
                 "concurrent attachment manifest/source bytes crossed or tore")


def _replace_lock_permission(root):
    from .edge_fixture_native import _sharing_denied
    store = _store(root)
    target = store.control_dir / "permission-locked.json"
    store._write_json_if_changed(target, {"keeper": "before"})
    before = target.read_bytes()
    with _sharing_denied(target):
        _reject(lambda: store._write_json_if_changed(target, {"forbidden": True}),
                "sharing-denied JSON destination was replaced", (OSError,))
    _require(target.read_bytes() == before, "sharing-denied JSON destination changed keeper bytes")
    _require(not list(target.parent.glob(target.name + ".*.tmp")),
             "denied JSON replacement retained staging file")


def _delete_permission(root):
    from .edge_fixture_native import _sharing_denied
    store = _store(root)
    primary = store.load_workspaces()[0]
    from .models import WorkspaceProfile
    secondary = WorkspaceProfile(**{**asdict(primary), "workspace_id": "permission-target",
                                    "name": "Permission target", "root_path": str(root / "target")})
    store.save_workspaces([primary, secondary])
    before = store.workspaces_path.read_bytes()
    with _sharing_denied(store.workspaces_path):
        _reject(lambda: store.delete_workspace(secondary.workspace_id),
                "sharing-denied workspace store allowed deletion", (OSError, RuntimeError, ValueError))
    _require(store.workspaces_path.read_bytes() == before,
             "denied workspace deletion changed durable workspace records")


def _delete_concurrent(root):
    from .models import WorkspaceProfile
    store = _store(root)
    primary = store.load_workspaces()[0]
    secondary = WorkspaceProfile(**{**asdict(primary), "workspace_id": "concurrent-target",
                                    "name": "Concurrent target", "root_path": str(root / "target")})
    store.save_workspaces([primary, secondary])
    keeper = _mission("keeper", "unrelated keeper")
    keeper.workspace_id = primary.workspace_id
    target = _mission("target", "removed workspace mission")
    target.workspace_id = secondary.workspace_id
    store.save_missions([keeper, target])
    store._write_json_if_changed(store.workspace_actions_path,
                                {primary.workspace_id: [{"keeper": True}], secondary.workspace_id: [{"target": True}]})
    barrier = threading.Barrier(2)
    def delete():
        barrier.wait(timeout=10)
        try:
            return store.delete_workspace(secondary.workspace_id)[0].workspace_id
        except ValueError:
            return "already-removed"
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: delete(), range(2)))
    _require(outcomes.count(secondary.workspace_id) == 1 and outcomes.count("already-removed") == 1,
             f"competing deletes did not produce one winner and one refusal: {outcomes}")
    _require([row.mission_id for row in store.load_missions()] == [keeper.mission_id],
             "competing delete lost or retained unrelated/matching mission state")
    _require(store.load_workspace_actions() == {primary.workspace_id: [{"keeper": True}]},
             "competing delete lost unrelated workspace history")


def _replace_lock_interrupted(root):
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    target = root / ".agent_control" / "replace-interrupted.json"
    store = _store(root)
    store._write_json_if_changed(target, {"keeper": "before"})
    before = target.read_bytes()
    ready = root / "replace-temp-ready.txt"
    code = "\n".join([
        "import sys,time",
        "from pathlib import Path",
        "sys.path.insert(0,sys.argv[1])",
        "from grant_agent.mission_control import ControlRoomStore",
        "path=Path(sys.argv[3]); original=Path.write_text",
        "def write_then_wait(self,data,*args,**kwargs):",
        " result=original(self,data,*args,**kwargs)",
        " if self.name.startswith(path.name+'.') and self.name.endswith('.tmp'):",
        "  Path(sys.argv[4]).write_text(str(self),encoding='utf-8'); time.sleep(60)",
        " return result",
        "Path.write_text=write_then_wait",
        "ControlRoomStore(Path(sys.argv[2]))._write_json_if_changed(path,{'replacement':'after'})",
    ])
    repo_src = str(Path(__file__).resolve().parents[1])
    child = subprocess.Popen([sys.executable, "-c", code, repo_src, str(root), str(target), str(ready)],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                             **hidden_windows_subprocess_kwargs())
    try:
        deadline = time.monotonic() + 15
        while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(.03)
        _require(ready.exists(), "JSON writer did not reach post-temp/pre-replace boundary")
        temporary = Path(ready.read_text(encoding="utf-8"))
        _require(temporary.is_file() and json.loads(temporary.read_text(encoding="utf-8")) == {"replacement": "after"},
                 "writer temporary did not contain the complete replacement before interruption")
        child.kill(); child.wait(timeout=10)
        _require(target.read_bytes() == before and json.loads(target.read_text(encoding="utf-8")) == {"keeper": "before"},
                 "interrupted atomic replacement changed the previous destination")
    finally:
        if child.poll() is None:
            child.kill(); child.wait(timeout=10)
        child.stderr.close()


def _parallel_json(root):
    store = _store(root)
    target = store.control_dir / "shared-write.json"
    payloads = [{"writer": index, "text": "same-target-雪" * 5000} for index in range(8)]
    barrier = threading.Barrier(8)
    def write(payload):
        barrier.wait(timeout=10)
        store._write_json_if_changed(target, payload)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(write, payloads))
    _require(json.loads(target.read_text(encoding="utf-8")) in payloads, "concurrent atomic write published torn JSON")
    _require(not list(target.parent.glob(target.name + ".*.tmp")), "concurrent successful write retained staging files")


def _parallel_instruction(root):
    from .harness_registry import save_harness_instruction
    save_harness_instruction(root, "AGENTS.md", "keeper")
    barrier = threading.Barrier(8)
    texts = [f"writer-{index}-雪" * 5000 for index in range(8)]
    def write(text):
        barrier.wait(timeout=10)
        return save_harness_instruction(root, "AGENTS.md", text)
    with ThreadPoolExecutor(max_workers=8) as pool:
        saved = list(pool.map(write, texts))
    _require((root / "AGENTS.md").read_bytes() in {text.encode() + b"\n" for text in texts}, "concurrent instruction save tore bytes")
    _require(all(Path(row["backupPath"]).is_file() for row in saved), "concurrent instruction save lost recoverable backup")


def _interrupted(root, kind):
    from .harness_jobs import HarnessJobStore, _exclusive_job_lock
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    store = HarnessJobStore(root)
    created = store.create({"message": "actual owned worker exited before settlement", "harnessId": "neyvia-agent"})
    identity = created["id"]
    ready = root / "owned-ready.json"
    code = "\n".join([
        "import json,os,sys,time",
        "from pathlib import Path",
        "from grant_agent.harness_jobs import HarnessJobStore,_exclusive_job_lock",
        "store=HarnessJobStore(Path(sys.argv[1])); job=sys.argv[2]",
        "store.mark_started(job,pid=os.getpid())",
        "with _exclusive_job_lock(store.job_path(job)):",
        " Path(sys.argv[3]).write_text(json.dumps({'pid':os.getpid(),'job':job}),encoding='utf-8')",
        " time.sleep(60)",
    ])
    child = subprocess.Popen([sys.executable, "-c", code, str(root), identity, str(ready)],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                             **hidden_windows_subprocess_kwargs())
    try:
        deadline = time.monotonic() + 15
        while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(.03)
        _require(ready.exists(), "owned worker did not reach real job-lock boundary")
        _require(json.loads(ready.read_text(encoding="utf-8"))["pid"] == child.pid, "worker readiness identity mismatch")
        before = store.job_path(identity).read_bytes()
        child.kill(); child.wait(timeout=10)
        if kind == "lock-recovery":
            with _exclusive_job_lock(store.job_path(identity), timeout_seconds=3):
                _require(store.job_path(identity).read_bytes() == before, "recovered lock replayed uncertain effect")
            _require(not store.job_path(identity).with_suffix(".json.lock").exists(), "dead owner compatibility lease retained after guarded recovery")
        else:
            restored = HarnessJobStore(root).load(identity)
            _require(restored["status"] == "interrupted" and restored["request"] == created["request"] and restored["result"] is None, "dead worker fabricated completion or lost request")
    finally:
        if child.poll() is None:
            child.kill(); child.wait(timeout=10)
        child.stderr.close()


def _control_stale(root, kind):
    """Change the real owned input, then invoke the checked owner again."""
    from . import mission_control as c
    store = _store(root)
    if kind == "workspaces":
        rows = store.load_workspaces()
        rows[0].name = "before-change"
        store.save_workspaces(rows)
        payload = json.loads(store.workspaces_path.read_text(encoding="utf-8"))
        payload[0]["name"] = "after-change"
        store.workspaces_path.write_text(json.dumps(payload), encoding="utf-8")
        _require(store.load_workspaces()[0].name == "after-change", "workspace loader returned stale pre-mutation state")
    elif kind == "cache":
        target = store.control_dir / "cache-stale.json"
        store._write_json_if_changed(target, {"revision": 1})
        _require(store._load_json(target, {}) == {"revision": 1}, "cache initial read mismatch")
        target.write_text('{"revision":2}', encoding="utf-8")
        os.utime(target, None)
        _require(store._load_json(target, {}) == {"revision": 2}, "cache retained stale file contents")
    elif kind == "events":
        from .models import MissionEvent
        store.append_event(MissionEvent(mission_id="fixture", kind="first", message="old"))
        first = store.recent_events(2)
        store.append_event(MissionEvent(mission_id="fixture", kind="second", message="new"))
        second = store.recent_events(2)
        _require([row["kind"] for row in first] == ["first"] and [row["kind"] for row in second] == ["second", "first"], "event reread omitted actual append or mutated earlier result")
    elif kind == "images":
        folder = root / ".agent_control/generated_image_artifacts"; folder.mkdir(parents=True, exist_ok=True)
        image_path = folder / "fresh.png"; image_path.write_bytes(_png())
        first = c._build_generated_image_artifacts_snapshot(root)
        image_path.unlink()
        second = c._build_generated_image_artifacts_snapshot(root)
        _require(any(Path(row["artifactPath"]) == image_path for row in first["items"]) and not any(Path(row["artifactPath"]) == image_path for row in second["items"]), "image scan retained a removed actual file")
    elif kind == "evidence":
        source = root / "evidence-current.jsonl"; source.write_text("first", encoding="utf-8")
        first = c._recover_evidence_path(root, str(source))
        source.unlink()
        second = c._recover_evidence_path(root, str(source))
        _require(first == source.resolve() and second == source.resolve() and not second.exists(), "evidence lookup fabricated currentness after source removal")
    elif kind == "preview":
        mission = _mission("fresh-preview")
        folder = root / ".agent_control/mission_artifacts/fresh-preview"; folder.mkdir(parents=True, exist_ok=True)
        entry = folder / "index.html"; entry.write_text("<main>current</main>", encoding="utf-8")
        first = c.mission_artifact_manifest_preview_url(mission, root=root)
        entry.unlink()
        second = c.mission_artifact_manifest_preview_url(mission, root=root)
        _require(first and not second, "preview lookup fabricated currentness after entrypoint removal")
    elif kind == "delete":
        primary = store.load_workspaces()[0]
        _reject(lambda: store.delete_workspace("removed-before-call"), "delete accepted a workspace absent from current durable state")
        _require([row.workspace_id for row in store.load_workspaces()] == [primary.workspace_id], "failed stale delete changed current workspace")
    elif kind == "attachment":
        source = root / "attachment-current.txt"; source.write_text("old", encoding="utf-8")
        source.write_text("new", encoding="utf-8")
        result = c.attach_verifier_proof_bundle(root, "fixture", "fresh", [{"path": str(source), "kind": "report"}])
        _require(Path(result["artifacts"][0]["path"]).read_text(encoding="utf-8") == "new", "attachment copied stale pre-mutation source")


def _workspace_initialization_interrupted(root):
    """Kill a real child after workspace initialization is durable, then recover."""
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    store = _store(root)
    ready = root / "workspace-initialized.marker"
    repo = Path(__file__).resolve().parents[2]
    code = (
        "import sys,time; from pathlib import Path; from grant_agent.mission_control import ControlRoomStore; "
        "s=ControlRoomStore(Path(sys.argv[1])); original=s.save_workspaces; "
        "def_save=original; "
        "exec('def hold(rows):\\n def_save(rows)\\n Path(sys.argv[2]).write_text(\\\"durable\\\")\\n time.sleep(60)'); "
        "s.save_workspaces=hold; s.load_workspaces()"
    )
    child = subprocess.Popen([sys.executable, "-c", code, str(root), str(ready)], cwd=repo,
                             env={**os.environ, 'PYTHONPATH': str(repo / 'src')},
                             **hidden_windows_subprocess_kwargs())
    try:
        deadline = time.monotonic() + 15
        while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(.02)
        _require(ready.exists(), "initialization child did not persist workspace before interruption")
        child.kill(); child.wait(timeout=10)
        recovered = _store(root).load_workspaces()
        durable = json.loads(store.workspaces_path.read_text(encoding="utf-8"))
        _require(len(recovered) == 1 and durable == [asdict(recovered[0])], "restarted workspace initialization lost or fabricated durable state")
    finally:
        if child.poll() is None:
            child.kill(); child.wait(timeout=10)


def _notification_ledger_case(root, mode):
    from . import mission_control as c
    from .edge_fixture_native import _sharing_denied
    store = _store(root)
    mission = _mission("ledger-mission", "Read the current local runtime result", "running")
    store.save_missions([mission])
    ledger = store.control_dir / "runtime_sessions" / "fixture.json"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    def write(message):
        ledger.write_text(json.dumps({"missionId": mission.mission_id, "delegated_id": "fixture-runtime",
            "runtime_id": "manual-local", "launch_command": "owned local fixture producer", "status": "completed", "detail": message,
            "latest_events": [{"kind": "runtime.output", "message": message}]}), encoding="utf-8")
    def feed():
        return c.ControlRoomStore._build_notification_feed(missions=[_store(root).get_mission(mission.mission_id)],
            activity=[], root=root, limit=10)
    write("ledger output revision one")
    first = feed()
    _require(any("ledger output revision one" in row.get("agentMessage", "") and row.get("agentMessageSource", "").startswith("runtime_output:") for row in first),
             "notification feed did not hydrate its actual runtime ledger")
    if mode == "stale":
        write("ledger output revision two")
        second = feed()
        _require(any("ledger output revision two" in row.get("agentMessage", "") for row in second)
                 and not any("ledger output revision one" in row.get("agentMessage", "") for row in second),
                 "notification feed retained stale hydrated ledger output")
    elif mode == "permissions":
        with _sharing_denied(ledger):
            denied = feed()
        _require(not any("ledger output revision one" in row.get("agentMessage", "") for row in denied),
                 "sharing-denied runtime ledger was reported as readable/current")
    elif mode == "concurrency":
        write("ledger output concurrent")
        with ThreadPoolExecutor(max_workers=4) as pool:
            snapshots = list(pool.map(lambda _: feed(), range(8)))
        _require(all(any("ledger output concurrent" in row.get("agentMessage", "") for row in rows) for rows in snapshots),
                 "concurrent notification reads disagreed with the stable runtime ledger")


def _concurrent_file_observation(root, kind):
    from . import mission_control as c
    store = _store(root)
    if kind == "workspaces":
        store.load_workspaces()
        action = lambda: [row.workspace_id for row in _store(root).load_workspaces()]
    elif kind == "images":
        folder = root / ".agent_control/generated_image_artifacts"; folder.mkdir(parents=True, exist_ok=True)
        path = folder / "stable.png"; path.write_bytes(_png())
        action = lambda: [row["artifactPath"] for row in c._build_generated_image_artifacts_snapshot(root)["items"]]
        expected = [str(path)]
    elif kind == "evidence":
        path = root / "stable.events.jsonl"; path.write_text("actual", encoding="utf-8")
        action = lambda: str(c._recover_evidence_path(root, str(path)))
        expected = str(path.resolve())
    elif kind == "preview":
        mission = _mission("parallel-preview")
        folder = root / ".agent_control/mission_artifacts/parallel-preview"; folder.mkdir(parents=True, exist_ok=True)
        path = folder / "index.html"; path.write_text("<main>stable</main>", encoding="utf-8")
        action = lambda: c.mission_artifact_manifest_preview_url(mission, root=root)
        expected = "/api/artifact?path=" + quote(str(path), safe="")
    elif kind == "validation-actions":
        (root / "package.json").write_text(json.dumps({"scripts": {"build": "echo owned"}}), encoding="utf-8")
        action = lambda: c._build_validation_actions(root)
        expected = None
    else:
        raise AssertionError(f"unsupported concurrent file observation {kind}")
    with ThreadPoolExecutor(max_workers=4) as pool:
        values = list(pool.map(lambda _: action(), range(8)))
    if kind == "workspaces":
        _require(all(value == values[0] and len(value) == 1 for value in values), "concurrent workspace reads disagreed")
    elif kind == "validation-actions":
        _require(all(value == values[0] and value and "npm run build" in value[0]["commands"] for value in values), "concurrent validation-action reads disagreed with package file")
    else:
        _require(all(value == expected for value in values), f"concurrent {kind} reads disagreed with stable actual file")


def _preview_permission(root):
    from . import mission_control as c
    from .edge_fixture_native import _sharing_denied
    mission = _mission("permission-preview")
    folder = root / ".agent_control/mission_artifacts/permission-preview"; folder.mkdir(parents=True, exist_ok=True)
    manifest = folder / "artifact_manifest.json"
    manifest.write_text(json.dumps({"previewUrl": "/api/artifact?path=secret-local-entry"}), encoding="utf-8")
    with _sharing_denied(manifest):
        result = c.mission_artifact_manifest_preview_url(mission, root=root)
    _require(result == "", "preview disclosed a manifest value while the actual manifest handle was denied")


def _validation_permission(root):
    from . import mission_control as c
    from .edge_fixture_native import _sharing_denied
    package = root / "package.json"
    package.write_text(json.dumps({"scripts": {"build": "echo owned"}}), encoding="utf-8")
    with _sharing_denied(package):
        try:
            result = c._build_validation_actions(root)
        except OSError:
            result = []
    _require(not any("npm run build" in row.get("commands", "") for row in result),
             "validation action trusted package contents while the actual package file was sharing-denied")


def _delete_interrupted(root):
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    store = _store(root)
    primary = store.load_workspaces()[0]
    from .models import WorkspaceProfile
    secondary = WorkspaceProfile(**{**asdict(primary), "workspace_id": "interrupted-target",
        "name": "Interrupted target", "root_path": str(root / "target")})
    store.save_workspaces([primary, secondary])
    keeper = _mission('interrupted-keeper', 'Preserve unrelated mission')
    keeper.workspace_id = primary.workspace_id
    target = _mission('interrupted-mission', 'Remove selected mission')
    target.workspace_id = secondary.workspace_id
    store.save_missions([keeper, target])
    store._write_json_if_changed(store.workspace_actions_path,
        {primary.workspace_id: [{'keeper': True}], secondary.workspace_id: [{'target': True}]})
    marker = root / "delete-write.marker"
    repo = Path(__file__).resolve().parents[2]
    code = "\n".join([
        "import sys,time", "from pathlib import Path", "from grant_agent.mission_control import ControlRoomStore",
        "root=Path(sys.argv[1]); marker=Path(sys.argv[2]); s=ControlRoomStore(root)",
        "original=s.save_workspaces",
        "def hold(rows):",
        " original(rows)",
        " if all(row.workspace_id != 'interrupted-target' for row in rows):",
        "  marker.write_text('workspace write durable')",
        "  time.sleep(60)",
        "s.save_workspaces=hold; s.delete_workspace('interrupted-target')",
    ])
    child = subprocess.Popen([sys.executable, "-c", code, str(root), str(marker)], cwd=repo,
                             env={**os.environ, 'PYTHONPATH': str(repo / 'src')},
                             **hidden_windows_subprocess_kwargs())
    try:
        deadline = time.monotonic() + 15
        while not marker.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(.02)
        _require(marker.exists(), "delete child did not reach the real post-workspace-write interruption boundary")
        child.kill(); child.wait(timeout=10)
        current = _store(root).load_workspaces()
        _require([row.workspace_id for row in current] == [primary.workspace_id],
                 "reopened durable workspaces did not reflect the observed interrupted deletion write")
        reopened = _store(root)
        _require([row.mission_id for row in reopened.load_missions()] == [keeper.mission_id]
                 and reopened.load_workspace_actions() == {primary.workspace_id: [{'keeper': True}]},
                 'Interrupted workspace removal retained orphan missions/history or lost unrelated records')
    finally:
        if child.poll() is None:
            child.kill(); child.wait(timeout=10)


def _proof_digest_stale(root):
    from . import mission_control as c
    mission = _mission("digest-current", "Bind current artifact")
    folder = root / ".agent_control/mission_artifacts/digest-current"; folder.mkdir(parents=True, exist_ok=True)
    entry = folder / "index.html"; entry.write_text("<main>first</main>", encoding="utf-8")
    first = c.ControlRoomStore._mission_proof_digest_payload(mission, root=root)
    entry.write_text("<main>second</main>", encoding="utf-8")
    second = c.ControlRoomStore._mission_proof_digest_payload(mission, root=root)
    _require(first.get("previewUrl") and second.get("previewUrl") == first.get("previewUrl"), "proof digest lost actual entry URL after content mutation")
    entry.unlink()
    third = c.ControlRoomStore._mission_proof_digest_payload(mission, root=root)
    _require(not third.get("previewUrl"), "proof digest retained artifact currentness after entry removal")


def _progress_stale(root):
    from . import mission_control as c
    mission = _mission("progress-current", "Inspect live output")
    folder = root / "output"; folder.mkdir(parents=True)
    mission.planned_file_scope = [str(folder)]
    first = c.ControlRoomStore._mission_summary_payload(mission, root=root)
    (folder / "README.md").write_text("current output", encoding="utf-8")
    second = c.ControlRoomStore._mission_summary_payload(mission, root=root)
    _require(first["plannedScopeArtifacts"]["status"] == "partial" and second["plannedScopeArtifacts"]["status"] == "ready"
             and second["plannedScopeArtifacts"]["readmeCount"] == 1,
             "mission progress retained stale planned-artifact filesystem facts")


def _route_trust_stale(root, *, summary=False):
    from . import mission_control as c
    missions = [_mission("route-feedback", "Real local closeout feedback", "completed")]
    closeout = root / ".agent_control/route_trust_sampling/closeout_review_latest.json"
    closeout.parent.mkdir(parents=True, exist_ok=True)
    def write(score):
        closeout.write_text(json.dumps({"schema": "fluxio.route_trust_sampling_closeout_review.v1", "proposals": [
            {"missionId": "local-feedback", "taskType": "general_coding", "score": score,
             "outcome": "useful" if score > 50 else "not_useful", "trustSignal": "promote" if score > 50 else "deprioritize"}]}), encoding="utf-8")
    def collect():
        if summary:
            return c.build_summary_harness_lab_snapshot(root, missions=missions)["routeTrustCoverage"]
        return c._build_route_trust_coverage_summary(root, missions=missions, include_route_outcome_trends=False)
    write(80); first = collect()
    write(20); second = collect()
    _require(first.get("lowValueCloseoutCount", 0) == 0 and second.get("lowValueCloseoutCount", 0) == 1,
             "route trust projection did not refresh actual changed closeout file")


def run(root, contracts, categories):
    root = Path(root).resolve(); root.mkdir(parents=True, exist_ok=True)
    rows = []
    def invoke(identity, category, action):
        if identity not in contracts or category not in categories:
            return
        started = time.perf_counter()
        row = {"id": f"control.{identity}.{category}", "category": category, "contracts": [identity],
               "boundary": "direct production action/projector; owned scratch files and independent bytes/state observations; no provider, network, supervisor or home discovery"}
        try:
            action(); row.update(status="passed", detail="Generated feature input and independent durable/projection effect agreed")
        except Exception as error:
            row.update(status="failed", detail=f"{type(error).__name__}: {error}")
        row["durationMs"] = round((time.perf_counter() - started) * 1000, 3); rows.append(row)
    for category, text in TEXTS.items():
        for kind in sorted(CONTROL_PURE):
            invoke("proofs-c.control." + kind, category, lambda kind=kind, category=category, text=text: _control_pure(kind, category, text))
        for kind in sorted(CONTROL_FILES):
            area = root / f"{kind}-{category}"; area.mkdir(exist_ok=True)
            invoke("proofs-c.control." + kind, category, lambda area=area, kind=kind, category=category, text=text: _control_files(area, kind, category, text))
        for kind in sorted(HARNESS_TEXT):
            area = root / f"harness-{kind}-{category}"; area.mkdir(exist_ok=True)
            invoke("proofs-b.harness." + kind, category, lambda area=area, kind=kind, category=category, text=text: _harness(area, kind, category, text))
    for kind in ("workspaces", "cache", "events", "images", "evidence", "preview", "delete", "attachment"):
        area = root / ("stale-" + kind); area.mkdir(exist_ok=True)
        invoke("proofs-c.control." + kind, "stale", lambda area=area, kind=kind: _control_stale(area, kind))
    for kind in ("workspaces", "images", "evidence", "preview", "validation-actions"):
        area = root / ("parallel-read-" + kind); area.mkdir(exist_ok=True)
        invoke("proofs-c.control." + kind, "concurrency", lambda area=area, kind=kind: _concurrent_file_observation(area, kind))
    for mode in ("concurrency", "permissions", "stale"):
        area = root / ("notification-ledger-" + mode); area.mkdir(exist_ok=True)
        invoke("proofs-c.control.notifications", mode, lambda area=area, mode=mode: _notification_ledger_case(area, mode))
    area = root / "preview-permission"; area.mkdir(exist_ok=True)
    invoke("proofs-c.control.preview", "permissions", lambda: _preview_permission(area))
    area = root / "validation-permission"; area.mkdir(exist_ok=True)
    invoke("proofs-c.control.validation-actions", "permissions", lambda: _validation_permission(area))
    area = root / "proof-digest-stale"; area.mkdir(exist_ok=True)
    invoke("proofs-c.control.proof-digest", "stale", lambda: _proof_digest_stale(area))
    area = root / "progress-stale"; area.mkdir(exist_ok=True)
    invoke("proofs-c.control.progress", "stale", lambda: _progress_stale(area))
    for kind, summary in (("route-trust", False), ("harness-summary", True)):
        area = root / (kind + "-stale"); area.mkdir(exist_ok=True)
        invoke("proofs-c.control." + kind, "stale", lambda area=area, summary=summary: _route_trust_stale(area, summary=summary))
    area = root / "workspace-init-interrupted"; area.mkdir(exist_ok=True)
    invoke("proofs-c.control.workspaces", "interrupted", lambda: _workspace_initialization_interrupted(area))
    area = root / "workspace-delete-interrupted"; area.mkdir(exist_ok=True)
    invoke("proofs-c.control.delete", "interrupted", lambda: _delete_interrupted(area))
    area = root / "profiles-concurrent"; area.mkdir(exist_ok=True)
    invoke("proofs-b.harness.public-profile", "concurrency", lambda: _concurrent_profiles(area))
    area = root / "admission-concurrent"; area.mkdir(exist_ok=True)
    invoke("proofs-b.harness.admission", "concurrency", lambda: _admission(area))
    for category in ("stale", "permissions"):
        area = root / ("policy-" + category); area.mkdir(exist_ok=True)
        invoke("proofs-b.harness.policy", category, lambda area=area, category=category: _policy(area, category))
    for kind in ("identity", "lifecycle", "lock-recovery"):
        area = root / ("worker-exit-" + kind); area.mkdir(exist_ok=True)
        invoke("proofs-b.harness." + kind, "interrupted", lambda area=area, kind=kind: _interrupted(area, kind))
    area = root / "instruction-denied"; area.mkdir(exist_ok=True)
    invoke("proofs-b.harness.instruction", "permissions", lambda: _instruction_permission(area))
    area = root / "attachment-denied"; area.mkdir(exist_ok=True)
    invoke("proofs-c.control.attachment", "permissions", lambda: _attachment_permission(area))
    area = root / "workspace-delete-denied"; area.mkdir(exist_ok=True)
    invoke("proofs-c.control.delete", "permissions", lambda: _delete_permission(area))
    area = root / "attachment-interrupted"; area.mkdir(exist_ok=True)
    invoke("proofs-c.control.attachment", "interrupted", lambda: _attachment_interrupted(area))
    area = root / "json-interrupted"; area.mkdir(exist_ok=True)
    invoke("proofs-c.control.replace-lock", "interrupted", lambda: _replace_lock_interrupted(area))
    area = root / "attachment-concurrent"; area.mkdir(exist_ok=True)
    invoke("proofs-c.control.attachment", "concurrency", lambda: _parallel_attachments(area))
    area = root / "workspace-delete-concurrent"; area.mkdir(exist_ok=True)
    invoke("proofs-c.control.delete", "concurrency", lambda: _delete_concurrent(area))
    area = root / "json-denied"; area.mkdir(exist_ok=True)
    invoke("proofs-c.control.replace-lock", "permissions", lambda: _replace_lock_permission(area))
    area = root / "json-concurrent"; area.mkdir(exist_ok=True)
    invoke("proofs-c.control.replace-lock", "concurrency", lambda: _parallel_json(area))
    area = root / "instruction-concurrent"; area.mkdir(exist_ok=True)
    invoke("proofs-b.harness.instruction", "concurrency", lambda: _parallel_instruction(area))
    return rows
