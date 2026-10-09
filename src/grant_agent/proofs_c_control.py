"""Control-room action invariants and local, durable manual self-checks.

No snapshots/provider discovery, supervisor calls, sync, or home-store reads are
performed by this self-check. The remaining cross-runtime cases stay retained.
"""
from __future__ import annotations
from .proof_ports import proof_port, proof_text

import inspect
import json
import re
import tempfile
import time
import zlib
import struct
from contextlib import nullcontext
from dataclasses import asdict
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path


def require(condition, contract, detail):
    if not condition:
        from .proof_contracts import ContractViolation
        raise ContractViolation(f"proofs-c.control.{contract}: {detail}")


def checked(kind):
    """Check actual action inputs/results without changing public signatures."""
    def decorate(action):
        signature = inspect.signature(action)
        @wraps(action)
        def invoke(*args, **kwargs):
            values = signature.bind(*args, **kwargs)
            values.apply_defaults()
            inputs = values.arguments
            # Keep the submitted write and its actual readback in one target
            # transaction. Otherwise a second successful writer can replace the
            # file while this call is validating it (and Windows denies replace
            # while another writer's read handle is open).
            guard = nullcontext()
            if kind == "replace-lock":
                from .harness_jobs import _exclusive_job_lock
                guard = _exclusive_job_lock(Path(inputs["path"]), timeout_seconds=120)
            with guard:
                before = capture(kind, inputs)
                result = action(*args, **kwargs)
                check(kind, inputs, result, before)
                return result
        return invoke
    return decorate


def capture(kind, inputs):
    store = inputs.get("self")
    if kind == "workspaces":
        payload = store._load_json(store.workspaces_path, [])
        return [dict(row) for row in payload if isinstance(row, dict)] if isinstance(payload, list) else []
    if kind == "delete":
        return {"workspaces": [asdict(row) for row in store.load_workspaces()],
                "missions": [asdict(row) for row in store.load_missions()],
                "history": store.load_workspace_actions()}
    if kind == "queue":
        return {row.mission_id: (row.state.queue_position, row.state.blocking_mission_id, row.state.queue_reason)
                for row in inputs["missions"]}
    if kind == "events":
        from .mission_control import _read_text_tail_lines
        rows = _read_text_tail_lines(store.events_path, limit=max(0, int(inputs["limit"])))
        output = []
        for line in reversed(rows):
            try:
                output.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return output
    if kind == "cache":
        from .mission_control import _CONTROL_ROOM_JSON_CACHE, _CONTROL_ROOM_JSON_CACHE_LOCK
        path = inputs["path"]
        try:
            stat = path.stat()
        except OSError:
            return None
        with _CONTROL_ROOM_JSON_CACHE_LOCK:
            row = _CONTROL_ROOM_JSON_CACHE.get(str(path.resolve()))
        stamp = (stat.st_mtime_ns, stat.st_size)
        return {"stamp": stamp, "cached": row if row and row[0:2] == stamp else None}
    if kind == "images":
        root = inputs["root"]
        direct = []
        has_manifests = False
        for suffix in ("image_playground_artifacts", "generated_image_artifacts", "design_references"):
            folder = root / ".agent_control" / suffix
            has_manifests = has_manifests or any(folder.rglob("*.manifest.json"))
            paths = [path for path in folder.rglob("*") if path.is_file() and path.suffix.lower() in {".apng", ".avif", ".gif", ".jpeg", ".jpg", ".png", ".webp"}]
            for path in sorted(paths, key=lambda value: value.stat().st_mtime, reverse=True)[:120]:
                if path.stat().st_size >= 512 and str(path.resolve()) not in direct:
                    direct.append(str(path.resolve()))
        return None if has_manifests else direct[:40]
    return None


def check(kind, inputs, result, before=None):
    from . import mission_control as control
    if kind in {"goal-audit", "loss-audit", "storage-triage", "preview", "proof-digest", "progress", "mission-counts", "workspace-queue", "route-trust", "release-quality", "notifications", "overnight", "git-actions", "validation-actions", "replace-lock", "harness-summary", "mission-loop"}:
        return check_projection(kind, inputs, result)
    if kind == "workspaces":
        store = inputs["self"]
        require(bool(result), kind, "workspace fallback missing")
        durable = json.loads(store.workspaces_path.read_text(encoding="utf-8"))
        require(durable == [asdict(row) for row in result], kind, "returned workspace differs from durable projection")
        if not before:
            require(len(result) == 1 and result[0].workspace_id == "workspace_primary" and result[0].root_path == str(store.root), kind, "default identity/root missing")
        old = {row.get("workspace_id"): row for row in before or []}
        current_release = store._split_release_path(str(store.root))
        for row in result:
            previous = old.get(row.workspace_id)
            if not previous:
                continue
            old_root = str(previous.get("root_path") or "")
            old_release = store._split_release_path(old_root)
            if current_release and old_release and store._path_identity_key(current_release[0]) == store._path_identity_key(old_release[0]):
                expected = str(Path(current_release[0]) / current_release[1] / old_release[2].lstrip("/\\"))
                require(store._path_identity_key(row.root_path) == store._path_identity_key(expected), kind, "release root not reanchored")
            else:
                require(row.root_path == old_root, kind, "unrelated workspace moved")
    elif kind == "delete":
        store, identity = inputs["self"], inputs["workspace_id"]
        remaining = store.load_workspaces()
        expected = [row["workspace_id"] for row in before["workspaces"] if row["workspace_id"] != identity]
        require([row.workspace_id for row in remaining] == expected and bool(expected), kind, "workspace removal lost unrelated/last workspace")
        removed = [row for row in before["missions"] if row["workspace_id"] == identity]
        require(result[0].workspace_id == identity and result[1] == len(removed), kind, "removal receipt count incorrect")
        require({row.mission_id for row in store.load_missions()} == {row["mission_id"] for row in before["missions"] if row["workspace_id"] != identity}, kind, "scoped mission deletion incorrect")
        expected_history = {key: value for key, value in before["history"].items() if key != identity}
        require(store.load_workspace_actions() == expected_history, kind, "workspace history deletion was not scoped")
    elif kind == "queue":
        missions = inputs["missions"]
        workspace_ids = {inputs["workspace_id"]} if inputs["workspace_id"] else {row.workspace_id for row in missions}
        for workspace_id in workspace_ids:
            local = [row for row in missions if row.workspace_id == workspace_id]
            eligible = [row for row in local if not control._mission_releases_workspace_slot(row) and str(row.state.status).lower() != "draft" and not control._mission_runtime_budget_exhausted(row)]
            active = [row for row in eligible if row.state.queue_position == 0]
            require(len(active) == (1 if eligible else 0), kind, "workspace does not have exactly one active eligible slot")
            waiting = sorted([row for row in eligible if row.state.queue_position > 0], key=lambda row: row.state.queue_position)
            require([row.state.queue_position for row in waiting] == list(range(1, len(waiting) + 1)), kind, "queue positions not contiguous")
            for row in waiting:
                require(row.state.status == "queued" and row.state.blocking_mission_id == active[0].mission_id and "active slot" in row.state.queue_reason, kind, "queued row lacks actual blocking owner")
            for row in local:
                if row in active or control._mission_releases_workspace_slot(row):
                    require(row.state.queue_position == 0 and row.state.blocking_mission_id is None and row.state.queue_reason == "", kind, "released/front row retains stale blocker")
                elif control._mission_runtime_budget_exhausted(row):
                    require(row.state.queue_position == 0 and row.state.blocking_mission_id is None and row.state.queue_reason in {"", "Runtime budget exhausted. Extend or resume with a fresh budget."}, kind, "exhausted row still holds another mission's queue blocker")
            for row in active:
                if any(before[row.mission_id]) and row.state.status == "queued":
                    require("front of the workspace queue" in row.proof.summary, kind, "promotion receipt absent")
    elif kind == "events":
        require(result == before and len(result) <= max(0, int(inputs["limit"])), kind, "event tail is not newest first or bounded")
    elif kind == "cache":
        path = inputs["path"]
        try:
            stat = path.stat()
        except OSError:
            return
        # Cache locking serializes readers, but an atomic writer can replace
        # the file between the captured stamp and the actual read. That read
        # legitimately observes the new revision instead of the old object.
        if before is None or before["stamp"] != (stat.st_mtime_ns, stat.st_size):
            return
        if before["cached"] is not None:
            require(result is before["cached"][2], kind, "unchanged cached parse identity lost")
        elif stat.st_size <= control.CONTROL_ROOM_JSON_CACHE_MAX_BYTES and isinstance(result, (list, dict)) and result is not inputs["default"]:
            with control._CONTROL_ROOM_JSON_CACHE_LOCK:
                cached = control._CONTROL_ROOM_JSON_CACHE.get(str(path.resolve()))
            require(cached is not None and cached[2] is result, kind, "new parse was not cached")
    elif kind == "mode":
        expected = {"focus": "fast", "autopilot": "autopilot", "deep run": "deep_run", "research": "swarms"}.get(inputs["mode"].strip().lower(), "autopilot")
        require(result == expected, kind, "desktop engine mode changed")
    elif kind == "title":
        text = re.split(r"[\n.!?]", re.sub(r"\s+", " ", inputs["objective"] or "").strip(), maxsplit=1)[0].strip()
        for prefix in control.MISSION_TITLE_PREFIXES:
            text = re.sub(prefix, "", text, flags=re.IGNORECASE).strip()
        tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9+./_-]*", text)
        significant = [token for index, token in enumerate(tokens) if index < 2 or token.lower() not in control.MISSION_TITLE_STOPWORDS][:6]
        expected = " ".join(significant)
        if expected:
            expected = expected[:1].upper() + expected[1:]
        require(result == (expected or "New Mission"), kind, "mission title loses significant words or retains prompt filler")
    elif kind == "scope":
        require(len(result) <= 8 and len({row.lower() for row in result}) == len(result), kind, "scope not bounded/deduplicated")
        require(all("\\" not in row and "://" not in row and not row.endswith("/") for row in result), kind, "scope paths not normalized")
        lines = (inputs["objective"] or "").splitlines()
        for line in lines:
            if "fusion workspace:" in line.lower():
                explicit = re.findall(r"`([^`]+)`", line)
                require(all(row.replace("\\", "/").rstrip("/") in result for row in explicit), kind, "explicit fusion workspace missing")
            if "source:" in line.lower() and "workspace" not in line.lower():
                require(all(row.replace("\\", "/").rstrip("/") not in result for row in re.findall(r"`([^`]+)`", line)), kind, "read-only source became edit scope")
        artifact = re.search(r"\b(?:all artifacts|artifacts) under\s+([^\s]+)", inputs["objective"] or "", re.IGNORECASE)
        if artifact:
            require(artifact[1].rstrip(".,;:)/").replace("\\", "/") in result, kind, "explicit artifact directory missing")
    elif kind == "budget":
        mission = inputs["mission"]
        require(all(result[key] >= 0 for key in ("maxRuntimeSeconds", "elapsedSeconds", "remainingSeconds")), kind, "negative budget")
        deadline = control._parse_iso_datetime(mission.run_budget.deadline_at)
        start = control._parse_iso_datetime(mission.created_at)
        now = (inputs["now"] or datetime.now(timezone.utc)).astimezone(timezone.utc)
        stored = max(0, int(mission.state.elapsed_runtime_seconds or 0))
        elapsed = max(0, round((now - start).total_seconds())) if start else 0
        if deadline and start and result["enforced"] and not (mission.state.status == "running" and stored > elapsed):
            require(result["deadlineAt"] == deadline.isoformat() and result["maxRuntimeSeconds"] == max(0, round((deadline - start).total_seconds())) and result["remainingSeconds"] == max(0, round((deadline - now).total_seconds())) and result["elapsedSeconds"] == elapsed, kind, "explicit deadline did not override nominal duration")
    elif kind == "verification":
        mission = inputs["mission"]
        if inputs["verification_result"] == "failed":
            failed = (mission.proof.failed_checks or mission.state.verification_failures)[:2]
            labels = []
            for row in failed:
                if isinstance(row, dict):
                    label = next((str(row[key]).strip() for key in ("checkId", "id", "label", "title", "message", "detail", "status") if row.get(key) and str(row[key]).strip()), json.dumps(row, sort_keys=True, ensure_ascii=True))
                else:
                    label = str(row)
                labels.append(label)
            require(result == ("Failed: " + ", ".join(labels) if labels else "Verification failed."), kind, "structured failed checks not labelled correctly")
    elif kind == "attachment":
        root = Path(inputs["root"]).resolve()
        require(result["schema"] == "fluxio.ui_verifier_proof_attachment.v1" and result["artifactCount"] == len(result["artifacts"]), kind, "attachment manifest schema/count incorrect")
        manifest_path = Path(result["manifestPath"])
        require(manifest_path.is_relative_to(root) and json.loads(manifest_path.read_text(encoding="utf-8")) == result, kind, "manifest not durable/confined")
        for row in result["artifacts"]:
            source, target = Path(row["originalPath"]), Path(row["path"])
            require(source.is_relative_to(root) and target.is_relative_to(root) and source.read_bytes() == target.read_bytes() and target.stat().st_size == row["bytes"], kind, "proof attachment not a faithful confined copy")
    elif kind == "images":
        require(result["summary"]["total"] == len(result["items"]), kind, "image summary count differs")
        if before is not None:
            require([str(Path(row["artifactPath"]).resolve()) for row in result["items"]] == before, kind, "manifest-free direct artifacts omitted/reordered")
        for row in result["items"]:
            path = Path(row["artifactPath"])
            require(path.is_file() and path.stat().st_size >= 512 and row["previewUrl"] == control._artifact_api_url(path), kind, "image evidence missing or URL unbound")
            if row["source"] == "generated_image_artifact_file":
                require(row["artifactId"] == path.stem, kind, "direct image identity missing")
    elif kind == "evidence":
        require(isinstance(result, Path), kind, "recovered evidence has no path")
        raw = str(inputs["raw_path"]).replace("\\", "/")
        embedded = re.search(r"[A-Za-z]:/[^\n]*", raw)
        if embedded:
            direct = Path(embedded[0]).resolve()
            if direct.is_file():
                require(result.resolve() == direct, kind, "existing embedded Windows evidence not recovered")


