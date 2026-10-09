from __future__ import annotations

from pathlib import Path
from .proofs_e_sv import enforced


@enforced("sv.suggestions.signals")
def collect_repo_signals(repo_path: Path) -> dict:
    tests_count = len(list(repo_path.glob("tests/**/*.py"))) if (repo_path / "tests").exists() else 0
    docs_count = len(list(repo_path.glob("docs/**/*.md"))) if (repo_path / "docs").exists() else 0
    has_pyproject = (repo_path / "pyproject.toml").exists()
    has_readme = (repo_path / "README.md").exists()
    return {
        "tests_count": tests_count,
        "docs_count": docs_count,
        "has_pyproject": has_pyproject,
        "has_readme": has_readme,
    }


@enforced("sv.suggestions.priority")
def build_vibe_next_steps(
    objective: str,
    run_state: dict,
    memory_hits: list[str],
    repo_signals: dict,
    limit: int = 6,
) -> list[str]:
    actions: list[str] = []
    remaining = run_state.get("next_actions", [])

    if remaining:
        actions.append(f"Finish remaining plan step: {remaining[0]}")

    if repo_signals.get("tests_count", 0) == 0:
        actions.append("Add a minimal smoke test suite to support faster hands-free iteration.")
    else:
        actions.append("Keep fast feedback loop: run targeted tests after each edit batch.")

    if repo_signals.get("docs_count", 0) == 0:
        actions.append("Create docs for architecture and runbook to improve future autonomous continuity.")
    else:
        actions.append("Update docs with new decisions so memory and resume stay aligned.")

    if memory_hits:
        actions.append("Review top memory hints and convert one into an explicit task for this run.")

    if "ui" in objective.lower() or "preview" in objective.lower():
        actions.append("Add preview validation checkpoints (desktop + mobile) in the vibe loop.")

    actions.append("Capture a checkpoint before risky edits so rollback stays one command away.")
    return actions[:limit]
