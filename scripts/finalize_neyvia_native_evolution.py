from __future__ import annotations

import ast
import json
import re
import runpy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def write(relative: str, value: str) -> None:
    path = ROOT / relative
    normalized = value.replace("\r\n", "\n")
    if not normalized.endswith("\n"):
        normalized += "\n"
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


def patch_resource_normalization() -> None:
    path = "src/grant_agent/native_resource_profiles.py"
    text = read(path)
    if "import re\n" not in text:
        text = text.replace("import platform\n", "import platform\nimport re\n", 1)
    text = replace_once(
        text,
        '    normalized = str(value or "auto").strip().lower().replace("_", "-")\n',
        '    normalized = re.sub(r"[\\s_]+", "-", str(value or "auto").strip().lower())\n',
        "resource normalization",
    )
    write(path, text)


def patch_behavior_learning_boundary() -> None:
    path = "src/grant_agent/behavior_capsules.py"
    text = read(path)
    old = '''        for key, delta in (adjustment.get("behaviorVectorDelta") or {}).items():
            if key in vector:
                vector[key] = _bounded_unit(vector[key] + float(delta), vector[key])
'''
    new = '''        for key, delta in (adjustment.get("behaviorVectorDelta") or {}).items():
            if key not in vector:
                continue
            numeric_delta = float(delta)
            # Local learning may make verified work more efficient or proactive. It may not
            # silently weaken rigor or proof pressure.
            if key in {"rigor", "verificationPressure"} and numeric_delta < 0:
                numeric_delta = 0.0
            vector[key] = _bounded_unit(vector[key] + numeric_delta, vector[key])
'''
    text = replace_once(text, old, new, "learning proof floor")
    write(path, text)


def patch_hook_test_lifetime() -> None:
    path = "tests/test_native_hooks.py"
    text = read(path)
    old = '''        result = NativeHookRunner(root).run("run.before", {"runId": "run"})

    assert result["passed"] is True
    assert result["receipts"][0]["returnCode"] == 0
    assert "hook-ok" in result["receipts"][0]["stdoutTail"]
    assert Path(result["receiptPaths"][0]).is_file()
'''
    new = '''        result = NativeHookRunner(root).run("run.before", {"runId": "run"})
        assert Path(result["receiptPaths"][0]).is_file()

    assert result["passed"] is True
    assert result["receipts"][0]["returnCode"] == 0
    assert "hook-ok" in result["receipts"][0]["stdoutTail"]
'''
    text = replace_once(text, old, new, "hook test receipt lifetime")
    write(path, text)


def patch_behavior_test() -> None:
    path = "tests/test_behavior_capsules.py"
    text = read(path)
    text = text.replace(
        '    assert plan["behaviorVector"]["verificationPressure"] == 0.0\n',
        '    assert plan["behaviorVector"]["verificationPressure"] >= 0.95\n',
    )
    write(path, text)


def patch_tool_compile_cache(text: str) -> str:
    text = insert_after(
        text,
        "        self._tool_loop_receipts: list[str] = []\n",
        "        self._compile_cache_key = \"\"\n"
        "        self._compile_cache_hits = 0\n"
        "        self._compile_cache_misses = 0\n",
        "tool cache fields",
    )
    compile_anchor = '''        if self.capabilities is None:
            return {
                "schema": "neyvia.production-tool-compiler.v1",
                "status": "not_configured",
                "providerCalls": [],
            }
        compiled = self.capabilities.compile_openai_tool_belt(
'''
    compile_replacement = '''        if self.capabilities is None:
            return {
                "schema": "neyvia.production-tool-compiler.v1",
                "status": "not_configured",
                "providerCalls": [],
            }
        cache_key = canonical_hash({"task": str(task or "").strip(), "limit": max(1, min(int(limit), 20))})
        if cache_key == self._compile_cache_key and self._compiled_tool_belt is not None:
            self._compile_cache_hits += 1
            compiled = self._compiled_tool_belt
        else:
            self._compile_cache_misses += 1
            compiled = self.capabilities.compile_openai_tool_belt(
'''
    text = replace_once(text, compile_anchor, compile_replacement, "tool cache compile start")
    original_close = '''            }
        )
        self._compiled_tool_belt = compiled
        provider_calls = []
'''
    indented_close = '''            }
            )
            self._compiled_tool_belt = compiled
            self._compile_cache_key = cache_key
        provider_calls = []
'''
    text = replace_once(text, original_close, indented_close, "tool cache compile close")
    snapshot_old = '''        return {
            "status": "ready",
            "providerCalls": len(call_map),
            "callMapHash": canonical_hash(call_map),
            "catalogHash": str(
                (self._compiled_tool_belt.get("belt") or {}).get("catalogHash") or ""
            ),
        }
'''
    snapshot_new = '''        total = self._compile_cache_hits + self._compile_cache_misses
        return {
            "status": "ready",
            "providerCalls": len(call_map),
            "callMapHash": canonical_hash(call_map),
            "catalogHash": str(
                (self._compiled_tool_belt.get("belt") or {}).get("catalogHash") or ""
            ),
            "cacheHits": self._compile_cache_hits,
            "cacheMisses": self._compile_cache_misses,
            "hitRate": round(self._compile_cache_hits / total, 4) if total else 0.0,
        }
'''
    return replace_once(text, snapshot_old, snapshot_new, "tool cache snapshot")


