from __future__ import annotations

import ast
import json
import runpy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "src" / "grant_agent" / "neyvia_agent.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def insert_after(text: str, anchor: str, addition: str, label: str) -> str:
    if addition.strip() in text:
        return text
    if anchor not in text:
        raise RuntimeError(f"{label}: anchor not found")
    return text.replace(anchor, anchor + addition, 1)


def insert_before(text: str, anchor: str, addition: str, label: str) -> str:
    if addition.strip() in text:
        return text
    if anchor not in text:
        raise RuntimeError(f"{label}: anchor not found")
    return text.replace(anchor, addition + anchor, 1)


def patch_gateway(text: str) -> str:
    text = replace_once(
        text,
        "    def __init__(self, root: Path, *, allow_mutations: bool = False) -> None:\n",
        "    def __init__(self, root: Path, *, allow_mutations: bool = False, run_id: str = \"\") -> None:\n",
        "gateway signature",
    )
    text = insert_after(
        text,
        "        self.allow_mutations = allow_mutations\n",
        "        self.run_id = str(run_id or \"\")\n"
        "        self.checkpoints = NativeCheckpointStore(self.root)\n"
        "        self._checkpoint_receipts: list[str] = []\n",
        "gateway checkpoint fields",
    )
    helper_anchor = "    def compile(self, task: str, limit: int = 12) -> dict[str, Any]:\n"
    helpers = '''    @staticmethod
    def _checkpoint_argument_paths(arguments: dict[str, Any]) -> list[str]:
        paths: list[str] = []
        for key in (
            "path", "paths", "file", "files", "target", "targetPath",
            "output", "outputPath", "destination", "destinationPath",
        ):
            value = arguments.get(key)
            if isinstance(value, str) and value.strip():
                paths.append(value.strip())
            elif isinstance(value, list):
                paths.extend(str(item).strip() for item in value if isinstance(item, str) and item.strip())
        result: list[str] = []
        for item in paths:
            if item not in result:
                result.append(item)
        return result[:20]

    def _checkpoint_before_mutation(
        self,
        operation: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any] | None:
        paths = self._checkpoint_argument_paths(arguments)
        if not paths:
            return None
        checkpoint = self.checkpoints.create(
            paths,
            run_id=self.run_id,
            reason=f"Before Native mutation: {operation}",
        )
        manifest_path = str(checkpoint.get("manifestPath") or "")
        if manifest_path and manifest_path not in self._checkpoint_receipts:
            self._checkpoint_receipts.append(manifest_path)
        return checkpoint

    @property
    def checkpoint_receipts(self) -> list[str]:
        return list(self._checkpoint_receipts)

'''
    text = insert_before(text, helper_anchor, helpers, "checkpoint helpers")
    text = replace_once(
        text,
        "        return self.native.call(tool_id, arguments or {})\n",
        "        call_arguments = arguments or {}\n"
        "        checkpoint = (\n"
        "            self._checkpoint_before_mutation(tool_id, call_arguments)\n"
        "            if mutability not in {\"read\", \"none\"}\n"
        "            else None\n"
        "        )\n"
        "        result = self.native.call(tool_id, call_arguments)\n"
        "        if checkpoint and isinstance(result, dict):\n"
        "            result = {**result, \"checkpoint\": checkpoint}\n"
        "        return result\n",
        "native checkpoint call",
    )
    managed_old = '''        return self.capabilities.execute_tool_operation(
            {
                "toolId": tool_id,
                "operationId": operation_id,
                "arguments": arguments or {},
                "permissionMode": (
                    "operator_approved" if self.allow_mutations else "workspace_safe"
                ),
                "approvedPermissions": permissions if self.allow_mutations else [],
            }
        )
'''
    managed_new = '''        call_arguments = arguments or {}
        checkpoint = (
            self._checkpoint_before_mutation(f"{tool_id}.{operation_id}", call_arguments)
            if mutating
            else None
        )
        result = self.capabilities.execute_tool_operation(
            {
                "toolId": tool_id,
                "operationId": operation_id,
                "arguments": call_arguments,
                "permissionMode": (
                    "operator_approved" if self.allow_mutations else "workspace_safe"
                ),
                "approvedPermissions": permissions if self.allow_mutations else [],
            }
        )
        if checkpoint and isinstance(result, dict):
            result = {**result, "checkpoint": checkpoint}
        return result
'''
    text = replace_once(text, managed_old, managed_new, "managed checkpoint call")
    compiled_old = '''        loop = self.capabilities.run_model_tool_plan(
            {
                "goal": f"Execute compiled provider call {normalized}",
'''
    compiled_new = '''        call_arguments = dict(resolved["arguments"])
        checkpoint = (
            self._checkpoint_before_mutation(normalized, call_arguments)
            if resolved.get("requiresApproval")
            else None
        )
        loop = self.capabilities.run_model_tool_plan(
            {
                "goal": f"Execute compiled provider call {normalized}",
'''
    text = replace_once(text, compiled_old, compiled_new, "compiled checkpoint before")
    text = text.replace('                        "arguments": resolved["arguments"],\n', '                        "arguments": call_arguments,\n', 1)
    text = replace_once(
        text,
        '''        return {
            "ok": loop.get("status") == "completed",
            "status": loop.get("status"),
            "providerCall": normalized,
            "callTarget": resolved["callTarget"],
            "run": loop,
        }
''',
        '''        return {
            "ok": loop.get("status") == "completed",
            "status": loop.get("status"),
            "providerCall": normalized,
            "callTarget": resolved["callTarget"],
            "checkpoint": checkpoint,
            "run": loop,
        }
''',
        "compiled checkpoint receipt",
    )
    return text