def self_check(root):
    from . import mission_control as control
    from .models import Mission, MissionRunBudget, MissionEvent
    started = time.perf_counter()
    base = Path(root).resolve()
    base.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="control-", dir=base))
    cases = []

    def run(case, kind, action):
        contracts = [f"proofs-c.control.{value}" for value in (kind if isinstance(kind, list) else [kind])]
        case_started = time.perf_counter()
        try:
            action()
            cases.append({"id": case, "contracts": contracts, "ok": True})
        except Exception as error:
            cases.append({"id": case, "contracts": contracts, "ok": False, "error": str(error)})
        cases[-1]["durationMs"] = round((time.perf_counter() - case_started) * 1000, 3)

    def store_at(name):
        store = control.ControlRoomStore(scratch / name)
        require(store.root.is_relative_to(scratch), "isolation", "authority setting redirects outside scratch")
        return store

    def fallback(content):
        store = store_at("fallback-" + str(len(cases)))
        store.workspaces_path.write_text(content, encoding="utf-8")
        rows = store.load_workspaces()
        require(len(rows) == 1 and rows[0].workspace_id == "workspace_primary", "workspaces", "fallback absent")
    run("test_empty_workspace_store_falls_back_to_default_workspace", "workspaces", lambda: fallback(""))
    run("test_invalid_workspace_store_falls_back_to_default_workspace", "workspaces", lambda: fallback("{"))

    def reanchor():
        store = store_at("syntelos/releases/20261003-000000")
        previous = scratch / "syntelos/releases/20261002-000000"
        previous.mkdir(parents=True)
        row = asdict(store._default_workspace_profile())
        row["root_path"] = str(previous)
        store._write_json_if_changed(store.workspaces_path, [row])
        require(store.load_workspaces()[0].root_path == str(store.root), "workspaces", "saved old release not reanchored")
    run("test_workspace_store_reanchors_old_release_root_to_current_release", "workspaces", reanchor)

    def preserve():
        store = store_at("preserve")
        unrelated = scratch / "unrelated"
        unrelated.mkdir()
        row = asdict(store._default_workspace_profile())
        row["root_path"] = str(unrelated)
        store._write_json_if_changed(store.workspaces_path, [row])
        require(store.load_workspaces()[0].root_path == str(unrelated), "workspaces", "external local workspace moved")
    run("test_workspace_store_keeps_non_release_roots_unchanged", "workspaces", preserve)

    def new_mission(store, workspace, objective):
        return store.create_mission(workspace_id=workspace, runtime_id="manual-local", objective=objective, success_checks=[], mode="Autopilot", verification_commands=[], max_runtime_seconds=3600)

    def deletion():
        store = store_at("deletion")
        primary = store.load_workspaces()[0]
        secondary = store.upsert_workspace(name="Secondary", root_path=str(scratch / "secondary"), default_runtime="manual-local", user_profile="builder", auto_sync_to_nas=False)
        mission = new_mission(store, secondary.workspace_id, "Keep local receipt")
        store.append_workspace_action(secondary.workspace_id, {"actionId": "local_receipt", "result": {"ok": True}})
        removed, count = store.delete_workspace(secondary.workspace_id)
        require(removed.workspace_id == secondary.workspace_id and count == 1 and mission.mission_id not in {row.mission_id for row in store.load_missions()} and store.get_workspace(primary.workspace_id) is not None and secondary.workspace_id not in store.load_workspace_actions(), "delete", "scoped deletion failed")
    run("test_delete_workspace_removes_scoped_missions_and_history", "delete", deletion)

    def promotion(status):
        store = store_at("promotion-" + status)
        workspace = store.load_workspaces()[0]
        first = new_mission(store, workspace.workspace_id, "First owns workspace")
        queued = new_mission(store, workspace.workspace_id, "Second waits")
        require(first.state.queue_position == 0 and queued.state.queue_position == 1 and queued.state.blocking_mission_id == first.mission_id, "queue", "second did not queue")
        first.state.status = status
        store.update_mission(first)
        store.rebalance_mission_queue(workspace.workspace_id)
        restored = control.ControlRoomStore(store.root).get_mission(queued.mission_id)
        require(restored.state.queue_position == 0 and restored.state.blocking_mission_id is None and restored.state.queue_reason == "" and "front of the workspace queue" in restored.proof.summary, "queue", "terminal owner did not release next mission after restart")
    run("test_completed_active_mission_promotes_next_queued_mission", "queue", lambda: promotion("completed"))
    run("test_blocked_active_mission_releases_next_queued_mission", "queue", lambda: promotion("blocked"))

    def events():
        store = store_at("events")
        for index in range(271):
            store.append_event(MissionEvent(mission_id="local", kind=f"record.{index}", message="Durable event"))
        require([row["kind"] for row in store.recent_events(5)] == [f"record.{index}" for index in range(270, 265, -1)], "events", "newest event window differs")
        with store.events_path.open("a", encoding="utf-8") as handle:
            handle.write("malformed\n")
        require(len(store.recent_events(5)) == 4 and store.recent_events(0) == [], "events", "malformed/zero tail handling failed")
    run("test_recent_events_reads_only_tail_rows_in_newest_first_order", "events", events)

    def cache_reuse():
        store = store_at("cache-reuse")
        path = store.control_dir / "sample.json"
        path.write_text(json.dumps([{"receipt": "first"}]), encoding="utf-8")
        first = store._load_json(path, [])
        second = store._load_json(path, [])
        require(first == [{"receipt": "first"}] and first is second, "cache", "unchanged durable parse not reused")
    run("test_control_room_json_loader_reuses_unchanged_file_parse", "cache", cache_reuse)
    def cache_invalidate():
        store = store_at("cache-invalidate")
        path = store.control_dir / "sample.json"
        store._write_json_if_changed(path, [{"receipt": 1}])
        first = store._load_json(path, [])
        store._write_json_if_changed(path, [{"receipt": 2}])
        require(first == [{"receipt": 1}] and store._load_json(path, []) == [{"receipt": 2}], "cache", "durable write retained stale parse")
    run("test_control_room_json_loader_invalidates_after_write", "cache", cache_invalidate)

    def modes():
        require([control.mission_mode_to_engine_mode(row) for row in ("Focus", "Autopilot", "Deep Run", "Research", "Unknown")] == ["fast", "autopilot", "deep_run", "swarms", "autopilot"], "mode", "desktop vocabulary changed")
    run("test_mode_mapping_matches_desktop_vocabulary", "mode", modes)
    def titles():
        require(control._mission_title("Please tighten Neyvia trust story and import Codex sessions.") == "Tighten Neyvia trust story import Codex" and control._mission_title("Can you repair restart continuity for delegated approvals?") == "Repair restart continuity delegated approvals" and control._mission_title("") == "New Mission", "title", "title prompt filler/significant words changed")
    run("test_mission_title_strips_prompt_filler_and_keeps_codex_style_name", "title", titles)
    def artifact_scope():
        target = str(scratch / "artifact-output").replace("\\", "/")
        require(control.infer_planned_file_scope(f"Put all artifacts under {target}.", []) == [target], "scope", "explicit artifact scope lost")
    run("test_infer_planned_file_scope_extracts_artifact_directory", "scope", artifact_scope)
    def fusion_scope():
        target = str(scratch / "fusion").replace("\\", "/")
        source = str(scratch / "source").replace("\\", "/")
        result = control.infer_planned_file_scope(f"Source projects:\n- Product source: `{source}`\n- Fusion workspace: `{target}`\nRun tests/build/smoke checks.", [])
        require(result == [target], "scope", "fusion includes source or validation prose")
    run("test_infer_planned_file_scope_prefers_fusion_workspace_over_sources", "scope", fusion_scope)

    def budget():
        mission = Mission(mission_id="budget", workspace_id="local", runtime_id="manual-local", objective="Work to deadline", success_checks=[], created_at="2026-10-02T22:00:00Z", run_budget=MissionRunBudget(mode="Autopilot", max_runtime_seconds=3600, deadline_at="2026-10-03T08:00:00Z", enforced=True))
        result = control.mission_time_budget_window(mission, now=datetime(2026, 10, 3, 1, tzinfo=timezone.utc))
        require((result["maxRuntimeSeconds"], result["elapsedSeconds"], result["remainingSeconds"]) == (36000, 10800, 25200), "budget", "deadline calculation wrong")
    run("test_mission_time_budget_window_prefers_explicit_deadline", "budget", budget)
    def failures():
        mission = Mission(mission_id="failure", workspace_id="local", runtime_id="manual-local", objective="Inspect failure", success_checks=[])
        mission.proof.failed_checks = [{"checkId": "durable_receipt", "detail": "Persisted"}, {"title": "Artifact gate", "status": "failed"}]
        require(control._verification_summary_for_mission(mission, "failed") == "Failed: durable_receipt, Artifact gate", "verification", "structured failed check labels changed")
    run("test_verification_summary_handles_structured_failed_check_rows", "verification", failures)

    def png_bytes():
        def chunk(name, value):
            return struct.pack(">I", len(value)) + name + value + struct.pack(">I", zlib.crc32(name + value) & 0xffffffff)
        pixels = b"".join(b"\x00" + bytes([index, 90, 180]) * 16 for index in range(16))
        return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 16, 16, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(pixels, 0)) + chunk(b"IEND", b"")
    def images():
        target = scratch / "images"
        artifact = target / ".agent_control/generated_image_artifacts/direct-proof.png"
        artifact.parent.mkdir(parents=True)
        artifact.write_bytes(png_bytes())
        result = control._build_generated_image_artifacts_snapshot(target)
        require(len(result["items"]) == 1 and result["items"][0]["source"] == "generated_image_artifact_file" and result["items"][0]["artifactId"] == "direct-proof", "images", "direct image lacks usable evidence")
    run("test_generated_image_artifact_snapshot_includes_direct_images_without_manifest", "images", images)
    def attachment():
        target = scratch / "attachments"
        run_dir = target / "proof-source"
        run_dir.mkdir(parents=True)
        image, report = run_dir / "preview.png", run_dir / "report.json"
        image.write_bytes(png_bytes())
        report.write_text(json.dumps({"ok": True, "source": "manual-self-check"}), encoding="utf-8")
        result = control.attach_verifier_proof_bundle(target, "local", "self-check", [{"path": str(image), "kind": "screenshot"}], report_path=str(report), checks=[{"checkId": "local", "passed": True}])
        require(result["artifactCount"] == 2, "attachment", "report not attached")
        outside = scratch / "outside.png"
        outside.write_bytes(png_bytes())
        try:
            control.attach_verifier_proof_bundle(target, "local", "rejected", [{"path": str(outside)}])
        except RuntimeError:
            pass
        else:
            require(False, "attachment", "out-of-root attachment accepted")
        require(not (target / ".agent_control/mission_artifacts/local/ui_verifier_proof/rejected/manifest.json").exists(), "attachment", "rejected attachment published manifest")
    run("test_attach_verifier_proof_bundle_copies_report_and_rejects_external_paths", "attachment", attachment)
    def evidence():
        target = scratch / "evidence"
        artifact = target / ".agent_control/runtime_sessions/delegate.events.jsonl"
        artifact.parent.mkdir(parents=True)
        artifact.write_text('{"kind":"runtime.output","message":"Local durable output"}\n', encoding="utf-8")
        require(bool(artifact.drive), "evidence", "Windows embedded path proof requires Windows")
        malformed = f"/mnt/c/scratch-placeholder/{artifact}"
        require(control._recover_evidence_path(target, malformed) == artifact.resolve(), "evidence", "embedded Windows path not recovered")
    run("test_recover_evidence_path_extracts_embedded_windows_runtime_path", "evidence", evidence)
    extended_self_check(scratch, run)
    return {"ok": all(row["ok"] for row in cases), "cases": cases, "contracts": sorted({identity for row in cases for identity in row["contracts"]}), "failures": [row for row in cases if not row["ok"]], "scratchRoot": str(scratch), "durationMs": round((time.perf_counter() - started) * 1000, 3), "frontier": "Mapped local projections consume recorded mission/evidence facts; they do not claim authenticated live observations. Unmapped collection, auth, supervisor, NAS and runtime paths remain retained."}


