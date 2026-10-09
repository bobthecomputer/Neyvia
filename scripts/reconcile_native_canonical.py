from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def write(relative: str, content: str) -> None:
    target = ROOT / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content.rstrip() + "\n", encoding="utf-8")


def patch_native_run_identity() -> None:
    relative = "src/grant_agent/neyvia_agent.py"
    text = read(relative)
    start = text.index("async def run_neyvia_agent(")
    control = text.index("    control_root = selected.control_root or selected.root\n", start)
    stream = text.index("    event_stream = NativeEventStream(", control)
    run_line = '    run_id = f"neyvia_{uuid.uuid4().hex}"\n'
    before_stream = text[control:stream]
    if run_line not in before_stream:
        insertion = control + len("    control_root = selected.control_root or selected.root\n")
        text = text[:insertion] + run_line + text[insertion:]
        stream = text.index("    event_stream = NativeEventStream(", start)
    # A run has one immutable identity across event stream, specialists, hooks,
    # checkpoints, proof audit, learning and final receipt.
    head, tail = text[:stream], text[stream:]
    tail = tail.replace(run_line, "")
    text = head + tail
    text = re.sub(
        r'("runId"\s*:\s*)f"neyvia_\{uuid\.uuid4\(\)\.hex\}"',
        r"\1run_id",
        text,
    )
    write(relative, text)


def patch_harness_control_render() -> None:
    relative = "web/src/neyvia/HarnessesSurface.jsx"
    text = read(relative)
    import_line = 'import NativeEvolutionPanel from "./NativeEvolutionPanel";'
    if import_line not in text:
        last_import = max(match.end() for match in re.finditer(r"^import .*?;\s*$", text, re.M))
        text = text[:last_import] + "\n" + import_line + text[last_import:]
    text = text.replace("<NativeEvolutionPanel />", "")
    main_return = text.rfind("\n  return (")
    if main_return < 0:
        raise RuntimeError("Harness Control main return was not found.")
    section = text.find("<section", main_return)
    section_close = text.find(">", section)
    if section < 0 or section_close < 0:
        raise RuntimeError("Harness Control root section was not found.")
    text = text[: section_close + 1] + "\n      <NativeEvolutionPanel />" + text[section_close + 1 :]
    write(relative, text)


def patch_hook_test_scope() -> None:
    relative = "tests/test_native_hooks.py"
    text = read(relative)
    lines = [
        line
        for line in text.splitlines()
        if 'assert Path(result["receiptPaths"][0]).is_file()' not in line
    ]
    output: list[str] = []
    in_call = False
    balance = 0
    indent = ""
    inserted = False
    for line in lines:
        output.append(line)
        if not inserted and "result = NativeHookRunner(root).run(" in line:
            in_call = True
            indent = line[: len(line) - len(line.lstrip())]
            balance = line.count("(") - line.count(")")
            if balance <= 0:
                output.append(indent + 'assert Path(result["receiptPaths"][0]).is_file()')
                inserted = True
                in_call = False
            continue
        if in_call:
            balance += line.count("(") - line.count(")")
            if balance <= 0:
                output.append(indent + 'assert Path(result["receiptPaths"][0]).is_file()')
                inserted = True
                in_call = False
    if not inserted:
        raise RuntimeError("Native hook execution test was not found.")
    write(relative, "\n".join(output))


def patch_dynamic_specialist_contract() -> None:
    relative = "tests/test_neyvia_agent.py"
    text = read(relative)
    text = text.replace(
        '                "delegate_to_neyvia_planner",\n'
        '                "delegate_to_neyvia_verifier",',
        '                "delegate_to_neyvia_specialist",',
    )
    text = text.replace(
        '["delegate_to_neyvia_planner", "delegate_to_neyvia_verifier"]',
        '["delegate_to_neyvia_specialist"]',
    )
    write(relative, text)


def strengthen_ui_contract() -> None:
    relative = "tests/test_native_evolution_ui_contract.py"
    text = read(relative)
    if "test_native_panel_is_rendered_once_in_harness_control" not in text:
        text += """


def test_native_panel_is_rendered_once_in_harness_control() -> None:
    surface = (ROOT / "web" / "src" / "neyvia" / "HarnessesSurface.jsx").read_text(encoding="utf-8")
    assert surface.count("<NativeEvolutionPanel />") == 1
    assert surface.rfind("<NativeEvolutionPanel />") > surface.rfind("return (")
"""
    write(relative, text)


