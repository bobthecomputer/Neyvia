from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from grant_agent.mcp_broker import McpOutboundBroker
from grant_agent.thunder_compute import (
    THUNDER_JOURNEY_SCHEMA,
    THUNDER_RESULT_SCHEMA,
    ThunderComputeSimulator,
    ThunderComputeSimulatorTransport,
    build_thunder_resource_policy,
    build_thunder_simulator_broker_config,
    run_simulated_asr_journey,
    thunder_acceptance_status,
    thunder_compute_tool_catalog,
)


def test_catalog_matches_official_resource_and_billing_shape() -> None:
    tools = {row["name"]: row for row in thunder_compute_tool_catalog()}

    assert {
        "list_instances",
        "create_instance",
        "delete_instance",
        "modify_instance",
        "run_command",
        "get_specs",
        "get_availability",
        "get_pricing",
        "list_snapshots",
        "create_snapshot",
        "get_meter_data",
        "get_upcoming_invoice",
        "get_subscription",
    }.issubset(tools)
    assert tools["list_instances"]["annotations"]["readOnlyHint"] is True
    assert tools["create_instance"]["annotations"]["requiresApproval"] is True
    assert tools["delete_instance"]["annotations"]["destructiveHint"] is True


def test_simulator_requires_explicit_non_production_opt_in(
    tmp_path: pathlib.Path,
) -> None:
    disabled_status = thunder_acceptance_status(tmp_path, environ={})
    enabled_status = thunder_acceptance_status(
        tmp_path, environ={"NEYVIA_ALLOW_THUNDER_SIMULATOR": "1"}
    )
    blocked = McpOutboundBroker(
        tmp_path,
        config={
            "servers": {
                "thunder": {
                    "transport": "thunder-simulator",
                    "authState": "authenticated",
                    "environment": "production",
                    "allowSimulation": True,
                }
            }
        },
        include_default_demo=False,
    )
    blocked_state = blocked.list_servers()[0]

    assert blocked_state["callable"] is False
    assert blocked_state["simulated"] is False
    assert "simulation_requires_explicit_test_or_development_opt_in" in blocked_state[
        "notes"
    ]
    assert disabled_status["status"] == "disabled"
    assert disabled_status["realPaidExecutionEnabled"] is False
    assert enabled_status["status"] == "ready"
    assert enabled_status["simulated"] is True

    enabled = McpOutboundBroker(
        tmp_path,
        config=build_thunder_simulator_broker_config(),
        include_default_demo=False,
    )
    enabled_state = enabled.list_servers()[0]

    assert enabled_state["callable"] is True
    assert enabled_state["simulated"] is True
    assert "never_use_as_production_success_evidence" in enabled_state["notes"]


def test_full_asr_journey_is_fast_durable_and_approval_gated(
    tmp_path: pathlib.Path,
) -> None:
    receipt = run_simulated_asr_journey(tmp_path)

    assert receipt["schema"] == THUNDER_JOURNEY_SCHEMA
    assert receipt["simulated"] is True
    assert receipt["passed"] is True
    assert receipt["durationMs"] < 2000
    assert all(receipt["checks"].values())
    assert pathlib.Path(receipt["statePath"]).exists()
    assert pathlib.Path(receipt["receiptPath"]).exists()
    assert receipt["steps"]["approvalBoundary"]["status"] == "approval_required"
    final = receipt["steps"]["finalStatus"]["result"]["structuredContent"]
    assert final["schema"] == THUNDER_RESULT_SCHEMA
    assert final["providerMode"] == "simulated"
    assert final["data"]["job"]["status"] == "completed"
    assert final["data"]["job"]["latestCheckpoint"].endswith("epoch-13.pt")
    assert final["data"]["job"]["artifacts"]


def test_restart_deduplicates_a_consequential_request(
    tmp_path: pathlib.Path,
) -> None:
    args = {
        "instanceId": "inst-asr-01",
        "command": "python train_asr.py --resume checkpoint.pt",
        "idempotencyKey": "stable-launch-key",
    }
    first = ThunderComputeSimulator(tmp_path).call("run_command", args)
    restarted = ThunderComputeSimulator(tmp_path)
    duplicate = restarted.call("run_command", args)
    state = restarted.snapshot()

    assert first["ok"] is True
    assert first["deduplicated"] is False
    assert duplicate["deduplicated"] is True
    assert (
        duplicate["data"]["job"]["jobId"]
        == first["data"]["job"]["jobId"]
        == state["instances"]["inst-asr-01"]["job"]["jobId"]
    )
    assert len(state["requests"]) == 1


def test_failure_fixtures_are_truthful_and_contained(
    tmp_path: pathlib.Path,
) -> None:
    unavailable = ThunderComputeSimulator(
        tmp_path / "unavailable", scenario="gpu_unavailable"
    )
    create = unavailable.call(
        "create_instance",
        {
            "gpuType": "A100-80GB",
            "idempotencyKey": "create-unavailable",
        },
    )
    failed_job = ThunderComputeSimulator(
        tmp_path / "failed-job", scenario="job_failed"
    )
    launched = failed_job.call(
        "run_command",
        {
            "instanceId": "inst-asr-01",
            "command": "python train_asr.py --resume checkpoint.pt",
            "idempotencyKey": "launch-failing-job",
        },
    )
    transport = ThunderComputeSimulatorTransport(
        tmp_path / "failed-job", scenario="job_failed"
    )
    transport.simulator.advance(16)
    current = transport.simulator.snapshot()["instances"]["inst-asr-01"]["job"]
    cost_limited = ThunderComputeSimulator(
        tmp_path / "cost-limited",
        resource_policy=build_thunder_resource_policy(
            max_estimated_cost=0.02,
            max_duration_seconds=120,
        ),
    ).call(
        "run_command",
        {
            "instanceId": "inst-asr-01",
            "command": "python train_asr.py --resume checkpoint.pt",
            "estimatedDurationSeconds": 120,
            "estimatedCost": 0.18,
            "idempotencyKey": "over-cost-policy",
        },
    )

    assert create["ok"] is False
    assert create["error"] == "gpu_capacity_unavailable"
    assert launched["ok"] is True
    assert current["status"] == "failed"
    assert "failed after checkpoint" in current["logs"][-1]
    assert cost_limited["ok"] is False
    assert cost_limited["error"] == "resource_policy_denied"
    assert cost_limited["resourceDecision"]["reasons"] == [
        "estimated_cost_limit_exceeded"
    ]
