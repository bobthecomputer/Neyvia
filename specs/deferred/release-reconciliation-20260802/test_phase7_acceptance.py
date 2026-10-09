from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import mock

import pytest

from grant_agent.crashproof import CrashProofStore
from grant_agent.nas_transfer import NasTransfer
from grant_agent.neyvia_coordinator import NeyviaCoordinator
from grant_agent.neyvia_extension_worker import run_extension_task
from grant_agent.thunder_compute import run_simulated_asr_journey


def test_journey_1_restart_resumes_without_duplicate_provider_launch() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        receipt = run_simulated_asr_journey(Path(temp_dir))

    assert receipt["passed"] is True
    assert receipt["checks"]["restartDeduplicated"] is True


def test_journey_2_research_continues_through_an_independent_alternative() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        store = CrashProofStore(root)
        task = store.submit_task(
            mission_id="research-paying-work",
            kind="extension.research",
            idempotency_key="research-paying-work-v1",
            payload={
                "query": "paid accessibility research tasks",
                "sources": ["https://failed.example/opportunities"],
                "discoverWeb": True,
                "allowAlternatives": True,
            },
        )

        def fetch(source: str) -> dict:
            if "failed.example" in source:
                raise TimeoutError("source timed out")
            return {
                "contentType": "text/html",
                "sha256": "a" * 64,
                "excerpt": "Independent opportunity evidence with application details.",
            }

        with (
            mock.patch(
                "grant_agent.neyvia_extension_worker._discover_web_sources",
                return_value=["https://independent.example/task"],
            ),
            mock.patch(
                "grant_agent.neyvia_extension_worker._fetch_web_source",
                side_effect=fetch,
            ),
        ):
            result = run_extension_task(root, task["taskId"])

        assert result["continuity"]["continuedAfterSourceFailure"] is True
        assert result["continuity"]["completedSources"] == 1
        assert store.get_task(task["taskId"])["status"] == "completed"


def test_journey_3_file_transfer_uses_two_proportional_checks_only() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        workspace = root / "workspace"
        nas = root / "projects"
        workspace.mkdir()
        nas.mkdir()
        source = workspace / "artifact.bin"
        source.write_bytes(b"phase-seven" * 4096)

        receipt = NasTransfer(
            workspace,
            nas,
            allow_local_nas_root=True,
        ).send(source, "proof/artifact.bin")
        verification = receipt["verification"]

        assert verification["executedCheckCount"] == 2
        assert all(check["passed"] for check in verification["checks"])
        assert verification["unrelatedChecksRun"] == []


def test_journey_4_simulated_gpu_work_finishes_with_proof_and_idle_release() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        receipt = run_simulated_asr_journey(Path(temp_dir))

    assert receipt["checks"]["completedWithCheckpoint"] is True
    assert receipt["checks"]["meterConfirmed"] is True
    assert receipt["checks"]["idlePolicyApplied"] is True
    assert receipt["steps"]["release"]["mode"] == "snapshot-and-delete"


def test_journey_5_tool_failure_is_bounded_and_coordinator_failure_is_visible() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        store = CrashProofStore(root)
        task = store.submit_task(
            mission_id="contained-tool-failure",
            kind="extension.browser",
            idempotency_key="contained-tool-failure-v1",
            payload={
                "startUrl": "https://example.invalid",
                "continuity": {"maxRetries": 1, "baseBackoffSeconds": 0},
            },
        )

        with mock.patch(
            "grant_agent.neyvia_extension_worker._run_browser",
            side_effect=TimeoutError("provider timeout"),
        ):
            with pytest.raises(TimeoutError):
                run_extension_task(root, task["taskId"])
            assert store.get_task(task["taskId"])["status"] == "queued"
            with pytest.raises(TimeoutError):
                run_extension_task(root, task["taskId"])

        failed = store.get_task(task["taskId"])
        assert failed["status"] == "failed"
        assert failed["error"]["continuity"]["action"] == "fail"

        report = NeyviaCoordinator(root).record_loop_failure(
            RuntimeError("coordinator fixture failure")
        )
        assert report["status"] == "contained"
        assert Path(report["receiptPath"]).is_file()
