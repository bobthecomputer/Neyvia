"""Mission operator journey through the persisted control-room read model."""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path


CONTRACT = "p22.mission-artifact-repair"


def mission_artifact_repair(root: Path) -> dict:
    """Observe a blocked saved mission, then repair it with a local report."""
    from . import mission_control as mc
    from .models import Mission, WorkspaceProfile

    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    store = mc.ControlRoomStore(root)
    workspace_id = "p22-mission-workbench"
    mission_id = "p22-report-journey"
    store.save_workspaces([
        WorkspaceProfile(
            workspace_id=workspace_id,
            name="Local mission proof",
            root_path=str(root),
            default_runtime="hermes",
            workspace_type="local",
            local_project_path=str(root),
            auto_sync_to_nas=False,
        )
    ])
    mission = Mission(
        mission_id=mission_id,
        workspace_id=workspace_id,
        runtime_id="hermes",
        objective="Build a previewable report from local evidence",
        success_checks=["Save a report and expose its preview"],
    )
    mission.title = "Previewable local report"
    mission.execution_scope.workspace_root = str(root)
    mission.execution_scope.execution_root = str(root)
    mission.state.status = "verification_failed"
    mission.state.stop_reason = "artifact_gate_failed"
    mission.state.last_runtime_event = "artifact_gate_failed"
    mission.state.verification_failures = [mc.HARD_ARTIFACT_GATE_CHECK_ID]
    store.save_missions([mission])

    blocked = store.build_mission_detail_snapshot(mission_id)
    saved_block = store.get_mission(mission_id)
    if not blocked["artifactGate"]["required"] or blocked["artifactGate"]["passed"]:
        raise AssertionError("Mission detail admitted a completion without runtime output and a saved artifact")
    if saved_block is None or saved_block.state.status != "verification_failed":
        raise AssertionError("A missing artifact changed the saved mission state")

    artifact_dir = root / ".agent_control" / "mission_artifacts" / mission_id
    proof_dir = artifact_dir / "proof"
    proof_dir.mkdir(parents=True)
    page = artifact_dir / "index.html"
    page.write_text(
        "<!doctype html><html><head><title>Local report</title></head>"
        "<body><main><h1>Local report</h1><p>Observed result: 42.</p></main></body></html>",
        encoding="utf-8",
    )
    output = proof_dir / "runtime_output.txt"
    output.write_text(
        "Local report completed. The saved page shows the observed result, 42, "
        "and is ready for operator review.",
        encoding="utf-8",
    )
    (artifact_dir / "artifact_manifest.json").write_text(
        json.dumps({"schema": "fluxio.mission_artifact.v1", "entrypoint": str(page),
                    "summary": "Local report for operator review."}, ensure_ascii=False),
        encoding="utf-8",
    )

    repaired = store.build_mission_detail_snapshot(mission_id)
    persisted = mc.ControlRoomStore(root).get_mission(mission_id)
    if not repaired["artifactGate"]["passed"]:
        raise AssertionError("Mission detail did not admit the saved runtime output and artifact")
    if persisted is None or persisted.state.status != "completed":
        raise AssertionError("Accepted artifact evidence did not persist the repaired mission state")
    if not page.is_file() or "Observed result: 42." not in page.read_text(encoding="utf-8"):
        raise AssertionError("The admitted preview does not resolve to the saved report")
    return {
        "blockedWithoutArtifact": True,
        "repairedStatus": persisted.state.status,
        "artifactGate": repaired["artifactGate"]["status"],
        "preview": repaired["proofDigest"].get("previewUrl", ""),
        "savedPage": str(page),
        "savedOutput": str(output),
        "boundary": "Actual local ControlRoomStore writes/reloads, mission detail projection, artifact gate and repair; no provider, network, browser rendering or model claim.",
    }


def self_check(scratch: str | Path) -> dict:
    from .contract_gate import wants
    from .proof_credential_guard import install

    scratch_root = Path(scratch).expanduser().resolve()
    allowed_root = Path("D:/NeyviaRuns/P22").resolve()
    try:
        scratch_root.relative_to(allowed_root)
    except ValueError as exc:
        raise ValueError("Mission journey scratch must stay under D:/NeyviaRuns/P22") from exc
    state = (scratch_root / ("mission-journey-" + uuid.uuid4().hex)).resolve()
    try:
        state.relative_to(scratch_root)
    except ValueError as exc:
        raise ValueError("Mission journey state escaped its supplied scratch root") from exc
    scratch_root.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=False)
    install(state)
    cases = []
    started = time.perf_counter()
    if wants(CONTRACT):
        case_root = state / "project"
        result = mission_artifact_repair(case_root)
        cases.append({"id": CONTRACT, "contracts": [CONTRACT], "ok": True, "observed": result,
                      "durationMs": round((time.perf_counter() - started) * 1000)})
    return {"area": "mission-journey", "ok": bool(cases) and all(case["ok"] for case in cases),
            "cases": cases, "durationMs": round((time.perf_counter() - started) * 1000),
            "runtimeState": str(state)}