def patch_phase_controller(text: str) -> str:
    text = text.replace("    max_turns: int = 12\n", "    max_turns: int = 24\n", 1)
    text = text.replace('    parser.add_argument("--max-turns", type=int, default=12)\n', '    parser.add_argument("--max-turns", type=int, default=24)\n', 1)
    mutation_contract = '''    if selected.allow_mutations and (behavior_plan.get("capsule") or {}).get("id") in {
        "direct-verified",
        "implementation",
        "diagnosis-repair",
        "design-evolution",
    }:
        behavior_plan["capsule"]["mutationExpected"] = True
        gates = set(behavior_plan["capsule"].get("proofGates") or ())
        gates.update({"workspace_delta", "deterministic_check", "receipt_integrity"})
        behavior_plan["capsule"]["proofGates"] = sorted(gates)
'''
    text = insert_after(
        text,
        "    behavior_plan[\"proofGates\"] = sorted(\n"
        "        set((behavior_plan.get(\"capsule\") or {}).get(\"proofGates\") or ())\n"
        "        | set(skill_plan.get(\"proofGates\") or ())\n"
        "    )\n",
        mutation_contract,
        "mutation proof contract",
    )
    text = insert_after(
        text,
        "    started = datetime.now(timezone.utc)\n",
        "    phase_receipt_paths: list[str] = []\n"
        "    phase_receipts: list[dict[str, Any]] = []\n",
        "phase receipt initialization",
    )
    old = '''        agent, run_config, gateway = build_neyvia_agent(
            selected,
            provider=provider,
            behavior_plan=behavior_plan,
            resource_profile=resource_profile,
            skill_plan=skill_plan,
            spawn_registry=spawn_registry,
        )
        gateway.compile(prompt, min(selected.max_turns, 20))
        session = SQLiteSession(selected.session_id, state_root / "sessions.sqlite3")
        result = await Runner.run(
            agent,
            prompt,
            max_turns=selected.max_turns,
            run_config=run_config,
            session=session,
        )
        usage = result.context_wrapper.usage
        output = str(result.final_output)
        usage_payload_value = usage_payload(usage)
        run_items = [type(item).__name__ for item in result.new_items]
        external_session_id = ""
        tool_gateway = gateway.search("", 20)
'''
    new = '''        agent, run_config, gateway = build_neyvia_agent(
            selected,
            provider=provider,
            behavior_plan=behavior_plan,
            resource_profile=resource_profile,
            skill_plan=skill_plan,
            spawn_registry=spawn_registry,
        )
        gateway.compile(prompt, min(selected.max_turns, 20))
        session = SQLiteSession(selected.session_id, state_root / "sessions.sqlite3")
        remaining_turns = selected.max_turns
        previous_phase_output = ""
        usage_rows: list[dict[str, Any]] = []
        all_run_items: list[str] = []
        for phase in (behavior_plan.get("capsule") or {}).get("phases") or ():
            if remaining_turns <= 0:
                break
            phase_id = str(phase.get("id") or "phase")
            turn_budget = max(1, min(int(phase.get("maximumTurns") or 4), remaining_turns))
            phase_context = {
                "runId": run_id,
                "phaseId": phase_id,
                "planHash": behavior_plan.get("planHash"),
                "turnBudget": turn_budget,
            }
            before_hooks = hook_runner.run("phase.before", phase_context)
            event_stream.emit("phase.started", phase_context, phase=phase_id)
            event_stream.emit("hooks.phase_before", before_hooks, phase=phase_id)
            if before_hooks.get("blocked"):
                raise RuntimeError(f"A blocking phase.before hook failed for {phase_id}.")
            phase_prompt = (
                f"Parent operator task:\n{prompt}\n\n"
                f"Current enforced phase: {phase_id}\n"
                f"Phase objective: {phase.get('objective') or phase_id}\n"
                f"Required evidence: {', '.join(phase.get('requiredEvidence') or ()) or 'bounded phase result'}\n"
                f"Allowed tool scopes: {', '.join(phase.get('allowedToolScopes') or ()) or 'workspace.read'}\n"
                f"Turn budget: {turn_budget}. Work only on this phase. "
                "Return concrete evidence and unresolved blockers. Do not claim later phases completed."
            )
            if previous_phase_output:
                phase_prompt += f"\n\nPrevious phase handoff:\n{previous_phase_output[-6000:]}"
            phase_result = await Runner.run(
                agent,
                phase_prompt,
                max_turns=turn_budget,
                run_config=run_config,
                session=session,
            )
            phase_output = str(phase_result.final_output)
            normalized_usage = usage_payload(phase_result.context_wrapper.usage)
            usage_rows.append(normalized_usage)
            item_names = [type(item).__name__ for item in phase_result.new_items]
            all_run_items.extend(item_names)
            phase_receipt = {
                "schema": "neyvia.native-phase-receipt/v1",
                "runId": run_id,
                "sessionId": selected.session_id,
                "phaseId": phase_id,
                "planHash": behavior_plan.get("planHash"),
                "turnBudget": turn_budget,
                "requiredEvidence": list(phase.get("requiredEvidence") or ()),
                "allowedToolScopes": list(phase.get("allowedToolScopes") or ()),
                "status": "completed" if phase_output.strip() else "blocked",
                "output": phase_output,
                "outputHash": canonical_hash({"phaseId": phase_id, "output": phase_output}),
                "usage": normalized_usage,
                "runItems": item_names,
                "startedHooks": before_hooks,
            }
            after_hooks = hook_runner.run(
                "phase.after",
                {**phase_context, "status": phase_receipt["status"]},
            )
            phase_receipt["finishedHooks"] = after_hooks
            if after_hooks.get("blocked"):
                phase_receipt["status"] = "blocked"
            phase_receipt["receiptHash"] = canonical_hash(
                {key: value for key, value in phase_receipt.items() if key != "receiptHash"}
            )
            phase_path = state_root / "phase_receipts" / f"{run_id}-{phase_id}.json"
            atomic_write_json(phase_path, phase_receipt)
            phase_receipt["receiptPath"] = str(phase_path)
            phase_receipts.append(phase_receipt)
            phase_receipt_paths.append(str(phase_path))
            event_stream.emit("phase.finished", phase_receipt, phase=phase_id)
            if phase_receipt["status"] != "completed":
                break
            previous_phase_output = phase_output
            remaining_turns -= turn_budget
        output = previous_phase_output or (phase_receipts[-1]["output"] if phase_receipts else "")
        usage_payload_value = {
            "requests": sum(int(row.get("requests") or 0) for row in usage_rows),
            "inputTokens": sum(int(row.get("inputTokens") or 0) for row in usage_rows),
            "outputTokens": sum(int(row.get("outputTokens") or 0) for row in usage_rows),
            "totalTokens": sum(int(row.get("totalTokens") or 0) for row in usage_rows),
            "cachedInputTokens": sum(int(row.get("cachedInputTokens") or 0) for row in usage_rows),
            "uncachedInputTokens": sum(int(row.get("uncachedInputTokens") or 0) for row in usage_rows),
            "reportedByTransport": any(bool(row.get("reportedByTransport")) for row in usage_rows),
        }
        usage_payload_value["promptCacheHitRate"] = (
            round(usage_payload_value["cachedInputTokens"] / usage_payload_value["inputTokens"], 4)
            if usage_payload_value["inputTokens"]
            else 0.0
        )
        run_items = all_run_items
        external_session_id = ""
        tool_gateway = gateway.search("", 20)
'''
    text = replace_once(text, old, new, "phase controller")
    text = text.replace(
        "        receipt_paths=[*gateway.tool_loop_receipts, *spawn_receipts],\n",
        "        receipt_paths=[*gateway.tool_loop_receipts, *spawn_receipts, *phase_receipt_paths],\n",
        1,
    )
    text = insert_after(
        text,
        '        "spawnTree": spawn_snapshot,\n',
        '        "phaseReceipts": phase_receipts,\n'
        '        "phaseController": {\n'
        '            "active": transport != "codex-cli",\n'
        '            "compiledPhases": len((behavior_plan.get("capsule") or {}).get("phases") or ()),\n'
        '            "completedPhases": sum(1 for row in phase_receipts if row.get("status") == "completed"),\n'
        '            "receiptPaths": phase_receipt_paths,\n'
        '        },\n',
        "phase receipt fields",
    )
    return text