def patch_build_run_id(text: str) -> str:
    text = replace_once(
        text,
        "    spawn_registry: NativeSpawnRegistry | None = None,\n",
        "    spawn_registry: NativeSpawnRegistry | None = None,\n    run_id: str = \"\",\n",
        "build run id parameter",
    )
    text = replace_once(
        text,
        '''    gateway = NeyviaToolGateway(
        selected.control_root or selected.root,
        allow_mutations=selected.allow_mutations,
    )
''',
        '''    gateway = NeyviaToolGateway(
        selected.control_root or selected.root,
        allow_mutations=selected.allow_mutations,
        run_id=run_id,
    )
''',
        "build gateway run id",
    )
    text = insert_after(
        text,
        "            spawn_registry=spawn_registry,\n",
        "            run_id=run_id,\n",
        "build invocation run id",
    )
    text = replace_once(
        text,
        '''        gateway = NeyviaToolGateway(
            control_root,
            allow_mutations=selected.allow_mutations,
        )
''',
        '''        gateway = NeyviaToolGateway(
            control_root,
            allow_mutations=selected.allow_mutations,
            run_id=run_id,
        )
''',
        "codex gateway run id",
    )
    return text


def patch_goal_and_spawn_evaluation(text: str) -> str:
    text = insert_after(
        text,
        "from .native_event_stream import NativeEventStream\n",
        "from .native_checkpoints import NativeCheckpointStore\n"
        "from .native_goals import NativeGoalStore\n"
        "from .native_spawn_evaluator import evaluate_spawn_tree\n",
        "goal checkpoint evaluator imports",
    )
    text = insert_after(
        text,
        "    stream_json_events: bool = False\n",
        "    goal_id: str = \"\"\n",
        "goal config",
    )
    text = insert_after(
        text,
        "            stream_json_events=bool(self.stream_json_events),\n",
        "            goal_id=self.goal_id.strip(),\n",
        "validated goal config",
    )
    goal_setup = '''    goal_store = NativeGoalStore(control_root)
    active_goal = None
    if selected.goal_id:
        active_goal = goal_store.heartbeat(
            selected.goal_id,
            run_id=run_id,
            next_action="Neyvia Native is executing the compiled behavior plan.",
            status="active",
            evidence={"planPending": True},
        )
        event_stream.emit(
            "goal.heartbeat",
            {"goalId": selected.goal_id, "status": "active"},
        )
'''
    text = insert_after(
        text,
        "    if run_before_hooks.get(\"blocked\"):\n"
        "        event_stream.emit(\"run.blocked\", {\"reason\": \"blocking run.before hook failed\"})\n"
        "        raise RuntimeError(\"A blocking Neyvia run.before hook failed.\")\n",
        goal_setup,
        "goal start",
    )
    spawn_eval = '''    spawn_evaluation = evaluate_spawn_tree(
        spawn_snapshot,
        expected_plan_hash=str(behavior_plan.get("planHash") or ""),
    )
'''
    text = insert_after(
        text,
        "    spawn_snapshot = spawn_registry.snapshot()\n",
        spawn_eval,
        "spawn evaluation",
    )
    proof_after_spawn = '''    if spawn_evaluation.get("counts", {}).get("rejected", 0):
        proof_audit["runStatus"] = "blocked"
        proof_audit["status"] = "blocked"
        proof_audit.setdefault("failures", []).append(
            "One or more spawned specialists failed independent route or evidence evaluation."
        )
'''
    text = insert_after(
        text,
        "    proof_audit = proof_auditor.audit(\n"
        "        before=before_workspace,\n"
        "        behavior_plan={\n"
        "            **behavior_plan,\n"
        "            \"capsule\": {\n"
        "                **(behavior_plan.get(\"capsule\") or {}),\n"
        "                \"proofGates\": behavior_plan.get(\"proofGates\") or (behavior_plan.get(\"capsule\") or {}).get(\"proofGates\") or [],\n"
        "            },\n"
        "        },\n"
        "        allow_mutations=selected.allow_mutations,\n"
        "        receipt_paths=[*gateway.tool_loop_receipts, *spawn_receipts, *phase_receipt_paths],\n"
        "    )\n",
        proof_after_spawn,
        "spawn evaluation proof gate",
    )
    goal_finish = '''    goal_snapshot = active_goal
    if selected.goal_id:
        proof_failures = proof_audit.get("failures") or []
        goal_snapshot = goal_store.heartbeat(
            selected.goal_id,
            run_id=run_id,
            next_action=(
                str(proof_failures[0])
                if proof_failures
                else "Review the verified run and select the next milestone."
            ),
            status="blocked" if proof_audit.get("runStatus") == "blocked" else "active",
            evidence={
                "proofStatus": proof_audit.get("status"),
                "auditHash": proof_audit.get("auditHash"),
            },
        )
        event_stream.emit(
            "goal.heartbeat",
            {"goalId": selected.goal_id, "status": goal_snapshot.get("status")},
        )
'''
    text = insert_before(
        text,
        "    proof_after_hooks = hook_runner.run(\n",
        goal_finish,
        "goal finish heartbeat",
    )
    text = insert_after(
        text,
        '        "spawnTree": spawn_snapshot,\n',
        '        "spawnEvaluation": spawn_evaluation,\n'
        '        "goal": goal_snapshot,\n'
        '        "checkpointReceipts": gateway.checkpoint_receipts,\n',
        "receipt goal spawn checkpoints",
    )
    text = text.replace(
        "        receipt_paths=[*gateway.tool_loop_receipts, *spawn_receipts, *phase_receipt_paths],\n",
        "        receipt_paths=[*gateway.tool_loop_receipts, *spawn_receipts, *phase_receipt_paths, *gateway.checkpoint_receipts],\n",
        1,
    )
    text = insert_after(
        text,
        '    parser.add_argument("--stream-json", action="store_true", help="Emit hash-chained Native lifecycle events as JSONL.")\n',
        '    parser.add_argument("--goal-id", default="", help="Attach this run to an existing durable Native goal.")\n',
        "goal cli",
    )
    text = insert_after(
        text,
        "                stream_json_events=args.stream_json,\n",
        "                goal_id=args.goal_id,\n",
        "goal config construction",
    )
    return text


