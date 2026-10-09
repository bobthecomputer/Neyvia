from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
import uuid

from .durability import atomic_write_json
from .models import RunState, utc_now_iso
from .harness_jobs import _exclusive_job_lock


@dataclass
class CheckpointRecord:
    checkpoint_id: str
    created_at: str
    session_id: str
    iteration: int
    objective: str
    context: dict
    doc_sources: list[str]
    state: dict


class CheckpointStore:
    def __init__(self, session_path: Path) -> None:
        self.session_path = session_path
        self.checkpoint_dir = session_path / "checkpoints"
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def save(
        self,
        session_id: str,
        iteration: int,
        run_state: RunState,
        context: dict,
        doc_sources: list[str],
    ) -> Path:
        checkpoint_id = f"ckpt_{iteration:03d}"
        record = CheckpointRecord(
            checkpoint_id=checkpoint_id,
            created_at=utc_now_iso(),
            session_id=session_id,
            iteration=iteration,
            objective=run_state.objective,
            context=context,
            doc_sources=doc_sources,
            state=asdict(run_state),
        )
        path = self.checkpoint_dir / f"{checkpoint_id}.json"
        # The OS guard survives threads/processes and releases on a crash. Once
        # acquired, no cooperating writer can still own this checkpoint's tails.
        # Keep abandoned bytes recoverable instead of treating them as records.
        with _exclusive_job_lock(path):
            tails = list(self.checkpoint_dir.glob(f".{path.name}.*.tmp"))
            if tails:
                recovery = self.checkpoint_dir / ".abandoned-writes"
                recovery.mkdir(exist_ok=True)
                recovery.resolve().relative_to(self.checkpoint_dir.resolve())
                for tail in tails:
                    tail.replace(recovery / f"{uuid.uuid4().hex}-{tail.name}")
            atomic_write_json(path, asdict(record))
            from .proofs_a_capabilities import check_checkpoint
            check_checkpoint(path, asdict(record))
        return path

    @staticmethod
    def list(session_path: Path) -> list[Path]:
        checkpoint_dir = session_path / "checkpoints"
        if not checkpoint_dir.exists():
            return []
        return sorted(
            [path for path in checkpoint_dir.glob("ckpt_*.json") if path.is_file()],
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )

    @staticmethod
    def load(checkpoint_path: Path) -> dict:
        return json.loads(checkpoint_path.read_text(encoding="utf-8"))

    @staticmethod
    def latest(session_path: Path) -> Path | None:
        checkpoints = CheckpointStore.list(session_path)
        return checkpoints[0] if checkpoints else None