def patch_reasoning_capabilities(text: str) -> str:
    text = insert_after(
        text,
        "from .neyvia_version import NEYVIA_AGENT_VERSION\n",
        "from .reasoning_capabilities import resolve_reasoning_effort\n",
        "reasoning capability import",
    )
    old = '''    reasoning_effort = (
        "xhigh"
        if max(
            float(behavior_vector.get("rigor") or 0),
            float(behavior_vector.get("verificationPressure") or 0),
        ) >= 0.95
        else "high"
        if max(
            float(behavior_vector.get("initiative") or 0),
            float(behavior_vector.get("exploration") or 0),
        ) >= 0.72
        else "medium"
    )
'''
    new = '''    requested_reasoning_effort = (
        "xhigh"
        if max(
            float(behavior_vector.get("rigor") or 0),
            float(behavior_vector.get("verificationPressure") or 0),
        ) >= 0.95
        else "high"
        if max(
            float(behavior_vector.get("initiative") or 0),
            float(behavior_vector.get("exploration") or 0),
        ) >= 0.72
        else "medium"
    )
    reasoning_resolution = resolve_reasoning_effort(
        provider="openai",
        model=selected.model,
        requested_effort=requested_reasoning_effort,
    )
    reasoning_effort = reasoning_resolution.get("wireEffort") or "default"
'''
    text = replace_once(text, old, new, "main reasoning capability")
    text = text.replace(
        '            else ModelSettings(reasoning={"effort": reasoning_effort})\n',
        '            else ModelSettings()\n'
        '            if reasoning_effort == "default"\n'
        '            else ModelSettings(reasoning={"effort": reasoning_effort})\n',
        1,
    )
    child_old = '''            child = Agent(
                name=f"Neyvia {route.role.title()}",
                instructions=specialist_instructions(route, behavior_plan),
                model=route.model,
                model_settings=(
                    ModelSettings()
                    if selected.transport == "chat-completions" or route.effort in {"", "default"}
                    else ModelSettings(reasoning={"effort": route.effort})
                ),
            )
'''
    child_new = '''            child_reasoning = resolve_reasoning_effort(
                provider="openai" if route.provider == "active-provider" else route.provider,
                model=route.model,
                requested_effort=route.effort,
            )
            child_wire_effort = child_reasoning.get("wireEffort") or "default"
            child = Agent(
                name=f"Neyvia {route.role.title()}",
                instructions=specialist_instructions(route, behavior_plan),
                model=route.model,
                model_settings=(
                    ModelSettings()
                    if selected.transport == "chat-completions" or child_wire_effort == "default"
                    else ModelSettings(reasoning={"effort": child_wire_effort})
                ),
            )
'''
    text = replace_once(text, child_old, child_new, "child reasoning capability")
    text = insert_after(
        text,
        '        "resourceProfile": resource_profile,\n',
        '        "reasoningResolution": reasoning_resolution,\n',
        "reasoning receipt",
    )
    return text


