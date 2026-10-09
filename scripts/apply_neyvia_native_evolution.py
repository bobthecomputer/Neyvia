from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def write(relative: str, content: str) -> None:
    path = ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = content.replace("\r\n", "\n")
    if not normalized.endswith("\n"):
        normalized += "\n"
    if path.is_file() and path.read_text(encoding="utf-8").replace("\r\n", "\n") == normalized:
        return
    path.write_text(normalized, encoding="utf-8")


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


def patch_neyvia_agent() -> None:
    path = "src/grant_agent/neyvia_agent.py"
    text = read(path)
    text = replace_once(
        text,
        "from dataclasses import dataclass\n",
        "from dataclasses import dataclass, replace\n",
        "dataclass import",
    )
    imports = (
        "from .behavior_capsules import BehaviorCapsuleRegistry\n"
        "from .native_learning import NativeLearningStore, usage_payload\n"
        "from .native_proof_audit import NativeProofAuditor\n"
        "from .native_resource_profiles import resolve_resource_profile\n"
        "from .native_spawn_contracts import (\n"
        "    NativeSpawnRegistry,\n"
        "    build_specialist_routes,\n"
        "    specialist_instructions,\n"
        ")\n"
        "from .skill_capsules import SkillCapsuleRegistry\n"
    )
    text = insert_after(
        text,
        "from .ui_tools import default_ui_surface\n",
        imports,
        "native evolution imports",
    )
    config_fields = (
        "    resource_mode: str = \"auto\"\n"
        "    behavior_capsule: str = \"auto\"\n"
        "    specialist_routes_json: str = \"\"\n"
        "    learning_enabled: bool = True\n"
    )
    text = insert_after(
        text,
        "    enable_specialists: bool = True\n",
        config_fields,
        "config fields",
    )
    return_fields = (
        "            resource_mode=self.resource_mode.strip().lower() or \"auto\",\n"
        "            behavior_capsule=self.behavior_capsule.strip().lower() or \"auto\",\n"
        "            specialist_routes_json=self.specialist_routes_json.strip(),\n"
        "            learning_enabled=bool(self.learning_enabled),\n"
    )
    text = insert_after(
        text,
        "            enable_specialists=self.enable_specialists,\n",
        return_fields,
        "validated config fields",
    )

    old_signature = (
        "def build_neyvia_agent(\n"
        "    config: NeyviaAgentConfig,\n"
        "    *,\n"
        "    provider: OpenAIProvider,\n"
        ") -> tuple[Agent[Any], RunConfig, NeyviaToolGateway]:\n"
    )
    new_signature = (
        "def build_neyvia_agent(\n"
        "    config: NeyviaAgentConfig,\n"
        "    *,\n"
        "    provider: OpenAIProvider,\n"
        "    behavior_plan: dict[str, Any] | None = None,\n"
        "    resource_profile: dict[str, Any] | None = None,\n"
        "    skill_plan: dict[str, Any] | None = None,\n"
        "    spawn_registry: NativeSpawnRegistry | None = None,\n"
        ") -> tuple[Agent[Any], RunConfig, NeyviaToolGateway]:\n"
    )
    text = replace_once(text, old_signature, new_signature, "build signature")
    build_setup = (
        "    behavior_plan = dict(behavior_plan or {})\n"
        "    resource_profile = dict(resource_profile or {})\n"
        "    skill_plan = dict(skill_plan or {})\n"
        "    spawn_registry = spawn_registry or NativeSpawnRegistry(\n"
        "        selected.control_root or selected.root, selected.session_id\n"
        "    )\n"
        "    behavior_vector = behavior_plan.get(\"behaviorVector\") or {}\n"
        "    reasoning_effort = (\n"
        "        \"xhigh\"\n"
        "        if max(\n"
        "            float(behavior_vector.get(\"rigor\") or 0),\n"
        "            float(behavior_vector.get(\"verificationPressure\") or 0),\n"
        "        ) >= 0.95\n"
        "        else \"high\"\n"
        "        if max(\n"
        "            float(behavior_vector.get(\"initiative\") or 0),\n"
        "            float(behavior_vector.get(\"exploration\") or 0),\n"
        "        ) >= 0.72\n"
        "        else \"medium\"\n"
        "    )\n"
    )
    text = insert_after(
        text,
        "    selected = config.validated()\n",
        build_setup,
        "build evolution setup",
    )

    start = text.find("    if selected.enable_specialists:\n        planner = Agent(")
    end = text.find("    agent = Agent(\n", start)
    if start >= 0 and end > start:
        specialist_block = '''    specialist_routes = build_specialist_routes(
        selected.model,
        raw_overrides=selected.specialist_routes_json,
        behavior_plan=behavior_plan,
        resource_profile=resource_profile,
    )
    if selected.enable_specialists and specialist_routes:
        @function_tool(
            name_override="delegate_to_neyvia_specialist",
            description_override=(
                "Spawn one receipt-bound Neyvia specialist. Roles are selected by the compiled "
                "behavior capsule and each child has its own model, effort, turn budget, session, "
                "read/write authority, and durable receipt."
            ),
        )
        async def delegate_to_neyvia_specialist(role: str, task: str) -> str:
            normalized_role = str(role or "").strip().lower()
            route = specialist_routes.get(normalized_role)
            if route is None:
                return _json_tool_result(
                    {
                        "ok": False,
                        "status": "role_not_compiled",
                        "role": normalized_role,
                        "availableRoles": sorted(specialist_routes),
                    }
                )
            if route.allow_mutations and not selected.allow_mutations:
                return _json_tool_result(
                    {
                        "ok": False,
                        "status": "approval_required",
                        "role": normalized_role,
                        "message": "The compiled specialist may mutate, but this parent run is read-only.",
                    }
                )
            contract = spawn_registry.start(
                route,
                task,
                str(behavior_plan.get("planHash") or ""),
            )
            child = Agent(
                name=f"Neyvia {route.role.title()}",
                instructions=specialist_instructions(route, behavior_plan),
                model=route.model,
                model_settings=(
                    ModelSettings()
                    if selected.transport == "chat-completions" or route.effort in {"", "default"}
                    else ModelSettings(reasoning={"effort": route.effort})
                ),
            )
            child_session = SQLiteSession(
                contract["childSessionId"], spawn_registry.session_db_path
            )
            try:
                child_result = await Runner.run(
                    child,
                    task,
                    max_turns=route.maximum_turns,
                    run_config=run_config,
                    session=child_session,
                )
                child_usage = usage_payload(child_result.context_wrapper.usage)
                child_output = str(child_result.final_output)
                receipt = spawn_registry.finish(
                    contract,
                    status="completed" if child_output.strip() else "blocked",
                    output=child_output,
                    usage=child_usage,
                    run_items=[type(item).__name__ for item in child_result.new_items],
                    error="" if child_output.strip() else "Specialist returned no result.",
                )
            except Exception as exc:
                receipt = spawn_registry.finish(
                    contract,
                    status="failed",
                    error=f"{type(exc).__name__}: {exc}",
                )
            return _json_tool_result(receipt)

        tools.append(delegate_to_neyvia_specialist)
'''
        text = text[:start] + specialist_block + text[end:]
    elif "delegate_to_neyvia_specialist" not in text:
        raise RuntimeError("specialist block anchor not found")

    instructions_old = (
        "            \"Mutating calls require operator-approved run mode.\"\n"
        "        ),\n"
    )
    instructions_new = (
        "            \"Mutating calls require operator-approved run mode. \"\n"
        "            f\"Compiled behavior: {(behavior_plan.get('capsule') or {}).get('label') or 'bounded native'}; \"\n"
        "            f\"plan hash {behavior_plan.get('planHash') or 'unavailable'}. \"\n"
        "            f\"Executable skill plan {skill_plan.get('planHash') or 'unavailable'}; \"\n"
        "            \"instruction prose never replaces its tool scopes, evidence gates, or checks.\"\n"
        "        ),\n"
    )
    text = replace_once(text, instructions_old, instructions_new, "main instructions")
    old_settings = (
        "            ModelSettings()\n"
        "            if selected.transport == \"chat-completions\"\n"
        "            else ModelSettings(reasoning={\"effort\": \"high\"})\n"
    )
    new_settings = (
        "            ModelSettings()\n"
        "            if selected.transport == \"chat-completions\"\n"
        "            else ModelSettings(reasoning={\"effort\": reasoning_effort})\n"
    )
    text = replace_once(text, old_settings, new_settings, "main reasoning effort")

    old_codex_signature = (
        "def _run_codex_supervised(\n"
        "    config: NeyviaAgentConfig,\n"
        "    prompt: str,\n"
        "    gateway: NeyviaToolGateway,\n"
        ") -> dict[str, Any]:\n"
    )
    new_codex_signature = (
        "def _run_codex_supervised(\n"
        "    config: NeyviaAgentConfig,\n"
        "    prompt: str,\n"
        "    gateway: NeyviaToolGateway,\n"
        "    behavior_plan: dict[str, Any] | None = None,\n"
        "    skill_plan: dict[str, Any] | None = None,\n"
        ") -> dict[str, Any]:\n"
    )
    text = replace_once(text, old_codex_signature, new_codex_signature, "codex signature")
    codex_context = (
        "    behavior_plan = dict(behavior_plan or {})\n"
        "    skill_plan = dict(skill_plan or {})\n"
    )
    text = insert_after(
        text,
        "    command = _codex_cli_command()\n",
        codex_context,
        "codex behavior setup",
    )
    text = replace_once(
        text,
        "        f\"Finish within {config.max_turns} model turns. \"\n",
        "        f\"Finish within {config.max_turns} model turns. \"\n"
        "        f\"Compiled behavior capsule: {(behavior_plan.get('capsule') or {}).get('label') or 'bounded native'}; \"\n"
        "        f\"plan hash {behavior_plan.get('planHash') or 'unavailable'}. \"\n"
        "        f\"Executable skill plan: {skill_plan.get('planHash') or 'unavailable'}. \"\n",
        "codex prompt contract",
    )

    run_anchor = (
        "    control_root = selected.control_root or selected.root\n"
        "    state_root = control_root / \".agent_control\" / \"neyvia_agent\"\n"
    )
    run_setup = '''    resource_profile = resolve_resource_profile(selected.resource_mode)
    behavior_registry = BehaviorCapsuleRegistry(control_root)
    selected_capsule = behavior_registry.select(prompt, selected.behavior_capsule)
    learning_store = NativeLearningStore(control_root)
    learned_adjustment = (
        learning_store.behavior_adjustment(
            selected_capsule.task_kinds[0] if selected_capsule.task_kinds else "general"
        )
        if selected.learning_enabled
        else {"applied": False, "evidenceRuns": 0, "behaviorVectorDelta": {}, "reason": "Learning disabled for this run."}
    )
    behavior_plan = behavior_registry.compile(
        prompt,
        preferred=selected.behavior_capsule,
        resource_profile=resource_profile,
        learned_adjustment=learned_adjustment,
    )
    skill_plan = SkillCapsuleRegistry(control_root).compile(
        (behavior_plan.get("capsule") or {}).get("skillIds") or ()
    )
    for key, delta in (skill_plan.get("behaviorVectorDelta") or {}).items():
        if key in behavior_plan.get("behaviorVector", {}):
            behavior_plan["behaviorVector"][key] = round(
                max(0.0, min(1.0, float(behavior_plan["behaviorVector"][key]) + float(delta))),
                4,
            )
    behavior_plan["skillRuntime"] = skill_plan
    behavior_plan["proofGates"] = sorted(
        set((behavior_plan.get("capsule") or {}).get("proofGates") or ())
        | set(skill_plan.get("proofGates") or ())
    )
    selected = replace(
        selected,
        max_turns=max(1, min(selected.max_turns, int(behavior_plan.get("maximumTurns") or selected.max_turns))),
    )
    spawn_registry = NativeSpawnRegistry(control_root, selected.session_id)
    proof_auditor = NativeProofAuditor(selected.root)
    before_workspace = proof_auditor.snapshot()
'''
    text = insert_after(text, run_anchor, run_setup, "run behavior setup")
    text = replace_once(
        text,
        "            gateway,\n        )\n",
        "            gateway,\n            behavior_plan,\n            skill_plan,\n        )\n",
        "codex invocation",
    )
    old_build_call = "        agent, run_config, gateway = build_neyvia_agent(selected, provider=provider)\n"
    new_build_call = (
        "        agent, run_config, gateway = build_neyvia_agent(\n"
        "            selected,\n"
        "            provider=provider,\n"
        "            behavior_plan=behavior_plan,\n"
        "            resource_profile=resource_profile,\n"
        "            skill_plan=skill_plan,\n"
        "            spawn_registry=spawn_registry,\n"
        "        )\n"
    )
    text = replace_once(text, old_build_call, new_build_call, "build invocation")
    old_usage = '''        usage_payload = {
            "requests": usage.requests,
            "inputTokens": usage.input_tokens,
            "outputTokens": usage.output_tokens,
            "totalTokens": usage.total_tokens,
            "reportedByTransport": True,
        }
'''
    text = replace_once(text, old_usage, "        usage_payload_value = usage_payload(usage)\n", "usage normalization")
    # Avoid shadowing the imported function while retaining the receipt key name.
    text = text.replace('"usage": usage_payload,', '"usage": usage_payload_value,')
    codex_usage = '''        usage_payload = {
            "requests": 1,
            "inputTokens": 0,
            "outputTokens": 0,
            "totalTokens": 0,
            "reportedByTransport": False,
        }
'''
    codex_usage_new = '''        usage_payload_value = {
            "requests": 1,
            "inputTokens": 0,
            "outputTokens": 0,
            "totalTokens": 0,
            "cachedInputTokens": 0,
            "uncachedInputTokens": 0,
            "promptCacheHitRate": 0.0,
            "reportedByTransport": False,
        }
'''
    text = replace_once(text, codex_usage, codex_usage_new, "codex usage")

    finish_anchor = "    finished = datetime.now(timezone.utc)\n    receipt = {\n"
    proof_setup = '''    spawn_snapshot = spawn_registry.snapshot()
    spawn_receipts = [
        str(item.get("receipt_path") or "")
        for item in spawn_snapshot.get("children") or []
        if str(item.get("receipt_path") or "")
    ]
    proof_audit = proof_auditor.audit(
        before=before_workspace,
        behavior_plan={
            **behavior_plan,
            "capsule": {
                **(behavior_plan.get("capsule") or {}),
                "proofGates": behavior_plan.get("proofGates") or (behavior_plan.get("capsule") or {}).get("proofGates") or [],
            },
        },
        allow_mutations=selected.allow_mutations,
        receipt_paths=[*gateway.tool_loop_receipts, *spawn_receipts],
    )
    finished = datetime.now(timezone.utc)
    run_id = f"neyvia_{uuid.uuid4().hex}"
    receipt = {
'''
    text = replace_once(text, finish_anchor, proof_setup, "proof setup")
    text = replace_once(
        text,
        '        "runId": f"neyvia_{uuid.uuid4().hex}",\n',
        '        "runId": run_id,\n',
        "stable run id",
    )
    text = replace_once(
        text,
        '        "status": "completed",\n',
        '        "status": proof_audit["runStatus"],\n',
        "proof status authority",
    )
    receipt_fields = (
        '        "behaviorPlan": behavior_plan,\n'
        '        "resourceProfile": resource_profile,\n'
        '        "skillRuntime": skill_plan,\n'
        '        "spawnTree": spawn_snapshot,\n'
        '        "proofAudit": proof_audit,\n'
        '        "optimizationTelemetry": {\n'
        '            "behaviorCompilerCache": behavior_registry.cache_snapshot(),\n'
        '            "promptCacheHitRate": usage_payload_value.get("promptCacheHitRate", 0.0),\n'
        '            "cachedInputTokens": usage_payload_value.get("cachedInputTokens", 0),\n'
        '            "backstage": True,\n'
        '        },\n'
    )
    text = insert_after(
        text,
        '        "toolLoopReceipts": gateway.tool_loop_receipts,\n',
        receipt_fields,
        "receipt evolution fields",
    )
    old_write = '''    receipt_path = state_root / "receipts" / f"{receipt['runId']}.json"
    atomic_write_json(receipt_path, receipt)
    return {**receipt, "receiptPath": str(receipt_path)}
'''
    new_write = '''    receipt_path = state_root / "receipts" / f"{receipt['runId']}.json"
    atomic_write_json(receipt_path, receipt)
    learning_snapshot = (
        learning_store.record_run({**receipt, "receiptPath": str(receipt_path)}, str(receipt_path))
        if selected.learning_enabled
        else {}
    )
    receipt["learning"] = {
        "run": learning_snapshot,
        "summary": learning_store.summary() if selected.learning_enabled else {},
        "truthBoundary": "Only real receipts and explicit feedback influence Native learning.",
    }
    atomic_write_json(receipt_path, receipt)
    return {**receipt, "receiptPath": str(receipt_path)}
'''
    text = replace_once(text, old_write, new_write, "learning write")

    cli_args_anchor = '    parser.add_argument("--no-specialists", action="store_true")\n'
    cli_args = (
        '    parser.add_argument("--resource-mode", choices=["auto", "eco", "balanced", "maximal", "memory-rich"], default="auto")\n'
        '    parser.add_argument("--behavior-capsule", default="auto")\n'
        '    parser.add_argument("--specialist-routes-json", default="")\n'
        '    parser.add_argument("--no-learning", action="store_true")\n'
    )
    text = insert_after(text, cli_args_anchor, cli_args, "cli native controls")
    construction_anchor = "                enable_specialists=not args.no_specialists,\n"
    construction_fields = (
        "                resource_mode=args.resource_mode,\n"
        "                behavior_capsule=args.behavior_capsule,\n"
        "                specialist_routes_json=args.specialist_routes_json,\n"
        "                learning_enabled=not args.no_learning,\n"
    )
    text = insert_after(text, construction_anchor, construction_fields, "cli construction")
    write(path, text)