def patch_package() -> None:
    path = ROOT / "package.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    scripts = payload.setdefault("scripts", {})
    scripts["native:rpc"] = "python -m grant_agent.neyvia_native_rpc"
    scripts["native:goals"] = "python -m grant_agent.neyvia_native_rpc"
    scripts["verify:native-breakthrough"] = (
        "python -m pytest -q tests/test_native_checkpoints.py tests/test_native_goals.py "
        "tests/test_neyvia_native_rpc.py tests/test_native_spawn_evaluator.py"
    )
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def patch_gates() -> None:
    path = ROOT / "GATES.md"
    text = path.read_text(encoding="utf-8")
    if "- [ ] G46:" not in text:
        text = text.rstrip() + '''

- [ ] G46: Before a bounded path-aware Native mutation, content-addressed checkpoints preserve existing and newly created files, reject secret-bearing/escaping paths, deduplicate blobs, and require explicit restore approval.
  CHECK: python -m pytest -q tests/test_native_checkpoints.py tests/test_native_checkpoint_integration_contract.py && echo NEYVIA_NATIVE_CHECKPOINTS_OK
  EXPECT: NEYVIA_NATIVE_CHECKPOINTS_OK
  EVIDENCE: pending

- [ ] G47: Native goals preserve objective, success checks, milestones, priority, schedule, due state, heartbeats, next action, run identity, and receipt-bound completion in durable SQLite state.
  CHECK: python -m pytest -q tests/test_native_goals.py && echo NEYVIA_NATIVE_GOALS_OK
  EXPECT: NEYVIA_NATIVE_GOALS_OK
  EVIDENCE: pending

- [ ] G48: Native exposes a strict line-delimited JSON-RPC control surface for capability, behavior, skill, resource, learning, goal, and checkpoint operations; parse, method, and parameter errors remain structured and external effects are not exposed by default.
  CHECK: python -m pytest -q tests/test_neyvia_native_rpc.py && echo NEYVIA_NATIVE_RPC_OK
  EXPECT: NEYVIA_NATIVE_RPC_OK
  EVIDENCE: pending

- [ ] G49: Every completed spawned specialist is independently evaluated for schema, parent session, plan hash, role route, model, effort, authority, runtime status, output integrity, and minimum evidence shape before its result can support Native completion.
  CHECK: python -m pytest -q tests/test_native_spawn_evaluator.py tests/test_native_spawn_contracts.py && echo NEYVIA_SPAWN_EVALUATION_OK
  EXPECT: NEYVIA_SPAWN_EVALUATION_OK
  EVIDENCE: pending
'''
    path.write_text(text + "\n", encoding="utf-8")


