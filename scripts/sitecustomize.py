"""One-shot reconciliation hook for the Native breakthrough sealing run.

This module is imported automatically by Python when the existing generator is
executed from scripts/.  It patches the generated tree at process exit, then
removes itself.  The final sealing workflow deletes the remaining migration
scripts and self-mutating workflows, leaving only canonical source and normal CI.
"""

from __future__ import annotations

import atexit
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = Path(sys.argv[0]).name == "apply_neyvia_native_breakthrough.py"


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content.rstrip() + "\n", encoding="utf-8")


def _patch_run_identity() -> None:
    path = "src/grant_agent/neyvia_agent.py"
    text = _read(path)
    marker = "    control_root = selected.control_root or selected.root\n"
    if marker not in text:
        raise RuntimeError("Could not locate Native control-root initialization.")
    function_start = text.index("async def run_neyvia_agent(")
    stream_pos = text.index("    event_stream = NativeEventStream(", function_start)
    prefix = text[function_start:stream_pos]
    run_line = '    run_id = f"neyvia_{uuid.uuid4().hex}"\n'
    if run_line not in prefix:
        insertion = text.index(marker, function_start) + len(marker)
        text = text[:insertion] + run_line + text[insertion:]
        stream_pos = text.index("    event_stream = NativeEventStream(", function_start)

    # The identity is immutable for the run.  Remove any later regeneration and
    # bind the final receipt to the same ID used by events, hooks, specialists,
    # checkpoints, proof and learning.
    tail = text[stream_pos:]
    tail = tail.replace(run_line, "")
    text = text[:stream_pos] + tail
    text = re.sub(
        r'("runId"\s*:\s*)f"neyvia_\{uuid\.uuid4\(\)\.hex\}"',
        r'\1run_id',
        text,
    )
    _write(path, text)


def _patch_harness_control() -> None:
    path = "web/src/neyvia/HarnessesSurface.jsx"
    text = _read(path)
    import_line = 'import NativeEvolutionPanel from "./NativeEvolutionPanel";'
    if import_line not in text:
        # Keep imports deterministic and local.
        first_import_end = text.find("\n", text.find("import "))
        text = text[: first_import_end + 1] + import_line + "\n" + text[first_import_end + 1 :]

    # Remove accidental insertions in effects/timer cleanup and render exactly
    # one integrated panel in the main Harness Control surface.
    text = text.replace("<NativeEvolutionPanel />", "")
    main_return = text.rfind("\n  return (")
    if main_return < 0:
        raise RuntimeError("Could not locate Harness Control main return.")
    section_start = text.find("<section", main_return)
    section_end = text.find(">", section_start)
    if section_start < 0 or section_end < 0:
        raise RuntimeError("Could not locate Harness Control root section.")
    insertion = section_end + 1
    text = text[:insertion] + "\n      <NativeEvolutionPanel />" + text[insertion:]
    _write(path, text)


def _patch_hook_test_lifetime() -> None:
    path = "tests/test_native_hooks.py"
    text = _read(path)
    lines = text.splitlines()
    inserted = False
    output: list[str] = []
    for line in lines:
        if 'assert Path(result["receiptPaths"][0]).is_file()' in line:
            # An assertion outside TemporaryDirectory only proves Python removed
            # its temporary directory.  The durable write is checked while the
            # workspace still exists below.
            continue
        output.append(line)
        if "result = NativeHookRunner(root).run(" in line and not inserted:
            output.append('            assert Path(result["receiptPaths"][0]).is_file()')
            inserted = True
    if not inserted:
        raise RuntimeError("Could not locate Native hook execution test.")
    _write(path, "\n".join(output))


def _patch_specialist_contract_test() -> None:
    path = "tests/test_neyvia_agent.py"
    text = _read(path)
    text = text.replace(
        '                "delegate_to_neyvia_planner",\n'
        '                "delegate_to_neyvia_verifier",',
        '                "delegate_to_neyvia_specialist",',
    )
    text = text.replace(
        '"delegate_to_neyvia_planner", "delegate_to_neyvia_verifier"',
        '"delegate_to_neyvia_specialist"',
    )
    _write(path, text)