def patch_harness_surface() -> None:
    path = "web/src/neyvia/HarnessesSurface.jsx"
    text = read(path)
    import_line = 'import NativeEvolutionPanel from "./NativeEvolutionPanel";\n'
    if import_line not in text:
        matches = list(re.finditer(r"^import .*?;\n", text, flags=re.MULTILINE))
        if not matches:
            raise RuntimeError("HarnessesSurface import block not found")
        position = matches[-1].end()
        text = text[:position] + import_line + text[position:]
    if "<NativeEvolutionPanel />" not in text:
        function_match = re.search(r"(?:export\s+default\s+|export\s+)?function\s+HarnessesSurface\b", text)
        if function_match is None:
            # Some builds export a const arrow function.
            function_match = re.search(r"(?:export\s+)?const\s+HarnessesSurface\b", text)
        if function_match is None:
            raise RuntimeError("HarnessesSurface component not found")
        return_index = text.find("return (", function_match.end())
        if return_index < 0:
            raise RuntimeError("HarnessesSurface return not found")
        opening_end = text.find(">", return_index)
        if opening_end < 0:
            raise RuntimeError("HarnessesSurface root opening tag not found")
        text = text[: opening_end + 1] + "\n      <NativeEvolutionPanel />" + text[opening_end + 1 :]
    write(path, text)


