"""Strict line-delimited JSON-RPC control surface for Neyvia Native."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Callable

from .behavior_capsules import BehaviorCapsuleRegistry
from .native_checkpoints import NativeCheckpointStore
from .native_device_operator_authority import OperatorAuthorizedDeviceCommandStore
from .native_goals import NativeGoalStore
from .native_learning import NativeLearningStore
from .native_pairing import NativePairingStore
from .native_resource_profiles import resolve_resource_profile
from .skill_capsules import SkillCapsuleRegistry
from .subprocess_utils import install_hidden_subprocess_default


RPC_VERSION = "neyvia-native-rpc/1"


class RpcError(Exception):
    def __init__(self, code: int, message: str, data: object = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


class NativeRpcServer:
    def __init__(
        self,
        root: Path,
        *,
        device_operator_public_key_path: str | Path | None = None,
        device_operator_key_id: str | None = None,
    ) -> None:
        self.root = root.resolve()
        self.behaviors = BehaviorCapsuleRegistry(self.root)
        self.skills = SkillCapsuleRegistry(self.root)
        self.learning = NativeLearningStore(self.root)
        self.goals = NativeGoalStore(self.root)
        self.checkpoints = NativeCheckpointStore(self.root)
        self.pairing = NativePairingStore(self.root)
        self.device_commands = OperatorAuthorizedDeviceCommandStore(
            self.root,
            operator_public_key_path=device_operator_public_key_path,
            operator_key_id=device_operator_key_id,
        )
        self._methods: dict[str, Callable[[dict[str, Any]], Any]] = {
            "native.alive": self.alive,
            "native.capabilities": self.capabilities,
            "native.behaviors.list": self.behaviors_list,
            "native.plan.compile": self.plan_compile,
            "native.skills.compile": self.skills_compile,
            "native.resources.resolve": self.resources_resolve,
            "native.learning.summary": self.learning_summary,
            "native.learning.recommend": self.learning_recommend,
            "native.goals.create": self.goal_create,
            "native.goals.get": self.goal_get,
            "native.goals.list": self.goal_list,
            "native.goals.heartbeat": self.goal_heartbeat,
            "native.goals.due": self.goal_due,
            "native.pairing.create": self.pairing_create,
            "native.pairing.redeem": self.pairing_redeem,
            "native.pairing.list": self.pairing_list,
            "native.pairing.revoke": self.pairing_revoke,
            "native.device.capabilities.publish": self.device_capabilities_publish,
            "native.device.approvals.request": self.device_approval_request,
            "native.device.approvals.get": self.device_approval_get,
            "native.device.commands.enqueue": self.device_command_enqueue,
            "native.device.commands.claim": self.device_command_claim,
            "native.device.commands.complete": self.device_command_complete,
            "native.device.commands.get": self.device_command_get,
            "native.device.commands.list": self.device_command_list,
            "native.checkpoints.create": self.checkpoint_create,
            "native.checkpoints.list": self.checkpoint_list,
            "native.checkpoints.restore": self.checkpoint_restore,
        }

    def alive(self, params: dict[str, Any]) -> dict[str, Any]:
        del params
        return {"alive": True, "version": RPC_VERSION, "root": str(self.root)}

    def capabilities(self, params: dict[str, Any]) -> dict[str, Any]:
        del params
        operator_authority = self.device_commands.operator_authority_status()
        result = {
            "version": RPC_VERSION,
            "methods": sorted(self._methods),
            "behaviorCapsules": len(self.behaviors.list()),
            "skillCapsules": len(self.skills.list()),
            "authority": {
                "default": "read-only",
                "checkpointRestoreRequiresApproval": True,
                "deviceCommandPolicy": (
                    "request exact device/action/arguments plus actor/session/run context; "
                    "a separate operator surface must sign the server-prepared transaction "
                    "with the pinned external Ed25519 authority; consume that approval once; "
                    "re-verify the signature and transaction binding immediately before device "
                    "claim; execution is proven only by an authenticated terminal device receipt"
                ),
                "deviceCommandAutomaticRetry": False,
                "deviceCommandHumanIdentityCryptographicallyVerified": False,
                "deviceCommandDecisionRpcExposed": False,
                "deviceCommandSignedOperatorAuthorizationRequired": True,
                "deviceCommandOperatorVerifierReady": operator_authority["ready"],
                "deviceCommandOperatorKeyId": operator_authority["keyId"],
                "deviceCommandApprovalBoundary": (
                    "This agent-facing Native RPC can request and inspect approval but cannot "
                    "approve, deny, sign, or human-cancel a device command. Approved side effects "
                    "require an externally signed transaction and fail closed when the pinned "
                    "operator verifier is unavailable. A valid signature proves control of the "
                    "configured operator key, not biometric presence or physical personhood."
                ),
                "externalEffects": (
                    "device commands are requests, not execution claims; the native app "
                    "transport/executor is a separate integration boundary"
                ),
            },
        }
        from .proofs_d_neyvia import rpc_capabilities
        rpc_capabilities(self, result)
        return result

    def behaviors_list(self, params: dict[str, Any]) -> dict[str, Any]:
        del params
        return {"capsules": self.behaviors.list()}

    def plan_compile(self, params: dict[str, Any]) -> dict[str, Any]:
        task = str(params.get("task") or "").strip()
        if not task:
            raise RpcError(-32602, "task is required")
        resource = resolve_resource_profile(params.get("resourceMode") or "auto")
        capsule = self.behaviors.select(task, str(params.get("behaviorCapsule") or "auto"))
        adjustment = (
            self.learning.behavior_adjustment(capsule.task_kinds[0] if capsule.task_kinds else "general")
            if bool(params.get("useLearning", True))
            else {"applied": False, "evidenceRuns": 0, "behaviorVectorDelta": {}, "reason": "Learning disabled by caller."}
        )
        plan = self.behaviors.compile(
            task,
            preferred=str(params.get("behaviorCapsule") or "auto"),
            resource_profile=resource,
            learned_adjustment=adjustment,
        )
        plan["compiledSkillPlan"] = self.skills.compile((plan.get("capsule") or {}).get("skillIds") or ())
        from .proofs_d_neyvia import require
        require(plan["resourceProfile"]["mode"] == resource["mode"] and plan.get("capsule") and plan.get("compiledSkillPlan"),
                "neyvia-core.rpc-plan", "compiled plan lost resource/behavior/skill binding")
        return plan

    def skills_compile(self, params: dict[str, Any]) -> dict[str, Any]:
        skill_ids = params.get("skillIds") or []
        if not isinstance(skill_ids, list):
            raise RpcError(-32602, "skillIds must be an array")
        return self.skills.compile([str(item) for item in skill_ids])

    def resources_resolve(self, params: dict[str, Any]) -> dict[str, Any]:
        return resolve_resource_profile(params.get("mode") or "auto")

    def learning_summary(self, params: dict[str, Any]) -> dict[str, Any]:
        del params
        return self.learning.summary()

    def learning_recommend(self, params: dict[str, Any]) -> dict[str, Any]:
        return self.learning.recommend(
            str(params.get("taskKind") or "general"),
            minimum_samples=max(2, min(100, int(params.get("minimumSamples") or 8))),
        )

    def goal_create(self, params: dict[str, Any]) -> dict[str, Any]:
        return self.goals.create(
            str(params.get("objective") or ""),
            goal_id=str(params.get("goalId") or ""),
            success_checks=[str(item) for item in params.get("successChecks") or []],
            priority=int(params.get("priority") or 50),
            next_action=str(params.get("nextAction") or ""),
            schedule_seconds=(
                int(params["scheduleSeconds"])
                if params.get("scheduleSeconds") is not None
                else None
            ),
            milestones=[str(item) for item in params.get("milestones") or []],
        )

    def goal_get(self, params: dict[str, Any]) -> dict[str, Any]:
        return self.goals.get(str(params.get("goalId") or ""))

    def goal_list(self, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "goals": self.goals.list(
                status=str(params.get("status") or "") or None,
                limit=int(params.get("limit") or 100),
            )
        }

    def goal_heartbeat(self, params: dict[str, Any]) -> dict[str, Any]:
        return self.goals.heartbeat(
            str(params.get("goalId") or ""),
            run_id=str(params.get("runId") or ""),
            next_action=str(params.get("nextAction") or ""),
            status=str(params.get("status") or "") or None,
            evidence=dict(params.get("evidence") or {}),
        )

    def goal_due(self, params: dict[str, Any]) -> dict[str, Any]:
        return {"goals": self.goals.due(int(params.get("limit") or 20))}

    def pairing_create(self, params: dict[str, Any]) -> dict[str, Any]:
        scopes = params.get("scopes")
        if scopes is not None and not isinstance(scopes, list):
            raise RpcError(-32602, "scopes must be an array")
        return self.pairing.create(
            str(params.get("target") or ""),
            scopes=[str(item) for item in scopes] if scopes else None,
            ttl_seconds=int(params.get("ttlSeconds") or 600),
            base_url=str(params.get("baseUrl") or ""),
        )

    def pairing_redeem(self, params: dict[str, Any]) -> dict[str, Any]:
        return self.pairing.redeem(
            str(params.get("pairingId") or ""),
            str(params.get("pairingToken") or ""),
            str(params.get("displayName") or ""),
        )

    def pairing_list(self, params: dict[str, Any]) -> dict[str, Any]:
        del params
        return {"devices": self.pairing.list_devices()}

    def pairing_revoke(self, params: dict[str, Any]) -> dict[str, Any]:
        return self.pairing.revoke(str(params.get("deviceId") or ""))

    def device_capabilities_publish(self, params: dict[str, Any]) -> dict[str, Any]:
        capabilities = params.get("capabilities")
        if not isinstance(capabilities, list):
            raise RpcError(-32602, "capabilities must be an array")
        return self.device_commands.publish_capabilities(
            str(params.get("deviceId") or ""),
            str(params.get("deviceSecret") or ""),
            [str(item) for item in capabilities],
        )

    def device_approval_request(self, params: dict[str, Any]) -> dict[str, Any]:
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise RpcError(-32602, "arguments must be an object")
        return self.device_commands.request_approval(
            str(params.get("deviceId") or ""),
            str(params.get("action") or ""),
            arguments=arguments,
            actor_id=str(params.get("actorId") or ""),
            session_id=str(params.get("sessionId") or ""),
            run_id=str(params.get("runId") or ""),
            ttl_seconds=int(params.get("ttlSeconds") or 300),
        )

    def device_approval_get(self, params: dict[str, Any]) -> dict[str, Any]:
        return self.device_commands.get_approval(str(params.get("approvalId") or ""))

    def device_command_enqueue(self, params: dict[str, Any]) -> dict[str, Any]:
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise RpcError(-32602, "arguments must be an object")
        return self.device_commands.enqueue(
            str(params.get("deviceId") or ""),
            str(params.get("action") or ""),
            arguments=arguments,
            idempotency_key=str(params.get("idempotencyKey") or ""),
            approval_id=str(params.get("approvalId") or ""),
            actor_id=str(params.get("actorId") or ""),
            session_id=str(params.get("sessionId") or ""),
            run_id=str(params.get("runId") or ""),
            ttl_seconds=int(params.get("ttlSeconds") or 300),
        )

    def device_command_claim(self, params: dict[str, Any]) -> dict[str, Any]:
        command = self.device_commands.claim(
            str(params.get("deviceId") or ""),
            str(params.get("deviceSecret") or ""),
            lease_seconds=int(params.get("leaseSeconds") or 45),
        )
        return {"command": command}

    def device_command_complete(self, params: dict[str, Any]) -> dict[str, Any]:
        result = params.get("result") or {}
        if not isinstance(result, dict):
            raise RpcError(-32602, "result must be an object")
        return self.device_commands.complete(
            str(params.get("deviceId") or ""),
            str(params.get("deviceSecret") or ""),
            str(params.get("commandId") or ""),
            str(params.get("claimId") or ""),
            status=str(params.get("status") or ""),
            result=result,
            error_code=str(params.get("errorCode") or ""),
            error_message=str(params.get("errorMessage") or ""),
        )

    def device_command_get(self, params: dict[str, Any]) -> dict[str, Any]:
        return self.device_commands.get(str(params.get("commandId") or ""))

    def device_command_list(self, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "commands": self.device_commands.list(
                device_id=str(params.get("deviceId") or ""),
                limit=int(params.get("limit") or 50),
            )
        }

    def checkpoint_create(self, params: dict[str, Any]) -> dict[str, Any]:
        paths = params.get("paths") or []
        if not isinstance(paths, list) or not paths:
            raise RpcError(-32602, "paths must be a non-empty array")
        return self.checkpoints.create(
            [str(item) for item in paths],
            run_id=str(params.get("runId") or ""),
            reason=str(params.get("reason") or "RPC-requested checkpoint"),
        )

    def checkpoint_list(self, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "checkpoints": self.checkpoints.list(int(params.get("limit") or 50)),
            "recovery": self.checkpoints.recovery_status(),
        }

    def checkpoint_restore(self, params: dict[str, Any]) -> dict[str, Any]:
        return self.checkpoints.restore(
            str(params.get("checkpointId") or ""),
            approved=bool(params.get("approved", False)),
        )

    def dispatch(self, request: object) -> dict[str, Any] | None:
        if not isinstance(request, dict):
            raise RpcError(-32600, "request must be an object")
        if request.get("jsonrpc") != "2.0":
            raise RpcError(-32600, "jsonrpc must be 2.0")
        method = request.get("method")
        if not isinstance(method, str) or not method:
            raise RpcError(-32600, "method is required")
        request_id = request.get("id")
        notification = "id" not in request
        params = request.get("params") or {}
        if not isinstance(params, dict):
            raise RpcError(-32602, "params must be an object")
        from .proofs_d_neyvia import rpc_methods, rpc_reply
        rpc_methods(self._methods)
        handler = self._methods.get(method)
        if handler is None:
            raise RpcError(-32601, f"method not found: {method}")
        result = handler(params)
        from .proofs_d_neyvia import rpc_device_response
        rpc_device_response(self, method, params, result)
        if notification:
            rpc_reply(request, result, None)
            return None
        response = {"jsonrpc": "2.0", "id": request_id, "result": result}
        rpc_reply(request, result, response)
        return response


def error_response(request_id: object, error: RpcError) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": error.code, "message": error.message},
    }
    if error.data is not None:
        payload["error"]["data"] = error.data
    from .proofs_d_neyvia import rpc_error
    rpc_error(request_id, error, payload)
    return payload


def serve(root: Path, input_stream=sys.stdin, output_stream=sys.stdout) -> int:
    server = NativeRpcServer(root)
    for raw in input_stream:
        line = raw.strip()
        if not line:
            continue
        request_id: object = None
        try:
            request = json.loads(line)
            if isinstance(request, dict):
                request_id = request.get("id")
            response = server.dispatch(request)
        except json.JSONDecodeError as exc:
            response = error_response(None, RpcError(-32700, "parse error", {"detail": str(exc)}))
        except RpcError as exc:
            response = error_response(request_id, exc)
        except (KeyError, ValueError, PermissionError) as exc:
            response = error_response(request_id, RpcError(-32602, str(exc)))
        except Exception as exc:
            response = error_response(request_id, RpcError(-32603, "internal error", {"type": type(exc).__name__}))
        if response is not None:
            output_stream.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
            output_stream.flush()
    return 0


def main(argv: list[str] | None = None) -> int:
    install_hidden_subprocess_default()
    parser = argparse.ArgumentParser(description="Run the strict Neyvia Native JSONL-RPC server.")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    return serve(args.root)


if __name__ == "__main__":
    raise SystemExit(main())
