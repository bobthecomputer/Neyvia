from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from grant_agent.capability_service import CapabilityService
from grant_agent.mesh_service import MeshService
from grant_agent.sdk import (
    advertise_mesh_service,
    get_mesh_enrollment_trust,
    get_mesh_migration_plan,
    get_mesh_service_catalog,
    get_mesh_snapshot,
    probe_mesh_peer,
    revoke_mesh_service,
)


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "config" / "capability_packs.json"


def test_mesh_snapshot_cache_keeps_provider_polling_off_hot_bootstrap(
    tmp_path: Path,
    monkeypatch,
) -> None:
    service = MeshService(tmp_path)
    calls = 0

    def provider() -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {
            "providerId": "tailscale-bridge",
            "available": True,
            "state": "running",
            "self": None,
            "peers": [],
        }

    monkeypatch.setattr(service, "_tailscale_snapshot", provider)

    first = service.snapshot()
    second = service.snapshot()

    assert calls == 1
    assert first["cache"] == "miss"
    assert second["cache"] == "hit"
    assert service.bootstrap()["detailsDeferred"] is True


def test_tailscale_node_sanitizer_never_returns_transport_keys_or_owner(
    tmp_path: Path,
) -> None:
    service = MeshService(tmp_path)
    row = service._sanitize_tailscale_node(
        {
            "ID": "node-id",
            "PublicKey": "nodekey:must-not-leak",
            "UserID": 123,
            "HostName": "phone",
            "DNSName": "phone.example.ts.net.",
            "OS": "android",
            "TailscaleIPs": ["192.0.2.10"],
            "Online": True,
            "Active": True,
            "CurAddr": "192.168.1.20:41641",
        }
    )

    serialized = json.dumps(row)
    assert row["deviceId"].startswith("mesh_")
    assert row["routeState"] == "direct"
    assert "nodekey" not in serialized
    assert "UserID" not in serialized
    assert "PublicKey" not in serialized


def test_mesh_ping_parser_distinguishes_direct_and_relay_paths(
    tmp_path: Path,
) -> None:
    service = MeshService(tmp_path)
    rows = service._parse_ping_output(
        "pong from nas (192.0.2.10) via 192.168.1.2:41641 in 6ms\n"
        "pong from phone (192.0.2.10) via DERP(par) in 38ms"
    )

    assert rows == [
        {
            "peerName": "nas",
            "address": "192.0.2.10",
            "route": "direct",
            "via": "192.168.1.2:41641",
            "latencyMs": 6,
        },
        {
            "peerName": "phone",
            "address": "192.0.2.10",
            "route": "relay",
            "via": "DERP(par)",
            "latencyMs": 38,
        },
    ]


def test_provider_owned_funnel_relays_are_excluded_from_agent_context(
    tmp_path: Path,
) -> None:
    service = MeshService(tmp_path)

    assert service._is_system_tailscale_node(
        {
            "HostName": "funnel-ingress-node",
            "OS": "",
            "DNSName": "",
            "ShareeNode": True,
        }
    ) is True
    assert service._is_system_tailscale_node(
        {
            "HostName": "friend-phone",
            "OS": "android",
            "DNSName": "friend-phone.example.ts.net.",
            "ShareeNode": True,
        }
    ) is False


def test_private_service_advertisement_requires_approval_and_rejects_secrets(
    tmp_path: Path,
    monkeypatch,
) -> None:
    service = MeshService(tmp_path)
    monkeypatch.setattr(
        service,
        "snapshot",
        lambda **_kwargs: {
            "provider": {
                "self": {
                    "deviceId": "mesh_self",
                    "online": True,
                    "hostName": "workstation",
                    "dnsName": "workstation.example.ts.net",
                    "addresses": ["192.0.2.10"],
                },
                "peers": [],
            }
        },
    )
    payload = {
        "serviceId": "context.local",
        "deviceId": "mesh_self",
        "serviceType": "context",
        "endpoint": "https://192.0.2.10:7443",
        "healthPath": "/health",
        "capabilities": ["context.bootstrap", "context.chunk"],
        "advertisedBy": "operator",
    }

    blocked = service.advertise_service(payload, approved=False)
    advertised = service.advertise_service(payload, approved=True)
    catalog = service.service_catalog()
    secret_payload = {**payload, "serviceId": "context.secret", "token": "bad"}

    assert blocked["status"] == "approval_required"
    assert advertised["status"] == "advertised"
    assert catalog["summary"]["total"] == 1
    with pytest.raises(ValueError, match="secret-bearing"):
        service.advertise_service(secret_payload, approved=True)

    revoked = service.revoke_service(
        "context.local",
        approved=True,
        revoked_by="operator",
        reason="test complete",
    )
    assert revoked["status"] == "revoked"