def patch_package() -> None:
    path = ROOT / "package.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.setdefault("bin", {})["neyvia"] = "scripts/neyvia-cli.mjs"
    payload["bin"].setdefault("fluxio", "scripts/fluxio-cli.mjs")
    scripts = payload.setdefault("scripts", {})
    scripts["neyvia"] = "python scripts/launch_neyvia.py"
    scripts.setdefault("fluxio", "python scripts/launch_fluxio.py")
    scripts["neyvia:doctor"] = "python scripts/neyvia_doctor.py --json"
    scripts["verify:native-evolution"] = (
        "python -m pytest -q tests/test_behavior_capsules.py tests/test_native_resource_profiles.py "
        "tests/test_native_learning.py tests/test_native_proof_audit.py tests/test_native_spawn_contracts.py"
    )
    files = payload.setdefault("files", [])
    for relative in (
        "scripts/neyvia-cli.mjs",
        "scripts/launch_neyvia.py",
        "scripts/neyvia_doctor.py",
    ):
        if relative not in files:
            files.append(relative)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def patch_agents() -> None:
    path = "AGENTS.md"
    text = read(path)
    section = '''
## Neyvia executable behavior and skill contracts

For substantial Native work, human-readable skills are only one layer. Compile the task
through `BehaviorCapsuleRegistry` and `SkillCapsuleRegistry` so phases, specialist roles,
tool scopes, resource budgets, proof gates, and stop conditions are durable and hash bound.

- Never claim that a behavior capsule changes hidden model activations. Neyvia's Behavior
  Space is an executable policy vector around the model.
- Spawned specialists require a child session, route, turn budget, authority boundary, and
  receipt. A pleasant child answer is not equivalent to verified work.
- Native learning may use only real run receipts and explicit operator feedback. Below the
  configured evidence floor, report that the system is still observing.
- Keep cache, token, latency, and optimization telemetry backstage unless a signal requires
  operator attention.
- Resource mode may reduce context, tools, specialists, and concurrency, but must never
  remove the verification reserve or silently weaken a required proof gate.
'''
    if "## Neyvia executable behavior and skill contracts" not in text:
        text = text.rstrip() + "\n\n" + section.strip() + "\n"
    write(path, text)