def write_integration_test() -> None:
    path = ROOT / "tests" / "test_native_checkpoint_integration_contract.py"
    path.write_text(
        '''from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_gateway_checkpoints_path_aware_mutations_and_proof_reads_manifests() -> None:
    source = (ROOT / "src" / "grant_agent" / "neyvia_agent.py").read_text(encoding="utf-8")

    assert "NativeCheckpointStore" in source
    assert "_checkpoint_before_mutation" in source
    assert "gateway.checkpoint_receipts" in source
    assert "Before Native mutation" in source
    assert "path", "static guard"


def test_goal_and_spawn_evaluation_are_receipt_fields() -> None:
    source = (ROOT / "src" / "grant_agent" / "neyvia_agent.py").read_text(encoding="utf-8")

    assert "NativeGoalStore" in source
    assert "evaluate_spawn_tree" in source
    assert '"spawnEvaluation": spawn_evaluation' in source
    assert '"goal": goal_snapshot' in source
''',
        encoding="utf-8",
    )


def main() -> int:
    namespace = runpy.run_path(str(ROOT / "scripts" / "finalize_neyvia_native_evolution_v2.py"))
    namespace["main"]()
    text = AGENT.read_text(encoding="utf-8")
    text = insert_after(
        text,
        "from .native_learning import NativeLearningStore, usage_payload\n",
        "from .native_checkpoints import NativeCheckpointStore\n"
        "from .native_goals import NativeGoalStore\n"
        "from .native_spawn_evaluator import evaluate_spawn_tree\n",
        "breakthrough imports",
    )
    text = patch_gateway(text)
    text = patch_build_run_id(text)
    text = patch_goal_and_spawn_evaluation(text)
    ast.parse(text, filename=str(AGENT))
    AGENT.write_text(text, encoding="utf-8")
    patch_package()
    patch_gates()
    write_integration_test()
    for relative in (
        "src/grant_agent/native_checkpoints.py",
        "src/grant_agent/native_goals.py",
        "src/grant_agent/neyvia_native_rpc.py",
        "src/grant_agent/native_spawn_evaluator.py",
        "src/grant_agent/neyvia_agent.py",
    ):
        ast.parse((ROOT / relative).read_text(encoding="utf-8"), filename=relative)
    print("NEYVIA_NATIVE_BREAKTHROUGH_FINALIZED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
