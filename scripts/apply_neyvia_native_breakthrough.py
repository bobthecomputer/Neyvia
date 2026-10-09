from __future__ import annotations

import ast
import runpy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "src" / "grant_agent" / "neyvia_agent.py"


def generated_behavior_layer() -> bool:
    if not AGENT.is_file():
        return False
    source = AGENT.read_text(encoding="utf-8")
    return (
        "BehaviorCapsuleRegistry" in source
        and "neyvia.native-phase-receipt/v1" in source
        and "NativeProofAuditor" in source
    )


def apply_complete_stack() -> None:
    namespace = runpy.run_path(str(ROOT / "scripts" / "finalize_neyvia_native_evolution_v5.py"))
    namespace["main"]()


def apply_breakthrough_delta() -> None:
    source = AGENT.read_text(encoding="utf-8")
    v3 = runpy.run_path(str(ROOT / "scripts" / "finalize_neyvia_native_evolution_v3.py"))
    source = v3["patch_gateway"](source)
    source = v3["patch_build_run_id"](source)
    source = v3["patch_goal_and_spawn_evaluation"](source)
    ast.parse(source, filename=str(AGENT))
    AGENT.write_text(source, encoding="utf-8")
    v3["patch_package"]()
    v3["patch_gates"]()
    v3["write_integration_test"]()

    v4 = runpy.run_path(str(ROOT / "scripts" / "finalize_neyvia_native_evolution_v4.py"))
    v4["patch_spawn_receipt"]()
    v4["patch_spawn_evaluator"]()
    v4["patch_spawn_evaluator_test"]()
    v4["patch_checkpoint_integration_test"]()

    v5 = runpy.run_path(str(ROOT / "scripts" / "finalize_neyvia_native_evolution_v5.py"))
    v5["patch_rpc"]()
    v5["patch_panel"]()
    v5["patch_docs"]()
    v5["patch_package_and_gates"]()


def validate() -> None:
    for relative in (
        "src/grant_agent/behavior_capsules.py",
        "src/grant_agent/native_resource_profiles.py",
        "src/grant_agent/native_learning.py",
        "src/grant_agent/native_proof_audit.py",
        "src/grant_agent/native_spawn_contracts.py",
        "src/grant_agent/native_spawn_evaluator.py",
        "src/grant_agent/native_hooks.py",
        "src/grant_agent/native_event_stream.py",
        "src/grant_agent/native_checkpoints.py",
        "src/grant_agent/native_goals.py",
        "src/grant_agent/native_pairing.py",
        "src/grant_agent/neyvia_native_rpc.py",
        "src/grant_agent/neyvia_agent.py",
    ):
        path = ROOT / relative
        if not path.is_file():
            raise RuntimeError(f"Native breakthrough file is missing: {relative}")
        ast.parse(path.read_text(encoding="utf-8"), filename=relative)


def main() -> int:
    if generated_behavior_layer():
        apply_breakthrough_delta()
        mode = "delta"
    else:
        apply_complete_stack()
        mode = "complete"
    validate()
    print(f"NEYVIA_NATIVE_BREAKTHROUGH_APPLIED mode={mode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