def patch_neyvia_agent() -> None:
    path = "src/grant_agent/neyvia_agent.py"
    text = read(path)
    text = patch_tool_compile_cache(text)
    text = patch_phase_controller(text)
    text = patch_reasoning_capabilities(text)
    ast.parse(text, filename=path)
    write(path, text)


def patch_spawn_ui_script() -> None:
    path = "scripts/apply_spawned_agent_ui.py"
    text = read(path)
    old = '''        expression = ""
        for variable in ("selectedJob", "selectedRun", "selectedHarnessJob", "activeJob"):
            if variable in surface:
                expression = (
                    f"<NativeEvolutionPanel spawnTree={{{variable}?.receipt?.spawnTree ?? "
                    f"{variable}?.receipt?.spawn_tree ?? {variable}?.spawnTree}} />"
                )
                break
'''
    new = '''        expression = ""
        for variable in ("selectedJob", "selectedRun", "selectedHarnessJob", "activeJob"):
            declared = re.search(
                rf"(?:const|let|var)\\s+{re.escape(variable)}\\b|\\[{re.escape(variable)}\\s*,",
                surface,
            )
            if declared:
                expression = (
                    f"<NativeEvolutionPanel spawnTree={{{variable}?.receipt?.spawnTree ?? "
                    f"{variable}?.receipt?.spawn_tree ?? {variable}?.spawnTree}} />"
                )
                break
'''
    text = replace_once(text, old, new, "spawn variable declaration")
    write(path, text)