def _patch_ui_contract() -> None:
    path = "tests/test_native_evolution_ui_contract.py"
    text = _read(path)
    # The panel is now canonical inside the real Harness Control render.  Keep
    # the contract explicit and reject a detached route-only implementation.
    if "<NativeEvolutionPanel />" not in text:
        text += (
            "\n\ndef test_native_panel_is_in_the_real_harness_control_render() -> None:\n"
            '    surface = (ROOT / "web" / "src" / "neyvia" / "HarnessesSurface.jsx").read_text(encoding="utf-8")\n'
            '    assert surface.count("<NativeEvolutionPanel />") == 1\n'
            '    assert surface.rfind("<NativeEvolutionPanel />") > surface.rfind("return (")\n'
        )
    _write(path, text)


def _write_normal_ci() -> None:
    content = """name: Neyvia Native CI

on:
  push:
    branches:
      - main
      - codex/neyvia-native-hybrid-evolution-20260826
  pull_request:

permissions:
  contents: read

concurrency:
  group: neyvia-native-ci-${{ github.ref }}
  cancel-in-progress: true

jobs:
  verify:
    runs-on: ubuntu-latest
    timeout-minutes: 45
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
      - name: Install Python project
        run: |
          python -m pip install --upgrade pip
          python -m pip install -e . pytest
      - name: Verify integrated Native fabric
        run: |
          python -m compileall -q src scripts tests
          python -m pytest -q \
            tests/test_behavior_capsules.py \
            tests/test_native_resource_profiles.py \
            tests/test_native_learning.py \
            tests/test_native_proof_audit.py \
            tests/test_native_spawn_contracts.py \
            tests/test_native_spawn_evaluator.py \
            tests/test_skill_capsules.py \
            tests/test_native_hooks.py \
            tests/test_native_event_stream.py \
            tests/test_native_checkpoints.py \
            tests/test_native_checkpoint_integration_contract.py \
            tests/test_native_goals.py \
            tests/test_native_pairing.py \
            tests/test_neyvia_native_rpc.py \
            tests/test_neyvia_design_skill_capsules.py \
            tests/test_native_phase_controller_contract.py \
            tests/test_native_evolution_ui_contract.py \
            tests/test_spawned_agent_ui_contract.py \
            tests/test_neyvia_agent.py \
            tests/test_harness_registry.py \
            tests/test_neyvia_harnesses.py \
            tests/test_provider_auth_broker.py \
            tests/test_launch_recommendation.py \
            tests/test_neyvia_brand_contract.py \
            tests/test_neyvia_ui_pass_contract.py \
            tests/test_neyvia_ui_polish_contract.py
      - name: Build production frontend
        run: |
          npm ci
          npm run frontend:build
"""
    _write(".github/workflows/neyvia-native-ci.yml", content)


def _remove_superseded_workflows() -> None:
    workflow_root = ROOT / ".github" / "workflows"
    current = "neyvia-native-breakthrough-final.yml"
    obsolete = {
        "codex-export-source.yml",
        "neyvia-native-evolution.yml",
        "neyvia-native-evolution-status.yml",
        "neyvia-native-runtime-hooks.yml",
        "neyvia-spawned-agent-ui.yml",
        "neyvia-native-finalize.yml",
        "neyvia-native-sealed-v2.yml",
    }
    for name in obsolete:
        path = workflow_root / name
        if path.exists() and name != current:
            path.unlink()


def _reconcile() -> None:
    _patch_run_identity()
    _patch_harness_control()
    _patch_hook_test_lifetime()
    _patch_specialist_contract_test()
    _patch_ui_contract()
    _write_normal_ci()
    _remove_superseded_workflows()
    # Do not leave the one-shot bridge in canonical Native source.
    Path(__file__).unlink(missing_ok=True)
    print("NEYVIA_NATIVE_CANONICAL_RECONCILIATION_OK")


if TARGET:
    atexit.register(_reconcile)