def patch_gates() -> None:
    path = "GATES.md"
    text = read(path)
    gates = '''

- [ ] G37: Neyvia Native compiles every substantial task into a versioned behavior capsule with a bounded behavior vector, phases, tool scopes, specialist roles, proof gates, resource profile, and immutable plan hash.
  CHECK: python -m pytest -q tests/test_behavior_capsules.py tests/test_native_resource_profiles.py && echo NEYVIA_BEHAVIOR_SPACE_OK
  EXPECT: NEYVIA_BEHAVIOR_SPACE_OK
  EVIDENCE: pending

- [ ] G38: Spawned Native specialists use explicit child sessions, role-specific model/effort/turn contracts, read/write authority, durable lineage, and completion or failure receipts; the UI never infers child success from the parent prose.
  CHECK: python -m pytest -q tests/test_native_spawn_contracts.py tests/test_neyvia_agent.py && echo NEYVIA_SPAWN_CONTRACT_OK
  EXPECT: NEYVIA_SPAWN_CONTRACT_OK
  EVIDENCE: pending

- [ ] G39: Native completion is bound to a fresh final-workspace fingerprint, readable child/tool receipts, expected workspace delta, and a bounded deterministic check when the behavior contract requires one.
  CHECK: python -m pytest -q tests/test_native_proof_audit.py && echo NEYVIA_NATIVE_PROOF_AUTHORITY_OK
  EXPECT: NEYVIA_NATIVE_PROOF_AUTHORITY_OK
  EVIDENCE: pending

- [ ] G40: Native learning records only real receipts and explicit feedback, exposes prompt/tool cache statistics backstage, and applies no recommendation before its minimum sample and conservative success-bound gates pass.
  CHECK: python -m pytest -q tests/test_native_learning.py && echo NEYVIA_NATIVE_TRUTHFUL_LEARNING_OK
  EXPECT: NEYVIA_NATIVE_TRUTHFUL_LEARNING_OK
  EVIDENCE: pending

- [ ] G41: Human-readable skills may compile into executable skill capsules with instruction hashes, behavior deltas, phase bindings, tool scopes, checks, and proof gates; missing instruction files remain visible rather than simulated.
  CHECK: python -m pytest -q tests/test_skill_capsules.py && echo NEYVIA_EXECUTABLE_SKILLS_OK
  EXPECT: NEYVIA_EXECUTABLE_SKILLS_OK
  EVIDENCE: pending

- [ ] G42: Harness Control presents the Native observe/compile/execute/prove/learn model and truthful computer, phone, and NAS setup paths in one responsive, reduced-motion-safe tonal surface without promoting optimization telemetry into primary chrome.
  CHECK: python -m pytest -q tests/test_native_evolution_ui_contract.py && npm run frontend:build && echo NEYVIA_NATIVE_EVOLUTION_UI_OK
  EXPECT: NEYVIA_NATIVE_EVOLUTION_UI_OK
  EVIDENCE: pending

- [ ] G43: The exact branch candidate passes focused tests, full frontend build, connected desktop/compact journeys, screenshot review, secret scan, and one immutable proof manifest before review or promotion.
  EVIDENCE: pending
'''
    if "- [ ] G37:" not in text:
        text = text.rstrip() + gates
    write(path, text)


