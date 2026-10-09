from __future__ import annotations

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


def main() -> int:
    namespace = runpy.run_path(str(ROOT / "scripts" / "apply_neyvia_native_evolution.py"))
    namespace["main"]()
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
    run_hooks = '''    event_stream = NativeEventStream(
        control_root,
        run_id,
        output=sys.stdout if selected.stream_json_events else None,
    )
    hook_runner = NativeHookRunner(
        control_root, mutations_allowed=selected.allow_mutations
    )
    event_stream.emit(
        "run.started",
        {
            "sessionId": selected.session_id,
            "model": selected.model,
            "transport": transport,
            "allowMutations": selected.allow_mutations,
        },
    )
    run_before_hooks = hook_runner.run(
        "run.before",
        {"runId": run_id, "sessionId": selected.session_id},
    )
    event_stream.emit("hooks.run_before", run_before_hooks)
    if run_before_hooks.get("blocked"):
        event_stream.emit("run.blocked", {"reason": "blocking run.before hook failed"})
        raise RuntimeError("A blocking Neyvia run.before hook failed.")
'''
    text = insert_after(
        text,
        "    control_root = selected.control_root or selected.root\n",
        run_hooks,
        "run hooks setup",
    )
    plan_hooks = '''    event_stream.emit(
        "plan.compiled",
        {
            "planHash": behavior_plan.get("planHash"),
            "capsuleId": (behavior_plan.get("capsule") or {}).get("id"),
            "skillPlanHash": skill_plan.get("planHash"),
            "resourceMode": resource_profile.get("mode"),
        },
    )
    plan_hooks = hook_runner.run(
        "plan.compiled",
        {"runId": run_id, "planHash": behavior_plan.get("planHash")},
    )
    event_stream.emit("hooks.plan_compiled", plan_hooks)
    if plan_hooks.get("blocked"):
        raise RuntimeError("A blocking Neyvia plan.compiled hook failed.")
'''
    text = insert_after(
        text,
        "    behavior_plan[\"skillRuntime\"] = skill_plan\n",
        plan_hooks,
        "plan hook event",
    )
    proof_before = '''    proof_before_hooks = hook_runner.run(
        "proof.before",
        {"runId": run_id, "planHash": behavior_plan.get("planHash")},
    )
    event_stream.emit("hooks.proof_before", proof_before_hooks)
    if proof_before_hooks.get("blocked"):
        raise RuntimeError("A blocking Neyvia proof.before hook failed.")
'''
    text = insert_before(
        text,
        "    proof_audit = proof_auditor.audit(\n",
        proof_before,
        "proof before hook",
    )
    # The base pass creates a later run id assignment; the early id is authoritative.
    text = text.replace('    run_id = f"neyvia_{uuid.uuid4().hex}"\n    receipt = {\n', '    receipt = {\n', 1)
    proof_end_anchor = "    finished = datetime.now(timezone.utc)\n    receipt = {\n"
    proof_after = '''    proof_after_hooks = hook_runner.run(
        "proof.after",
        {
            "runId": run_id,
            "status": proof_audit.get("status"),
            "auditHash": proof_audit.get("auditHash"),
        },
    )
    event_stream.emit("proof.completed", proof_audit)
    event_stream.emit("hooks.proof_after", proof_after_hooks)
    if proof_after_hooks.get("blocked"):
        proof_audit["runStatus"] = "blocked"
        proof_audit.setdefault("failures", []).append(
            "A blocking proof.after hook failed."
        )
    run_after_hooks = hook_runner.run(
        "run.after",
        {"runId": run_id, "status": proof_audit.get("runStatus")},
    )
    event_stream.emit("hooks.run_after", run_after_hooks)
    if run_after_hooks.get("blocked"):
        proof_audit["runStatus"] = "blocked"
        proof_audit.setdefault("failures", []).append(
            "A blocking run.after hook failed."
        )
    event_stream.emit(
        "run.finished",
        {
            "status": proof_audit.get("runStatus"),
            "proofStatus": proof_audit.get("status"),
        },
    )
    event_stream_verification = event_stream.verify()
    finished = datetime.now(timezone.utc)
    receipt = {
'''
    text = replace_once(text, proof_end_anchor, proof_after, "proof after hooks")
    hook_fields = '''        "hooks": {
            "catalog": hook_runner.catalog(),
            "runBefore": run_before_hooks,
            "planCompiled": plan_hooks,
            "proofBefore": proof_before_hooks,
            "proofAfter": proof_after_hooks,
            "runAfter": run_after_hooks,
        },
        "eventStream": event_stream_verification,
'''
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
