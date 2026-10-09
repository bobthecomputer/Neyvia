from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

MISSION_RUN_ARTIFACT_LAYOUT_SCHEMA = "fluxio.mission_run_artifact_layout.v1"
MISSION_RUN_ARTIFACT_DIRS = (
    "receipts",
    "events",
    "artifacts",
    "proof",
    "logs",
    "capsules",
    "runtime",
    "reports",
    "snapshots",
)
_MISSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


@dataclass
class MissionRunArtifactLayout:
    schema: str
    mission_id: str
    root: str
    receipts_dir: str
    receipts_jsonl: str
    events_dir: str
    event_stream_jsonl: str
    artifacts_dir: str
    proof_dir: str
    logs_dir: str
    capsules_dir: str
    runtime_dir: str
    reports_dir: str
    final_report_json: str
    snapshots_dir: str


def mission_run_artifact_root(root: str | Path, mission_id: str) -> Path:
    mission_key = _validate_mission_id(mission_id)
    canonical_root = Path(root).expanduser().resolve()
    return canonical_root / ".agent_control" / "mission_runs" / mission_key


def build_mission_run_artifact_layout(
    root: str | Path,
    mission_id: str,
    *,
    create: bool = True,
) -> MissionRunArtifactLayout:
    run_root = mission_run_artifact_root(root, mission_id)
    if create:
        run_root.mkdir(parents=True, exist_ok=True)
        for dirname in MISSION_RUN_ARTIFACT_DIRS:
            (run_root / dirname).mkdir(parents=True, exist_ok=True)

    layout = MissionRunArtifactLayout(
        schema=MISSION_RUN_ARTIFACT_LAYOUT_SCHEMA,
        mission_id=_validate_mission_id(mission_id),
        root=str(run_root),
        receipts_dir=str(run_root / "receipts"),
        receipts_jsonl=str(run_root / "receipts" / "mission_receipts.jsonl"),
        events_dir=str(run_root / "events"),
        event_stream_jsonl=str(run_root / "events" / "events.jsonl"),
        artifacts_dir=str(run_root / "artifacts"),
        proof_dir=str(run_root / "proof"),
        logs_dir=str(run_root / "logs"),
        capsules_dir=str(run_root / "capsules"),
        runtime_dir=str(run_root / "runtime"),
        reports_dir=str(run_root / "reports"),
        final_report_json=str(run_root / "reports" / "final_report.json"),
        snapshots_dir=str(run_root / "snapshots"),
    )
    from .proofs_c_missions import check_layout
    check_layout(layout, root, create)
    return layout


def mission_run_artifact_layout_payload(
    root: str | Path,
    mission_id: str,
    *,
    create: bool = True,
) -> dict[str, Any]:
    return asdict(build_mission_run_artifact_layout(root, mission_id, create=create))


def _validate_mission_id(mission_id: str) -> str:
    value = str(mission_id or "").strip()
    if not _MISSION_ID_RE.fullmatch(value):
        raise ValueError("mission_id must be a simple file-safe id")
    if value in {".", ".."}:
        raise ValueError("mission_id must not be a relative path segment")
    return value