def write_launchers_and_doctor() -> None:
    write(
        "scripts/neyvia-cli.mjs",
        '''#!/usr/bin/env node
import { spawn } from "node:child_process";
import process from "node:process";

const python = process.env.PYTHON || process.env.PYTHON3 || "python";
const child = spawn(python, ["scripts/launch_neyvia.py", ...process.argv.slice(2)], {
  cwd: process.cwd(),
  env: process.env,
  stdio: "inherit",
  shell: false,
});
child.on("exit", (code, signal) => {
  if (signal) process.kill(process.pid, signal);
  process.exit(code ?? 1);
});
''',
    )
    write(
        "scripts/launch_neyvia.py",
        '''"""Canonical Neyvia launcher; legacy Fluxio launchers remain compatibility wrappers."""
from __future__ import annotations

import runpy
from pathlib import Path


if __name__ == "__main__":
    legacy = Path(__file__).with_name("launch_fluxio.py")
    if not legacy.is_file():
        raise SystemExit("Neyvia launcher backend is missing.")
    runpy.run_path(str(legacy), run_name="__main__")
''',
    )
    write(
        "scripts/neyvia_doctor.py",
        '''from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import sys
from pathlib import Path

from grant_agent.native_resource_profiles import resolve_resource_profile


def check(root: Path) -> dict:
    root = root.resolve()
    state = root / ".agent_control"
    state.mkdir(parents=True, exist_ok=True)
    probes = {
        "python": {"ready": sys.version_info >= (3, 11), "detail": sys.version.split()[0]},
        "node": {"ready": bool(shutil.which("node")), "detail": shutil.which("node") or "not found"},
        "npm": {"ready": bool(shutil.which("npm")), "detail": shutil.which("npm") or "not found"},
        "git": {"ready": bool(shutil.which("git")), "detail": shutil.which("git") or "not found"},
        "workspace": {"ready": root.is_dir(), "detail": str(root)},
        "stateWritable": {"ready": os.access(state, os.W_OK), "detail": str(state)},
    }
    return {
        "schema": "neyvia.doctor/v1",
        "ready": all(item["ready"] for item in probes.values()),
        "host": socket.gethostname(),
        "resourceProfile": resolve_resource_profile("auto"),
        "probes": probes,
        "next": "npm run neyvia" if all(item["ready"] for item in probes.values()) else "Resolve the failed probes, then rerun npm run neyvia:doctor.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check this computer for a local Neyvia launch.")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = check(args.root)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("Neyvia doctor:", "ready" if result["ready"] else "needs attention")
        for name, row in result["probes"].items():
            print(f"  {'OK' if row['ready'] else 'NO'} {name}: {row['detail']}")
        print(result["next"])
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
''',
    )