def write_single_fabric_contract() -> None:
    content = '''from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_native_runtime_composes_one_execution_fabric() -> None:
    source = (ROOT / "src" / "grant_agent" / "neyvia_agent.py").read_text(encoding="utf-8")
    required = (
        "behavior_capsules",
        "native_resource_profiles",
        "skill_capsules",
        "native_spawn_contracts",
        "native_spawn_evaluator",
        "native_proof_audit",
        "native_learning",
        "native_event_stream",
        "native_hooks",
        "native_checkpoints",
        "native_goals",
    )
    for module in required:
        assert module in source, f"{module} is not connected to Neyvia Native"
    assert "delegate_to_neyvia_specialist" in source
    assert "run_id = f\"neyvia_{uuid.uuid4().hex}\"" in source


def test_native_ui_projects_the_real_fabric() -> None:
    harness = (ROOT / "web" / "src" / "neyvia" / "HarnessesSurface.jsx").read_text(encoding="utf-8")
    panel = (ROOT / "web" / "src" / "neyvia" / "NativeEvolutionPanel.jsx").read_text(encoding="utf-8")
    lineage = (ROOT / "web" / "src" / "neyvia" / "SpawnedAgentLineage.jsx").read_text(encoding="utf-8")
    assert harness.count("<NativeEvolutionPanel />") == 1
    assert "preview-control" not in panel.lower()
    assert "receipt" in panel.lower()
    assert "receipt" in lineage.lower()
    assert "model" in lineage.lower()


def test_self_mutating_native_generators_are_not_product_architecture() -> None:
    obsolete = (
        "apply_neyvia_native_evolution.py",
        "apply_neyvia_native_runtime_hooks.py",
        "apply_neyvia_native_runtime_hooks_v2.py",
        "apply_spawned_agent_ui.py",
        "finalize_neyvia_native_evolution.py",
        "finalize_neyvia_native_evolution_v2.py",
        "finalize_neyvia_native_evolution_v3.py",
        "apply_neyvia_native_breakthrough.py",
    )
    for name in obsolete:
        assert not (ROOT / "scripts" / name).exists(), f"obsolete generator remains: {name}"
'''
    write("tests/test_native_single_fabric_contract.py", content)


def write_architecture_doc() -> None:
    content = '''# Neyvia Native Execution Fabric

Neyvia Native is one product runtime, not a collection of sidecars. Every run compiles
one authoritative execution contract and every user surface projects the resulting
receipt and event ledger.

## One compiled contract

A Native run binds together:

- task and domain contract;
- behavior capsule and cognitive workspace;
- resource profile, including Eco, Balanced, Performance and Memory-rich operation;
- executable skill capsules and phase gates;
- dynamic receipt-bound specialist topology;
- task-scoped tool capability boundary;
- session lineage, goals, hooks and reversible workspace checkpoints;
- deterministic proof obligations;
- proof-bound learning eligibility;
- device and execution target.

The model may propose work. Neyvia owns authority, execution boundaries, receipts and
completion state.

## Features absorbed from the harness ecosystem

Neyvia Native incorporates the useful mechanics rather than wrapping their branding:

- Codex: resumable headless work, MCP/skills interoperability and supervised subscription transport;
- Claude Code: lifecycle hooks, explicit permission boundaries and specialist delegation;
- Grok Build: isolated worktree thinking, streaming events, custom model routes and plugin concepts;
- Kimi Code: routine/deep task lanes;
- OpenCode: provider neutrality and semantic tonal presentation;
- Cursor: workspace rules and approachable agent sessions;
- Prime Agent: durable goals, heartbeats, schedules and recursive delegation concepts;
- Pi: compact tool exposure, strict RPC and tree-structured sessions;
- DeepSeek Harness / J-Space research: append-only traces, selective cognitive modules,
  seam/stall detection, behavior capsules and falsification loops;
- GPTMe and related systems: transparent tool activity and recoverable session state.

External harnesses remain available through Neyvia Hybrid when their own runtime is the
right execution engine. Native does not pretend an external CLI is an internal provider.

## Proof and learning

Completion is proof-bound. For mutating work, Neyvia fingerprints the bounded workspace,
executes an independently selected test/build oracle, validates tool/hook/checkpoint/skill
receipts and blocks narrative success when evidence is missing or failed.

Learning is append-only and conservative. A run may influence future routing only when its
proof is valid and its human value is known. Human feedback cannot override a failed proof.

## UI projection

Chat, Agent Live, Harness Control, desktop, phone and NAS use the same contract and event
ledger. Routine cache/token/latency statistics stay under Evidence & diagnostics. The
foreground emphasizes current work, exact route, authority, progress, blocker, proof and
next action.
'''
    write("docs/NEYVIA_NATIVE_EXECUTION_FABRIC.md", content)


