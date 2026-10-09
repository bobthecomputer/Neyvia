"""Semantic contracts at planning/UI service boundaries; no rendered-UI claims."""
from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path


def require(condition, contract, detail):
    if not condition:
        raise ValueError(f"Contract {contract}: {detail}")


def check_plan(objective, docs, plan):
    execute = any(marker in objective.lower() for marker in ("execute first", "no preflight", "first action must"))
    expected = "Implement smallest vertical slice in product files" if execute else (
        "Review referenced docs and extract constraints" if docs else "Collect missing docs/spec links before implementation")
    require(plan.plan_steps[0] == expected, "d-ui.plan-order", "first step contradicts requested execution policy")
    require(bool(plan.acceptance_checks) and ("Preview reflects expected UI behavior on desktop and mobile" in plan.acceptance_checks)
            == any(word in objective.lower() for word in ("ui", "preview")), "d-ui.plan-order", "UI proof ladder missing")


def check_plan_receipt(receipt, objective, docs, selected, brief, plan):
    require(receipt.schema == "fluxio.plan_receipt.v1" and receipt.phase == "planner" and receipt.status == "planned",
            "d-ui.plan-compact", "receipt identity changed")
    require(len(receipt.file_scope) <= 80 and len(receipt.selected_skills) <= 24 and len(receipt.forbidden_paths) <= 40
            and len(receipt.expected_changed_files) <= 80 and len(receipt.expected_artifacts) <= 40,
            "d-ui.plan-compact", "receipt exceeds list budgets")
    require(receipt.tasks and all(set(row) == {"id", "title", "status"} and len(row["title"]) <= 160 and row["status"] == "pending"
                                 for row in receipt.tasks), "d-ui.plan-compact", "task shape/budget changed")
    require(receipt.inputs["docsTruncated"] == any(len(str(row or "")) > 500 for row in docs or [])
            and not set(receipt.inputs) & {"docs", "documents"}, "d-ui.plan-compact", "raw documents leaked into compact inputs")
    from .planner import _compact_text, _selected_skill_ids_from_brief
    expected = selected if selected is not None else _selected_skill_ids_from_brief(brief)
    expected = [_compact_text(row, 120) for row in expected or [] if str(row or "").strip()][:24]
    require(receipt.selected_skills == expected and receipt.inputs["skillBriefId"] == (brief.get("brief_id") or "")
            and receipt.inputs["skillBriefSchema"] == (brief.get("schema") or ""), "d-ui.plan-skills", "manual skill override/provenance lost")
    require(receipt.verification_ladder == [_compact_text(row, 180) for row in plan.acceptance_checks[:12]]
            and receipt.goal_restatement == _compact_text(objective, 500), "d-ui.plan-compact", "receipt differs from planned goal/checks")