def write_docs() -> None:
    write(
        "docs/NEYVIA_NATIVE_BEHAVIOR_SPACE.md",
        '''# Neyvia Native Behavior Space

Neyvia Native now separates three layers:

1. **Human guidance** — readable skill instructions and user preferences.
2. **Executable behavior** — a versioned capsule containing phases, resource budgets,
   specialist roles, tool scopes, proof gates, stop conditions, and a bounded behavior vector.
3. **Evidence authority** — child/tool receipts, final-workspace fingerprinting, and a
   deterministic verification command when the task contract requires one.

The seven behavior dimensions are initiative, rigor, exploration, tool autonomy,
compression, interruption sensitivity, and verification pressure. They are runtime policy
around the provider model. Neyvia does not claim to edit or observe hidden model activations.

This architecture is inspired by the useful goal behind behavior-space research: represent
capability and working style more structurally than a single prompt. The implementation is
Neyvia-specific and deliberately falsifiable. Every compiled plan has a stable hash and the
receipt says which portion was instruction, which portion was enforced, and which evidence
actually passed.

## Truthful learning

Learning begins observationally. A route or capsule must accumulate real run receipts before
it becomes eligible for recommendation. Verified success is measured conservatively with a
Wilson lower bound; explicit operator value may break ties but cannot convert a failed proof
into a success. Cache and token statistics remain diagnostics, not product theater.

## Resource modes

- `eco`: low memory, one specialist, narrow catalog, verification reserve preserved.
- `balanced`: portable default.
- `maximal`: deeper bounded execution and more parallel specialist capacity.
- `memory-rich`: retain more local context/cache on large-memory hosts.
- `auto`: select from detected physical memory, with the selected mode recorded.
''',
    )
    write(
        "docs/NEYVIA_CONNECT_COMPUTER_PHONE_NAS.md",
        '''# Connect Neyvia on computer, phone, and NAS

## Computer

```bash
npm install
npm run neyvia:doctor
npm run neyvia
```

The doctor reports concrete missing prerequisites. It does not treat command discovery as
provider authentication.

## Phone

```bash
npm run web:serve
```

Publish the existing PWA behind HTTPS, open the authenticated route on the phone, then choose
**Add Neyvia**. The browser receives mission state and proof, not copied provider credentials.

## NAS

```bash
python scripts/nas_setup.py --account-user paul --display-name "Paul"
npm run web:backend
```

Connect a worker only after the backend and account state are healthy. Candidate promotion
must preserve hashes and rollback information; copying a mutable workspace directly into
`current` is not a release proof.

## Resource profile

Native accepts `--resource-mode auto|eco|balanced|maximal|memory-rich`. Resource reductions
may limit context, catalog breadth, specialists, or concurrency. They may not silently remove
proof gates.
''',
    )


def main() -> int:
    patch_neyvia_agent()
    patch_harness_surface()
    patch_package()
    patch_agents()
    patch_gates()
    write_launchers_and_doctor()
    write_docs()
    print("NEYVIA_NATIVE_EVOLUTION_APPLIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