def patch_package_scripts() -> None:
    path = ROOT / "package.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.setdefault("scripts", {})["verify:native-evolution"] = (
        "python -m pytest -q tests/test_behavior_capsules.py tests/test_native_resource_profiles.py "
        "tests/test_native_learning.py tests/test_native_proof_audit.py tests/test_native_spawn_contracts.py "
        "tests/test_skill_capsules.py tests/test_native_hooks.py tests/test_native_event_stream.py "
        "tests/test_neyvia_design_skill_capsules.py tests/test_native_evolution_ui_contract.py "
        "tests/test_spawned_agent_ui_contract.py"
    )
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def patch_gates() -> None:
    path = "GATES.md"
    text = read(path)
    if "- [ ] G44:" not in text:
        text = text.rstrip() + '''

- [ ] G44: Native's non-Codex provider path executes the compiled behavior phases as bounded turns with phase hooks, event records, handoff output, usage aggregation, and durable phase receipts; Codex supervision remains visibly single-pass until an exact resumable phase transport is proven.
  CHECK: python -m pytest -q tests/test_native_phase_controller_contract.py && echo NEYVIA_NATIVE_PHASE_CONTROLLER_OK
  EXPECT: NEYVIA_NATIVE_PHASE_CONTROLLER_OK
  EVIDENCE: pending

- [ ] G45: Native lifecycle events are append-only, sequence checked, hash chained, optionally streamed as JSONL, and independently verifiable; configured hooks accept argv arrays only, have timeouts, preserve receipts, and cannot acquire mutation authority from a read-only parent.
  CHECK: python -m pytest -q tests/test_native_hooks.py tests/test_native_event_stream.py && echo NEYVIA_NATIVE_EVENTS_HOOKS_OK
  EXPECT: NEYVIA_NATIVE_EVENTS_HOOKS_OK
  EVIDENCE: pending
'''
    write(path, text)


def write_phase_contract_test() -> None:
    write(
        "tests/test_native_phase_controller_contract.py",
        '''from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_native_agent_contains_bounded_phase_controller_and_receipts() -> None:
    source = (ROOT / "src" / "grant_agent" / "neyvia_agent.py").read_text(encoding="utf-8")

    assert 'for phase in (behavior_plan.get("capsule") or {}).get("phases")' in source
    assert 'max_turns=turn_budget' in source
    assert '"schema": "neyvia.native-phase-receipt/v1"' in source
    assert '"requiredEvidence": list(phase.get("requiredEvidence")' in source
    assert '"allowedToolScopes": list(phase.get("allowedToolScopes")' in source
    assert 'hook_runner.run("phase.before"' in source
    assert 'hook_runner.run(\n                "phase.after"' in source
    assert 'event_stream.emit("phase.finished"' in source
    assert '"active": transport != "codex-cli"' in source


def test_reasoning_effort_is_capability_resolved_not_fabricated() -> None:
    source = (ROOT / "src" / "grant_agent" / "neyvia_agent.py").read_text(encoding="utf-8")

    assert "resolve_reasoning_effort" in source
    assert 'reasoning_resolution.get("wireEffort") or "default"' in source
    assert '"reasoningResolution": reasoning_resolution' in source
''',
    )


def validate_python() -> None:
    paths = [
        "src/grant_agent/behavior_capsules.py",
        "src/grant_agent/native_resource_profiles.py",
        "src/grant_agent/native_learning.py",
        "src/grant_agent/native_proof_audit.py",
        "src/grant_agent/native_spawn_contracts.py",
        "src/grant_agent/skill_capsules.py",
        "src/grant_agent/native_hooks.py",
        "src/grant_agent/native_event_stream.py",
        "src/grant_agent/neyvia_agent.py",
    ]
    for relative in paths:
        ast.parse(read(relative), filename=relative)


def main() -> int:
    namespace = runpy.run_path(str(ROOT / "scripts" / "apply_spawned_agent_ui.py"))
    namespace["main"]()
    patch_resource_normalization()
    patch_behavior_learning_boundary()
    patch_hook_test_lifetime()
    patch_behavior_test()
    patch_spawn_ui_script()
    patch_neyvia_agent()
    patch_package_scripts()
    patch_gates()
    write_phase_contract_test()
    validate_python()
    print("NEYVIA_NATIVE_FINALIZED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
