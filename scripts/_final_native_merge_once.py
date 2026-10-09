from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content.rstrip() + "\n", encoding="utf-8")


def patch_run_identity() -> None:
    path = "src/grant_agent/neyvia_agent.py"
    text = read(path)
    start = text.index("async def run_neyvia_agent(")
    marker = "    control_root = selected.control_root or selected.root\n"
    control = text.index(marker, start)
    run_line = '    run_id = f"neyvia_{uuid.uuid4().hex}"\n'
    boundary_positions = [
        position
        for token in ("    event_stream = NativeEventStream(", "    state_root = ", "    started = datetime.now(")
        if (position := text.find(token, control)) >= 0
    ]
    boundary = min(boundary_positions) if boundary_positions else control + len(marker)
    if run_line not in text[control : boundary + 160]:
        insertion = control + len(marker)
        text = text[:insertion] + run_line + text[insertion:]
    function = text[start:]
    first = function.find(run_line)
    if first < 0:
        raise RuntimeError("Native run identity was not materialized.")
    function = function[: first + len(run_line)] + function[first + len(run_line) :].replace(run_line, "")
    text = text[:start] + function
    text = re.sub(
        r'("runId"\s*:\s*)f"neyvia_\{uuid\.uuid4\(\)\.hex\}"',
        r"\1run_id",
        text,
    )
    write(path, text)


def patch_harness_control() -> None:
    path = "web/src/neyvia/HarnessesSurface.jsx"
    text = read(path)
    import_line = 'import NativeEvolutionPanel from "./NativeEvolutionPanel";'
    output = []
    seen = False
    for line in text.splitlines():
        if line.strip() == import_line:
            if seen:
                continue
            seen = True
        output.append(line)
    text = "\n".join(output) + "\n"
    if not seen:
        imports = list(re.finditer(r"^import .*?;\s*$", text, re.M))
        if not imports:
            raise RuntimeError("Harness Control import block was not found.")
        position = imports[-1].end()
        text = text[:position] + "\n" + import_line + text[position:]
    text = text.replace("<NativeEvolutionPanel />", "")
    main_return = text.rfind("\n  return (")
    section = text.find("<section", main_return)
    close = text.find(">", section)
    if main_return < 0 or section < 0 or close < 0:
        raise RuntimeError("Harness Control root render was not found.")
    text = text[: close + 1] + "\n      <NativeEvolutionPanel />" + text[close + 1 :]
    write(path, text)


def patch_tests() -> None:
    hook_path = ROOT / "tests/test_native_hooks.py"
    if hook_path.exists():
        lines = [
            line
            for line in hook_path.read_text(encoding="utf-8").splitlines()
            if 'assert Path(result["receiptPaths"][0]).is_file()' not in line
        ]
        output: list[str] = []
        active = False
        balance = 0
        indent = ""
        inserted = False
        for line in lines:
            output.append(line)
            if not inserted and "result = NativeHookRunner(root).run(" in line:
                active = True
                indent = line[: len(line) - len(line.lstrip())]
                balance = line.count("(") - line.count(")")
                continue
            if active:
                balance += line.count("(") - line.count(")")
                if balance <= 0:
                    output.append(indent + 'assert Path(result["receiptPaths"][0]).is_file()')
                    active = False
                    inserted = True
        if inserted:
            write("tests/test_native_hooks.py", "\n".join(output))

    agent_path = ROOT / "tests/test_neyvia_agent.py"
    if agent_path.exists():
        text = agent_path.read_text(encoding="utf-8")
        text = text.replace(
            '                "delegate_to_neyvia_planner",\n                "delegate_to_neyvia_verifier",',
            '                "delegate_to_neyvia_specialist",',
        )
        text = text.replace(
            '["delegate_to_neyvia_planner", "delegate_to_neyvia_verifier"]',
            '["delegate_to_neyvia_specialist"]',
        )
        write("tests/test_neyvia_agent.py", text)