def write_stable_ci() -> None:
    content = '''name: Neyvia Native CI

on:
  push:
    branches: [main, codex/neyvia-native-hybrid-evolution-20260826]
  pull_request:

permissions:
  contents: read

concurrency:
  group: neyvia-native-ci-${{ github.ref }}
  cancel-in-progress: true

jobs:
  verify:
    runs-on: ubuntu-latest
    timeout-minutes: 50
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - uses: actions/setup-node@v4
        with:
          node-version: "22"
          cache: npm
      - name: Install
        run: |
          python -m pip install --upgrade pip
          python -m pip install -e . pytest
          npm ci
      - name: Verify Native execution fabric
        run: |
          python -m compileall -q src scripts tests
          python -m pytest -q tests/test_native_single_fabric_contract.py tests/test_neyvia_agent.py tests/test_native_proof_audit.py tests/test_native_learning.py tests/test_native_spawn_contracts.py tests/test_native_spawn_evaluator.py tests/test_skill_capsules.py tests/test_native_hooks.py tests/test_native_event_stream.py tests/test_native_checkpoints.py tests/test_native_goals.py tests/test_native_pairing.py tests/test_neyvia_native_rpc.py tests/test_native_evolution_ui_contract.py tests/test_spawned_agent_ui_contract.py tests/test_neyvia_harnesses.py tests/test_harness_registry.py tests/test_provider_auth_broker.py tests/test_neyvia_brand_contract.py tests/test_neyvia_ui_pass_contract.py tests/test_neyvia_ui_polish_contract.py
          npm run frontend:build
'''
    write(".github/workflows/neyvia-native-ci.yml", content)


def remove_generation_architecture() -> None:
    obsolete_workflows = (
        "codex-export-source.yml",
        "neyvia-native-evolution.yml",
        "neyvia-native-evolution-status.yml",
        "neyvia-native-runtime-hooks.yml",
        "neyvia-spawned-agent-ui.yml",
        "neyvia-native-finalize.yml",
        "neyvia-native-breakthrough-final.yml",
        "neyvia-native-sealed-v2.yml",
        "zz-neyvia-native-canonical.yml",
    )
    for name in obsolete_workflows:
        (ROOT / ".github" / "workflows" / name).unlink(missing_ok=True)
    obsolete_scripts = (
        "apply_neyvia_native_evolution.py",
        "apply_neyvia_native_runtime_hooks.py",
        "apply_neyvia_native_runtime_hooks_v2.py",
        "apply_spawned_agent_ui.py",
        "finalize_neyvia_native_evolution.py",
        "finalize_neyvia_native_evolution_v2.py",
        "finalize_neyvia_native_evolution_v3.py",
        "apply_neyvia_native_breakthrough.py",
        "sitecustomize.py",
        "usercustomize.py",
    )
    for name in obsolete_scripts:
        (ROOT / "scripts" / name).unlink(missing_ok=True)


def write_reconciliation_receipt() -> None:
    receipt = {
        "schema": "neyvia.native-canonical-reconciliation/v1",
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "architecture": "single-native-execution-fabric",
        "dynamicSpecialistTool": "delegate_to_neyvia_specialist",
        "canonicalSources": [
            "src/grant_agent/neyvia_agent.py",
            "src/grant_agent/behavior_capsules.py",
            "src/grant_agent/native_resource_profiles.py",
            "src/grant_agent/skill_capsules.py",
            "src/grant_agent/native_spawn_contracts.py",
            "src/grant_agent/native_spawn_evaluator.py",
            "src/grant_agent/native_proof_audit.py",
            "src/grant_agent/native_learning.py",
            "src/grant_agent/native_event_stream.py",
            "src/grant_agent/native_hooks.py",
            "src/grant_agent/native_checkpoints.py",
            "src/grant_agent/native_goals.py",
            "web/src/neyvia/NativeEvolutionPanel.jsx",
            "web/src/neyvia/SpawnedAgentLineage.jsx",
        ],
        "selfMutatingGeneratorsRetained": False,
        "optimizationTelemetryPlacement": "evidence-and-diagnostics",
    }
    write("proof/neyvia-native-canonical/reconciliation.json", json.dumps(receipt, indent=2))


def main() -> None:
    patch_native_run_identity()
    patch_harness_control_render()
    patch_hook_test_scope()
    patch_dynamic_specialist_contract()
    strengthen_ui_contract()
    write_architecture_doc()
    write_stable_ci()
    write_reconciliation_receipt()
    remove_generation_architecture()
    write_single_fabric_contract()
    Path(__file__).unlink(missing_ok=True)
    print("NEYVIA_NATIVE_SINGLE_FABRIC_RECONCILED")


if __name__ == "__main__":
    main()
