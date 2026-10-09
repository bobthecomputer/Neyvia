from __future__ import annotations

import runpy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "src" / "grant_agent" / "neyvia_agent.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if text.count(old) != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {text.count(old)}")
    return text.replace(old, new, 1)


def insert_after(text: str, anchor: str, addition: str, label: str) -> str:
    if addition.strip() in text:
        return text
    if anchor not in text:
        raise RuntimeError(f"{label}: anchor not found")
    return text.replace(anchor, anchor + addition, 1)


def main() -> int:
    # Make the second pass independently reproducible from the baseline branch.
    runpy.run_path(str(ROOT / "scripts" / "apply_neyvia_native_evolution.py"), run_name="__neyvia_apply_base__")
    text = AGENT.read_text(encoding="utf-8")
    text = insert_after(
        text,
        "from .native_learning import NativeLearningStore, usage_payload\n",
        "from .native_event_stream import NativeEventStream\nfrom .native_hooks import NativeHookRunner\n",
        "hook imports",
    )
    text = insert_after(
        text,
        "    learning_enabled: bool = True\n",
        "    stream_json_events: bool = False\n",
        "stream config",
    )
    text = insert_after(
        text,
        "            learning_enabled=bool(self.learning_enabled),\n",
        "            stream_json_events=bool(self.stream_json_events),\n",
        "validated stream config",
    )
    text = insert_after(
        text,
        "    if not prompt.strip():\n        raise ValueError(\"Neyvia Agent prompt cannot be empty.\")\n",
        "    run_id = f\"neyvia_{uuid.uuid4().hex}\"\n",
        "early run id",
    )
    text = insert_after(
        text,
        "    control_root = selected.control_root or selected.root\n",
        "    event_stream = NativeEventStream(\n"
        "        control_root,\n"
        "        run_id,\n"
        "        output=sys.stdout if selected.stream_json_events else None,\n"
        "    )\n"
        "    hook_runner = NativeHookRunner(\n"
        "        control_root, mutations_allowed=selected.allow_mutations\n"
        "    )\n"
        "    event_stream.emit(\n"
        "        \"run.started\",\n"
        "        {\n"
        "            \"sessionId\": selected.session_id,\n"
        "            \"model\": selected.model,\n"
        "            \"transport\": transport,\n"
        "            \"allowMutations\": selected.allow_mutations,\n"
        "        },\n"
        "    )\n"
        "    run_before_hooks = hook_runner.run(\n"
        "        \"run.before\",\n"
        "        {\"runId\": run_id, \"sessionId\": selected.session_id},\n"
        "    )\n"
        "    event_stream.emit(\"hooks.run_before\", run_before_hooks)\n"
        "    if run_before_hooks.get(\"blocked\"):\n"
        "        event_stream.emit(\"run.blocked\", {\"reason\": \"blocking run.before hook failed\"})\n"
        "        raise RuntimeError(\"A blocking Neyvia run.before hook failed.\")\n",
        "run hooks setup",
    )
    text = insert_after(
        text,
        "    behavior_plan[\"skillRuntime\"] = skill_plan\n",
        "    event_stream.emit(\n"
        "        \"plan.compiled\",\n"
        "        {\n"
        "            \"planHash\": behavior_plan.get(\"planHash\"),\n"
        "            \"capsuleId\": (behavior_plan.get(\"capsule\") or {}).get(\"id\"),\n"
        "            \"skillPlanHash\": skill_plan.get(\"planHash\"),\n"
        "            \"resourceMode\": resource_profile.get(\"mode\"),\n"
        "        },\n"
        "    )\n"
        "    plan_hooks = hook_runner.run(\n"
        "        \"plan.compiled\",\n"
        "        {\"runId\": run_id, \"planHash\": behavior_plan.get(\"planHash\")},\n"
        "    )\n"
        "    event_stream.emit(\"hooks.plan_compiled\", plan_hooks)\n"
        "    if plan_hooks.get(\"blocked\"):\n"
        "        raise RuntimeError(\"A blocking Neyvia plan.compiled hook failed.\")\n",
        "plan hook event",
    )
    text = insert_after(
        text,
        "    proof_audit = proof_auditor.audit(\n",
        "    proof_before_hooks = hook_runner.run(\n"
        "        \"proof.before\",\n"
        "        {\"runId\": run_id, \"planHash\": behavior_plan.get(\"planHash\")},\n"
        "    )\n"
        "    event_stream.emit(\"hooks.proof_before\", proof_before_hooks)\n"
        "    if proof_before_hooks.get(\"blocked\"):\n"
        "        raise RuntimeError(\"A blocking Neyvia proof.before hook failed.\")\n",
        "proof before hook",
    )
    # The base pass creates a later run_id assignment; the early id is authoritative.
    text = text.replace('    run_id = f"neyvia_{uuid.uuid4().hex}"\n    receipt = {\n', '    receipt = {\n', 1)
    text = insert_after(
        text,
        "    proof_audit = proof_auditor.audit(\n        before=before_workspace,\n",
        "",
        "proof anchor check",
    )
    proof_end_anchor = "    finished = datetime.now(timezone.utc)\n    receipt = {\n"
    proof_after = (
        "    proof_after_hooks = hook_runner.run(\n"
        "        \"proof.after\",\n"
        "        {\n"
        "            \"runId\": run_id,\n"
        "            \"status\": proof_audit.get(\"status\"),\n"
        "            \"auditHash\": proof_audit.get(\"auditHash\"),\n"
        "        },\n"
        "    )\n"
        "    event_stream.emit(\"proof.completed\", proof_audit)\n"
        "    event_stream.emit(\"hooks.proof_after\", proof_after_hooks)\n"
        "    if proof_after_hooks.get(\"blocked\"):\n"
        "        proof_audit[\"runStatus\"] = \"blocked\"\n"
        "        proof_audit.setdefault(\"failures\", []).append(\n"
        "            \"A blocking proof.after hook failed.\"\n"
        "        )\n"
        "    run_after_hooks = hook_runner.run(\n"
        "        \"run.after\",\n"
        "        {\n"
        "            \"runId\": run_id,\n"
        "            \"status\": proof_audit.get(\"runStatus\"),\n"
        "        },\n"
        "    )\n"
        "    event_stream.emit(\"hooks.run_after\", run_after_hooks)\n"
        "    if run_after_hooks.get(\"blocked\"):\n"
        "        proof_audit[\"runStatus\"] = \"blocked\"\n"
        "        proof_audit.setdefault(\"failures\", []).append(\n"
        "            \"A blocking run.after hook failed.\"\n"
        "        )\n"
        "    event_stream.emit(\n"
        "        \"run.finished\",\n"
        "        {\n"
        "            \"status\": proof_audit.get(\"runStatus\"),\n"
        "            \"proofStatus\": proof_audit.get(\"status\"),\n"
        "        },\n"
        "    )\n"
        "    event_stream_verification = event_stream.verify()\n"
        "    finished = datetime.now(timezone.utc)\n"
        "    receipt = {\n"
    )
    text = replace_once(text, proof_end_anchor, proof_after, "proof after hooks")
    hook_fields = (
        '        "hooks": {\n'
        '            "catalog": hook_runner.catalog(),\n'
        '            "runBefore": run_before_hooks,\n'
        '            "planCompiled": plan_hooks,\n'
        '            "proofBefore": proof_before_hooks,\n'
        '            "proofAfter": proof_after_hooks,\n'
        '            "runAfter": run_after_hooks,\n'
        '        },\n'
        '        "eventStream": event_stream_verification,\n'
    )
    text = insert_after(
        text,
        '        "proofAudit": proof_audit,\n',
        hook_fields,
        "receipt hooks",
    )
    text = insert_after(
        text,
        '    parser.add_argument("--no-learning", action="store_true")\n',
        '    parser.add_argument("--stream-json", action="store_true", help="Emit hash-chained Native lifecycle events as JSONL.")\n',
        "stream cli arg",
    )
    text = insert_after(
        text,
        "                learning_enabled=not args.no_learning,\n",
        "                stream_json_events=args.stream_json,\n",
        "stream config construction",
    )
    AGENT.write_text(text, encoding="utf-8")
    print("NEYVIA_NATIVE_HOOKS_APPLIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