def cadence_healthy(summary):
    pressure = int(summary.get("currentPressureIndex") or 0)
    next_pressure = int(summary.get("nextPressureIndex") or 0)
    advancing = int(summary.get("pressureDelta") or max(0, next_pressure - pressure)) > 0 or next_pressure > pressure > 0 or str(summary.get("status") or "").lower() in {"advancing", "escalating", "passing", "proven"}
    return int(summary.get("runCount") or 0) > 0 and int(summary.get("satisfiedEscalationTargets") or 0) > 0 and bool(summary.get("cleanPass")) and int(summary.get("latestResistanceScore") or summary.get("resistance_score") or 0) >= 90 and int(summary.get("nextAttemptBudget") or 0) > 0 and advancing


def exhausted(mission):
    state, budget = mission.state, mission.run_budget
    status = str(state.status).lower()
    if status in {"completed", "failed", "stopped", "blocked", "verification_failed", "draft"} or not budget.enforced:
        return False
    if str(state.stop_reason or state.last_budget_pause_reason).lower() == "runtime_budget" or str(state.time_budget_status).lower() in {"budget_exhausted", "runtime_budget_exhausted"}:
        return True
    active_window = status == "running" and state.remaining_runtime_seconds > 0 and str(state.time_budget_status).lower() in {"running", "delegated_active", "resume_dispatched", "active"}
    return status == "running" and budget.max_runtime_seconds > 0 and state.elapsed_runtime_seconds > 0 and (state.remaining_runtime_seconds <= 0 or state.elapsed_runtime_seconds >= budget.max_runtime_seconds and not active_window)