def check_compiled(program, payload, canonical):
    complete = set()
    steps = {row["step_id"]: row for row in payload["steps"]}
    for stage in payload["executionStages"]:
        require(all(set(steps[identity]["after"]) <= complete for identity in stage["stepIds"]),
                "d-ui.compiler-dag", "stage precedes its dependencies")
        complete.update(stage["stepIds"])
    require(complete == set(steps) and len(complete) == len(payload["steps"]), "d-ui.compiler-dag", "stages lose or duplicate steps")
    lane_map = {lane.lane_id: lane for lane in program.lanes}
    for row in payload["steps"]:
        lane = lane_map[row["lane_id"]]
        require(row["permissionEnvelope"] == {"allowed": lane.permissions, "mutability": row["risk"],
                "approvalRequired": row["risk"] in {"external_write", "destructive"}}
                and row["proofRequired"] == bool(row["output"] or row["acceptance"] or row["action"] == "verify"),
                "d-ui.compiler-authority", "permission/proof requirement differs from declared risk")
    require(payload["planHash"] == hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            and payload["estimatedPlanTokens"] == max(1, (len(canonical) + 3) // 4), "d-ui.compiler-hash", "compiled plan hash/size differs")


def check_readiness(receipt):
    failures = [key for key, passed in receipt.checks.items() if not passed]
    require(receipt.failures == failures and receipt.status == ("blocked" if failures else "passed")
            and receipt.phase == "preflight", "d-ui.night-readiness", "failed preflight allowed admission")
    require(all(value == "missing" or value == "***" or ("..." in value and len(value.split("...")[0]) == 3
                and len(value.split("...")[1]) == 4) for value in receipt.masked_keys.values()),
            "d-ui.night-readiness", "key status is not bounded/redacted")


def check_digest(root, digest):
    stored = json.loads(Path(digest["jsonPath"]).read_text(encoding="utf-8"))
    expected = {key: value for key, value in digest.items() if key not in {"jsonPath", "markdownPath"}}
    require(stored == expected, "d-ui.night-digest", "saved digest differs from returned receipt")
    for key, count in (("completedItems", "completedCount"), ("blockedItems", "blockedCount"), ("proofGaps", "proofGapCount")):
        require(digest[count] == len(digest[key]), "d-ui.night-digest", "digest count differs from evidence rows")
    markdown = Path(digest["markdownPath"]).read_text(encoding="utf-8")
    require(all(str(row) in markdown for key in ("completedItems", "blockedItems", "proofGaps", "risks", "proofCommands", "changedFiles")
                for row in digest[key]) and digest["nasSyncStatus"] in markdown and digest["firstUncheckedItem"] in markdown,
            "d-ui.night-digest", "markdown omits persisted evidence/gaps")


def check_night_policy(kind, gateway, pressure, result):
    from .night_mode import NIGHT_QUEUE_PRIORITY
    expected = "allow" if kind in NIGHT_QUEUE_PRIORITY or kind in {"browser_verification", "full_frontend_build"} else "hold"
    if kind in {"destructive_git_action", "package_upgrade", "outside_leased_workspace"} or (kind == "browser_verification" and not gateway) or (kind == "full_frontend_build" and pressure):
        expected = "defer"
    require(result["decision"] == expected and result["kind"] == kind, "d-ui.night-policy", "classification violates capacity/approval policy")


def check_night_profile(value):
    require(value["autopilot"] is True and value["mission_execution_allowed"] is True and value["profile_id"] == "production_night"
            and value["default_runtime"] == "hermes" and value["controller_host_role"] == "nas" and value["accelerator_host_role"] == "pc_gateway"
            and {"headless_executor_work", "headless_verifier_work"} <= set(value["allowed_work"])
            and {"readiness_receipt", "verification_receipt"} <= set(value["proof_requirements"])
            and "browser_verification_without_pc_gateway" in value["deferred_work"], "d-ui.night-policy", "night production policy lost execution or proof constraints")


def check_night_queue(items, value):
    require(sum(len(value[key]) for key in ("ranked","deferred","held")) == len(items)
            and value["ranked"] == sorted(value["ranked"],key=lambda row:(int(row["priority"]),row["id"]))
            and all(row["decision"] == decision for key,decision in (("ranked","allow"),("deferred","defer"),("held","hold")) for row in value[key]),
            "d-ui.night-policy", "queue loses work or misorders eligibility")


def check_notification(receipt, result, path):
    failures = receipt.get("failures") or []
    blocked = receipt.get("status") == "blocked" or bool(failures)
    require(result["receiptPath"] == path and result["status"] == ("action" if blocked else "skipped")
            and (not blocked or result["failureCount"] == len(failures) and result["failures"] == failures
                 and all(str(failure) in result["body"] for failure in failures)), "d-ui.night-notification", "notification differs from readiness receipt")


def check_ocr_aggregate(rows, result):
    require(result["samples"] == len(rows) and result["exactRate"] == round(sum(bool(row.get("exact")) for row in rows)/len(rows),8),
            "d-ui.ocr-quality", "quality count or exact rate differs from observations")
    for source, target in (("latencyMs","meanLatencyMs"),("readingOrderErrorRate","meanReadingOrderErrorRate"),("characterErrorRate","meanCharacterErrorRate"),("wordErrorRate","meanWordErrorRate")):
        values = [float(row[source]) for row in rows if row.get(source) is not None]
        require(result[target] == (round(sum(values)/len(values),8) if values else None), "d-ui.ocr-quality", "aggregate omits quality/performance dimension")
    require(result["peakVramMb"] == max((float(row["peakVramMb"]) for row in rows if row.get("peakVramMb") is not None),default=None),
            "d-ui.ocr-quality", "peak resource use lost")


def check_ocr_metric(expected, actual, value):
    require(math.isfinite(value) and value >= 0 and (expected != actual or value == 0)
            and math.isclose(value * max(1,len(expected)),round(value * max(1,len(expected)))),
            "d-ui.ocr-quality", "error rate violates normalized equality/denominator")


def check_ocr_candidates(value):
    roles = {"pp-ocrv6-medium":"primary-text", "paddleocr-vl-1.6":"primary-structured", "glm-ocr":"verified-fast-recognizer", "tesseract-5.5.2":"emergency-fallback"}
    for row in value["candidates"]:
        if row["candidateId"] in roles:
            require(row.get("role") == roles[row["candidateId"]] and (row["candidateId"] != "tesseract-5.5.2" or row.get("eligible") is False),
                    "d-ui.ocr-candidates", "known OCR identity lost role/emergency eligibility boundary")


def check_capsules(root, plan):
    from .skill_capsules import _hash
    for row in plan["instructionReceipts"]:
        path = (root / row["path"]).resolve()
        available = path.is_relative_to(root) and path.is_file()
        require(row["available"] == available and row["sha256"] == (hashlib.sha256(path.read_bytes()).hexdigest() if available else ""),
                "d-ui.design-capsules", "instruction receipt differs from current bounded source")
    require(plan["planHash"] == _hash({key:value for key,value in plan.items() if key != "planHash"}),
            "d-ui.design-capsules", "skill plan digest differs")


def check_ocr_route(signals, result):
    complex_page = any((signals.requires_layout,signals.contains_table,signals.contains_formula,signals.contains_chart,signals.contains_handwriting,signals.distorted_or_photographed))
    expected = signals.requested_engine.strip().lower() or ("native-pdf" if signals.native_text_characters >= 32 else
        "glm-ocr-bf16" if signals.prefer_fast_full_page and signals.gpu_available else "paddleocr-vl-1.6" if complex_page and signals.gpu_available else
        "pp-ocrv6-medium" if signals.gpu_available else "tesseract-fallback")
    require(result["engine"] == expected and result["automatic"] == (not bool(signals.requested_engine.strip())),
            "d-ui.ocr-route", "native/GPU/structured/override precedence changed")


def mesh_self_checks(root, run, prove, reject):
    """Validator evidence is a scratch JSON artifact, never a browser capture."""
    from copy import deepcopy
    from datetime import UTC, datetime, timedelta
    from scripts.verify_personal_mesh_browser_proof import validate_receipt, ProofError, SCHEMA
    folder = root / "mesh-validator"
    folder.mkdir(exist_ok=True)
    source = folder / "panel.jsx"
    source.write_text("scratch source\n", encoding="utf-8")
    current = datetime.now(UTC)
    template = {"schema":SCHEMA, "capturedAt":current.isoformat(), "maxAgeSeconds":900,
        "sourceFiles":[{"path":source.name,"sha256":hashlib.sha256(source.read_bytes()).hexdigest()}],
        "states":{"route":{"before":"/control","after":"/control"},"modal":{"before":"open","after":"closed"},
            "entry":{"before":"Lab","after":"Personal Mesh"},"meshTabs":{key:{"visited":True,"capture":"scratch:" + key,"visibleValues":[key]} for key in ("trust","nearby","sync")}},
        "api":{"historyCount":1},"ui":{"historyCount":1,"visibleValues":["Nearby Send","1 completed transfer"]},
        "computedStyles":[{"name":"heading","foreground":"#fff","background":"#000"}]}
    def validate(value):
        return validate_receipt(value,root=folder,now=current + timedelta(minutes=5))
    run("test_personal_mesh_browser_proof","test_validates_current_source_hash_and_contrast",["d-ui.mesh-receipt"],
        lambda: prove(validate(deepcopy(template))["contrast"] == [{"name":"heading","ratio":21.0}]))
    def invalid():
        for area,field,value,message in (("ui","historyCount",2,"history count mismatch"),("ui","visibleValues",["undefined"],"undefined user-visible")):
            receipt = deepcopy(template)
            receipt[area][field] = value
            reject(lambda: validate(receipt),message,ProofError)
        for mutation,message in ((lambda r:r["computedStyles"][0].update(background="#fff"),"below 4.5"),
            (lambda r:r["states"]["modal"].update(after="open"),"captured closed state"),(lambda r:r["states"]["meshTabs"]["sync"].update(visited=False),"meshTabs.sync")):
            receipt = deepcopy(template)
            mutation(receipt)
            reject(lambda:validate(receipt),message,ProofError)
    run("test_personal_mesh_browser_proof","test_rejects_invalid_ui_evidence",["d-ui.mesh-receipt"],invalid)
    def changed():
        source.write_text("changed",encoding="utf-8")
        try:
            reject(lambda:validate(deepcopy(template)),"stale embedded proof",ProofError)
        finally:
            source.write_text("scratch source\n",encoding="utf-8")
    run("test_personal_mesh_browser_proof","test_rejects_stale_embedded_proof_after_source_changes",["d-ui.mesh-receipt"],changed)
    run("test_personal_mesh_browser_proof","test_rejects_stale_capture_time",["d-ui.mesh-receipt"],
        lambda:reject(lambda:validate_receipt(deepcopy(template),root=folder,now=current+timedelta(minutes=30)),"stale",ProofError))
    def metadata():
        receipt = deepcopy(template)
        receipt["metadata"] = {"optionalBrowserVersion":None}
        prove(validate(receipt)["ok"])
        receipt["metadata"]["authorization"] = "redacted"
        reject(lambda:validate(receipt),"authorization",ProofError)
    run("test_personal_mesh_browser_proof","test_allows_null_metadata_but_rejects_sensitive_keys",["d-ui.mesh-receipt"],metadata)
    def ages():
        for value in (0,-1,3601,"900",True):
            receipt = deepcopy(template)
            receipt["maxAgeSeconds"] = value
            reject(lambda:validate(receipt),"maxAgeSeconds",ProofError)
    run("test_personal_mesh_browser_proof","test_rejects_unbounded_or_non_integer_max_age",["d-ui.mesh-receipt"],ages)
    def paths():
        for value in ("../panel.jsx","C:/panel.jsx"):
            receipt = deepcopy(template)
            receipt["sourceFiles"][0]["path"] = value
            reject(lambda:validate(receipt),"safe relative path",ProofError)
    run("test_personal_mesh_browser_proof","test_rejects_absolute_and_traversal_source_paths",["d-ui.mesh-receipt"],paths)


def check_usage(usage, reading):
    total = usage.get("totalTokens")
    known = type(total) is int
    cached = usage.get("cachedInputTokens")
    cached = cached if type(cached) is int and 0 <= cached <= (total or 0) else None
    require(reading["used"] == (total - cached if known and cached is not None else total if known else None)
            and reading["cached"] == cached and reading["total"] == (total if known else None),
            "d-ui.usage-truth", "cached/unknown tokens misrepresented")
    headline = "usage unknown" if not known else f"{total - cached:,} new tokens" if cached is not None else f"{total:,} tokens"
    require(headline in reading["label"] and ("(partial)" in reading["label"]) == (usage.get("coverage") == "partial"),
            "d-ui.usage-truth", "headline hides provenance")


def check_search(root, report, glob, maximum):
    from .research import EXCLUDED_DIRS, GENERATED_DIRS, _glob_matches
    rows = report["matches"]
    require(report["count"] == len(rows) <= maximum and (not report["timedOut"] or not report["complete"]),
            "d-ui.search-bounds", "search count/completeness contradicts budget")
    for row in rows:
        path = Path(row["path"])
        require(not path.is_absolute() and ".." not in path.parts and not set(path.parts[:-1]) & (EXCLUDED_DIRS | GENERATED_DIRS)
                and (root / path).resolve().is_relative_to(root) and _glob_matches(path.as_posix(), glob)
                and row["line"] > 0 and len(row["snippet"]) <= 2000,
                "d-ui.search-bounds", "match escaped root/glob/generated-tree policy")


def check_arranged(bus, prior, patch, result):
    require(bus.get("arrangement") == {**prior, **patch} and result["event"]["action"] == "view.arrange"
            and result["event"]["payload"] == patch, "d-ui.view-arrange", "layout mutation/event did not preserve omitted fields")


def check_workspace_evidence(original, before, after, result):
    available = bool(before and after and before.get("complete") and after.get("complete"))
    evidence = result["workspaceSnapshotEvidence"]
    require(evidence["available"] == available, "d-ui.workspace-snapshots", "partial snapshot fabricated authoritative content evidence")
    if not available:
        require(all(result.get(key) == value for key,value in original.items() if key != "workspaceSnapshotEvidence"),
                "d-ui.workspace-snapshots", "partial snapshot changed runtime-adapter evidence")
        return
    old = before.get("files") if isinstance(before.get("files"),dict) else {}
    new = after.get("files") if isinstance(after.get("files"),dict) else {}
    observed = sorted(path for path in old.keys() | new.keys() if old.get(path) != new.get(path))
    prior = original.get("filesChanged") if isinstance(original.get("filesChanged"),list) else []
    require(result["filesChanged"] == list(dict.fromkeys([*observed,*map(str,prior)]))
            and result["changeEvidenceAvailable"] is True and result["changeEvidenceSource"] == "neyvia-pre-post-content-snapshot"
            and evidence["algorithm"] == "sha256" and evidence["changedFileCount"] == len(observed)
            and evidence["changedFiles"] == observed[:30] and evidence["truncated"] == (len(observed) > 30),
            "d-ui.workspace-snapshots", "content changes, provenance or bounded change summary differ from snapshots")


def check_integrity(result, receipt):
    observed = bool(result.get("changeEvidenceAvailable"))
    readonly = result.get("readOnly") if isinstance(result.get("readOnly"),dict) else {}
    protected = bool(readonly.get("enforced") and str(readonly.get("sourceWorkspace") or "").strip() and str(readonly.get("executionWorkspace") or "").strip())
    files = receipt["filesChanged"]
    expected_status = "changed" if observed and files else "unchanged" if observed else "source-protected" if protected else "unavailable"
    require(receipt["status"] == expected_status and receipt["evidenceAvailable"] == (observed or protected)
            and receipt["changeEvidenceAvailable"] == observed and receipt["baseline"]["repositoryIndependent"] is True
            and receipt["workspaceState"] == ("observed-change" if files else "unchanged" if observed or protected else "unknown")
            and receipt["sourceWorkspaceStatus"] == ("protected" if protected else "observed" if observed else "unknown")
            and (observed or not files) and len(files) <= 30 and len(set(files)) == len(files),
            "d-ui.workspace-integrity", "integrity receipt promotes unavailable evidence or loses its authority boundary")
    expected_source = str(result.get("changeEvidenceSource") or "").strip() if observed else ""
    expected_source = expected_source or ("runtime-adapter-structured-change-evidence" if observed else "isolated_read_only_workspace" if protected else "no-authoritative-change-evidence")
    require(receipt["provenance"]["source"] == expected_source
            and (expected_source != "neyvia-pre-post-content-snapshot" or receipt["scope"] == "pre/post content-hash workspace changes"),
            "d-ui.workspace-integrity", "provenance claims an unobserved snapshot")


def check_dependency_context(node, dependencies, completed, rows):
    ancestors, pending = set(),list(dependencies.get(node) or [])
    while pending:
        identity = pending.pop()
        if identity not in ancestors:
            ancestors.add(identity)
            pending.extend(dependencies.get(identity) or [])
    for row in rows:
        if row["kind"] != "dependency-result":
            continue
        value = json.loads(row["content"].removeprefix("Completed dependency result: "))
        source = value["sourceId"]
        dependency = source.removeprefix("agent-node:").removesuffix(":result")
        require(dependency in ancestors and dependency in completed and not {"raw","compartment","toolTimeline"} & value.keys(),
                "d-ui.dependency-context", "dependency context includes future/unrelated nodes or runtime noise")
        parent = completed[dependency]
        result = parent.get("result") if isinstance(parent.get("result"),dict) else {}
        route = parent.get("routeSelection") if isinstance(parent.get("routeSelection"),dict) else result.get("route") if isinstance(result.get("route"),dict) else {}
        reply = str(result.get("reply") or result.get("finalMessage") or result.get("message") or "").strip()[:3600]
        require(value["routeSelection"] == route and value["reply"] == reply
                and value["status"] == str(result.get("status") or parent.get("status") or "unknown"),
                "d-ui.dependency-context", "salient reply/route/status lost behind runtime noise")


def check_route_context(conversation_id, conversation, rows):
    metadata = conversation.get("metadata") if isinstance(conversation,dict) else {}
    metadata = metadata if isinstance(metadata,dict) else {}
    snapshot = metadata.get("routeSnapshot")
    if not isinstance(snapshot,dict) or not snapshot:
        return
    route_rows = [row for row in rows if row.get("kind") == "conversation-route-snapshot"]
    require(route_rows and route_rows[0]["sourceId"] == f"conversation:{conversation_id}:route-snapshot"
            and rows[0] is route_rows[0], "d-ui.route-context", "authoritative frozen route is absent or follows ordinary context")
    content = route_rows[0]["content"]
    prefix = "Immutable conversation route snapshot (authoritative): "
    require(content.startswith(prefix) and len(content) <= len(prefix)+3800, "d-ui.route-context", "frozen route projection is unbounded or mislabeled")
    expected = {str(role):{key:route.get(key) for key in ("role","runtimeId","runtime","provider","model","model_id","effort") if route.get(key) not in (None,"")}
                for role,route in snapshot.items() if isinstance(role,str) and isinstance(route,dict)}
    projection = {"routes":expected,"routeSnapshotVersion":metadata.get("routeSnapshotVersion") or 1,"immutableAtCreation":bool(metadata.get("immutableAtCreation",True))}
    require(content == prefix + json.dumps(projection,ensure_ascii=False,sort_keys=True)[:3800],
            "d-ui.route-context", "frozen route identities differ from persisted conversation metadata")


def check_selected_prompt(payload, adaptive, prompt):
    from .neyvia_ecosystem import TASK_PROMPT_PROFILES
    profile = adaptive["profile"]
    requested = str(payload.get("systemPromptProfile") or payload.get("system_prompt_profile") or payload.get("taskProfile") or "").strip().lower().replace("-","_")
    if requested in TASK_PROMPT_PROFILES:
        require(profile["profileId"] == requested and profile["selection"] == "explicit",
                "d-ui.selected-profile", "normal compiled prompt silently replaced explicitly selected profile")
    marker = f"Task profile: {profile['profileId']} ({profile['selection']})."
    require(marker in prompt and adaptive["prompt"] in prompt and str(payload.get("message") or "").strip() in prompt,
            "d-ui.selected-profile", "normal execution prompt lost profile contract or original request")


def orchestration_self_checks(root,run,prove):
    import tempfile
    from .web_backend import FluxioWebBackend
    # Constructor sees a new owned root: no persisted credential file exists.
    scratch = Path(tempfile.mkdtemp(prefix="orchestration-",dir=root))
    backend = FluxioWebBackend(_fixture_root(scratch),scratch)
    def integrity(result):
        return backend._workspace_integrity_receipt(node_id="executor",invocation_id="scratch-call",conversation_id="scratch-conversation",
            mission_id="scratch-mission",workspace_path=scratch,result=result)
    def absent():
        value = integrity({"status":"completed","filesChanged":[]})
        prove(value["status"] == "unavailable" and value["evidenceAvailable"] is False and value["filesChanged"] == [] and value["baseline"]["repositoryIndependent"] is True)
        changed = integrity({"status":"completed","filesChanged":["app.py"],"changeEvidenceAvailable":True})
        prove(changed["status"] == "changed" and changed["evidenceAvailable"] is True and changed["filesChanged"] == ["app.py"])
        protected = integrity({"status":"completed","filesChanged":[],"readOnly":{"enforced":True,"sourceWorkspace":str(scratch),"executionWorkspace":str(scratch/"mirror")}})
        prove(protected["status"] == "source-protected" and protected["workspaceState"] == "unchanged" and protected["sourceWorkspaceStatus"] == "protected"
              and protected["provenance"]["source"] == "isolated_read_only_workspace")
        return {"unavailable":value,"runtimeReportedChange":changed,"readOnlyProtection":protected}
    run("test_neyvia_orchestration_execution","test_workspace_integrity_receipt_fails_closed_without_adapter_change_evidence",["d-ui.workspace-integrity"],absent)
    def snapshots():
        path = scratch / "app.js"
        path.write_text("before\n",encoding="utf-8")
        before = backend._orchestration_workspace_snapshot(scratch)
        path.write_text("after\n",encoding="utf-8")
        (scratch/"new.txt").write_text("created\n",encoding="utf-8")
        after = backend._orchestration_workspace_snapshot(scratch)
        changed = backend._apply_orchestration_workspace_evidence({"status":"completed","filesChanged":[]},before=before,after=after)
        prove(changed["changeEvidenceAvailable"] is True and changed["filesChanged"] == ["app.js","new.txt"]
              and changed["changeEvidenceSource"] == "neyvia-pre-post-content-snapshot" and changed["workspaceSnapshotEvidence"]["changedFileCount"] == 2)
        unchanged = backend._apply_orchestration_workspace_evidence({"status":"completed","filesChanged":[]},before=after,after=backend._orchestration_workspace_snapshot(scratch))
        value = integrity(unchanged)
        prove(unchanged["changeEvidenceAvailable"] is True and unchanged["filesChanged"] == [] and value["status"] == "unchanged" and value["evidenceAvailable"] is True
              and value["changeEvidenceAvailable"] is True and value["workspaceState"] == "unchanged" and value["sourceWorkspaceStatus"] == "observed"
              and value["provenance"]["source"] == "neyvia-pre-post-content-snapshot" and value["scope"] == "pre/post content-hash workspace changes")
        incomplete = backend._apply_orchestration_workspace_evidence({"status":"completed","filesChanged":[]},before={**before,"complete":False},after=after)
        prove(incomplete["workspaceSnapshotEvidence"]["available"] is False and not incomplete.get("changeEvidenceAvailable"))
        return {"before":before,"after":after,"changed":changed,"unchangedIntegrity":value,"incomplete":incomplete["workspaceSnapshotEvidence"]}
    run("test_neyvia_orchestration_execution","test_writable_orchestration_snapshot_proves_changed_and_unchanged_files",["d-ui.workspace-snapshots","d-ui.workspace-integrity"],snapshots)
    def dependency():
        route = {"role":"planner","runtimeId":"codex","provider":"openai-codex","model":"gpt-5.6-sol","effort":"xhigh"}
        rows = backend._dependency_context_rows(node_id="executor",dependencies={"executor":{"planner"}},completed_results={
            "planner":{"routeSelection":route,"result":{"reply":"PLANNER_THREE_STEP_PLAN","status":"completed","runtime":"codex","elapsedMs":42,"route":route,
                "filesChanged":[],"changeEvidenceAvailable":False,"raw":"RAW_SHOULD_NOT_APPEAR","compartment":{"messages":"noise"*5000,"toolTimeline":"tool-noise"*5000}},
                "receipt":{"status":"completed","sessionId":"planner-session"}},
            "future":{"result":{"reply":"FUTURE_MUST_NOT_APPEAR","status":"completed"}}})
        content = next(row["content"] for row in rows if row["kind"] == "dependency-result")
        prove(all(token in content for token in ("PLANNER_THREE_STEP_PLAN","gpt-5.6-sol",'"status": "completed"'))
              and all(token not in content for token in ("RAW_SHOULD_NOT_APPEAR","compartment","toolTimeline","FUTURE_MUST_NOT_APPEAR")))
        return {"rows":rows}
    run("test_neyvia_orchestration_execution","test_dependency_context_keeps_salient_result_evidence_ahead_of_runtime_noise",["d-ui.dependency-context"],dependency)
    def route_context():
        store = backend.neyvia_mcp.conversations
        routes = {role:{"role":role,"runtimeId":"codex","provider":"openai-codex","model":model,"effort":effort}
            for role,model,effort in (("planner","gpt-5.6-sol","xhigh"),("executor","gpt-5.6-luna","high"),("verifier","gpt-5.6-terra","medium"))}
        created = store.create_conversation(kind="orchestration",title="Route context",metadata={"routeSnapshotVersion":1,"immutableAtCreation":True,
            "teamSelection":{"roles":["planner","executor","verifier"]},"routeSnapshot":routes})
        identity = created["conversationId"]
        for index in range(8):
            store.append_turn(identity,role="user",content=f"Context turn {index}",turn_id=f"scratch-turn-{index}")
        conversation = store.get_conversation(identity,include_turns=True)
        rows = backend._build_neyvia_base_context(conversation_id=identity,conversation=conversation,explicit_selection=None)
        route_row = next(row for row in rows if row["kind"] == "conversation-route-snapshot")
        prove(route_row["sourceId"] == f"conversation:{identity}:route-snapshot" and all(model in route_row["content"] for model in ("gpt-5.6-sol","gpt-5.6-luna","gpt-5.6-terra"))
              and rows.index(route_row) < next(index for index,row in enumerate(rows) if row["kind"] == "conversation-turn")
              and store.get_conversation(identity)["metadata"]["routeSnapshot"] == routes)
        return {"conversationId":identity,"databasePath":str(store.database_path),"routeRow":route_row,"turnRows":len([row for row in rows if row["kind"] == "conversation-turn"])}
    run("test_neyvia_orchestration_execution","test_base_context_exposes_immutable_route_snapshot_before_bounded_turns",["d-ui.route-context"],route_context)
    def selected_profiles():
        from .web_backend import _chat_prompt
        base = {"message":"Make this clear.","_profileWorkspacePath":str(scratch)}
        general = _chat_prompt({**base,"systemPromptProfile":"general"})
        ui = _chat_prompt({**base,"systemPromptProfile":"ui_ux"})
        prove("Task profile: general (explicit)." in general and "Task profile: ui_ux (explicit)." in ui and general != ui)
        return {"generalSha256":hashlib.sha256(general.encode()).hexdigest(),"uiSha256":hashlib.sha256(ui.encode()).hexdigest(),
            "generalProfile":"general (explicit)","uiProfile":"ui_ux (explicit)","different":general != ui}
    run("test_neyvia_system_prompt_selector","test_selected_profile_changes_the_compiled_execution_prompt",["d-ui.selected-profile"],selected_profiles)


def self_check(root):
    from .planner import build_docs_first_plan, build_docs_first_plan_receipt
    from .orchestration_language import compile_neyvia_program, NeyviaLanguageError
    from . import night_mode as night
    from .research import search_workspace, search_workspace_bounded
    from .neyvia_workspace_tools import WorkspaceTools, DEFINITIONS
    from .neyvia_analytics import publish_indicator
    from .model_usage import claude_receipt
    from .product_catalog import ProductDescriptor
    from .ocr_benchmark import character_error_rate, word_error_rate, score_ocr_sample, aggregate_scores, select_ocr_route, OcrPageSignals, load_candidate_registry
    started = time.perf_counter()
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    cases = []
    manual_receipts = []

    def run(file, name, contracts, action):
        from .contract_gate import wants
        if not wants(contracts):
            return
        try:
            observed = action()
            row = {"id": f"tests/{file}.py::{name}", "contracts": contracts, "ok": True}
            if isinstance(observed,dict):
                row["observed"] = observed
            cases.append(row)
        except Exception as exc:
            cases.append({"id": f"tests/{file}.py::{name}", "contracts": contracts, "ok": False, "error": str(exc)[:400]})

    def reject(action, message, error=ValueError):
        try:
            action()
        except error as exc:
            require(message in str(exc), "d-ui.self-check", "refusal reason differs")
        else:
            raise ValueError("Rejected input succeeded")

    def prove(value):
        require(value, "d-ui.self-check", "observed behavior differs")

    def plan_receipt(**args):
        return build_docs_first_plan_receipt(objective=args.pop("objective", "Review current state."), docs=args.pop("docs", []),
            mission_id="scratch-mission", mission_run_id="scratch-run", host="scratch", runtime="codex", workspace=str(root), **args)

    def compact():
        receipt = plan_receipt(objective="Implement receipt-backed overnight planning.", docs=["A" * 1000], file_scope=["planner.py"], selected_skills=["manual_skill"])
        prove(receipt.inputs["docsTruncated"] and "A" * 100 not in str(receipt.inputs) and receipt.mission_run_id == "scratch-run")

    def caps():
        receipt = plan_receipt(file_scope=[f"f{i}" for i in range(100)], selected_skills=[f"s{i}" for i in range(40)], forbidden_paths=[f"p{i}" for i in range(60)])
        prove((len(receipt.file_scope), len(receipt.selected_skills), len(receipt.forbidden_paths), receipt.risk_level) == (80, 24, 40, "low"))

    def skills():
        from .skill_library import SkillLibrary
        from .skills import SkillRegistry
        repo = Path(__file__).resolve().parents[2]
        brief = SkillLibrary(repo, SkillRegistry(repo / "config/skills.json")).build_skill_brief(
            task_brief="Search the workspace and run verification for a planner change.", mission_id="scratch", top_k=3)
        receipt = plan_receipt(skill_brief=brief)
        prove(receipt.selected_skills == [item["skillId"] for item in brief.selected_skills])

    run("test_planner", "PlannerTests.test_execute_first_objective_starts_with_product_implementation", ["d-ui.plan-order"],
        lambda: prove(build_docs_first_plan("EXECUTE FIRST, NO PREFLIGHT TESTS. First action must edit product files.", ["doc"]).plan_steps[0] == "Implement smallest vertical slice in product files"))
    for name, action, ids in (("test_docs_first_planner_produces_compact_plan_receipt", compact, ["d-ui.plan-compact"]),
        ("test_plan_receipt_caps_large_lists_for_context_efficiency", caps, ["d-ui.plan-compact"]),
        ("test_plan_receipt_selects_skills_from_skill_brief", skills, ["d-ui.plan-skills"]),
        ("test_manual_selected_skills_override_skill_brief", lambda: prove(plan_receipt(selected_skills=["manual_skill"], skill_brief={"schema":"fluxio.skill_brief.v1", "brief_id":"b", "selected_skills":[{"skillId":"workspace_search"}]}).selected_skills == ["manual_skill"]), ["d-ui.plan-skills"])):
        run("test_planner", "PlannerTests." + name, ids, action)
    program = 'NEYVIA/1\nGOAL text="Make a proof"\nLANE worker runtime=codex model=local effort=low permissions=read,write\nSTEP inspect lane=worker action=runtime risk=read output=evidence.json\nSTEP implement lane=worker after=inspect risk=workspace_write\nVERIFY verify lane=worker after=implement command="node --version" output=receipt.json'
    def compiled():
        payload = compile_neyvia_program(program)
        prove(payload["executionStages"][0]["stepIds"] == ["inspect"] and payload["executionStages"][2]["stepIds"] == ["verify"]
              and payload["steps"][1]["permissionEnvelope"]["mutability"] == "workspace_write" and payload["steps"][2]["proofRequired"] and payload["estimatedPlanTokens"] < 1000)
    run("test_orchestration_language", "OrchestrationLanguageTests.test_compiles_typed_stages_permissions_and_hash", ["d-ui.compiler-dag", "d-ui.compiler-authority", "d-ui.compiler-hash"], compiled)
    run("test_orchestration_language", "OrchestrationLanguageTests.test_rejects_dependency_cycles_before_execution", ["d-ui.compiler-dag"],
        lambda: reject(lambda: compile_neyvia_program('NEYVIA/1\nGOAL text="Cycle"\nLANE worker permissions=read\nSTEP first lane=worker after=second\nSTEP second lane=worker after=first'), "cycle", NeyviaLanguageError))
    run("test_orchestration_language", "OrchestrationLanguageTests.test_external_writes_require_approval", ["d-ui.compiler-authority"],
        lambda: prove(compile_neyvia_program('NEYVIA/1\nGOAL text="Send"\nLANE worker permissions=send\nSTEP send lane=worker action=tool tool=example.send risk=external_write')["steps"][0]["permissionEnvelope"]["approvalRequired"]))

    def readiness(ready):
        return night.build_night_readiness_receipt(root=root, mission_id="scratch", runtime_auth_available=ready, runtime_available=ready,
            nas_worker_alive=ready, notification_channel="browser" if ready else "", model_key_names=["NEYVIA_PROOF_MISSING_KEY"])
    def ready_masked():
        import os
        key = "NEYVIA_PROOF_SYNTHETIC_KEY"
        prior = os.environ.get(key)
        os.environ[key] = "sk-proof-123456789"
        try:
            receipt = night.build_night_readiness_receipt(root=root,mission_id="scratch",host="scratch",runtime="hermes",runtime_auth_available=True,
                runtime_available=True,selected_skills_available=True,nas_worker_alive=True,desktop_gateway_status="online",notification_channel="browser",
                model_key_names=[key,"NEYVIA_PROOF_MISSING_KEY"])
            prove(receipt.schema == "fluxio.night_readiness_receipt.v1" and receipt.status == "passed" and receipt.phase == "preflight"
                  and receipt.checks["nas_worker_alive"] and receipt.checks["selected_runtime_exists"] and receipt.checks["mission_queue_can_run"]
                  and receipt.masked_keys[key] == "sk-...6789" and receipt.masked_keys["NEYVIA_PROOF_MISSING_KEY"] == "missing" and receipt.failures == []
                  and receipt.next_action == "Claim production night queue work.")
        finally:
            if prior is None:
                os.environ.pop(key,None)
            else:
                os.environ[key] = prior
    run("test_night_mode","test_night_readiness_receipt_passes_only_when_required_checks_pass",["d-ui.night-readiness"],ready_masked)
    run("test_night_mode", "test_night_readiness_receipt_blocks_without_worker_runtime_or_auth", ["d-ui.night-readiness"],
        lambda: prove(readiness(False).status == "blocked" and readiness(False).notification_channel == "skipped" and {"nas_worker_alive", "runtime_auth_available", "selected_runtime_exists"} <= set(readiness(False).failures)))
    run("test_night_mode", "test_readiness_failure_message_links_to_blocked_receipt", ["d-ui.night-notification"],
        lambda: prove(night.build_readiness_failure_message(readiness(False), receipt_path="readiness.json")["failureCount"] == len(readiness(False).failures)))
    run("test_night_mode", "test_readiness_failure_message_skips_when_readiness_passes", ["d-ui.night-notification"],
        lambda: prove(night.build_readiness_failure_message(readiness(True), receipt_path="readiness.json")["status"] == "skipped"))
    run("test_night_mode", "test_production_night_profile_allows_real_mission_work_with_receipts", ["d-ui.night-policy"],
        lambda: prove(night.production_night_profile_payload()["autopilot"] and night.production_night_profile_payload()["mission_execution_allowed"] and night.production_night_profile_payload()["default_runtime"] == "hermes" and {"readiness_receipt", "verification_receipt"} <= set(night.production_night_profile_payload()["proof_requirements"])))
    def classifier():
        for kind, gateway, pressure, expected in (("headless_executor_work",False,False,"allow"),("browser_verification",False,False,"defer"),
            ("browser_verification",True,False,"allow"),("full_frontend_build",False,True,"defer"),("destructive_git_action",False,False,"defer"),("unknown_thing",False,False,"hold")):
            prove(night.classify_night_work(kind, pc_gateway_online=gateway, nas_pressure_high=pressure)["decision"] == expected)
    run("test_night_mode", "test_night_work_classifier_defers_capacity_and_approval_sensitive_work", ["d-ui.night-policy"], classifier)
    def ranked():
        kinds = list(reversed(night.NIGHT_QUEUE_PRIORITY))
        result = night.rank_night_queue([{"id":kind,"kind":kind} for kind in kinds])
        prove([row["kind"] for row in result["ranked"]] == list(night.NIGHT_QUEUE_PRIORITY) and not result["deferred"] and not result["held"])
    run("test_night_mode", "test_night_queue_policy_ranks_allowed_work_in_production_order", ["d-ui.night-policy"], ranked)
    def deferred():
        result = night.rank_night_queue([{"id":key,"kind":kind} for key,kind in (("browser","browser_verification"),("build","full_frontend_build"),("unknown","custom_gpu_job"))], nas_pressure_high=True)
        prove([row["id"] for row in result["deferred"]] == ["browser","build"] and result["held"][0]["id"] == "unknown" and not result["ranked"])
    run("test_night_mode", "test_night_queue_policy_defers_capacity_sensitive_work_and_holds_unknowns", ["d-ui.night-policy"], deferred)
    run("test_night_mode", "test_write_morning_digest_creates_json_and_markdown_receipts", ["d-ui.night-digest"],
        lambda: prove(night.write_morning_digest(root, completed_items=["complete"], blocked_items=["blocked"], proof_commands=["neyvia verify"], changed_files=["planner.py"],
            nas_sync_status="not requested", first_unchecked_item="next", proof_gaps=["browser capture"], risks=["pending"]) ["summary"] == "1 completed, 1 blocked, 1 proof gaps; next item: next."))
    workspace = WorkspaceTools(_fixture_root(root / "view"))
    try:
        def schemas():
            schemas = {row[0]:row[2] for row in DEFINITIONS}
            prove(set(schemas["view.arrange"]["order"]["items"]["enum"]) == {"sidebar","main","panel","canopy"}
                  and schemas["view.arrange"]["dock"]["enum"] == ["left","right"])
        run("test_neyvia_view_arrange","test_the_contract_lists_view_arrange_with_its_regions_and_widgets",["d-ui.view-schemas"],schemas)
        run("test_neyvia_view_arrange","test_replay_and_accounts_are_panes_the_agent_can_open",["d-ui.view-schemas"],
            lambda:prove({"replay","builder","accounts"} <= set({row[0]:row[2] for row in DEFINITIONS}["pane.show"]["kind"]["enum"])))
        def reading(usage):
            publish_indicator(workspace.bus, {"type":"usage.updated", "runId":"scratch", "usage":usage})
            return workspace.bus.get("indicators")["usage"]
        def cache():
            row = reading(claude_receipt({"input_tokens":12,"output_tokens":4000,"cache_read_input_tokens":2400000,"cache_creation_input_tokens":30000}))
            prove((row["used"],row["total"],row["cached"],row["label"]) == (34012,2434012,2400000,"Latest run · 34,012 new tokens · 2,400,000 cached"))
        run("test_neyvia_usage_indicator", "test_cache_reads_do_not_inflate_the_headline", ["d-ui.usage-truth"], cache)
        run("test_neyvia_usage_indicator", "test_unknown_cache_split_falls_back_to_the_reported_total", ["d-ui.usage-truth"], lambda: prove(reading({"totalTokens":900,"cachedInputTokens":None})["label"] == "Latest run · 900 tokens"))
        run("test_neyvia_usage_indicator", "test_unknown_usage_stays_unknown", ["d-ui.usage-truth"], lambda: prove(reading({"totalTokens":None,"coverage":"partial"})["label"] == "Latest run · usage unknown (partial)"))
        def arrange():
            workspace.call("view.arrange", {"order":["main","sidebar","panel","canopy"],"dock":"left"})
            workspace.call("view.arrange", {"widgets":[{"id":"needs","size":"l"}]})
            prove(workspace.bus.snapshot()["arrangement"] == {"order":["main","sidebar","panel","canopy"],"dock":"left","widgets":[{"id":"needs","size":"l"}]})
        run("test_neyvia_view_arrange", "test_arrangement_is_emitted_and_kept_merging_with_earlier_ones", ["d-ui.view-arrange"], arrange)
        def refusals():
            before = workspace.bus.snapshot()
            with workspace.bus.connect() as db:
                events_before = db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            for args,message in (({},"at least one"),({"order":["main","main"]},"each region once"),({"order":["main","dock"]},"each region once"),({"widgets":[{"id":"weather"}]},"Unknown widget")):
                try:
                    workspace.call("view.arrange",args)
                except ValueError as exc:
                    prove(message in str(exc) or "precondition" in str(exc))
                else:
                    raise ValueError("Invalid arrangement reached state mutation")
                prove(workspace.bus.snapshot() == before)
                with workspace.bus.connect() as db:
                    prove(db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == events_before)
        run("test_neyvia_view_arrange", "test_bad_arrangements_are_refused_with_a_reason", ["d-ui.view-arrange"], refusals)
        def scenes():
            prove(workspace.call("view.scene",{"name":"focus"})["event"]["payload"] == {"name":"focus"})
            prove(workspace.call("view.scene",{"save":"Night review"})["event"]["payload"] == {"save":"Night review"})
            reject(lambda:workspace.call("view.scene",{"save":"Cockpit"}),"built-in")
            reject(lambda:workspace.call("view.scene",{}),"either name")
            prove(workspace.call("view.theme",{"theme":"sunset"})["event"]["action"] == "view.theme" and workspace.bus.snapshot()["theme"] == "sunset")
            workspace.call("view.theme",{"theme":"night"})
            prove(workspace.bus.snapshot()["theme"] == "night")
            try:
                workspace.call("view.theme",{"theme":"neon"})
            except ValueError as exc:
                prove("Themes are" in str(exc) or "precondition" in str(exc))
            else:
                raise ValueError("Invalid theme accepted")
            workspace.bus.update("sessions",{"chat-1":{"title":"Known chat"}})
            prove(workspace.call("view.float",{"id":"chat-1"})["floating"] is True and workspace.call("view.float",{"id":"chat-1","floating":False})["floating"] is False)
        run("test_neyvia_view_arrange","test_scene_float_and_theme_are_checked_before_anything_is_emitted",["d-ui.view-controls"],scenes)
        def manual_startup():
            from .native_tools import NativeToolRegistry
            from . import neyvia_manuals
            registry = NativeToolRegistry(_fixture_root(workspace.bus.root))
            def dispatch(tool,args,action_id=""):
                require(tool == "neyvia.state", "d-ui.self-check", "manual dispatch escaped local state observer")
                return workspace.call("state",args)
            observed = neyvia_manuals.call(workspace,"manual.observe",{"id":"ui-planning","chapter":"proofs-d-ui-state","state":"current"},dispatcher=dispatch,registry=registry)
            prove(observed.get("ok"))
            completed = neyvia_manuals.call(workspace,"manual.run",{"id":"ui-planning","chapter":"proofs-d-ui-state","procedure":"observe-local-state","inputs":{}},dispatcher=dispatch,registry=registry)
            prove(completed.get("ok") and completed.get("status") == "completed" and all(row["passed"] for row in completed["checks"]))
            manual_receipts.extend([{"id":"ui-planning","observer":"current","ok":True},
                {"id":"ui-planning","procedure":"observe-local-state","runId":completed["runId"],"checks":len(completed["checks"]),"ok":True}])
        run("ui-planning","manual-startup",[],manual_startup)
    finally:
        workspace.close()
    search = root / "search"
    (search / "src").mkdir(parents=True, exist_ok=True)
    (search / "src/app.py").write_text("needle in source\n", encoding="utf-8")
    (search / "top.txt").write_text("needle in top\n", encoding="utf-8")
    for folder in ("node_modules/pkg", "src-tauri/target/release", ".agent_control/runs"):
        (search / folder).mkdir(parents=True, exist_ok=True)
        (search / folder / "copy.txt").write_text("needle", encoding="utf-8")
    (search / "src/blob.bin").write_bytes(b"needle\x00")
    def generated():
        rows, complete = search_workspace_bounded(search,"needle")
        prove(complete and sorted(Path(row["path"]).as_posix() for row in rows) == ["src/app.py","top.txt"])
        prove([row["path"] for row in search_workspace(search,"needle",include_glob="**/*.txt")] == ["top.txt"] and search_workspace(search,"needle",include_glob="*.py") == [])
    run("test_research", "ResearchTests.test_generated_folders_and_binaries_are_skipped", ["d-ui.search-bounds"], generated)
    run("test_research", "ResearchTests.test_time_budget_returns_what_was_found", ["d-ui.search-bounds"], lambda: prove(search_workspace_bounded(search,"needle",time_budget=1e-9) == ([],False)))
    run("test_research", "ResearchTests.test_search_workspace_returns_matches", ["d-ui.search-bounds"],
        lambda:prove(len(search_workspace(Path(__file__).resolve().parent,"AutonomousEngine",include_glob="*.py",max_results=10)) >= 1))
    for name,kind,source,message in (("test_tool_with_user_surface_must_be_an_app","tool","","classified as an app"), ("test_app_requires_independent_github_source","app","https://example.test/pdf","GitHub source")):
        run("test_product_catalog","ProductCatalogTests." + name,["d-ui.product-boundary"],lambda kind=kind,source=source,message=message: reject(lambda: ProductDescriptor("proof.pdf","PDF",kind,"shared","Proof",("pdf.open",),("ui://pdf",),source,user_interactive=True).validate(),message))
    run("test_ocr_benchmark", "test_error_metrics_are_deterministic_and_unicode_normalized", ["d-ui.ocr-quality"], lambda: prove(character_error_rate("café","cafe\u0301") == 0 and math.isclose(word_error_rate("one two three","one two four"),1/3)))
    def scores():
        rows = [score_ocr_sample(reference_text="alpha beta",hypothesis_text=h,reference_order=["a","b"],hypothesis_order=o,reference_blocks=2,hypothesis_blocks=b,latency_ms=l,peak_vram_mb=v) for h,o,b,l,v in (("alpha beta",["a","b"],2,100,800),("alpha zeta",["b","a"],3,200,900))]
        result = aggregate_scores(rows)
        prove((result["samples"],result["exactRate"],result["meanLatencyMs"],result["peakVramMb"],result["meanReadingOrderErrorRate"]) == (2,.5,150,900,.5))
    run("test_ocr_benchmark", "test_score_and_aggregate_preserve_quality_and_runtime_dimensions", ["d-ui.ocr-quality"], scores)
    def routes():
        for signals,engine in ((OcrPageSignals(native_text_characters=100),"native-pdf"),(OcrPageSignals(),"pp-ocrv6-medium"),(OcrPageSignals(prefer_fast_full_page=True),"glm-ocr-bf16"),(OcrPageSignals(contains_table=True),"paddleocr-vl-1.6"),(OcrPageSignals(contains_table=True,gpu_available=False),"tesseract-fallback")):
            prove(select_ocr_route(signals)["engine"] == engine)
    run("test_ocr_benchmark", "test_router_uses_native_text_then_text_ocr_then_structured_vlm", ["d-ui.ocr-route"], routes)
    def candidates():
        value = load_candidate_registry(Path(__file__).resolve().parents[2] / "config/ocr_model_candidates.json")
        by_id = {row["candidateId"]:row for row in value["candidates"]}
        prove({"pp-ocrv6-medium","paddleocr-vl-1.6","glm-ocr","tesseract-5.5.2"} <= by_id.keys())
        check_ocr_candidates(value)
    run("test_ocr_benchmark","test_candidate_registry_is_licensed_sourced_and_loadable",["d-ui.ocr-candidates"],candidates)
    def capsules():
        from .skill_capsules import SkillCapsuleRegistry
        plan = SkillCapsuleRegistry(Path(__file__).resolve().parents[2]).compile(["neyvia-aesthetic-innovation-master","neyvia-design-taste-v2","neyvia-design-taste-v3"])
        prove(not plan["missingSkillIds"] and len(plan["instructionReceipts"]) == 3 and all(row["available"] and row["sha256"] for row in plan["instructionReceipts"])
              and {"critic_receipt","screenshot_set"} <= set(plan["proofGates"]) and plan["planHash"])
    run("test_neyvia_design_skill_capsules", "test_repository_design_skills_are_installed_and_hash_bound", ["d-ui.design-capsules"],capsules)
    from .capability_service import CapabilityService
    office = CapabilityService(_fixture_root(root / "office"), catalog_path=Path(__file__).resolve().parents[2] / "config/capability_packs.json")
    run("test_office_suite_operator_workspace","test_office_suite_backend_error_unknown_operation",["d-ui.office-boundary"],
        lambda:reject(lambda:office.execute_tool_operation({"toolId":"tool.libreoffice","operationId":"office.not-a-real-operation","arguments":{}}),"does not expose operation",KeyError))
    def office_unavailable():
        libre = office.describe_tool_suite({"toolId":"tool.libreoffice"})
        pandoc = office.describe_tool_suite({"toolId":"tool.pandoc"})
        prove(libre["toolId"] == "tool.libreoffice" and pandoc["toolId"] == "tool.pandoc" and "agentReady" in libre and "operations" in libre)
        if office.adapters.descriptor("document.libreoffice").supports_execution and libre.get("agentReady") is True:
            raise ValueError("Installed Office adapter needs a separately reviewed readiness fixture")
        value = office.execute_tool_operation({"toolId":"tool.libreoffice","operationId":"office.version","arguments":{}})
        prove(value["ok"] is False and value["status"] in {"tool_not_ready","adapter_required"})
    run("test_office_suite_operator_workspace","test_office_suite_unavailable_when_adapter_not_executable",["d-ui.office-boundary"],office_unavailable)
    def office_invalid():
        source = root / "office/source.md"
        source.parent.mkdir(parents=True,exist_ok=True)
        source.write_text("# argument proof\n",encoding="utf-8")
        value = office.execute_tool_operation({"toolId":"tool.pandoc","operationId":"document.convert","arguments":{"path":str(source)}})
        prove(value["ok"] is False and value["status"] == "invalid_arguments" and value["inputValidation"]["valid"] is not True)
    run("test_office_suite_operator_workspace","test_office_suite_invalid_arguments_for_pandoc_convert",["d-ui.office-boundary"],office_invalid)
    mesh_self_checks(root,run,prove,reject)
    orchestration_self_checks(root,run,prove)
    return {"ok": all(row["ok"] for row in cases), "cases":cases, "contracts": sorted({identity for row in cases for identity in row["contracts"]}),
            "failures":[row for row in cases if not row["ok"]], "scratchRoot":str(root), "durationMs":round((time.perf_counter()-started)*1000,3),
            "manualReceipts":manual_receipts,
            "frontier":"Source-only UI cases await actual DOM/state/desktop journeys; provider detection and office execution need owned real runtimes. No rendered UI proof is claimed."}


def _fixture_root(root):
    """Bind the real consumer to an empty broker config in disposable state."""
    from .proof_credential_guard import prepare_broker_fixture
    root = Path(root).resolve()
    if not (root / "config/neyvia_secret_broker.json").exists():
        prepare_broker_fixture(root)
    return root