def test_mesh_sdk_surface_is_complete_and_migration_remains_fail_closed() -> None:
    plan = get_mesh_migration_plan(workspace_root=ROOT)

    assert plan["currentProvider"] == "tailscale-bridge"
    assert plan["targetProvider"] == "netbird"
    assert plan["cutoverAllowed"] is False
    assert plan["action"] == "keep-current-bridge"
    assert callable(get_mesh_snapshot)
    assert callable(probe_mesh_peer)
    assert callable(get_mesh_service_catalog)
    assert callable(advertise_mesh_service)
    assert callable(revoke_mesh_service)
    assert callable(get_mesh_enrollment_trust)


def test_mesh_tool_operations_are_typed_and_write_actions_require_approval(
    tmp_path: Path,
) -> None:
    service = CapabilityService(tmp_path, catalog_path=CATALOG)

    status = service.execute_tool_operation(
        {
            "toolId": "tool.neyvia-mesh",
            "operationId": "mesh.status",
            "arguments": {},
        }
    )
    blocked = service.execute_tool_operation(
        {
            "toolId": "tool.neyvia-mesh",
            "operationId": "mesh.advertise-service",
            "arguments": {
                "approved": True,
                "service": {
                    "serviceId": "context.local",
                    "deviceId": "mesh_local",
                    "serviceType": "context",
                    "endpoint": "http://127.0.0.1:7443",
                },
            },
        }
    )
    advertised = service.execute_tool_operation(
        {
            "toolId": "tool.neyvia-mesh",
            "operationId": "mesh.advertise-service",
            "approvedPermissions": ["network.write"],
            "arguments": {
                "approved": True,
                "service": {
                    "serviceId": "context.local",
                    "deviceId": "mesh_local",
                    "serviceType": "context",
                    "endpoint": "http://127.0.0.1:7443",
                    "advertisedBy": "test-operator",
                },
            },
        }
    )

    assert status["ok"] is True, status
    assert status["outputValidation"]["valid"] is True
    assert status["result"]["provider"]["credentialsExposed"] is False
    assert blocked["status"] == "approval_required"
    assert advertised["ok"] is True, advertised
    assert advertised["result"]["status"] == "advertised"


@pytest.mark.skipif(
    shutil.which("tailscale") is None,
    reason="Tailscale bridge is not installed on this worker",
)
def test_live_mesh_snapshot_is_sanitized_and_within_live_budget() -> None:
    result = MeshService(ROOT).snapshot(refresh=True)

    assert result["provider"]["available"] is True
    assert result["durationMs"] < 750
    serialized = json.dumps(result)
    assert "nodekey:" not in serialized
    assert "@gmail.com" not in serialized


def test_mesh_enrollment_trust_surfaces_blocked_gates_and_route_summary(
    tmp_path: Path,
    monkeypatch,
) -> None:
    service = MeshService(tmp_path)

    def provider() -> dict[str, object]:
        return {
            "providerId": "tailscale-bridge",
            "available": True,
            "state": "running",
            "self": {
                "deviceId": "mesh_self",
                "hostName": "workstation",
                "routeState": "direct",
                "online": True,
            },
            "peers": [
                {
                    "deviceId": "mesh_peer",
                    "hostName": "phone",
                    "dnsName": "phone.example.ts.net",
                    "os": "android",
                    "addresses": ["192.0.2.10"],
                    "online": True,
                    "active": True,
                    "routeState": "direct",
                }
            ],
            "credentialsExposed": False,
        }

    monkeypatch.setattr(service, "_tailscale_snapshot", provider)
    status = service.enrollment_and_trust_status()

    assert status["schema"] == "neyvia.mesh-enrollment-trust/v1"
    assert status["enrollment"]["available"] is False
    assert status["enrollment"]["state"] == "blocked-pending-cutover-gates"
    assert status["policy"]["agentMayEnrollDevices"] is False
    assert status["trust"]["directActive"] == 1
    assert status["services"]["deviceRevocationImplemented"] is False
    assert any(
        row["gate"] == "android-client" and row["passed"] is False
        for row in status["enrollment"]["gates"]
    )


def test_mesh_enrollment_trust_tool_operation_is_typed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    capability = CapabilityService(tmp_path, catalog_path=CATALOG)

    def provider() -> dict[str, object]:
        return {
            "providerId": "tailscale-bridge",
            "available": True,
            "state": "running",
            "self": None,
            "peers": [],
            "credentialsExposed": False,
        }

    monkeypatch.setattr(
        capability.mesh,
        "_tailscale_snapshot",
        provider,
    )
    result = capability.execute_tool_operation(
        {
            "toolId": "tool.neyvia-mesh",
            "operationId": "mesh.enrollment-trust",
            "arguments": {},
        }
    )

    assert result["ok"] is True, result
    assert result["outputValidation"]["valid"] is True
    assert result["result"]["schema"] == "neyvia.mesh-enrollment-trust/v1"
    assert result["result"]["enrollment"]["approvalRequired"] is True