def check_projection(kind, inputs, result):
    from . import mission_control as control
    if kind == "goal-audit":
        rows = {row["id"]: row for row in result["rows"]}
        design, advance, live, red = (inputs[key] for key in ("design_debt_summary", "mission_advancement_summary", "live_progress", "red_summary"))
        repair = int(advance.get("repairMissionCount") or 0)
        expected_beginner = "passed" if design.get("schema") and repair == 0 and (int(design.get("interfaceScoreOutOf20") or 0) >= 20 or design.get("agentFirstViewProofPathPassed")) else "partial" if design.get("schema") else "missing"
        expected_output = "blocked" if repair else "passed" if int(advance.get("realOutputMissionCount") or 0) > 0 or int(live.get("completedMissionCount") or 0) > 0 else "partial" if int(live.get("activeMissionCount") or 0) or int(live.get("missionCount") or advance.get("missionCount") or 0) > 0 else "missing"
        expected_red = "passed" if int(red.get("runCount") or 0) > 0 and (int(red.get("pendingEscalationTargets") or 0) == 0 or cadence_healthy(red)) else "partial" if int(red.get("pendingEscalationTargets") or 0) else "missing"
        require(rows["beginner-interface"]["status"] == expected_beginner and rows["mission-output-quality"]["status"] == expected_output and rows["red-team-escalation"]["status"] == expected_red, kind, "recorded proof/cadence/output evidence misclassified")
        if design.get("agentFirstViewProofPathPassed"):
            require("Agent first-view proof path passed" in rows["beginner-interface"]["evidence"], kind, "first-view proof credit missing")
        grouped = {status: [row for row in result["rows"] if row["status"] == status] for status in ("passed", "partial", "missing", "blocked")}
        for status, items in grouped.items():
            require(result[status + "Count"] == len(items), kind, "audit count differs from requirements")
        attention = grouped["blocked"] or grouped["partial"] or grouped["missing"]
        expected_status = "blocked" if grouped["blocked"] else "partial" if grouped["partial"] or grouped["missing"] else "complete"
        weights = sum(row["weight"] for row in result["rows"])
        score = sum({"passed": 1, "partial": .55, "blocked": .2, "missing": 0}[row["status"]] * row["weight"] for row in result["rows"])
        require(result["status"] == expected_status and result["topBlocker"] == (attention[0] if attention else {}) and result["completionPercent"] == round(score / weights * 100), kind, "completion/top blocker not grounded in weighted requirements")
    elif kind == "loss-audit":
        live, red = inputs["live_progress"], inputs["red_summary"]
        drivers = {row["id"]: row for row in result["drivers"]}
        quiet = int(live.get("activeMissionCount") or 0) == 0 and all(int(live.get(key) or 0) == 0 for key in ("queuedMissionCount", "attentionMissionCount", "blockedMissionCount")) and int(live.get("missionCount") or 0) > 0 and int(live.get("completedMissionCount") or 0) > 0 and bool(live.get("zeroActiveQueueHealthy") or live.get("schedulerQueueProofPassed"))
        require(("no-active-live-missions" in drivers) == (int(live.get("missionCount") or 0) > 0 and int(live.get("activeMissionCount") or 0) == 0 and not quiet), kind, "zero-active queue proof ignored")
        if int(red.get("pendingEscalationTargets") or 0) > 0 or int(red.get("nextAttemptBudget") or 0) > 0:
            row = drivers.get("red-team-escalation-pressure")
            require(row is not None, kind, "cadence driver omitted")
            if cadence_healthy(red):
                require(row["title"] == "Red-team maintenance is scheduled" and row["lossOutOf20"] == 0 and "not a product blocker" in row["detail"], kind, "healthy cadence became a product gap")
            else:
                require(row["title"] == "Red-team difficulty must keep rising" and row["lossOutOf20"] > 0 and "benchmark becomes harder" in row["detail"], kind, "unhealthy cadence lost its gap")
        scores = [max(0, min(20, float(row.get("fluxioScore") or 0))) for row in inputs["categories"] if isinstance(row, dict) and str(row.get("category") or "").strip() and row.get("fluxioScore") is not None and str(row["fluxioScore"]).strip()]
        average = round(sum(scores) / max(1, len(scores)), 1)
        require(result["averageLossOutOf20"] == round(max(0, 20 - average), 1), kind, "category score loss not grounded")
    elif kind == "storage-triage":
        pressure = inputs["nas_storage_pressure"]
        if (pressure.get("probeConnectFailed") or pressure.get("probeTimedOut")) and not pressure.get("measuredUsageAvailable"):
            require(not result.get("measuredUsageAvailable") and result["status"] != "blocked" and any(row["severity"] == "warn" and "not a measured full-disk state" in row["nextAction"] for row in result["rows"]), kind, "unmeasured probe failure treated as full disk")
        require(not result["destructiveActionsExecuted"], kind, "triage reports a destructive action")
    elif kind == "preview":
        expected = ""
        for candidate in control._mission_artifact_root_candidates(inputs["mission"], root=inputs["root"]):
            folder = candidate / ".agent_control/mission_artifacts" / inputs["mission"].mission_id
            manifest = control._read_gate_json(folder / "artifact_manifest.json")
            if manifest.get("previewUrl"):
                expected = str(manifest["previewUrl"]).strip()
            elif manifest.get("entrypoint"):
                from urllib.parse import quote
                expected = "/api/artifact?path=" + quote(str(manifest["entrypoint"]).strip(), safe="")
            elif (folder / "index.html").is_file():
                from urllib.parse import quote
                expected = "/api/artifact?path=" + quote(str(folder / "index.html"), safe="")
            if expected:
                break
        require(result == expected, kind, "artifact preview did not bind real manifest/entrypoint/bare index")
    elif kind == "proof-digest":
        mission = inputs["mission"]
        live = getattr(mission.state, "last_preview_url", "") or getattr(mission.state, "preview_url", "")
        manifest = control.mission_artifact_manifest_preview_url(mission, root=inputs["root"]) if not live else ""
        require(result["previewUrl"] == (live or manifest or "") and result["previewSource"] == ("served_live_preview" if live else "mission_artifact_manifest" if manifest else "fixture_or_evidence_timeline"), kind, "proof digest preview precedence changed")
    elif kind == "progress":
        mission, progress = inputs["mission"], result["liveProgress"]
        state, budget = mission.state, mission.run_budget
        counts = progress["signalCounts"]
        elapsed, remaining = max(0, state.elapsed_runtime_seconds), max(0, state.remaining_runtime_seconds)
        configured_window = max(0, budget.max_runtime_seconds) if control.mission_runtime_budget_enforced(mission) else 0
        extended_window = (state.status == "running" and configured_window > 0
                           and elapsed >= configured_window and remaining > 0
                           and state.time_budget_status in control.ACTIVE_TIME_BUDGET_STATUSES)
        effective_window = (elapsed + remaining if remaining > 0 else 0) if configured_window <= 0 or extended_window else configured_window
        require(progress["maxRuntimeSeconds"] == effective_window, kind, "runtime window differs from recorded budget")
        require(progress["schema"] == "fluxio.mission_live_progress.v1" and counts["actions"] == len(mission.action_history) and counts["delegatedSessions"] == len(mission.delegated_runtime_sessions) and counts["activeRuntimeLanes"] == result["activeDelegatedLaneCount"], kind, "progress signals do not match persisted action/session facts")
        is_exhausted = exhausted(mission)
        blocked = state.status in {"blocked", "verification_failed", "failed"} or bool(state.verification_failures)
        if is_exhausted:
            require(progress["source"] == "mission_runtime_budget_exhausted" and progress["label"] == "Runtime budget exhausted" and progress["progressKind"] == "runtime_budget_exhausted" and not progress["displayAsCompletion"] and "Extend the runtime budget" in progress["nextAction"], kind, "exhausted work rendered as completion")
        elif blocked:
            require(progress["source"] == "mission_proof_repair_readiness" and progress["label"] == "Proof repair readiness" and progress["progressKind"] == "proof_repair" and not progress["displayAsCompletion"] and progress["value"] <= 64, kind, "failed work rendered as runtime completion")
        elif state.status == "queued":
            require(progress["source"] == "mission_activity_signals" and progress["label"] == "Queued live state" and progress["value"] == 4 and progress["displayAsCompletion"] and progress["progressKind"] == "runtime_progress", kind, "queued work used stale completion denominator")
        elif state.status == "running" and (
            effective_window <= 0
            or round(elapsed / max(1, effective_window) * 100) <= 0 and result["activeDelegatedLaneCount"] > 0
            or extended_window
        ):
            require(progress["source"] == "mission_activity_signals" and progress["label"] == "Live activity progress" and isinstance(progress["value"], int) and 0 < progress["value"] < 99 and progress["displayAsCompletion"], kind, "active/extended window lacks grounded activity floor")
            if budget.enforced and state.elapsed_runtime_seconds >= budget.max_runtime_seconds and state.remaining_runtime_seconds > 0:
                require(progress["maxRuntimeSeconds"] == state.elapsed_runtime_seconds + state.remaining_runtime_seconds, kind, "extended denominator lost")
        elif state.status == "running":
            require(progress["source"] == "mission_state_runtime_budget"
                    and progress["label"] == "Budget window progress"
                    and progress["value"] == max(0, min(99, round(elapsed / max(1, effective_window) * 100)))
                    and progress["displayAsCompletion"], kind, "recorded runtime window lost its budget progress")
        require(progress["remainingSeconds"] == max(0, state.remaining_runtime_seconds), kind, "remaining recorded window changed")
        if inputs.get("root") is not None and mission.planned_file_scope:
            artifacts = result["plannedScopeArtifacts"]
            require(artifacts["scopeCount"] == len(artifacts["entries"]) and artifacts["readyCount"] == sum(row.get("status") == "ready" for row in artifacts["entries"]), kind, "planned artifact counts do not match measured entries")
    elif kind == "mission-counts":
        missions = inputs["missions"]
        active = sum(row.state.status in {"launching", "running", "resume_dispatched"} and row.state.time_budget_status != "reconcile_pending" and row.state.queue_position == 0 and not exhausted(row) for row in missions)
        blocked = sum(row.state.status in {"blocked", "needs_approval", "verification_failed"} for row in missions)
        budgets = sum(exhausted(row) for row in missions)
        queued = sum(row.state.status not in control.TERMINAL_MISSION_STATUSES and row.state.queue_position > 0 for row in missions)
        require(result == {"active": active, "blocked": blocked, "runtimeBudgetAttention": budgets, "attention": blocked + budgets, "queued": queued}, kind, "mission counts confuse runtime attention with blocking/active state")
    elif kind == "workspace-queue":
        local = [row for row in inputs["missions"] if row.workspace_id == inputs["workspace_id"]]
        active = next((row for row in local if row.state.status not in control.WORKSPACE_SLOT_RELEASE_STATUSES and row.state.status != "draft" and row.state.time_budget_status != "reconcile_pending" and row.state.queue_position == 0 and not exhausted(row)), None)
        queued = [row for row in local if row.state.queue_position > 0 and (inputs["include_terminal_queue"] or row.state.status not in control.TERMINAL_MISSION_STATUSES)]
        require(result["activeMissionId"] == (active.mission_id if active else "") and result["queuedMissionCount"] == len(queued) and result["queuedMissionIds"] == [row.mission_id for row in queued], kind, "workspace projection lost actual active/queued ownership")
    elif kind == "route-trust":
        missions = inputs["missions"]
        rows = {row["taskType"]: row for row in result["taskCoverage"]}
        expected = {}
        for mission in missions:
            feedback = mission.state.operator_value_feedback
            if not isinstance(feedback, dict):
                continue
            try:
                score = int(feedback.get("score"))
            except (ValueError, TypeError):
                score = -1
            outcome = str(feedback.get("outcome") or "").lower().strip()
            signal = str(feedback.get("trustSignal") or feedback.get("trust_signal") or "").lower().strip()
            if score < 0 and not outcome and not signal:
                continue
            task = control._route_trust_task_type(asdict(mission))
            value = expected.setdefault(task, [0, 0, 0])
            value[0] += 1
            value[1] += signal == "promote" or outcome == "useful" or score >= 80
            value[2] += signal == "deprioritize" or outcome == "not_useful" or 0 <= score < 50
        for task, row in rows.items():
            counts = expected.get(task, [0, 0, 0])
            require(row["operatorValueSamples"] == counts[0] and row["usefulOperatorValueSamples"] == counts[1] and row["operatorPromoteCount"] == counts[1] and row["operatorDeprioritizeCount"] == counts[2] and row["lowValueOperatorSamples"] == counts[2] and row["missingOperatorValueSamples"] == max(0, row["requiredOperatorValueSamples"] - counts[1]), kind, "unscored completion promoted route trust")
            require((row["status"] == "proven") == (row["missingOperatorValueSamples"] == 0 and not row["repairRequired"]), kind, "route trust ignores useful sample threshold/repair")
        require(result["activeSamplingMissionCount"] == len(result["activeSamplingMissionIds"]), kind, "sampling count differs")
        for repair in result["repairPlan"]:
            row = rows[repair["taskType"]]
            require(row["repairRequired"] and "Codex gpt-5.5 high" in repair["modelPolicy"] and repair["missionId"] in row["sampleMissionObjective"] and "proof digest" in row["sampleMissionObjective"] and "operator-value closeout" in row["sampleMissionObjective"] and any("previous low-value sample failed" in text for text in row["sampleMissionSuccessChecks"]), kind, "low-value repair lacks artifact/value verification requirements")
        for mission in missions:
            for task, template in control.ROUTE_TRUST_SAMPLE_TEMPLATES.items():
                if template["objective"].lower() in mission.objective.lower() and mission.state.operator_value_feedback:
                    require(control._route_trust_task_type(asdict(mission)) == task or bool(mission.state.operator_value_feedback.get("routeTrustTaskType") or mission.state.operator_value_feedback.get("route_trust_task_type")), kind, "sampling objective lost to unrelated default route")
    elif kind == "release-quality":
        clip = lambda value: max(0, min(int(value), 100))
        completion = max(clip(inputs["completion_rate"]), clip(inputs["completed_or_continuing_rate"] or 0))
        resume = max(inputs["resume_completion_rate"], inputs["resume_completed_or_continuing_rate"] or 0) if inputs["resume_run_rate"] > 0 else 50
        expected = round((completion + clip(inputs["delegated_run_rate"] * 2) + clip(resume) + clip(100 - inputs["verification_pause_rate"])) / 4)
        require(result == expected, kind, "live continuation/terminal completion quality scoring differs")
    elif kind == "notifications":
        require(len(result) <= max(0, inputs["limit"]) and all(len(row.get("agentMessage", "")) <= 320 for row in result), kind, "notification projection not bounded")
        mission_ids = {row.mission_id for row in inputs["missions"]}
        require(all(not row.get("missionId") or row["missionId"] == "control_room" or row["missionId"] in mission_ids for row in result), kind, "notification refers to removed/legacy mission")
        for mission in inputs["missions"]:
            concrete = [(session, event) for session in mission.delegated_runtime_sessions for event in session.latest_events if event.get("kind") in control.PROCESS_RUNTIME_KINDS and event.get("message") and str(event["message"]).strip().lower() not in {"running", "completed", "read completed."}]
            if mission.state.status == "completed" and concrete and inputs["limit"] > 0:
                slices = [row for row in result if row.get("kind") == "mission_slice_completed" and row.get("missionId") == mission.mission_id]
                # Limit handling guarantees at least one slice globally, not a slice per mission.
                if len(inputs["missions"]) == 1:
                    session, event = concrete[-1]
                    require(bool(slices) and str(event["message"])[:200] in slices[0]["agentMessage"] and slices[0]["agentMessageSource"] == f"runtime_output:{session.runtime_id}:{session.delegated_id}", kind, "completed concrete runtime output lost its slice/source notification")
    elif kind == "overnight":
        missions = inputs["missions"]
        active = [row for row in missions if row.state.status not in control.TERMINAL_MISSION_STATUSES and row.state.status != "draft"]
        held = [row for row in active if row.state.status == "queued" and row.state.queue_position > 0]
        repair = [row for row in active if row not in held and (row.state.status in {"blocked", "needs_approval", "verification_failed"} or exhausted(row) or row.proof.pending_approvals or row.proof.failed_checks)]
        require(result["counts"]["heldQueued"] == len(held) and result["counts"]["actionRequired"] == len(repair) and result["counts"]["blocked"] == len(repair) and result["counts"]["attention"] == len(held) + len(repair), kind, "safely held queue misreported as repair")
        for row in result["focusItems"]:
            mission = next(value for value in missions if value.mission_id == row["missionId"])
            if mission in held:
                require(row["attentionKind"] == "held_queue" and row["blockingMissionId"] == mission.state.blocking_mission_id and "Held behind active mission" in row["summary"] and "Keep queued" in row["nextAction"], kind, "held queue loses safe ownership guidance")
        if held and repair:
            require(result["headline"] == f"{len(repair)} mission(s) need repair \u00b7 {len(held)} held safely" and "split their file scope" in result["nextAction"], kind, "overnight repair/held headline differs")
    elif kind == "git-actions":
        snapshot = inputs["git_snapshot"]
        rows = {row["actionId"]: row for row in result}
        if snapshot.get("repoDetected") and snapshot.get("trackingBranch"):
            require("pull_branch" in rows and rows["pull_branch"]["commandSurface"] == "git.pull" and rows["pull_branch"]["command"] == "git pull --ff-only", kind, "tracked branch lacks fast-forward pull action")
            if inputs["profile_parameters"].get("gitActionPolicy") == "approval_gated":
                require(rows["pull_branch"]["requiresApproval"], kind, "approval-gated pull bypassed")
        if snapshot.get("dirty") and snapshot.get("suggestedCommitMessage"):
            require(snapshot["suggestedCommitMessage"] in rows["commit_changes"]["command"], kind, "commit suggestion lost")
    elif kind == "validation-actions":
        require(len(result) <= 1, kind, "workspace validation is duplicated")
        if result:
            require(result[0]["actionId"] == "validate_workspace" and result[0]["commandSurface"] == "validate.workspace", kind, "validation action has wrong dispatch surface")
            package = control._load_json_file(inputs["workspace_root"] / "package.json") or {}
            if "frontend:build" in package.get("scripts", {}):
                require("npm run frontend:build" in result[0]["command"], kind, "detected frontend build omitted")
    elif kind == "replace-lock":
        path = inputs["path"]
        require(path.read_text(encoding="utf-8") == json.dumps(inputs["payload"], indent=2), kind, "successful atomic replace differs from actual submitted JSON")
    elif kind == "harness-summary":
        missions = inputs["missions"]
        require(result["source"] == "mission_store_delegated_sessions_summary" and result["fullSessionScanDeferred"], kind, "summary scanned unrelated runtime history")
        health = result["sessionHealth"]
        session_count = sum(len(mission.delegated_runtime_sessions) for mission in missions)
        require(health["schema"] == "fluxio.runtime_session_health.summary.v1" and health["source"] == "mission_store_delegated_sessions" and health["totalSessions"] == session_count, kind, "summary session health not confined to mission index")
        recent = sorted([mission for mission in missions if str(mission.state.status).strip()], key=lambda row: row.updated_at or row.created_at, reverse=True)[:control.HARNESS_RECENT_RUN_LIMIT]
        status = lambda row: str(row.state.status or "").strip().lower()
        completed = [row for row in recent if status(row) == "completed"]
        continuing = [row for row in recent if status(row) not in control.TERMINAL_MISSION_STATUSES and (str(row.state.stop_reason or row.state.last_budget_pause_reason or "").lower() == "delegated_runtime_running" or row.delegated_runtime_sessions or row.action_history or str(row.state.planner_loop_status or "").strip().lower() in {"running", "launching", "resume_dispatched"})]
        total = len(recent)
        efficiency = result["efficiency"]
        expected = round(len(completed) / total * 100) if total else 0
        require(efficiency["completionRate"] == expected and efficiency["completedOrContinuingRate"] == (round((len(completed) + len(continuing)) / total * 100) if total else 0), kind, "continuing work overwrote completed efficiency")
        resumed = [row for row in recent if row.current_plan_revision_id]
        require(efficiency["resumeCompletionRate"] == (round(sum(row in completed for row in resumed) / len(resumed) * 100) if resumed else 0) and efficiency["resumeCompletedOrContinuingRate"] == (round(sum(row in completed or row in continuing for row in resumed) / len(resumed) * 100) if resumed else 0), kind, "resumed terminal/continuing efficiency differs")
    elif kind == "mission-loop":
        mission = inputs["mission"]
        require(result["timeBudget"]["runUntilBehavior"] == mission.run_budget.run_until_behavior and result["timeBudget"]["enforced"] == mission.run_budget.enforced, kind, "loop loses persisted budget behavior")
        sessions = mission.delegated_runtime_sessions
        if mission.state.status not in control.TERMINAL_MISSION_STATUSES and mission.state.stop_reason == "delegated_runtime_running" and sessions and all(row.status == "completed" for row in sessions) and any(not row.acknowledged for row in sessions):
            require(result["continuityState"] == "resume_available" and result["pauseReason"] == "Delegated runtime lane completed and needs one reconciliation resume.", kind, "completed lane is still reported as active continuity")