def write_contracts() -> None:
    write(
        "docs/NEYVIA_NATIVE_EXECUTION_FABRIC.md",
        """# Neyvia Native Execution Fabric

Neyvia Native is one product runtime, not a collection of sidecars. Every run compiles
one authoritative contract and every user surface projects the same receipt and
hash-chained event ledger.

A Native run binds task and domain contract, behavior capsule, J-Space-inspired cognitive
workspace, resource profile, executable skill phases, receipt-bound specialists,
task-scoped tools, session lineage, goals, hooks, reversible workspace checkpoints,
deterministic proof, proof-bound learning, and device target.

The model proposes work. Neyvia owns authority, execution boundaries, receipts and
completion. External harnesses remain available through Neyvia Hybrid when their own
runtime is the right executor; they are never silently presented as Native providers.

For mutating work Neyvia fingerprints the workspace, runs an independently selected
test/build oracle, validates tool, hook, checkpoint and skill receipts, and blocks
narrative success when evidence is missing or failed. Learning is append-only and may
influence routing only from proved outcomes plus human value.

Chat, Agent Live, Harness Control, desktop, phone and NAS project this same contract.
Routine cache, token and latency telemetry remains under Evidence & diagnostics; foreground
UI emphasizes work, exact route, authority, phase, blocker, proof and next action.
""",
    )
    write(
        "tests/test_native_single_fabric_contract.py",
        '''from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_native_runtime_is_one_composed_execution_fabric() -> None:
    source = (ROOT / "src" / "grant_agent" / "neyvia_agent.py").read_text(encoding="utf-8")
    for name in ("behavior_capsules", "native_resource_profiles", "skill_capsules", "native_spawn_contracts", "native_spawn_evaluator", "native_proof_audit", "native_learning", "native_event_stream", "native_hooks", "native_checkpoints", "native_goals"):
        assert name in source, f"{name} is not connected to Neyvia Native"
    assert "delegate_to_neyvia_specialist" in source
    assert 'run_id = f"neyvia_{uuid.uuid4().hex}"' in source


def test_harness_control_and_lineage_project_receipt_state() -> None:
    harness = (ROOT / "web" / "src" / "neyvia" / "HarnessesSurface.jsx").read_text(encoding="utf-8")
    panel = (ROOT / "web" / "src" / "neyvia" / "NativeEvolutionPanel.jsx").read_text(encoding="utf-8")
    lineage = (ROOT / "web" / "src" / "neyvia" / "SpawnedAgentLineage.jsx").read_text(encoding="utf-8")
    assert harness.count("<NativeEvolutionPanel />") == 1
    assert "receipt" in panel.lower()
    assert "receipt" in lineage.lower()
    assert "model" in lineage.lower()


def test_no_self_mutating_native_generators_remain() -> None:
    for name in ("apply_neyvia_native_evolution.py", "apply_neyvia_native_runtime_hooks.py", "apply_neyvia_native_runtime_hooks_v2.py", "apply_spawned_agent_ui.py", "finalize_neyvia_native_evolution.py", "finalize_neyvia_native_evolution_v2.py", "finalize_neyvia_native_evolution_v3.py", "apply_neyvia_native_breakthrough.py", "reconcile_native_canonical.py", "_final_native_merge_once.py"):
        assert not (ROOT / "scripts" / name).exists(), name
''',
    )


def remove_migration_machinery() -> None:
    for name in (
        "codex-export-source.yml",
        "neyvia-native-evolution.yml",
        "neyvia-native-evolution-status.yml",
        "neyvia-native-runtime-hooks.yml",
        "neyvia-spawned-agent-ui.yml",
        "neyvia-native-finalize.yml",
        "neyvia-native-breakthrough-final.yml",
        "neyvia-native-sealed-v2.yml",
        "zz-neyvia-native-canonical.yml",
        "zzz-neyvia-native-final.yml",
        "zzzz-finalize-native-and-merge.yml",
    ):
        (ROOT / ".github/workflows" / name).unlink(missing_ok=True)
    for name in (
        "apply_neyvia_native_evolution.py",
        "apply_neyvia_native_runtime_hooks.py",
        "apply_neyvia_native_runtime_hooks_v2.py",
        "apply_spawned_agent_ui.py",
        "finalize_neyvia_native_evolution.py",
        "finalize_neyvia_native_evolution_v2.py",
        "finalize_neyvia_native_evolution_v3.py",
        "apply_neyvia_native_breakthrough.py",
        "reconcile_native_canonical.py",
        "sitecustomize.py",
        "usercustomize.py",
        "_final_native_merge_once.py",
    ):
        (ROOT / "scripts" / name).unlink(missing_ok=True)
    for relative in (
        "proof/neyvia-native-canonical/.pr-ready",
        "proof/neyvia-native-canonical/DO_NOT_ADD_MORE_MARKERS",
    ):
        (ROOT / relative).unlink(missing_ok=True)


def write_stable_ci() -> None:
    write(
        ".github/workflows/neyvia-native-ci.yml",
        '''name: Neyvia Native CI

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
      - run: python -m pip install --upgrade pip && python -m pip install -e . pytest
      - run: npm ci
      - run: python -m compileall -q src scripts tests
      - run: python -m pytest -q tests/test_native_single_fabric_contract.py tests/test_neyvia_agent.py tests/test_native_proof_audit.py tests/test_native_learning.py tests/test_native_spawn_contracts.py tests/test_native_spawn_evaluator.py tests/test_skill_capsules.py tests/test_native_hooks.py tests/test_native_event_stream.py tests/test_native_checkpoints.py tests/test_native_goals.py tests/test_native_pairing.py tests/test_neyvia_native_rpc.py tests/test_native_evolution_ui_contract.py tests/test_spawned_agent_ui_contract.py tests/test_neyvia_harnesses.py tests/test_harness_registry.py tests/test_provider_auth_broker.py tests/test_neyvia_brand_contract.py tests/test_neyvia_ui_pass_contract.py tests/test_neyvia_ui_polish_contract.py
      - run: npm run frontend:build
''',
    )


def main() -> None:
    patch_run_identity()
    patch_harness_control()
    patch_tests()
    write_contracts()
    write_stable_ci()
    proof = ROOT / "proof/neyvia-native-canonical"
    proof.mkdir(parents=True, exist_ok=True)
    receipt = {
        "schema": "neyvia.native-final-reconciliation/v1",
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "architecture": "single-native-execution-fabric",
        "specialistInterface": "delegate_to_neyvia_specialist",
        "selfMutatingGeneratorsRetained": False,
        "optimizationTelemetryPlacement": "evidence-and-diagnostics",
    }
    write("proof/neyvia-native-canonical/reconciliation.json", json.dumps(receipt, indent=2))
    remove_migration_machinery()
    print("NEYVIA_NATIVE_FINAL_RECONCILIATION_OK")


if __name__ == "__main__":
    main()