def extended_self_check(scratch, run):
    """Exercise persisted projection inputs, local process output and bad receipts.

    Audit facts here are explicitly admitted scratch inputs to a projection, not
    evidence that an external provider, authenticated browser or supervisor ran.
    """
    import subprocess
    import sys
    from contextlib import contextmanager
    from . import mission_control as control
    from .models import DelegatedRuntimeSession
    from .proof_contracts import ContractViolation
    from .subprocess_utils import hidden_windows_subprocess_kwargs

    def persisted(name, value):
        path = scratch / (name + ".json")
        with path.open("w", encoding="utf-8", newline="") as handle:
            json.dump(value, handle, indent=2)
        return json.loads(path.read_text(encoding="utf-8"))

    def store_at(name):
        store = control.ControlRoomStore(scratch / ("projection-" + name))
        require(store.root.is_relative_to(scratch), "isolation", "authority redirects out of scratch")
        return store

    def mission_at(store, objective="Inspect a local projection", budget=3600):
        workspace = store.load_workspaces()[0]
        mission = store.create_mission(workspace_id=workspace.workspace_id, runtime_id="manual-local", objective=objective, success_checks=[], mode="Autopilot", verification_commands=[], max_runtime_seconds=budget)
        return workspace, mission

    def deny(kind, inputs, result):
        try:
            check_projection(kind, inputs, result)
        except ContractViolation:
            return
        require(False, kind, "adversarial corrupt projection accepted")

    @contextmanager
    def actual_local_process():
        # This is a real owned Python process, never a substitute provider/harness.
        program = "import sys; print('Local scratch process produced a report body.', flush=True); sys.stdin.readline()"
        child = subprocess.Popen([sys.executable, "-I", "-c", program], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **hidden_windows_subprocess_kwargs())
        try:
            body = child.stdout.readline().strip()
            require(child.poll() is None and bool(body), "local-process", "local producer did not start")
            yield child, body
        finally:
            if child.poll() is None:
                child.communicate("finish\n", timeout=5)
            require(child.returncode == 0, "local-process", "owned local producer did not complete")

    clean_red = {"runCount": 6, "status": "passing", "latestResistanceScore": 100, "currentPressureIndex": 12, "nextPressureIndex": 14, "pressureDelta": 2, "nextAttemptBudget": 4, "cleanPass": True, "satisfiedEscalationTargets": 5, "pendingEscalationTargets": 2}
    base_goal = {"system_loss_breakdown": {"schema": "fluxio.system_loss_breakdown.v1", "averageScoreOutOf20": 20, "averageLossOutOf20": 0},
        "speed_supervisor_summary": {"summaryOk": True, "detailOk": True, "summaryMaxWallMs": 10, "detailMaxWallMs": 20},
        "design_debt_summary": {"schema": "fluxio.design_debt_summary.v1", "interfaceScoreOutOf20": 20, "repairMissionCount": 0, "agentFirstViewProofPathPassed": True},
        "mission_advancement_summary": {"repairMissionCount": 0, "realOutputMissionCount": 1}, "storage_triage_summary": {"status": "ready", "usedPercent": 60, "availableBytes": 1024},
        "deployment_durability_summary": {"durable": True, "status": "durable", "temporarySymlinkCount": 0}, "public_launch_readiness": {"status": "ready"},
        "route_trust": {"provenTaskCount": 1, "taskCount": 1, "status": "proven"}, "red_summary": clean_red,
        "live_progress": {"missionCount": 1, "workspaceCount": 1, "activeMissionCount": 0, "completedMissionCount": 1}, "t3_reference": {"latestObservedRelease": "scratch"}, "must_beat_status": {"ahead": 1, "total": 1, "deficitCount": 0}}

    def goal(scenario):
        facts = persisted("goal-" + scenario, base_goal)
        if scenario == "first-view":
            facts["design_debt_summary"]["interfaceScoreOutOf20"] = 17
        elif scenario == "missing-output":
            facts["mission_advancement_summary"]["realOutputMissionCount"] = 0
            facts["live_progress"]["completedMissionCount"] = 0
        result = control._goal_completion_audit_summary(**facts)
        rows = {row["id"]: row for row in result["rows"]}
        if scenario == "first-view":
            require(rows["beginner-interface"]["status"] == "passed" and "Agent first-view proof path passed" in rows["beginner-interface"]["evidence"], "goal-audit", "recorded first-view proof not credited")
        elif scenario == "clean-cadence":
            require(result["status"] == "complete" and result["completionPercent"] == 100 and result["topBlocker"] == {} and rows["red-team-escalation"]["status"] == "passed" and rows["mission-output-quality"]["status"] == "passed", "goal-audit", "historical red targets became blocker")
        else:
            require(rows["mission-output-quality"]["status"] == "partial" and result["status"] == "partial" and result["partialCount"] == 1 and result["topBlocker"]["id"] == "mission-output-quality" and result["completionPercent"] < 100, "goal-audit", "missing output rendered as complete")
        corrupt = json.loads(json.dumps(result))
        corrupt["completionPercent"] = -1
        deny("goal-audit", facts, corrupt)
    run("test_goal_completion_credits_authenticated_agent_first_view_proof", "goal-audit", lambda: goal("first-view"))
    run("test_goal_completion_credits_clean_red_team_cadence_with_historical_pending_targets", "goal-audit", lambda: goal("clean-cadence"))
    run("test_goal_completion_does_not_mark_missing_mission_output_as_complete", "goal-audit", lambda: goal("missing-output"))

    def loss(proven, red_state=None):
        facts = persisted("loss-" + str(proven) + str(red_state), {"categories": [{"category": "Local builder", "fluxioScore": 20, "t3Score": 17}], "deficits": [], "score_cap_reason": "", "route_trust": {"missingOperatorValueSamples": 0}, "release": {"requiredGateSummary": {"passed": 1, "total": 1}}, "red_summary": clean_red if red_state else {}, "live_progress": {"missionCount": 6, "activeMissionCount": 0, "queuedMissionCount": 0, "blockedMissionCount": 0, "attentionMissionCount": 0, "completedMissionCount": 5, "schedulerQueueProofPassed": proven}})
        if red_state == "bad":
            facts["red_summary"].update({"cleanPass": False, "latestResistanceScore": 60, "pressureDelta": 0, "nextPressureIndex": 12, "status": "needs_attention"})
        result = control._system_loss_breakdown(**facts)
        drivers = {row["id"]: row for row in result["drivers"]}
        require(("no-active-live-missions" in drivers) != proven, "loss-audit", "queue-proof zero-active interpretation changed")
        if red_state:
            driver = drivers["red-team-escalation-pressure"]
            require((driver["lossOutOf20"] == 0) == (red_state == "good"), "loss-audit", "cadence gap interpretation changed")
        corrupt = json.loads(json.dumps(result))
        corrupt["averageLossOutOf20"] = -1
        deny("loss-audit", facts, corrupt)
    run("test_system_loss_does_not_flag_healthy_zero_active_scheduler_state", "loss-audit", lambda: loss(True))
    run("test_system_loss_flags_zero_active_state_without_queue_proof", "loss-audit", lambda: loss(False))
    run("test_system_loss_keeps_healthy_red_team_cadence_visible_without_gap_loss", "loss-audit", lambda: loss(True, "good"))
    run("test_system_loss_flags_unhealthy_red_team_cadence_as_gap", "loss-audit", lambda: loss(True, "bad"))

    def triage():
        facts = persisted("storage-probe-failure", {"nas_storage_pressure": {"schema": "fluxio.nas_storage_pressure.v1", "checkedAt": datetime.now(timezone.utc).isoformat(), "mount": str(scratch), "status": "probe_connect_failed", "probeConnectFailed": True, "measuredUsageAvailable": False, "usedPercent": 0, "availableBytes": 0}, "nas_storage_cleanup_plan": {}})
        result = control._storage_triage_summary(**facts)
        require(result["status"] == "ok" and not result["measuredUsageAvailable"] and result["rows"][0]["severity"] == "warn", "storage-triage", "unknown capacity became blocker")
        corrupt = json.loads(json.dumps(result)); corrupt["status"] = "blocked"
        deny("storage-triage", facts, corrupt)
    run("test_storage_triage_probe_failure_is_warning_not_blocked", "storage-triage", triage)

    def preview(live):
        store = store_at("preview-" + str(live))
        workspace, mission = mission_at(store, "Review local served artifact")
        require(control.mission_artifact_manifest_preview_url(mission, root=store.root) == "", "preview", "empty mission has a fabricated preview")
        folder = store.root / ".agent_control/mission_artifacts" / mission.mission_id
        folder.mkdir(parents=True)
        entry = folder / "index.html"
        entry.write_text("<!doctype html><title>Local report</title><main>Verified local report</main>", encoding="utf-8")
        bare = control.mission_artifact_manifest_preview_url(mission, root=store.root)
        require(bare.startswith("/api/artifact?path=") and "index.html" in bare, "preview", "bare entrypoint did not bind")
        manifest_url = "/api/artifact?path=" + str(entry)
        with (folder / "artifact_manifest.json").open("w", encoding="utf-8", newline="") as handle:
            json.dump({"schema": "fluxio.artifact_manifest.v2", "missionId": mission.mission_id, "previewUrl": manifest_url}, handle)
        if live:
            mission.state.last_preview_url = proof_text("http://127.0.0.1:48481/local-report")
        store.update_mission(mission)
        mission = control.ControlRoomStore(store.root).get_mission(mission.mission_id)
        if live:
            # last_preview_url is a transient live view property, not a field in
            # the persisted MissionStateSnapshot. Admit the saved view event.
            mission.state.last_preview_url = persisted("live-preview-event", {"url": proof_text("http://127.0.0.1:48481/local-report"), "source": "scratch projection input; no live serving claim"})["url"]
        result = control.ControlRoomStore._mission_proof_digest_payload(mission, workspace=workspace, root=store.root)
        expected = mission.state.last_preview_url if live else manifest_url
        require(result["previewUrl"] == expected and result["previewSource"] == ("served_live_preview" if live else "mission_artifact_manifest"), "proof-digest", "preview selection changed")
        corrupt = dict(result); corrupt["previewUrl"] = ""
        deny("proof-digest", {"mission": mission, "root": store.root}, corrupt)
    run("test_mission_artifact_manifest_preview_url_binds_into_proof_digest", ["preview", "proof-digest"], lambda: preview(False))
    run("test_mission_proof_digest_prefers_live_preview_over_artifact_manifest", ["preview", "proof-digest"], lambda: preview(True))

    def progress(scenario):
        store = store_at("progress-" + scenario)
        budget = 0 if scenario == "activity" else 3600 if scenario == "fresh" else 100
        workspace, mission = mission_at(store, "Inspect recorded mission progress", budget)
        mission.state.status = "queued" if scenario == "queued" else "verification_failed" if scenario == "failed" else "running"
        mission.state.planner_loop_status = "running"
        mission.state.elapsed_runtime_seconds = 0 if scenario in {"activity", "fresh"} else 99 if scenario in {"failed", "queued"} else 125
        mission.state.remaining_runtime_seconds = 3600 if scenario == "fresh" else 1 if scenario in {"failed", "queued"} else 25 if scenario in {"extended", "reconcile"} else 0
        mission.state.time_budget_status = "reconcile_pending" if scenario == "reconcile" else "delegated_active" if scenario in {"extended", "fresh"} else "running"
        if scenario in {"activity", "failed"}:
            local_receipt = store.root / "local-output.md"
            local_receipt.write_text("# Local production receipt\nA local file action was completed.\n", encoding="utf-8")
            mission.action_history = [{"action_id": "write_report", "proposal": {"kind": "file_patch"}, "result": {"result_summary": "Local report file written", "path": str(local_receipt)}}]
        if scenario == "failed":
            mission.state.verification_failures = ["artifact_gate"]
            mission.proof.failed_checks = ["Artifact gate failed"]
        with actual_local_process() as (child, body):
            if scenario in {"activity", "extended", "fresh"}:
                mission.delegated_runtime_sessions = [DelegatedRuntimeSession(delegated_id="owned-local", runtime_id="manual-local", launch_command="Owned local Python scratch producer", status="running", pid=child.pid, latest_events=[{"kind": "runtime.output", "message": body}])]
            store.update_mission(mission)
            restored = control.ControlRoomStore(store.root).get_mission(mission.mission_id)
            row = control.ControlRoomStore._mission_summary_payload(restored, root=store.root, workspace=workspace)
            output = row["liveProgress"]
            if scenario == "activity":
                require(output["signalCounts"]["actions"] == 1 and output["signalCounts"]["activeRuntimeLanes"] == 3, "progress", "unlimited activity lost actual local signals")
            elif scenario == "failed":
                require(output["value"] < 99 and output["value"] <= 64, "progress", "failed work displays stale runtime completion")
            elif scenario == "queued":
                require(output["value"] == 4, "progress", "queued work displays stale runtime completion")
            elif scenario == "extended":
                require(output["maxRuntimeSeconds"] == 150 and output["remainingSeconds"] == 25 and "Extend the runtime budget" not in output["nextAction"], "progress", "renewed window became exhausted")
            elif scenario == "fresh":
                require(output["value"] > 0, "progress", "real fresh lane lacks started floor")
            elif scenario == "reconcile":
                require(output["remainingSeconds"] == 25 and not output["displayAsCompletion"], "progress", "reconcile pending became completion")
            else:
                counts = control._control_mission_counts_projection(store.load_missions())
                require(counts == {"active": 0, "queued": 0, "blocked": 0, "runtimeBudgetAttention": 1, "attention": 1} and output["value"] == 99, "mission-counts", "exhausted counts differ")
            corrupt = json.loads(json.dumps(row)); corrupt["liveProgress"]["remainingSeconds"] = -1
            deny("progress", {"mission": restored, "root": store.root}, corrupt)
    for scenario, case in [("activity", "test_summary_running_mission_progress_falls_back_to_live_activity_signals"), ("failed", "test_summary_failed_mission_progress_uses_proof_repair_readiness"), ("queued", "test_summary_queued_mission_progress_does_not_use_stale_runtime_budget"), ("extended", "test_summary_running_mission_with_extended_remaining_budget_is_not_exhausted"), ("fresh", "test_summary_fresh_running_delegated_mission_uses_activity_progress_floor"), ("reconcile", "test_summary_reconcile_pending_over_budget_mission_is_not_completion_progress"), ("exhausted", "test_summary_over_budget_running_mission_is_not_completion_progress")]:
        run("helper_only_runtime_budget_count_projection" if scenario == "exhausted" else case, ["progress", "mission-counts"] if scenario == "exhausted" else "progress", lambda scenario=scenario: progress(scenario))

    def workspace_owner(exhaust_owner):
        store = store_at("workspace-owner-" + str(exhaust_owner))
        workspace, first = mission_at(store, "Own active workspace", 100)
        if exhaust_owner:
            first.state.status = "running"; first.state.planner_loop_status = "running"
            first.state.elapsed_runtime_seconds = 360; first.state.remaining_runtime_seconds = 0; first.state.time_budget_status = "running"
            store.update_mission(first)
        _, second = mission_at(store, "Wait safely for workspace", 600)
        missions = control.ControlRoomStore(store.root).load_missions()
        result = control._control_workspace_queue_projection(workspace.workspace_id, missions, include_terminal_queue=True)
        require(result["activeMissionId"] == (second.mission_id if exhaust_owner else first.mission_id) and result["queuedMissionCount"] == (0 if exhaust_owner else 1), "workspace-queue", "workspace owner selection differs")
        if exhaust_owner:
            counts = control._control_mission_counts_projection(missions)
            require(counts["active"] == 0 and counts["blocked"] == 0 and counts["attention"] == 1 and counts["runtimeBudgetAttention"] == 1, "mission-counts", "exhausted old owner retains active slot")
            rows = {row.mission_id: control.ControlRoomStore._mission_summary_payload(row, root=store.root, workspace=workspace) for row in missions}
            require(rows[first.mission_id]["liveProgress"]["progressKind"] == "runtime_budget_exhausted" and rows[second.mission_id]["liveProgress"]["progressKind"] != "runtime_budget_exhausted", "progress", "fresh next mission inherits exhaustion")
        else:
            queued = next(row for row in missions if row.mission_id == second.mission_id)
            require(queued.state.queue_position == 1 and queued.state.blocking_mission_id == first.mission_id and "active slot" in queued.state.queue_reason, "queue", "second mission lacks actual blocker")
        corrupt = dict(result); corrupt["activeMissionId"] = "absent"
        deny("workspace-queue", {"workspace_id": workspace.workspace_id, "missions": missions, "include_terminal_queue": True}, corrupt)
    run("test_second_mission_is_queued_behind_active_workspace_mission", ["queue", "workspace-queue"], lambda: workspace_owner(False))
    run("helper_only_exhausted_workspace_slot_projection", ["workspace-queue", "mission-counts", "progress"], lambda: workspace_owner(True))

    def route(scenario):
        store = store_at("route-" + scenario)
        if scenario == "repair":
            workspace, mission = mission_at(store, "Build frontend progress surface")
            mission.state.status = "running"; store.update_mission(mission)
            folder = store.control_dir / "route_trust_sampling"; folder.mkdir()
            (folder / "latest.json").write_text(json.dumps({"schema": "fluxio.route_trust_live_sampling_run.v1", "launchedSamplingMissions": [{"missionId": mission.mission_id, "taskType": "frontend_design", "runtime": "manual-local"}]}), encoding="utf-8")
            (folder / "closeout_review_latest.json").write_text(json.dumps({"schema": "fluxio.route_trust_sampling_closeout_review.v1", "proposals": [{"missionId": "local_low_value", "taskType": "data_f1_analytics", "missionStatus": "completed", "score": 30, "outcome": "not_useful", "trustSignal": "deprioritize"}]}), encoding="utf-8")
        elif scenario == "low-value":
            for index in range(2):
                workspace, mission = mission_at(store, f"Build F1 telemetry analytics artifact {index}")
                mission.state.status = "completed"; mission.state.operator_value_feedback = {"schema": "fluxio.mission_operator_value_feedback.v1", "score": 30, "outcome": "not_useful", "trustSignal": "deprioritize"}; store.update_mission(mission)
        else:
            workspace, mission = mission_at(store, control.ROUTE_TRUST_SAMPLE_TEMPLATES["general_coding"]["objective"])
            mission.route_configs = [{"role": "planner", "provider": "openai-codex", "model": "gpt-5.5", "task_type": "frontend_design"}]
            mission.state.status = "completed"; mission.state.operator_value_feedback = {"schema": "fluxio.mission_operator_value_feedback.v1", "score": 92, "outcome": "useful", "trustSignal": "promote"}; store.update_mission(mission)
        missions = control.ControlRoomStore(store.root).load_missions()
        result = control._build_route_trust_coverage_summary(store.root, missions=missions)
        rows = {row["taskType"]: row for row in result["taskCoverage"]}
        if scenario == "repair":
            require(result["repairPlanStatus"] == "required" and result["lowValueCloseoutCount"] == 1 and result["activeSamplingMissionIds"] == [mission.mission_id] and result["nextSamplingPlan"][0]["repairRequired"] and result["repairPlan"][0]["taskType"] == "data_f1_analytics" and result["nextSamplingPlan"][0]["sampleMissionTitle"] == "Repair F1/data analytics route trust sample", "route-trust", "low-value route repair lost priority")
        elif scenario == "low-value":
            row = rows["data_f1_analytics"]
            require(row["operatorValueSamples"] == 2 and row["operatorPromoteCount"] == 0 and row["lowValueOperatorSamples"] == 2 and row["missingOperatorValueSamples"] == 2 and row["status"] == "sampling" and "useful value-scored" in row["nextAction"], "route-trust", "bad closeouts were treated as trust")
        else:
            require(rows["general_coding"]["operatorValueSamples"] == 1 and rows["general_coding"]["usefulOperatorValueSamples"] == 1 and rows["frontend_design"]["operatorValueSamples"] == 0, "route-trust", "declared sample lost to route defaults")
        corrupt = json.loads(json.dumps(result)); corrupt["taskCoverage"][0]["operatorValueSamples"] = -1
        deny("route-trust", {"missions": missions}, corrupt)
    run("test_route_trust_coverage_surfaces_low_value_repair_plan", "route-trust", lambda: route("repair"))
    run("test_route_trust_proven_requires_useful_operator_value_samples", "route-trust", lambda: route("low-value"))
    run("test_route_trust_coverage_uses_sampling_objective_before_workspace_route_defaults", "route-trust", lambda: route("objective"))

    def quality():
        values = persisted("release-quality", {"completion_rate": 45, "completed_or_continuing_rate": 75, "delegated_run_rate": 40, "resume_run_rate": 95, "resume_completion_rate": 47, "resume_completed_or_continuing_rate": 79, "verification_pause_rate": 0})
        result = control._release_quality_score(**values)
        require(result == 84, "release-quality", "continuing quality score differs")
        deny("release-quality", values, 0)
    run("test_release_quality_counts_live_continuity_without_erasing_terminal_completion", "release-quality", quality)

    def notification(hydrate):
        store = store_at("notification-" + str(hydrate))
        workspace, mission = mission_at(store, "Inspect actual local producer notification")
        mission.title = "Local producer receipt"
        with actual_local_process() as (child, body):
            session = DelegatedRuntimeSession(delegated_id="owned-notification", runtime_id="manual-local", launch_command="Owned local Python producer", status="running", pid=child.pid, latest_events=[{"kind": "runtime.output", "message": body}])
            if hydrate:
                folder = store.control_dir / "runtime_sessions"; folder.mkdir()
                payload = asdict(session); payload["missionId"] = mission.mission_id
                (folder / "owned-notification.json").write_text(json.dumps(payload), encoding="utf-8")
                mission.state.status = "running"; mission.delegated_runtime_sessions = []
            else:
                child.communicate("finish\n", timeout=5)
                session.status = "completed"; mission.state.status = "completed"; mission.delegated_runtime_sessions = [session]
            store.update_mission(mission)
            restored = control.ControlRoomStore(store.root).get_mission(mission.mission_id)
            result = control.ControlRoomStore._build_notification_feed(missions=[restored], activity=[], root=store.root, workspace_by_id={workspace.workspace_id: workspace})
            kind = "mission_status" if hydrate else "mission_slice_completed"
            selected = [row for row in result if row["kind"] == kind and row.get("missionId") == mission.mission_id]
            require(selected and body in selected[0]["agentMessage"] and selected[0]["agentMessageSource"] == "runtime_output:manual-local:owned-notification", "notifications", "local runtime output was not hydrated/credited")
            if not hydrate:
                require("Slice completed: Local producer receipt" in selected[0]["title"], "notifications", "completion slice title missing")
            corrupt = json.loads(json.dumps(result)); corrupt[0]["missionId"] = "absent"
            deny("notifications", {"missions": [restored], "limit": 24}, corrupt)
    run("test_completed_runtime_status_emits_slice_notification", "notifications", lambda: notification(False))
    run("test_running_notification_hydrates_missing_workflow_sessions", "notifications", lambda: notification(True))

    def overnight():
        store = store_at("overnight")
        workspace, blocker = mission_at(store, "Own the actual local scope")
        blocker.state.status = "running"; store.update_mission(blocker)
        _, held = mission_at(store, "Hold overlapping local scope")
        held.proof.failed_checks = ["Artifact waits behind active scope"]; store.update_mission(held)
        _, failed = mission_at(store, "Repair the local failed artifact")
        failed.state.status = "verification_failed"; failed.proof.failed_checks = ["Verifier rejected output"]; store.update_mission(failed)
        missions = control.ControlRoomStore(store.root).load_missions()
        result = control.ControlRoomStore._overnight_progress_projection(missions=missions, recent_missions=missions, workspaces=[workspace], activity=[], notifications=[], telegram_destination="", delivery_receipts=[], web_push={}, ntfy={})
        require("1 repair \u00b7 1 held" in result["phoneSummary"] and result["counts"]["actionRequired"] == 1 and result["counts"]["heldQueued"] == 1, "overnight", "repair and held queue collapsed")
        corrupt = json.loads(json.dumps(result)); corrupt["counts"]["heldQueued"] = -1
        deny("overnight", {"missions": missions}, corrupt)
    run("test_overnight_digest_separates_repair_from_safely_held_queue", "overnight", overnight)

    def artifacts():
        store = store_at("planned-artifacts")
        workspace, mission = mission_at(store, "Build local planned report")
        folder = store.root / "planned-output"; folder.mkdir()
        (folder / "README.md").write_text("# Local artifact\nReview the served report.\n", encoding="utf-8")
        (folder / "index.html").write_text("<!doctype html><main>Local report</main>", encoding="utf-8")
        mission.planned_file_scope = [str(folder)]; mission.state.status = "completed"; store.update_mission(mission)
        restored = control.ControlRoomStore(store.root).get_mission(mission.mission_id)
        row = control.ControlRoomStore._mission_summary_payload(restored, root=store.root, workspace=workspace)
        output = row["plannedScopeArtifacts"]
        require((output["status"], output["scopeCount"], output["readyCount"], output["readmeCount"], output["previewableCount"], output["entries"][0]["fileCount"]) == ("ready", 1, 1, 1, 1, 2), "progress", "measured local artifact readiness missing")
    run("test_mission_summary_includes_planned_scope_artifact_readiness", "progress", artifacts)

    def git_actions():
        values = persisted("git-actions", {"git_snapshot": {"repoDetected": True, "remotes": [{"name": "origin", "url": "https://example.invalid/local-scratch"}], "trackingBranch": "origin/main", "ahead": 0, "behind": 2, "dirty": True, "suggestedCommitMessage": "Update local mission receipt", "deployTarget": {"available": False}}, "profile_parameters": {"gitActionPolicy": "approval_gated"}})
        result = control._build_git_actions(**values)
        require([row["actionId"] for row in result][:4] == ["inspect_repo_state", "pull_branch", "commit_changes", "push_branch"], "git-actions", "tracked branch action ordering changed")
        corrupt = [dict(row) for row in result]
        next(row for row in corrupt if row["actionId"] == "pull_branch")["requiresApproval"] = False
        deny("git-actions", values, corrupt)
    run("test_build_git_actions_includes_pull_for_tracked_branch", "git-actions", git_actions)
    def validation():
        folder = scratch / "validation-project"; folder.mkdir(); (folder / "tests").mkdir()
        (folder / "pyproject.toml").write_text("[project]\nname='local-proof'\n", encoding="utf-8")
        (folder / "package.json").write_text(json.dumps({"scripts": {"frontend:build": "vite build"}}), encoding="utf-8")
        result = control._build_validation_actions(folder)
        require(len(result) == 1 and "npm run frontend:build" in result[0]["command"], "validation-actions", "real project build command omitted")
        corrupt = [dict(result[0])]; corrupt[0]["commandSurface"] = "absent"
        deny("validation-actions", {"workspace_root": folder}, corrupt)
    run("test_build_validation_actions_uses_detected_commands", "validation-actions", validation)

    def locked_replace():
        import ctypes
        import os
        import threading
        from ctypes import wintypes
        require(os.name == "nt", "replace-lock", "actual share-delete-denial proof requires Windows")
        store = store_at("locked-replace")
        target = store.control_dir / "locked.json"
        store._write_json_if_changed(target, {"phase": "before"})
        keeper = store.control_dir / "keeper.json"
        keeper.write_bytes(b'{"unrelated":"keeper"}\n')
        keeper_bytes = keeper.read_bytes()
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        handle = kernel.CreateFileW(str(target), 0x80000000, 0x00000001, None, 3, 0x80, None)
        require(handle not in {None, ctypes.c_void_p(-1).value}, "replace-lock", "read lease could not be acquired")
        released = threading.Event()
        def release():
            kernel.CloseHandle(handle)
            released.set()
        timer = threading.Timer(.15, release)
        timer.start()
        started = time.perf_counter()
        try:
            store._write_json_if_changed(target, {"phase": "after", "actualShareDeleteDenied": True})
        finally:
            timer.join(timeout=2)
            if not released.is_set():
                release()
        elapsed = time.perf_counter() - started
        require(released.is_set() and elapsed >= .14 and json.loads(target.read_text(encoding="utf-8")) == {"phase": "after", "actualShareDeleteDenied": True} and keeper.read_bytes() == keeper_bytes and not list(store.control_dir.glob("locked.json.*.tmp")), "replace-lock", "real locked replace did not retry, persist or preserve unrelated file")
    run("test_control_room_json_writer_retries_transient_replace_lock", "replace-lock", locked_replace)

    def harness(continuing):
        store = store_at("harness-" + str(continuing))
        workspace, mission = mission_at(store, "Observe actual local harness session")
        with actual_local_process() as (child, body):
            mission.state.status = "running"; mission.state.planner_loop_status = "running"
            mission.current_plan_revision_id = "recorded_running_plan"
            mission.delegated_runtime_sessions = [DelegatedRuntimeSession(delegated_id="actual-harness-local", runtime_id="manual-local", launch_command="Owned local scratch producer", status="running", pid=child.pid, heartbeat_status="healthy", heartbeat_at=datetime.now(timezone.utc).isoformat(), heartbeat_interval_seconds=10, latest_events=[{"kind": "runtime.output", "message": body}])]
            store.update_mission(mission)
            if continuing:
                # Complete a second actual owned producer before admitting its
                # terminal receipt; the running producer remains active.
                with actual_local_process() as (finished, finished_body):
                    finished.communicate("finish\n", timeout=5)
                    _, completed = mission_at(store, "Record completed local harness receipt")
                    completed.state.status = "completed"; completed.current_plan_revision_id = "recorded_completed_plan"
                    completed.delegated_runtime_sessions = [DelegatedRuntimeSession(delegated_id="actual-harness-completed", runtime_id="manual-local", launch_command="Owned local scratch producer", status="completed", pid=finished.pid, latest_events=[{"kind": "runtime.output", "message": finished_body}])]
                    store.update_mission(completed)
            else:
                folder = store.control_dir / "runtime_sessions"; folder.mkdir()
                for index in range(17):
                    (folder / f"unrelated-history-{index}.json").write_text(json.dumps({"delegated_id": f"unrelated-{index}", "status": "running", "heartbeat_status": "stale"}), encoding="utf-8")
            restored = control.ControlRoomStore(store.root).load_missions()
            result = control.build_summary_harness_lab_snapshot(store.root, missions=restored)
            if continuing:
                efficiency = result["efficiency"]
                require((efficiency["completionRate"], efficiency["completedOrContinuingRate"], efficiency["resumeCompletionRate"], efficiency["resumeCompletedOrContinuingRate"]) == (50, 100, 50, 100), "harness-summary", "live/terminal continuity rates differ")
            else:
                health = result["sessionHealth"]
                require((health["totalSessions"], health["activeCount"], health["delegatedHealthyCount"], health["delegatedStaleCount"]) == (1, 1, 1, 0), "harness-summary", "unrelated history leaked into summary")
            corrupt = json.loads(json.dumps(result)); corrupt["sessionHealth"]["totalSessions"] = -1
            deny("harness-summary", {"missions": restored}, corrupt)
    run("test_summary_harness_lab_uses_mission_session_index_without_full_runtime_scan", "harness-summary", lambda: harness(False))
    run("test_summary_harness_lab_reports_completed_or_continuing_live_missions", "harness-summary", lambda: harness(True))

    def loop(completed):
        store = store_at("loop-" + str(completed))
        workspace, mission = mission_at(store, "Maintain recorded run-until behavior", 7200)
        mission.run_budget.mode = "Deep Run"; mission.run_budget.run_until_behavior = "continue_until_blocked"
        if completed:
            with actual_local_process() as (child, body):
                child.communicate("finish\n", timeout=5)
                mission.delegated_runtime_sessions = [DelegatedRuntimeSession(delegated_id="actual-loop-completed", runtime_id="manual-local", launch_command="Owned local scratch producer", status="completed", acknowledged=False, latest_events=[{"kind": "runtime.output", "message": body}])]
                mission.state.status = "running"; mission.state.stop_reason = "delegated_runtime_running"
        store.update_mission(mission)
        restored = control.ControlRoomStore(store.root).get_mission(mission.mission_id)
        result = control.build_mission_loop_snapshot(restored)
        if completed:
            require(result["continuityState"] == "resume_available" and result["pauseReason"] == "Delegated runtime lane completed and needs one reconciliation resume.", "mission-loop", "completed lane remained active")
        else:
            require(asdict(restored)["run_budget"]["run_until_behavior"] == "continue_until_blocked" and result["timeBudget"]["runUntilBehavior"] == "continue_until_blocked" and result["timeBudget"]["remainingSeconds"] > 0 and result["currentRuntimeLane"] == "manual-local primary lane queued", "mission-loop", "loop loses persisted time budget/run-until behavior")
        corrupt = json.loads(json.dumps(result)); corrupt["timeBudget"]["runUntilBehavior"] = "absent"
        deny("mission-loop", {"mission": restored}, corrupt)
    run("test_snapshot_surfaces_time_budget_and_run_until_behavior", "mission-loop", lambda: loop(False))
    run("test_snapshot_does_not_report_completed_delegated_lane_as_active", "mission-loop", lambda: loop(True))
